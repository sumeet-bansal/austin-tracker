#!/usr/bin/env python3
"""
Austin PCT Tracker — daily Slack update service.

Scrapes hike.austinscarter.com (Next.js SSR, no public API) and posts to
#austin-tracker. Runs daily — posts whenever there are new trail updates
(created in the last 25 hours). On Fridays, always posts a stats summary
(with map) even if there are no new trail updates. Only includes trail
updates that are actually recent. Stateless — no persistence needed since
the website always has current data.

Environment variables:
  SLACK_BOT_TOKEN   Required. xoxb-... bot token with chat:write scope.
  SLACK_CHANNEL_ID  Required. Channel to post to (e.g. C0123456789).
  MAPBOX_TOKEN      Optional. Enables trail progress map in the message.
"""

import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.formatter import format_fallback, format_stats
from src.map import build_map_url
from src.scraper import extract_data, fetch_post_body, fetch_url
from src.slack import build_blocks, post_to_slack
from src.types import Config, Post, PostDecision

TRACKER_URL = "https://hike.austinscarter.com/"
PACIFIC = ZoneInfo("America/Los_Angeles")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def get_config() -> Config:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    mapbox_token = os.environ.get("MAPBOX_TOKEN", "").strip()

    if not token:
        log.error("SLACK_BOT_TOKEN is not set")
        sys.exit(1)
    if not channel:
        log.error("SLACK_CHANNEL_ID is not set")
        sys.exit(1)

    return Config(token=token, channel=channel, mapbox_token=mapbox_token)


def recent_posts(posts: list[Post], now: datetime, hours: int = 25) -> list[Post]:
    """Return only posts created within the last N hours."""
    cutoff = now - timedelta(hours=hours)
    result = []
    for post in posts:
        created = post.get("created_at", "")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(created)
            if dt >= cutoff:
                result.append(post)
        except (ValueError, TypeError):
            continue
    return result


def decide_post(posts: list[Post], now: datetime) -> PostDecision:
    """Determine whether to post and what to include.

    Rules:
    - Recent trail update (last 25h) → post stats + trail updates
    - Friday, no recent update → post stats only (weekly summary)
    - Not Friday, no recent update → skip
    """
    is_friday = now.astimezone(PACIFIC).weekday() == 4
    recent = recent_posts(posts, now)

    if not is_friday and not recent:
        return PostDecision(should_post=False, include_posts=[])

    return PostDecision(should_post=True, include_posts=recent if recent else [])


def main():
    config = get_config()
    log.info("Starting Austin PCT tracker update")

    data = extract_data(fetch_url(TRACKER_URL).decode("utf-8"))
    posts: list[Post] = data.get("posts", [])
    log.info(f"Parsed: mile={data.get('current_mile')}, day={data.get('day')}, posts={len(posts)}")

    decision = decide_post(posts, datetime.now(UTC))

    if not decision.should_post:
        log.info("No new trail updates and not Friday — skipping post")
        return

    # Fetch full body text for recent posts
    for post in decision.include_posts[:3]:
        post_id = post.get("id")
        body = post.get("body", "")
        if post_id and (not body or body.startswith("$")):
            fetched = fetch_post_body(post_id, TRACKER_URL)
            if fetched:
                post["body"] = fetched

    stats_text = format_stats(data, TRACKER_URL)
    fallback = format_fallback(data, TRACKER_URL, recent=decision.include_posts)

    map_url = None
    if data.get("lat") and data.get("lng") and config.mapbox_token:
        map_url = build_map_url(data["lat"], data["lng"], data.get("current_mile", 0), config.mapbox_token)

    blocks = build_blocks(stats_text, TRACKER_URL, posts=decision.include_posts, map_url=map_url)
    post_to_slack(fallback, blocks, config.token, config.channel)

    log.info("Done")


if __name__ == "__main__":
    main()
