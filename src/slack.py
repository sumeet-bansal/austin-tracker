"""Slack API and Block Kit message construction."""

import json
import logging
import sys
import urllib.error
import urllib.request

from src.formatter import format_timestamp
from src.markdown_to_richtext import markdown_to_rich_text_blocks
from src.types import Post

log = logging.getLogger(__name__)

# Slack rejects messages whose blocks cumulatively exceed ~13k chars with
# `msg_blocks_too_long`. The budget scales with how many posts have bodies and
# whether the map image block is included, so single-post non-map days get the
# most room for long trail-journal excerpts.
_CUMULATIVE_JSON_BUDGET = 13000
_STATS_RESERVE = 500  # mrkdwn stats section
_MAP_RESERVE = 2300  # image block with Mapbox URL (~2000 chars)
_PER_POST_RESERVE = 500  # divider + mrkdwn header + optional photo block
_RICH_TEXT_JSON_INFLATION = 1.12  # rich_text is ~12% more verbose than plain text


def build_blocks(
    stats_text: str,
    tracker_url: str,
    posts: list[Post] | None = None,
    map_url: str | None = None,
) -> list[dict]:
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": stats_text}}]

    # Map comes right after stats
    if map_url:
        blocks.append(
            {
                "type": "image",
                "image_url": map_url,
                "alt_text": "Austin's current location on the PCT",
            }
        )

    included = list((posts or [])[:3])
    body_count = sum(1 for p in included if p.get("body") and not p.get("body", "").startswith("$"))
    per_post_budget = _per_post_body_budget(body_count, has_map=bool(map_url))

    # Trail updates — full post with blockquoted body and photo
    for post in included:
        post_id = post.get("id")
        title = post.get("title", "Update")
        trail_mile = post.get("trail_mile")
        created = post.get("created_at", "")
        body = post.get("body", "")
        photo_url = post.get("photo_url")

        blocks.append({"type": "divider"})

        # Header linking to the post
        post_url = f"{tracker_url}post/{post_id}" if post_id else tracker_url
        meta_parts: list[str] = []
        if trail_mile:
            meta_parts.append(f"Mile {round(float(trail_mile))}")
        date_str = format_timestamp(created)
        if date_str:
            meta_parts.append(date_str)
        header = f"*<{post_url}|{title}>*"
        if meta_parts:
            header += f"\n_{' · '.join(meta_parts)}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header}})

        # Photo before body text
        if photo_url:
            blocks.append(
                {
                    "type": "image",
                    "image_url": photo_url,
                    "alt_text": title,
                }
            )

        # Blockquoted body — rendered via rich_text blocks (see
        # slack-blockkit-mrkdwn-vs-richtext skill for why not mrkdwn).
        if body and not body.startswith("$"):
            truncated = _truncate_body(body, post_url, per_post_budget)
            blocks.extend(markdown_to_rich_text_blocks(truncated))

    return blocks


def _per_post_body_budget(num_posts_with_body: int, has_map: bool) -> int:
    """Max body text chars per post to keep cumulative blocks JSON under Slack's limit."""
    if num_posts_with_body <= 0:
        return 0
    overhead = _STATS_RESERVE + (_MAP_RESERVE if has_map else 0) + _PER_POST_RESERVE * num_posts_with_body
    body_json_budget = _CUMULATIVE_JSON_BUDGET - overhead
    body_text_budget = int(body_json_budget / _RICH_TEXT_JSON_INFLATION)
    return max(1000, body_text_budget // num_posts_with_body)


def _truncate_body(body: str, post_url: str, max_chars: int) -> str:
    """Cap a post body at max_chars, cutting at a paragraph/line/word boundary
    and appending a linked marker so readers know to follow to the full post.
    """
    if len(body) <= max_chars:
        return body
    cut = body.rfind("\n\n", 0, max_chars)
    if cut <= max_chars // 2:
        cut = body.rfind("\n", 0, max_chars)
    if cut <= max_chars // 2:
        cut = body.rfind(" ", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    return body[:cut].rstrip() + f"\n\n… _[continued on the tracker]({post_url})_"


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


def post_to_slack(text: str, blocks: list[dict], token: str, channel: str) -> None:
    payload = {
        "channel": channel,
        "text": text,
        "blocks": blocks,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    body = slack_api("chat.postMessage", payload, token)
    log.info(f"Posted to Slack channel {channel} (ts={body.get('ts')})")
