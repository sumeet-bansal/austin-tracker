"""Tests for text formatting helpers."""

from src.formatter import format_stats


def _data(**overrides) -> dict:
    defaults = {
        "current_mile": 421.2,
        "day": 33,
        "pct_complete": 15.9,
        "pace_mi_per_day": 12.8,
        "elevation_gain_display": "48.4k ft",
    }
    defaults.update(overrides)
    return defaults


def test_stats_has_no_week_in_review_header():
    """The :hikege: header was dropped — stats should lead with the miles line."""
    out = format_stats(_data(), "https://hike.austinscarter.com/")
    assert ":hikege:" not in out
    assert "Week in Review" not in out
    assert out.lstrip().startswith("*Miles hiked:*")


def test_stats_includes_all_expected_fields():
    out = format_stats(_data(), "https://hike.austinscarter.com/")
    assert "421.2" in out
    assert "15.9%" in out
    assert "Day 33" in out
    assert "12.8 mi/day" in out
    assert "48.4k ft" in out
    assert "hike.austinscarter.com" in out
