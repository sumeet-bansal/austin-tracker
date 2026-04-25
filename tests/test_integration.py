"""End-to-end tests: real HTML fixtures → final Slack blocks.

These tests catch the bugs that isolated unit tests miss — escape artifacts in
the Next.js flight payload, markdown rendering quirks, emoji handling, and
structural drift on hike.austinscarter.com.

Refresh fixtures when the site changes:
    uv run python -c "from src.scraper import fetch_url; \
        open('tests/fixtures/listing.html','w').write(fetch_url('https://hike.austinscarter.com/').decode())"
"""

import json
from pathlib import Path
from unittest.mock import patch

from src.scraper import extract_data, fetch_post_body
from src.slack import build_blocks

FIXTURES = Path(__file__).parent / "fixtures"
TRACKER_URL = "https://hike.austinscarter.com/"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _body_for(fixture_name: str) -> str:
    """Decode a post body via fetch_post_body, using the fixture as the fetch result."""
    html = _load(fixture_name)
    with patch("src.scraper.fetch_url", return_value=html.encode("utf-8")):
        body = fetch_post_body("dummy-id", TRACKER_URL)
    assert body is not None, f"No body decoded from {fixture_name}"
    return body


def _walk_text_elements(blocks: list) -> list[str]:
    """Collect every `text` string from every nested element in a block list."""
    texts: list[str] = []

    def recurse(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "text" and isinstance(obj.get("text"), str):
                texts.append(obj["text"])
            for v in obj.values():
                recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)

    recurse(blocks)
    return texts


# ---------- extract_data against real listing HTML ----------


def test_listing_parses_core_stats():
    data = extract_data(_load("listing.html"))
    assert data["current_mile"] > 0
    assert data["day"] > 0
    assert "lat" in data and "lng" in data
    assert len(data["posts"]) > 0


def test_listing_preserves_emoji_in_titles():
    data = extract_data(_load("listing.html"))
    titles = {p.get("title", "") for p in data["posts"]}
    # Fixture contains posts with emoji in titles — exercise that JSON decoding
    # of the embedded posts array handles unicode escapes and surrogate pairs.
    assert any("🐺" in t for t in titles), f"Expected 🐺 in some title; got {titles}"
    assert any("🧙" in t for t in titles), f"Expected 🧙 in some title; got {titles}"


def test_listing_post_shape():
    """Posts should have the fields build_blocks expects."""
    data = extract_data(_load("listing.html"))
    for post in data["posts"]:
        assert "id" in post
        assert "title" in post
        assert "created_at" in post


# ---------- fetch_post_body decodes JSON string escapes ----------


def test_body_decodes_ampersand_not_as_escape():
    """The regression we just fixed: \\u0026 must decode to & (M&Ms, not M\\u0026Ms)."""
    body = _body_for("post_sanbu.html")
    assert "M&Ms" in body
    assert "\\u0026" not in body
    assert "\\u003" not in body  # also no stray \u003c, \u003e


def test_body_has_no_residual_json_escapes():
    """No fixture body should contain literal JSON escape sequences — json.loads should decode all."""
    for fixture in ["post_sanbu.html", "post_big_bad_wolf.html", "post_raining_magic.html"]:
        body = _body_for(fixture)
        # Any \uXXXX sequence still present means decoding missed a case.
        # We look for the exact pattern `\u` followed by 4 hex chars.
        import re

        residuals = re.findall(r"\\u[0-9a-fA-F]{4}", body)
        assert residuals == [], f"{fixture}: residual JSON escapes {residuals[:5]}"


def test_emoji_in_title_survives_pipeline():
    """Surrogate pair escapes in the posts JSON (e.g. \\uD83D\\uDC3A = 🐺) must
    decode through extract_data and reach the final block header."""
    data = extract_data(_load("listing.html"))
    wolf = next(p for p in data["posts"] if "Big Bad Wolf" in p.get("title", ""))
    assert "🐺" in wolf["title"]

    wolf["body"] = _body_for("post_big_bad_wolf.html")
    blocks = build_blocks(stats_text="x", tracker_url=TRACKER_URL, posts=[wolf])
    # Header text is rendered via mrkdwn section (not rich_text text elements),
    # so check the raw block JSON for the emoji.
    raw = json.dumps(blocks, ensure_ascii=False)
    assert "🐺" in raw, "Expected 🐺 to appear in final blocks JSON"


# ---------- full pipeline: HTML → rich_text blocks ----------


def test_sanbu_pipeline_produces_correct_rich_text():
    """M&Ms reaches the final Slack payload as literal '&', not an escape."""
    body = _body_for("post_sanbu.html")
    post = {
        "id": "sanbu",
        "title": "Sànbù",
        "body": body,
        "trail_mile": 264.5,
        "created_at": "2026-04-19T20:12:30+00:00",
        "photo_url": None,
    }
    blocks = build_blocks(
        stats_text="*Miles hiked:* 421.2",
        tracker_url=TRACKER_URL,
        posts=[post],
    )
    all_text = "".join(_walk_text_elements(blocks))
    assert "M&Ms" in all_text
    assert "M\\u0026Ms" not in all_text


def test_bold_becomes_styled_text_element():
    """**BIG KIDS** should become text with style.bold=True, not literal '**'."""
    body = _body_for("post_sanbu.html")
    assert "**B I G K I D S**" in body, "Fixture sanity check — source has bold markdown"

    post = {
        "id": "sanbu",
        "title": "Sànbù",
        "body": body,
        "trail_mile": 264.5,
        "created_at": "2026-04-19T20:12:30+00:00",
        "photo_url": None,
    }
    blocks = build_blocks(stats_text="x", tracker_url=TRACKER_URL, posts=[post])

    # Find the text element(s) for "B I G K I D S" and assert bold styling
    found_bold = False

    def walk(obj):
        nonlocal found_bold
        if isinstance(obj, dict):
            if obj.get("type") == "text" and "B I G K I D S" in obj.get("text", ""):
                assert obj.get("style", {}).get("bold") is True, f"Expected bold styling on {obj}"
                found_bold = True
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(blocks)
    assert found_bold, "Did not find a text element containing 'B I G K I D S'"
    # And crucially, the literal '**' should not appear as text anywhere
    assert "**" not in "".join(_walk_text_elements(blocks))


def test_source_blockquote_produces_bordered_rich_text_quote():
    """`> Then I'll huff` in source markdown should become a rich_text_quote with border: 1."""
    body = _body_for("post_big_bad_wolf.html")
    assert body.startswith("> Then I'll huff"), "Fixture sanity check — source opens with blockquote"

    post = {
        "id": "wolf",
        "title": "The Big Bad Wolf 🐺",
        "body": body,
        "trail_mile": 166.4,
        "created_at": "2026-04-18T03:08:24+00:00",
        "photo_url": None,
    }
    blocks = build_blocks(stats_text="x", tracker_url=TRACKER_URL, posts=[post])

    # Find any rich_text_quote with border:1 — that's the one holding the source quote
    bordered = []

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "rich_text_quote" and obj.get("border") == 1:
                bordered.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(blocks)
    assert bordered, "Expected at least one rich_text_quote with border:1 for source blockquote"
    # And its content should include "Then I'll huff"
    bordered_text = "".join(_walk_text_elements(bordered))
    assert "Then I'll huff" in bordered_text


def test_full_message_under_slack_cumulative_limit():
    """End-to-end: a realistic 2-post message must serialize under Slack's ~13k char limit."""
    data = extract_data(_load("listing.html"))
    posts = []
    for fixture, pid in [
        ("post_sanbu.html", "a4abcae3-a17b-49fc-b400-68f9618384a6"),
        ("post_big_bad_wolf.html", "13bbf114-7ceb-49ac-a844-11ed38221a73"),
    ]:
        post = next((p for p in data["posts"] if p["id"] == pid), None)
        assert post is not None, f"Post {pid} not in listing fixture"
        post["body"] = _body_for(fixture)
        posts.append(post)

    blocks = build_blocks(
        stats_text="*Miles hiked:* 421.2",
        tracker_url=TRACKER_URL,
        posts=posts,
        map_url="https://api.mapbox.com/fake-url-for-size-accounting",
    )
    size = len(json.dumps(blocks, ensure_ascii=False))
    # Slack's cumulative ceiling is ~13,000 — use a conservative 12,500 in tests
    assert size < 12500, f"Blocks JSON size {size} exceeds 12,500-char safety ceiling"
