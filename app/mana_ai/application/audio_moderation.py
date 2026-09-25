import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from app.mana_ai.application.audio_moderation_ports import (
    AudioAssetSource,
    AudioAssetUnprocessableError,
    AudioModerationCallbackSender,
    AudioModerationTransientError,
    AudioRiskAnalyzer,
)
from app.mana_ai.domain.audio_moderation import (
    AudioModerationAcceptedResponse,
    AudioModerationCallback,
    AudioModerationCallbackStatus,
    AudioModerationJobRequest,
    AudioRiskAssessment,
    AudioRiskCategory,
    AudioRiskSeverity,
)

logger = logging.getLogger("app.audio_moderation")


class AudioModerationSubmissionError(RuntimeError):
    """The submitted job violates the public service contract."""


class AudioModerationQueueFullError(RuntimeError):
    """The service cannot accept a job without risking asset expiry."""


class AudioModerationUnavailableError(RuntimeError):
    """The service worker is not running."""


@dataclass(frozen=True, slots=True)
class _QueuedJob:
    request: AudioModerationJobRequest
    enqueued_at: float


class AudioModerationURLPolicy:
    def __init__(
        self,
        *,
        allowed_audio_hosts: tuple[str, ...],
        allowed_callback_hosts: tuple[str, ...],
    ) -> None:
        self._allowed_audio_hosts = allowed_audio_hosts
        self._allowed_callback_hosts = allowed_callback_hosts

    def validate(self, job: AudioModerationJobRequest) -> None:
        audio = _secure_url(str(job.audio_url), label="audio")
        callback = _secure_url(str(job.callback_url), label="callback")
        if not _host_allowed(audio.hostname, self._allowed_audio_hosts):
            raise AudioModerationSubmissionError("audio_url host is not allowed")
        if not _host_allowed(callback.hostname, self._allowed_callback_hosts):
            raise AudioModerationSubmissionError("callback_url host is not allowed")
        if not audio.query:
            raise AudioModerationSubmissionError("audio_url must be a presigned URL")
        if callback.query or callback.fragment:
            raise AudioModerationSubmissionError("callback_url cannot contain query or fragment")
        expected_path = f"/api/v1/child/audios/{job.audio_id}/moderation/"
        if callback.path != expected_path:
            raise AudioModerationSubmissionError("callback_url does not match audio_id")


class AudioModerationService:
    def __init__(
        self,
        *,
        assets: AudioAssetSource,
        analyzer: AudioRiskAnalyzer,
        callbacks: AudioModerationCallbackSender,
        url_policy: AudioModerationURLPolicy,
        worker_count: int,
        queue_capacity: int,
        max_queue_delay_seconds: float,
        safe_confidence_threshold: float,
        completed_cache_size: int = 10_000,
    ) -> None:
        self._assets = assets
        self._analyzer = analyzer
        self._callbacks = callbacks
        self._url_policy = url_policy
        self._worker_count = worker_count
        self._queue: asyncio.Queue[_QueuedJob] = asyncio.Queue(maxsize=queue_capacity)
        self._max_queue_delay_seconds = max_queue_delay_seconds
        self._safe_confidence_threshold = safe_confidence_threshold
        self._completed_cache_size = completed_cache_size
        self._active: set[int] = set()
        self._completed: OrderedDict[int, None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(), name=f"audio-moderation-{index}")
            for index in range(self._worker_count)
        ]

    @property
    def is_running(self) -> bool:
        return bool(self._workers) and all(not worker.done() for worker in self._workers)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    async def stop(self) -> None:
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        async with self._lock:
            while not self._queue.empty():
                queued = self._queue.get_nowait()
                self._active.discard(queued.request.audio_id)
                self._queue.task_done()
            self._active.clear()
            self._completed.clear()

    async def submit(
        self,
        job: AudioModerationJobRequest,
    ) -> AudioModerationAcceptedResponse:
        if not self.is_running:
            raise AudioModerationUnavailableError("Audio moderation worker is unavailable")
        self._url_policy.validate(job)
        async with self._lock:
            if job.audio_id in self._active or job.audio_id in self._completed:
                return AudioModerationAcceptedResponse(
                    audio_id=job.audio_id,
                    disposition="duplicate",
                )
            try:
                self._queue.put_nowait(_QueuedJob(request=job, enqueued_at=time.monotonic()))
            except asyncio.QueueFull:
                raise AudioModerationQueueFullError("Audio moderation queue is full") from None
            self._active.add(job.audio_id)
            queue_depth = self._queue.qsize()
        logger.info(
            "Audio moderation job accepted",
            extra={"audio_id": job.audio_id, "queue_depth": queue_depth},
        )
        return AudioModerationAcceptedResponse(audio_id=job.audio_id, disposition="queued")

    async def _worker(self) -> None:
        while True:
            queued = await self._queue.get()
            completed = False
            try:
                completed = await self._process(queued)
            except Exception as exc:
                logger.warning(
                    "Audio moderation job failed; backend retry remains authoritative",
                    extra={
                        "audio_id": queued.request.audio_id,
                        "failure_type": type(exc).__name__,
                    },
                )
            finally:
                async with self._lock:
                    self._active.discard(queued.request.audio_id)
                    if completed:
                        self._remember_completed(queued.request.audio_id)
                self._queue.task_done()

    async def _process(self, queued: _QueuedJob) -> bool:
        if time.monotonic() - queued.enqueued_at > self._max_queue_delay_seconds:
            raise AudioModerationTransientError("Audio asset may expire before processing")
        try:
            asset = await self._assets.fetch(str(queued.request.audio_url))
            assessment = await self._analyzer.analyze(
                audio_id=queued.request.audio_id,
                asset=asset,
            )
        except AudioAssetUnprocessableError:
            assessment = AudioRiskAssessment(
                category=AudioRiskCategory.UNCERTAIN,
                severity=AudioRiskSeverity.HIGH,
                confidence=0.0,
            )
        callback = _to_callback(
            assessment,
            safe_confidence_threshold=self._safe_confidence_threshold,
        )
        await self._callbacks.send(job=queued.request, callback=callback)
        logger.info(
            "Audio moderation callback delivered",
            extra={
                "audio_id": queued.request.audio_id,
                "status": callback.status.value,
                "reason_code": callback.reason,
            },
        )
        return True

    def _remember_completed(self, audio_id: int) -> None:
        self._completed[audio_id] = None
        self._completed.move_to_end(audio_id)
        while len(self._completed) > self._completed_cache_size:
            self._completed.popitem(last=False)


def _to_callback(
    assessment: AudioRiskAssessment,
    *,
    safe_confidence_threshold: float,
) -> AudioModerationCallback:
    if (
        assessment.category in {AudioRiskCategory.SAFE, AudioRiskCategory.NO_SPEECH}
        and assessment.confidence >= safe_confidence_threshold
    ):
        reason = (
            "no_speech_detected"
            if assessment.category is AudioRiskCategory.NO_SPEECH
            else "no_child_safety_risk_detected"
        )
        return AudioModerationCallback(
            status=AudioModerationCallbackStatus.REJECTED,
            reason=reason,
        )
    if assessment.category in {AudioRiskCategory.SAFE, AudioRiskCategory.NO_SPEECH}:
        reason = "manual_review_required:low_confidence_safe_classification"
    elif assessment.category is AudioRiskCategory.UNCERTAIN:
        reason = "manual_review_required:audio_could_not_be_confidently_classified"
    else:
        reason = f"child_safety_risk:{assessment.category.value}:{assessment.severity.value}"
    return AudioModerationCallback(
        status=AudioModerationCallbackStatus.APPROVED,
        reason=reason,
    )


def _secure_url(value: str, *, label: str) -> SplitResult:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise AudioModerationSubmissionError(f"{label}_url port is invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise AudioModerationSubmissionError(f"{label}_url must be a public HTTPS URL")
    return parsed


def _host_allowed(hostname: str | None, patterns: tuple[str, ...]) -> bool:
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    for pattern in patterns:
        candidate = pattern.rstrip(".").lower()
        if candidate.startswith("*."):
            suffix = candidate[1:]
            if normalized.endswith(suffix) and normalized != suffix[1:]:
                return True
        elif normalized == candidate:
            return True
    return False
