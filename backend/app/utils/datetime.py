from datetime import datetime, timezone

utcmin = datetime.min.replace(tzinfo=timezone.utc)
utcmax = datetime.max.replace(tzinfo=timezone.utc)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)
