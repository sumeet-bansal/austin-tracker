#!/usr/bin/env python3
"""
Austin PCT Tracker — weekly Slack update service.

Scrapes hike.austinscarter.com (Next.js SSR, no public API) and posts a
week-in-review message to #austin-tracker. Stateless — no persistence needed
since the website always has current data.

Environment variables:
  SLACK_BOT_TOKEN   Required. xoxb-... bot token with chat:write scope.
  SLACK_CHANNEL_ID  Required. Channel to post to (e.g. C0123456789).
  MAPBOX_TOKEN      Optional. Enables trail progress map in the message.
"""

import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TRACKER_URL = "https://hike.austinscarter.com/"
CENTERLINE_URL = "https://hike.austinscarter.com/data/pct-centerline.geojson"
MAX_FETCH_RETRIES = 3
FETCH_RETRY_DELAY = 5  # seconds between retries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def get_config() -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    mapbox_token = os.environ.get("MAPBOX_TOKEN", "").strip()

    if not token:
        log.error("SLACK_BOT_TOKEN is not set")
        sys.exit(1)
    if not channel:
        log.error("SLACK_CHANNEL_ID is not set")
        sys.exit(1)

    return {"token": token, "channel": channel, "mapbox_token": mapbox_token}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as e:
            log.warning(f"Fetch attempt {attempt}/{MAX_FETCH_RETRIES} failed: {e}")
            if attempt < MAX_FETCH_RETRIES:
                time.sleep(FETCH_RETRY_DELAY)
    log.error(f"All {MAX_FETCH_RETRIES} fetch attempts failed for {url}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_data(html: str) -> dict:
    """
    Extract stats from the React flight JSON and rendered HTML.

    Next.js App Router embeds SSR props in __next_f.push([1, "..."]) script tags.
    Inside that JS string, double quotes are escaped as \\", so patterns use \\\\?".
    Rendered HTML stats (the visible divs) are parsed separately — no escaping there.
    """
    data: dict = {}
    warnings = []

    # --- React flight payload (escaped JSON) ---

    mile_match = re.search(r'currentMile\\?":(\d+\.?\d*)', html)
    if mile_match:
        data["current_mile"] = float(mile_match.group(1))
    else:
        warnings.append("current_mile not found in flight payload")

    pos_match = re.search(
        r'currentPosition\\?":\{\\?"lat\\?":(-?\d+\.?\d*),\\?"lng\\?":(-?\d+\.?\d*)\}',
        html,
    )
    if pos_match:
        data["lat"] = float(pos_match.group(1))
        data["lng"] = float(pos_match.group(2))
    else:
        warnings.append("currentPosition not found in flight payload")

    # Posts array — bracket-depth counter handles nested objects correctly.
    posts_start = html.find('posts\\":[')
    if posts_start == -1:
        posts_start = html.find('posts":[')
    if posts_start != -1:
        bracket_start = html.index("[", posts_start)
        depth, bracket_end = 0, bracket_start
        for i, ch in enumerate(html[bracket_start:], bracket_start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    bracket_end = i
                    break
        raw = html[bracket_start : bracket_end + 1].replace('\\"', '"').replace("\\\\", "\\")
        try:
            data["posts"] = json.loads(raw)
        except json.JSONDecodeError as e:
            warnings.append(f"posts JSON parse failed: {e}")
            data["posts"] = []
    else:
        data["posts"] = []

    # --- Rendered HTML stats (no escaping) ---

    day_match = re.search(r">Day (\d+)<", html)
    if day_match:
        data["day"] = int(day_match.group(1))
    else:
        warnings.append("day not found in rendered HTML")

    pace_match = re.search(r">(\d+\.?\d*)</div>\s*<div[^>]*>mi/day avg<", html)
    if pace_match:
        data["pace_mi_per_day"] = float(pace_match.group(1))

    elev_match = re.search(r">([0-9.]+k? ft)</div>\s*<div[^>]*>elevation gain<", html)
    if elev_match:
        data["elevation_gain_display"] = elev_match.group(1)

    pct_match = re.search(r">(\d+\.?\d*)%</div>\s*<div[^>]*>complete<", html)
    if pct_match:
        data["pct_complete"] = float(pct_match.group(1))

    for w in warnings:
        log.warning(f"Parse warning: {w}")

    if "current_mile" not in data and "day" not in data:
        log.error("No critical fields parsed — site structure may have changed")
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_message(data: dict) -> str:
    miles = data.get("current_mile", 0)
    day = data.get("day", "?")
    pct = data.get("pct_complete", 0)
    pace = data.get("pace_mi_per_day", 0)
    elev = data.get("elevation_gain_display", "?")
    posts = data.get("posts", [])

    lines = [
        ":hikege: *Austin's PCT Week in Review*",
        "",
        f"*Miles hiked:* {miles:.1f} of 2,650 ({pct:.1f}% complete)",
        f"*Day on trail:* Day {day}",
        f"*Avg pace:* {pace} mi/day",
        f"*Elevation gain:* {elev}",
    ]

    # Posts schema: id, title, trail_mile, photo_url, created_at
    if posts:
        lines += ["", f"*Trail updates ({len(posts)}):*"]
        for post in posts[-3:]:
            title = post.get("title", "Update")
            trail_mile = post.get("trail_mile")
            post_id = post.get("id")
            mile_str = f" _(mile {int(float(trail_mile))})_" if trail_mile else ""
            link = f"<{TRACKER_URL}post/{post_id}|{title}>" if post_id else title
            lines.append(f"  • {link}{mile_str}")
    else:
        lines += ["", "No trail updates yet."]

    lines += ["", f"<{TRACKER_URL}|Follow along on his tracker>"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def fetch_centerline() -> list:
    """Fetch PCT centerline as [[lng, lat], ...] directly from the tracker site."""
    log.info("Fetching PCT centerline...")
    raw = fetch_url(CENTERLINE_URL)
    geojson = json.loads(raw)
    if geojson.get("type") == "FeatureCollection":
        geojson = geojson["features"][0]
    coords = geojson["geometry"]["coordinates"]
    log.info(f"Centerline: {len(coords)} coords")
    return coords


def sample_coords(coords: list, n: int) -> list:
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

    def make_url(c, r):
        geojson_str = json.dumps({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": r},
                 "properties": {"stroke": "#C5C9BC", "stroke-width": 2}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": c},
                 "properties": {"stroke": "#B55119", "stroke-width": 4}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]},
                 "properties": {"marker-color": "#8D2B00", "marker-size": "large"}},
            ],
        }, separators=(",", ":"))
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


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def build_blocks(text: str, map_url: str | None = None) -> list:
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if map_url:
        blocks.append({
            "type": "image",
            "image_url": map_url,
            "alt_text": "Austin's current location on the PCT",
        })
    return blocks


def slack_api(endpoint: str, payload: dict, token: str) -> dict:
    req = urllib.request.Request(
        f"https://slack.com/api/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as e:
        log.error(f"Slack API {endpoint} failed: {e}")
        sys.exit(1)
    if not body.get("ok"):
        log.error(f"Slack API {endpoint} error: {body.get('error', 'unknown')}")
        sys.exit(1)
    return body


def post_to_slack(text: str, blocks: list, token: str, channel: str):
    body = slack_api("chat.postMessage", {"channel": channel, "text": text, "blocks": blocks}, token)
    log.info(f"Posted to Slack channel {channel} (ts={body.get('ts')})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = get_config()
    log.info("Starting Austin PCT tracker update")

    data = extract_data(fetch_url(TRACKER_URL).decode("utf-8"))
    log.info(f"Parsed: mile={data.get('current_mile')}, day={data.get('day')}, posts={len(data.get('posts', []))}")

    message = format_message(data)

    map_url = None
    if data.get("lat") and data.get("lng") and config["mapbox_token"]:
        map_url = build_map_url(data["lat"], data["lng"], data.get("current_mile", 0), config["mapbox_token"])

    blocks = build_blocks(message, map_url)
    post_to_slack(message, blocks, config["token"], config["channel"])

    log.info("Done")


if __name__ == "__main__":
    main()
