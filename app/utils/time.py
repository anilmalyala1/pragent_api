from datetime import datetime, timezone

def humanize_from_now(iso_ts: str) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())
    mins = secs // 60
    hours = mins // 60
    days = hours // 24

    if days > 0:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if mins > 0:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    return f"{secs} second{'s' if secs != 1 else ''} ago"
