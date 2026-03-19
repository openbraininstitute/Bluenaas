from contextvars import ContextVar

# Correlation ID (CID) — a short, unique identifier assigned to each incoming
# HTTP request.  It is propagated through RQ job metadata to workers and
# subprocesses so that every log line produced while handling a single request
# can be traced back to it.  The middleware sets this var on request entry;
# LoggingWorker sets it when picking up a job.
cid_var: ContextVar[str | None] = ContextVar("cid", default=None)
