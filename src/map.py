"""Mapbox trail progress map generation."""

import json
import logging
import urllib.parse

from src.scraper import fetch_url

CENTERLINE_URL = "https://hike.austinscarter.com/data/pct-centerline.geojson"

log = logging.getLogger(__name__)


def fetch_centerline() -> list[list[float]]:
    """Fetch PCT centerline as [[lng, lat], ...] directly from the tracker site."""
    log.info("Fetching PCT centerline...")
    raw = fetch_url(CENTERLINE_URL)
    geojson = json.loads(raw)
    if geojson.get("type") == "FeatureCollection":
        geojson = geojson["features"][0]
    coords = geojson["geometry"]["coordinates"]
    log.info(f"Centerline: {len(coords)} coords")
    return coords


def sample_coords(coords: list[list[float]], n: int) -> list[list[float]]:
    """Evenly sample up to n coordinates, rounded to 4 decimal places."""
    if len(coords) <= n:
        return [[round(c[0], 4), round(c[1], 4)] for c in coords]
    indices = [int(i * (len(coords) - 1) / (n - 1)) for i in range(n)]
    return [[round(coords[i][0], 4), round(coords[i][1], 4)] for i in indices]


def build_map_url(lat: float, lng: float, current_mile: float, mapbox_token: str) -> str:
    coords = fetch_centerline()

    total = len(coords)
    split_idx = max(2, min(total - 2, int(total * current_mile / 2650)))
    completed_raw, remaining_raw = coords[:split_idx], coords[split_idx:]

    # 80 total points keeps the URL under Slack's 3000-char image_url limit
    completed_budget = max(15, int(80 * len(completed_raw) / total))
    remaining_budget = 80 - completed_budget

    def make_url(c: list[list[float]], r: list[list[float]]) -> str:
        geojson_str = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": r},
                        "properties": {"stroke": "#C5C9BC", "stroke-width": 2},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": c},
                        "properties": {"stroke": "#B55119", "stroke-width": 4},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "properties": {"marker-color": "#8D2B00", "marker-size": "large"},
                    },
                ],
            },
            separators=(",", ":"),
        )
        encoded = urllib.parse.quote(geojson_str)
        return (
            f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/"
            f"geojson({encoded})/{lng},{lat},8,0/700x380@2x"
            f"?access_token={mapbox_token}"
        )

    completed = sample_coords(completed_raw, completed_budget)
    remaining = sample_coords(remaining_raw, remaining_budget)
    url = make_url(completed, remaining)

    if len(url) > 3000:
        log.warning(f"Map URL too long ({len(url)} chars), reducing points")
        completed = sample_coords(completed_raw, max(8, completed_budget // 2))
        remaining = sample_coords(remaining_raw, remaining_budget // 2)
        url = make_url(completed, remaining)

    log.info(f"Map URL: {len(url)} chars")
    return url
