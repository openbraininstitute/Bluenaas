from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    """ApiResponse."""

    message: str
    data: T | None = None
