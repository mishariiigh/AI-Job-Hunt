from datetime import datetime, timezone


def normalize_source_timestamp(value):
    if value in (None, ""):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = None

    if numeric is not None:
        if numeric > 100_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return str(value)

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text
