"""Text formatting for Slack messages."""

from datetime import datetime


def format_timestamp(iso_str: str) -> str:
    """Format '2026-03-20T01:45:31.457625+00:00' as 'March 20, 2026 at 1:45 AM'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        month = dt.strftime("%B")
        hour = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{month} {dt.day}, {dt.year} at {hour}:{dt.minute:02d} {ampm}"
    except (ValueError, TypeError):
        return ""


def format_stats(data: dict, tracker_url: str) -> str:
    miles = data.get("current_mile", 0)
    day = data.get("day", "?")
    pct = data.get("pct_complete", 0)
    pace = data.get("pace_mi_per_day", 0)
    elev = data.get("elevation_gain_display", "?")

    lines = [
        ":hikege: *Austin's PCT Week in Review*",
        "",
        f"*Miles hiked:* {miles:.1f} of 2,650 ({pct:.1f}% complete)",
        f"*Day on trail:* Day {day}",
        f"*Avg pace:* {pace} mi/day",
        f"*Elevation gain:* {elev}",
        "",
        f"<{tracker_url}|Follow along on his tracker>",
    ]
    return "\n".join(lines)


def format_fallback(data: dict, tracker_url: str) -> str:
    """Plain-text fallback for notifications and non-block clients."""
    stats = format_stats(data, tracker_url)
    posts = data.get("posts", [])
    if posts:
        titles = [p.get("title", "Update") for p in posts[-3:]]
        stats += "\n\nTrail updates: " + " | ".join(titles)
    return stats
