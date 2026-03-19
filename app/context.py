from contextvars import ContextVar

cid_var: ContextVar[str | None] = ContextVar("cid", default=None)
