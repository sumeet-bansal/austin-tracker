"""Tests for Slack Block Kit message construction."""

from src.slack import _per_post_body_budget, _truncate_body, build_blocks

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


def _richtext_blocks(blocks: list[dict]) -> list[dict]:
    """Return only the rich_text blocks (post bodies)."""
    return [b for b in blocks if b["type"] == "rich_text"]


def _all_text(block: dict) -> str:
    """Concatenate every text string inside a rich_text block, regardless of nesting."""
    parts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") in ("text", "link"):
                parts.append(node.get("text", ""))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(block)
    return "".join(parts)


def _find_elements(block: dict, element_type: str) -> list[dict]:
    """Return every sub-element of a given type inside a block."""
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == element_type:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(block)
    return found


# --- body rendering ---


def test_source_blockquote_becomes_border_quote():
    """A `>` source quote becomes a sibling rich_text_quote with border:1."""
    body = "Intro paragraph.\n\n> Trail magic (noun)\n> A kind act for hikers\n\nClosing paragraph."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    rich = _richtext_blocks(blocks)
    quotes = _find_elements(rich[0], "rich_text_quote")
    # Outer + source + outer
    assert len(quotes) == 3
    border_quotes = [q for q in quotes if q.get("border") == 1]
    assert len(border_quotes) == 1
    assert "Trail magic" in _all_text(border_quotes[0])
    # Surrounding paragraphs are in borderless outer quotes
    outer_quotes = [q for q in quotes if "border" not in q]
    outer_text = " ".join(_all_text(q) for q in outer_quotes)
    assert "Intro paragraph." in outer_text
    assert "Closing paragraph." in outer_text


def test_nested_source_quotes_flatten_to_single_border_quote():
    """`> > text` flattens to one border:1 quote (Slack caps at 2 visual levels)."""
    body = "> Outer level\n>\n> > Inner level"
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    rich = _richtext_blocks(blocks)
    quotes = _find_elements(rich[0], "rich_text_quote")
    border_quotes = [q for q in quotes if q.get("border") == 1]
    assert len(border_quotes) == 1
    text = _all_text(border_quotes[0])
    assert "Outer level" in text
    assert "Inner level" in text


def test_markdown_headers_become_bold():
    body = "### Day 4\nStarted hiking.\n## Day 5\nPushed 20 miles."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    rich = _richtext_blocks(blocks)
    texts = _find_elements(rich[0], "text")
    bolds = [t for t in texts if (t.get("style") or {}).get("bold")]
    bold_text = " ".join(t.get("text", "") for t in bolds)
    assert "Day 4" in bold_text
    assert "Day 5" in bold_text


def test_markdown_italic_becomes_styled_text():
    body = "It was a *steep* descent."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    rich = _richtext_blocks(blocks)
    italics = [t for t in _find_elements(rich[0], "text") if (t.get("style") or {}).get("italic")]
    assert any(t.get("text") == "steep" for t in italics)


def test_markdown_link_becomes_link_element():
    body = "See my [last post](https://example.com/x) for context."
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    rich = _richtext_blocks(blocks)
    links = _find_elements(rich[0], "link")
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/x"
    assert links[0]["text"] == "last post"
    # Raw markdown link syntax must not leak
    assert "[last post]" not in _all_text(rich[0])


def test_dollar_body_skipped():
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post("$11")])
    assert _richtext_blocks(blocks) == []


def test_long_body_split_across_blocks():
    body = "\n\n".join([f"Paragraph {i} with some padding text to burn chars." for i in range(200)])
    blocks = build_blocks("stats", TRACKER_URL, posts=[_post(body)])
    assert len(_richtext_blocks(blocks)) >= 2


def test_caps_at_three_posts():
    """build_blocks slices to the first 3 posts even if more are passed in."""
    posts = [_post(f"Post {i}") for i in range(5)]
    blocks = build_blocks("stats", TRACKER_URL, posts=posts)
    assert len([b for b in blocks if b["type"] == "divider"]) == 3


# --- truncation ---


def test_short_body_not_truncated():
    body = "Just a normal-length trail update."
    out = _truncate_body(body, "https://example.com/post", max_chars=500)
    assert out == body
    assert "continued on the tracker" not in out


def test_long_body_truncated_with_marker():
    body = "\n\n".join([f"Paragraph {i} " + "pad " * 80 for i in range(40)])
    assert len(body) > 3000
    out = _truncate_body(body, "https://example.com/post/abc", max_chars=3000)
    assert len(out) < len(body)
    assert "continued on the tracker" in out
    assert "https://example.com/post/abc" in out


def test_truncation_prefers_paragraph_boundary():
    """If a \\n\\n boundary sits past max_chars//2, the cut snaps to it rather
    than mid-line — avoids truncating in the middle of a sentence."""
    first = "This is the first paragraph and it has enough characters to land past the halfway mark."
    body = f"{first}\n\nSecond paragraph that gets cut completely.\n\nThird paragraph."
    out = _truncate_body(body, "https://x.test/p", max_chars=120)
    cut_body = out.split("\n\n…")[0]
    assert cut_body == first


def test_per_post_budget_scales_with_count():
    one = _per_post_body_budget(1, has_map=False)
    two = _per_post_body_budget(2, has_map=False)
    three = _per_post_body_budget(3, has_map=False)
    assert one > two > three
    # Single post should have at least ~8k of room for long trail entries
    assert one >= 8000


def test_per_post_budget_shrinks_when_map_included():
    without = _per_post_body_budget(1, has_map=False)
    with_map = _per_post_body_budget(1, has_map=True)
    assert without > with_map
