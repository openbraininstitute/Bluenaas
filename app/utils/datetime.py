from datetime import datetime, timezone


def iso_now() -> str:
    """Return the current time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
