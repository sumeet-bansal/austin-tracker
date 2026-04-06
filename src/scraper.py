"""Scrape hike.austinscarter.com for trail stats and post content."""

import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request

from src.types import Post, TrackerData

MAX_FETCH_RETRIES = 3
FETCH_RETRY_DELAY = 5  # seconds between retries

log = logging.getLogger(__name__)


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


def extract_data(html: str) -> TrackerData:
    """
    Extract stats from the React flight JSON and rendered HTML.

    Next.js App Router embeds SSR props in __next_f.push([1, "..."]) script tags.
    Inside that JS string, double quotes are escaped as \\", so patterns use \\\\?".
    Rendered HTML stats (the visible divs) are parsed separately — no escaping there.
    """
    data: TrackerData = {}
    warnings: list[str] = []

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


def fetch_post_body(post_id: str, tracker_url: str) -> str | None:
    """Fetch the body text for a trail update from its individual page."""
    url = f"{tracker_url}post/{post_id}"
    log.info(f"Fetching post body: {post_id}")
    try:
        html = fetch_url(url).decode("utf-8")
    except SystemExit:
        log.warning(f"Failed to fetch post {post_id}, skipping body")
        return None
    # Body text lives in a standalone flight payload chunk — the longest plain
    # text blob that isn't React component markup.
    chunks = re.findall(r'__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    best = ""
    for chunk in chunks:
        text = chunk.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\').replace('\\u003e', '>').replace('\\u003c', '<')
        # Skip chunks that are React/JS code
        if re.match(r'^\d+:', text) or text.startswith('[') or '["$"' in text[:50]:
            continue
        if len(text) > len(best):
            best = text
    return best.strip() if len(best) > 50 else None
