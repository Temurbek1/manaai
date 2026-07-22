import logging
from collections.abc import Sequence

from pydantic import JsonValue

logger = logging.getLogger(__name__)


class StructuredLogNotificationAdapter:
    """Delivers the explicit ``log`` channel without exposing report contents."""

    async def send(
        self,
        *,
        channels: Sequence[str],
        subject: str,
        message: str,
        metadata: dict[str, JsonValue],
    ) -> None:
        del message
        unsupported = sorted(set(channels) - {"log"})
        if "log" in channels:
            logger.info(
                "Operation report notification",
                extra={"subject": subject, "metadata": metadata, "channel": "log"},
            )
        if unsupported:
            logger.warning(
                "Unsupported notification channels were skipped",
                extra={"channels": unsupported, "metadata": metadata},
            )
