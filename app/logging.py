import functools
import logging
import sys

from loguru import logger

from app.constants import CID_LENGTH, NULL_CID

_THIS_FILE = __file__


def _build_format(*, show_cid: bool, show_source: bool) -> str:
    cid = "{extra[cid]: <" + str(CID_LENGTH) + "} | " if show_cid else ""
    source = "{name}:{function}:{line} - " if show_source else ""
    return f"<level>{{level: <8}}</level> | {cid}{source}{{message}}"


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

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
    - Applies separate log levels for app code vs library code
    """
    from app.config.settings import settings

    app_level = level or settings.LOG_LEVEL
    lib_level = settings.LOG_LEVEL_LIBS
    fmt = _build_format(show_cid=settings.LOG_SHOW_CID, show_source=settings.LOG_SHOW_SOURCE)

    app_level_no = logger.level(app_level).no
    lib_level_no = logger.level(lib_level).no
    sink_level_no = min(app_level_no, lib_level_no)

    def _filter(record) -> bool:
        if record["name"].startswith("app"):
            return record["level"].no >= app_level_no
        return record["level"].no >= lib_level_no

    logger.remove()
    logger.configure(extra={"cid": NULL_CID})
    logger.add(sys.stderr, format=fmt, level=sink_level_no, filter=_filter, colorize=True)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Remove handlers that libraries (notably RQ) attach to their own loggers.
    # Without this, RQ messages appear twice: once from RQ's handler and once
    # from our intercept handler on root.
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).handlers.clear()


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
