import functools
import logging
import sys

from loguru import logger

from app.constants import CID_LENGTH, NULL_CID

_CID = "{extra[cid]: <" + str(CID_LENGTH) + "} | "
_SOURCE = "{name}:{function}:{line} - "


def _build_format(*, show_cid: bool, show_source: bool) -> str:
    cid = _CID if show_cid else ""
    source = _SOURCE if show_source else ""
    return f"<level>{{level: <8}}</level> | {cid}{source}{{message}}"


_THIS_FILE = __file__

# Third-party modules (using loguru directly) that are too verbose at INFO.
_NOISY_LOGURU_MODULES = ("bluecellulab",)

_WARNING_NO = 30  # loguru WARNING level number


def _filter(record) -> bool:
    for prefix in _NOISY_LOGURU_MODULES:
        if record["name"].startswith(prefix):
            return record["level"].no >= _WARNING_NO
    return True


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk past our handler frame and all stdlib logging internals.
        frame, depth = logging.currentframe(), 2
        while frame is not None:
            if frame.f_code.co_filename not in (logging.__file__, _THIS_FILE):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str | None = None) -> None:
    """Configure loguru as the single logging sink.

    - Removes default loguru handler
    - Adds a handler with the project log format
    - Intercepts stdlib ``logging`` so third-party libraries (uvicorn, rq, …)
      are routed through loguru
    - Silences noisy stdlib loggers to WARNING+
    """
    from app.config.settings import settings

    resolved_level = level or settings.LOG_LEVEL
    fmt = _build_format(show_cid=settings.LOG_SHOW_CID, show_source=settings.LOG_SHOW_SOURCE)

    logger.remove()
    logger.configure(extra={"cid": NULL_CID})
    logger.add(sys.stderr, format=fmt, level=resolved_level, filter=_filter, colorize=True)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Remove handlers that libraries (notably RQ) attach to their own loggers.
    # Without this, RQ messages appear twice: once from RQ's handler and once
    # from our intercept handler on root.
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).handlers.clear()

    for noisy in (
        "uvicorn.access",
        "httpcore",
        "httpx",
        "rq.worker_pool",
        "numexpr",
        "matplotlib",
        "matplotlib.font_manager",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def worker_subprocess(fn):
    """Decorator for functions that run in a spawned subprocess.

    Calls ``setup_logging()`` and binds the ``cid`` kwarg (if present) to the
    loguru context, then removes it from kwargs before calling the wrapped
    function.  The decorated function must accept an optional ``cid`` keyword
    argument.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        cid = kwargs.pop("cid", None)
        setup_logging()
        if cid:
            logger.configure(extra={"cid": cid})
        return fn(*args, **kwargs)

    return wrapper
