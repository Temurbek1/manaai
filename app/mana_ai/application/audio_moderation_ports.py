from dataclasses import dataclass
from typing import Protocol

from app.mana_ai.domain.audio_moderation import (
    AudioModerationCallback,
    AudioModerationJobRequest,
    AudioRiskAssessment,
)


class AudioModerationError(RuntimeError):
    """Base class for sanitized audio-moderation failures."""


class AudioAssetUnprocessableError(AudioModerationError):
    """The supplied asset cannot be analyzed and needs conservative handling."""


class AudioModerationTransientError(AudioModerationError):
    """A retry by the 360REC backend may succeed later."""


class AudioModerationCallbackRejectedError(AudioModerationError):
    """The callback endpoint permanently rejected the service response."""


@dataclass(frozen=True, slots=True)
class AudioAsset:
    content: bytes
    filename: str
    media_type: str


class AudioAssetSource(Protocol):
    async def fetch(self, url: str) -> AudioAsset: ...


class AudioRiskAnalyzer(Protocol):
    async def analyze(self, *, audio_id: int, asset: AudioAsset) -> AudioRiskAssessment: ...


class AudioModerationCallbackSender(Protocol):
    async def send(
        self,
        *,
        job: AudioModerationJobRequest,
        callback: AudioModerationCallback,
    ) -> None: ...
