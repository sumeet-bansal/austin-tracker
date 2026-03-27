"""Tests for src/scraper.py — extract_data against HTML fixtures."""

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
    escaped: bool = True,
) -> str:
    """Build minimal HTML mimicking the Next.js flight payload + rendered stats."""
    if escaped:
        flight = (
            f'<script>self.__next_f.push([1,"'
            f'currentMile\\":{mile},'
            f'currentPosition\\":{{\\"lat\\":{lat},\\"lng\\":{lng}}},'
            f'posts\\":{posts_json}'
            f'"])</script>'
        )
    else:
        flight = (
            f'<script>self.__next_f.push([1,"'
            f'currentMile":{mile},'
            f'currentPosition":{{"lat":{lat},"lng":{lng}}},'
            f'posts":{posts_json}'
            f'"])</script>'
        )
    rendered = (
        f'<div>Day {day}</div>'
        f'<div>{pace}</div><div class="stat-label">mi/day avg</div>'
        f'<div>{elev}</div><div class="stat-label">elevation gain</div>'
        f'<div>{pct}%</div><div class="stat-label">complete</div>'
    )
    # Make the rendered stats regex-matchable
    rendered = rendered.replace(
        f"<div>{pace}</div><div",
        f"<div>{pace}</div>\n<div"
    ).replace(
        f"<div>{elev}</div><div",
        f"<div>{elev}</div>\n<div"
    ).replace(
        f"<div>{pct}%</div><div",
        f"<div>{pct}%</div>\n<div"
    )
    return flight + rendered


def test_extract_basic_stats():
    html = _flight_html()
    data = extract_data(html)
    assert data["current_mile"] == 500.5
    assert data["lat"] == 34.0522
    assert data["lng"] == -118.2437
    assert data["day"] == 30
    assert data["pace_mi_per_day"] == 16.7
    assert data["elevation_gain_display"] == "120k ft"
    assert data["pct_complete"] == 18.9
    assert data["posts"] == []


def test_extract_unescaped_json():
    html = _flight_html(escaped=False)
    data = extract_data(html)
    assert data["current_mile"] == 500.5
    assert data["lat"] == 34.0522


def test_extract_posts():
    posts_json = '[{\\"id\\":\\"abc\\",\\"title\\":\\"Summit Day\\",\\"created_at\\":\\"2026-03-20T12:00:00+00:00\\"}]'
    html = _flight_html(posts_json=posts_json)
    data = extract_data(html)
    assert len(data["posts"]) == 1
    assert data["posts"][0]["title"] == "Summit Day"


def test_extract_no_flight_payload_exits():
    html = "<html><body><div>Day 30</div></body></html>"
    # Only has day, not current_mile — should still parse day
    data = extract_data(html)
    assert data["day"] == 30
    assert "current_mile" not in data


def test_extract_no_critical_fields_exits():
    html = "<html><body>nothing useful</body></html>"
    with pytest.raises(SystemExit):
        extract_data(html)


def test_extract_integer_mile():
    html = _flight_html(mile=500)
    data = extract_data(html)
    assert data["current_mile"] == 500.0


def test_extract_negative_coordinates():
    html = _flight_html(lat=-33.8688, lng=151.2093)
    data = extract_data(html)
    assert data["lat"] == -33.8688
    assert data["lng"] == 151.2093
