"""Cross-cutting observability: process uptime and an in-memory log ring buffer.

The admin panel polls ``/admin/logs`` and ``/admin/health``; both read from the
state held here rather than from ``main.py``. ``setup_logging`` must run at
startup (from the lifespan) so the capture handler is attached.
"""

import logging
import time
from collections import deque
from itertools import count

from app.config import settings

_start_time = time.time()
_log_history: deque[dict] = deque(maxlen=300)
_log_counter = count(1)


class _LogCaptureHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _log_history.append(
            {
                "id": next(_log_counter),
                "t": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            }
        )


_capture_handler = _LogCaptureHandler()
_capture_handler.setFormatter(logging.Formatter("%(message)s"))


def setup_logging() -> None:
    """Route ``app.*`` logs through uvicorn's handlers plus the capture buffer."""
    uvicorn_logger = logging.getLogger("uvicorn")
    app_logger = logging.getLogger("app")
    app_logger.handlers = list(uvicorn_logger.handlers)
    app_logger.addHandler(_capture_handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False


def uptime_seconds() -> int:
    return int(time.time() - _start_time)


def get_logs(after: int = 0) -> list[dict]:
    """Return captured log entries with an id strictly greater than ``after``."""
    return [e for e in _log_history if e["id"] > after]
