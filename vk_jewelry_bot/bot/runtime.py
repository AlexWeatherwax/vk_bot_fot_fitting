"""Writable Long Poll state and bounded application logging."""
import logging
from pathlib import Path
import sys

from loguru import logger as sdk_logger
from vkbottle.polling import BotPolling


class StatefulBotPolling(BotPolling):
    def __init__(self, state_dir: Path, **kwargs):
        super().__init__(**kwargs)
        self.state_dir = Path(state_dir)

    @property
    def ts_state_path(self) -> Path:
        if self.group_id is None:
            raise RuntimeError("Polling group_id is not resolved")
        return self.state_dir / f"{self.group_id}.json"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The SDK uses Loguru independently of Python logging. Its DEBUG events
    # contain message/photo data; diagnostic tracebacks also expose local values.
    sdk_logger.remove()
    sdk_logger.add(sys.stderr, level=level, backtrace=False, diagnose=False, colorize=False)
