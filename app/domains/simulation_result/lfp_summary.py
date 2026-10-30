from enum import StrEnum

from pydantic import BaseModel


class LfpSummaryState(StrEnum):
    READY = "ready"
    BUILDING = "building"
    # Never built: the reason says why
    REFUSED = "refused"
    # The build and its retry failed, it is not tried again for a while
    FAILED = "failed"


class NoSummaryReason(StrEnum):
    NOT_LFP_REPORT = "not_lfp_report"
    TOO_LARGE = "too_large"
    UNREADABLE = "unreadable"


class LfpSummaryStatus(BaseModel):
    state: LfpSummaryState
    # Of a ready summary
    size: int | None = None
    sha256: str | None = None
    # Of a build waiting in its queue
    queue_position: int | None = None
    # Of a refused one
    reason: NoSummaryReason | None = None
