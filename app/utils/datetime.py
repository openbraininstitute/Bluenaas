from datetime import datetime, timezone


def iso_now() -> str:
    """Return the current time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_isoformat(date: datetime | None) -> str | None:
    """Return the ISO 8601 formatted date string or None."""
    return date.isoformat() if date else None
