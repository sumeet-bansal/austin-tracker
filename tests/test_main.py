"""Tests for posting decision logic in src/main.py."""

from datetime import UTC, datetime, timedelta

from src.main import decide_post, recent_posts

# Wednesday 2026-03-25 at noon UTC
WED_NOON = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
# Friday 2026-03-27 at noon UTC
FRI_NOON = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)


def _post(hours_ago: float, now: datetime = WED_NOON, **kwargs) -> dict:
    """Create a post with created_at relative to a given time."""
    ts = now - timedelta(hours=hours_ago)
    return {"id": "1", "title": "Test", "created_at": ts.isoformat(), **kwargs}


# --- recent_posts ---


def test_recent_post_within_window():
    assert len(recent_posts([_post(10)], WED_NOON)) == 1


def test_old_post_outside_window():
    assert recent_posts([_post(26)], WED_NOON) == []


def test_empty_posts():
    assert recent_posts([], WED_NOON) == []


def test_missing_created_at():
    assert recent_posts([{"id": "1", "title": "Test"}], WED_NOON) == []


def test_invalid_created_at():
    assert recent_posts([{"created_at": "not-a-date"}], WED_NOON) == []


def test_custom_hours_window():
    assert len(recent_posts([_post(48)], WED_NOON, hours=72)) == 1
    assert recent_posts([_post(48)], WED_NOON, hours=24) == []


def test_mixed_old_and_new():
    posts = [_post(48), _post(10)]
    result = recent_posts(posts, WED_NOON)
    assert len(result) == 1
    assert result[0] == posts[1]


# --- decide_post ---


def test_weekday_with_recent_post():
    posts = [_post(10)]
    decision = decide_post(posts, WED_NOON)
    assert decision.should_post is True
    assert decision.include_posts == posts


def test_weekday_mixed_old_and_new_only_includes_recent():
    old_post = _post(48)
    new_post = _post(10)
    decision = decide_post([old_post, new_post], WED_NOON)
    assert decision.should_post is True
    assert decision.include_posts == [new_post]


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


# --- Real-shape scenario: mix of old and recent posts ---
# Simulates a real bug where a Mar 20 trail update kept reposting on Apr 6
# weekly summaries because it was still in the posts list.

APR6_NOON = datetime(2026, 4, 6, 12, 0, tzinfo=UTC)


def test_real_scenario_decide_post_excludes_old():
    """4 posts on site (3 recent, 1 old) → decide_post includes only the 3 recent ones."""
    posts = [
        {"id": "mono", "title": "Monotony", "trail_mile": 86.6, "created_at": "2026-04-05T19:35:33+00:00"},
        {"id": "rain", "title": "It's Raining Magic", "trail_mile": 106.5, "created_at": "2026-04-05T19:21:19+00:00"},
        {"id": "desert", "title": "Desert Highway", "trail_mile": 74.1, "created_at": "2026-04-05T19:15:51+00:00"},
        {"id": "blister", "title": "Blistering Heat", "trail_mile": 39.5, "created_at": "2026-03-20T01:45:31+00:00"},
    ]
    decision = decide_post(posts, APR6_NOON)
    assert decision.should_post is True
    assert len(decision.include_posts) == 3
    assert "blister" not in {p["id"] for p in decision.include_posts}
