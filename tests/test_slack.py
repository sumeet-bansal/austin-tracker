"""Tests for Slack Block Kit message construction."""

from src.slack import build_blocks


TRACKER_URL = "https://hike.austinscarter.com/"


def _post(body: str = "", **kwargs) -> dict:
    defaults = {
        "id": "abc123",
        "title": "Test Post",
        "trail_mile": 100,
        "created_at": "2026-04-05T19:00:00+00:00",
        "body": body,
        "photo_url": None,
    }
    defaults.update(kwargs)
    return defaults


def _body_texts(blocks: list[dict]) -> list[str]:
    """Extract section text from body blocks (skip stats/header sections)."""
    texts = []
    for b in blocks:
        if b["type"] == "section":
            text = b["text"]["text"]
            # Body blocks start with >
            if text.startswith(">"):
                texts.append(text)
    return texts


# --- blockquote formatting ---


def test_body_is_blockquoted():
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post("Hello world")])
    body_texts = _body_texts(blocks)
    assert len(body_texts) == 1
    assert body_texts[0].startswith("> Hello world")


def test_source_blockquotes_become_nested():
    """Lines starting with > in source body should render as nested blockquotes."""
    body = "> Trail magic (noun)\n> A kind act for hikers\n\nGreat day on trail."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    body_texts = _body_texts(blocks)
    combined = "\n".join(body_texts)
    # Source blockquotes become nested (> > text)
    assert "> > Trail magic (noun)" in combined
    assert "> > A kind act for hikers" in combined
    # Regular text is still single-blockquoted
    assert "> Great day on trail." in combined


def test_markdown_headers_become_bold():
    """Markdown ### headers should become Slack bold."""
    body = "### Day 4\nStarted hiking early.\n## Day 5\nPushed for 20 miles."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    body_texts = _body_texts(blocks)
    combined = "\n".join(body_texts)
    assert "> *Day 4*" in combined
    assert "> *Day 5*" in combined
    assert "###" not in combined


def test_markdown_italic_converted():
    """Markdown *text* should become Slack _text_ italic."""
    body = "It was a *steep* descent."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    body_texts = _body_texts(blocks)
    assert "> It was a _steep_ descent." in body_texts[0]


def test_dollar_body_skipped():
    """Bodies starting with $ are placeholder refs and should be skipped."""
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post("$11")])
    body_texts = _body_texts(blocks)
    assert body_texts == []


def test_long_body_split_across_blocks():
    """Bodies > 3000 chars should be split across multiple section blocks."""
    # Use multi-line body so the splitter can find line boundaries
    body = "\n".join(["Line " + str(i) for i in range(500)])
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    body_texts = _body_texts(blocks)
    assert len(body_texts) >= 2


def test_only_recent_posts_shown():
    """build_blocks caps at 3 posts maximum."""
    posts = [_post(f"Post {i}") for i in range(5)]
    blocks = build_blocks("stats", TRACKER_URL, posts=posts)
    # Count dividers — one per post
    dividers = [b for b in blocks if b["type"] == "divider"]
    assert len(dividers) == 3


def test_single_post_produces_single_update():
    """A single post should produce exactly one trail update section."""
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post("Solo update")])
    dividers = [b for b in blocks if b["type"] == "divider"]
    assert len(dividers) == 1
    body_texts = _body_texts(blocks)
    assert len(body_texts) == 1


def test_no_posts_no_dividers():
    """No posts means no trail update sections."""
    blocks = build_blocks("stats", TRACKER_URL, posts=[])
    dividers = [b for b in blocks if b["type"] == "divider"]
    assert dividers == []
