"""Tests for src/scraper.py — extract_data edge cases.

End-to-end coverage (real site HTML → parsed fields → final Slack blocks)
lives in tests/test_integration.py. This file holds the narrow edge-case
tests that aren't cheap to hit with a real fixture: the unescaped-JSON
fallback path, graceful-degradation on missing flight payload, and the
hard-fail path when no critical fields parse.
"""

import pytest

from src.scraper import extract_data


def _flight_html(
    mile: float = 500.5,
    lat: float = 34.0522,
    lng: float = -118.2437,
    day: int = 30,
    pace: float = 16.7,
    elev: str = "120k ft",
    pct: float = 18.9,
    posts_json: str = "[]",
) -> str:
    """Build minimal HTML mimicking the Next.js flight payload + rendered stats."""
    flight = (
        f'<script>self.__next_f.push([1,"'
        f'currentMile\\":{mile},'
        f'currentPosition\\":{{\\"lat\\":{lat},\\"lng\\":{lng}}},'
        f'posts\\":{posts_json}'
        f'"])</script>'
    )
    rendered = (
        f"<div>Day {day}</div>"
        f'<div>{pace}</div>\n<div class="stat-label">mi/day avg</div>'
        f'<div>{elev}</div>\n<div class="stat-label">elevation gain</div>'
        f'<div>{pct}%</div>\n<div class="stat-label">complete</div>'
    )
    return flight + rendered


def test_partial_html_still_extracts_what_it_can():
    """If the flight payload is missing but rendered stats are present, we
    should still parse `day` and skip quietly. Used to degrade gracefully
    when the site partially renders."""
    html = "<html><body><div>Day 30</div></body></html>"
    data = extract_data(html)
    assert data["day"] == 30
    assert "current_mile" not in data


def test_no_critical_fields_exits():
    """Hard fail if nothing parses — better to surface in logs than silently
    post a broken message."""
    html = "<html><body>nothing useful</body></html>"
    with pytest.raises(SystemExit):
        extract_data(html)


def test_integer_mile_parses_as_float():
    """currentMile on day 1 of a trip is `0`, not `0.0` — make sure the
    non-decimal variant of the regex still matches."""
    html = _flight_html(mile=500)
    data = extract_data(html)
    assert data["current_mile"] == 500.0


def test_negative_coordinates():
    """lat/lng regex must handle negative values (the PCT is entirely in
    negative longitude, and Southern Hemisphere future-proofing)."""
    html = _flight_html(lat=-33.8688, lng=151.2093)
    data = extract_data(html)
    assert data["lat"] == -33.8688
    assert data["lng"] == 151.2093
