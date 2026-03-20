#!/usr/bin/env python3
"""
Austin PCT Tracker — daily Slack update service.

Scrapes hike.austinscarter.com (Next.js SSR, no public API) and posts to
#austin-tracker. Runs daily at noon ET — posts whenever there are new trail
updates (created in the last 25 hours), and always on Fridays regardless.
Stateless — no persistence needed since the website always has current data.

Environment variables:
  SLACK_BOT_TOKEN   Required. xoxb-... bot token with chat:write scope.
  SLACK_CHANNEL_ID  Required. Channel to post to (e.g. C0123456789).
  MAPBOX_TOKEN      Optional. Enables trail progress map in the message.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from formatter import format_fallback, format_stats
from map import build_map_url
from scraper import extract_data, fetch_post_body, fetch_url
from slack import build_blocks, post_to_slack

TRACKER_URL = "https://hike.austinscarter.com/"
PACIFIC = ZoneInfo("America/Los_Angeles")

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


def has_recent_posts(posts: list, hours: int = 25) -> bool:
    """Check if any posts were created within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for post in posts:
        created = post.get("created_at", "")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(created)
            if dt >= cutoff:
                return True
        except (ValueError, TypeError):
            continue
    return False


def main():
    config = get_config()
    log.info("Starting Austin PCT tracker update")

    data = extract_data(fetch_url(TRACKER_URL).decode("utf-8"))
    posts = data.get("posts", [])
    log.info(f"Parsed: mile={data.get('current_mile')}, day={data.get('day')}, posts={len(posts)}")

    now_pt = datetime.now(PACIFIC)
    is_friday = now_pt.weekday() == 4

    if not is_friday and not has_recent_posts(posts):
        log.info("No new trail updates and not Friday — skipping post")
        return

    # Fetch full body text for recent posts
    for post in posts[-3:]:
        post_id = post.get("id")
        body = post.get("body", "")
        if post_id and (not body or body.startswith("$")):
            fetched = fetch_post_body(post_id, TRACKER_URL)
            if fetched:
                post["body"] = fetched

    stats_text = format_stats(data, TRACKER_URL)
    fallback = format_fallback(data, TRACKER_URL)

    map_url = None
    if data.get("lat") and data.get("lng") and config["mapbox_token"]:
        map_url = build_map_url(data["lat"], data["lng"], data.get("current_mile", 0), config["mapbox_token"])

    blocks = build_blocks(stats_text, TRACKER_URL, posts=posts, map_url=map_url)
    post_to_slack(fallback, blocks, config["token"], config["channel"])

    log.info("Done")


if __name__ == "__main__":
    main()
