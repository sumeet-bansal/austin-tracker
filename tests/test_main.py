"""Tests for posting decision logic in src/main.py."""

from datetime import datetime, timedelta, timezone

from src.main import decide_post, has_recent_posts

# Wednesday 2026-03-25 at noon UTC
WED_NOON = datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc)
# Friday 2026-03-27 at noon UTC
FRI_NOON = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)


def _post(hours_ago: float, now: datetime = WED_NOON) -> dict:
    """Create a post with created_at relative to a given time."""
    ts = now - timedelta(hours=hours_ago)
    return {"id": "1", "title": "Test", "created_at": ts.isoformat()}


# --- has_recent_posts ---


def test_recent_post_within_window():
    assert has_recent_posts([_post(10)], WED_NOON) is True


def test_recent_post_at_boundary():
    assert has_recent_posts([_post(24)], WED_NOON) is True


def test_old_post_outside_window():
    assert has_recent_posts([_post(26)], WED_NOON) is False


def test_empty_posts():
    assert has_recent_posts([], WED_NOON) is False


def test_missing_created_at():
    assert has_recent_posts([{"id": "1", "title": "Test"}], WED_NOON) is False


def test_invalid_created_at():
    assert has_recent_posts([{"created_at": "not-a-date"}], WED_NOON) is False


def test_custom_hours_window():
    assert has_recent_posts([_post(48)], WED_NOON, hours=72) is True
    assert has_recent_posts([_post(48)], WED_NOON, hours=24) is False


def test_mixed_old_and_new():
    assert has_recent_posts([_post(48), _post(10)], WED_NOON) is True


# --- decide_post ---


def test_weekday_with_recent_post():
    posts = [_post(10)]
    decision = decide_post(posts, WED_NOON)
    assert decision.should_post is True
    assert decision.include_posts == posts


def test_weekday_no_recent_post_skips():
    decision = decide_post([_post(48)], WED_NOON)
    assert decision.should_post is False
    assert decision.include_posts == []


def test_friday_no_recent_post_posts_without_updates():
    decision = decide_post([_post(48, now=FRI_NOON)], FRI_NOON)
    assert decision.should_post is True
    assert decision.include_posts == []


def test_friday_with_recent_post_includes_updates():
    posts = [_post(10, now=FRI_NOON)]
    decision = decide_post(posts, FRI_NOON)
    assert decision.should_post is True
    assert decision.include_posts == posts


def test_weekday_no_posts_at_all_skips():
    decision = decide_post([], WED_NOON)
    assert decision.should_post is False


def test_friday_no_posts_at_all_still_posts():
    decision = decide_post([], FRI_NOON)
    assert decision.should_post is True
    assert decision.include_posts == []
