from enum import StrEnum

from pydantic import BaseModel


class MorphologyPackState(StrEnum):
    READY = "ready"
    BUILDING = "building"
    # Never built: the reason says why
    REFUSED = "refused"
    # The build and its retry failed, it is not tried again for a while
    FAILED = "failed"


class NoPackReason(StrEnum):
    SINGLE_NEURON = "single_neuron"
    TOO_LARGE = "too_large"
    NO_MORPHOLOGIES = "no_morphologies"


class MorphologyPackStatus(BaseModel):
    state: MorphologyPackState
    # Of a ready pack
    size: int | None = None
    sha256: str | None = None
    # Of a build waiting in its queue
    queue_position: int | None = None
    # Of a refused one
    reason: NoPackReason | None = None
