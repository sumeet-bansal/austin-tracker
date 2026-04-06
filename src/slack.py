"""Slack API and Block Kit message construction."""

import json
import logging
import re
import sys
import urllib.error
import urllib.request

from src.formatter import format_timestamp
from src.types import Post

log = logging.getLogger(__name__)


def build_blocks(
    stats_text: str,
    tracker_url: str,
    posts: list[Post] | None = None,
    map_url: str | None = None,
) -> list[dict]:
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": stats_text}}]

    # Map comes right after stats
    if map_url:
        blocks.append({
            "type": "image",
            "image_url": map_url,
            "alt_text": "Austin's current location on the PCT",
        })

    # Trail updates — full post with blockquoted body and photo
    for post in (posts or [])[:3]:
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
            blocks.append({
                "type": "image",
                "image_url": photo_url,
                "alt_text": title,
            })

        # Blockquoted body
        if body and not body.startswith("$"):
            # Slack mrkdwn uses *text* for bold — convert markdown *text* to _text_ for italics
            body = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'_\1_', body)
            # Convert markdown headers to Slack bold
            body = re.sub(r'^#{1,6}\s*(.+)$', r'*\1*', body, flags=re.MULTILINE)
            quoted_lines: list[str] = []
            for line in body.split("\n"):
                quoted_lines.append(f"> {line}" if line.strip() else ">")
            quoted = "\n".join(quoted_lines)
            # Slack section text limit is 3000 chars — split across blocks if needed
            while quoted:
                chunk = quoted[:3000]
                if len(quoted) > 3000:
                    # Split at a line boundary
                    last_nl = chunk.rfind("\n")
                    if last_nl > 0:
                        chunk = quoted[:last_nl]
                    quoted = quoted[len(chunk):].lstrip("\n")
                else:
                    quoted = ""
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

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
