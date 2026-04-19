"""Convert Markdown to Slack Block Kit rich_text blocks.

Source content is Austin's trail journal (Markdown-ish prose). We emit `rich_text`
blocks rather than mrkdwn sections so bold/italic/links/nested quotes render
correctly — see the `slack-blockkit-mrkdwn-vs-richtext` skill for background.

Design choices
--------------
- Top-level paragraphs and headings are wrapped in an outer `rich_text_quote`
  (no `border`), preserving the visual "post excerpt" bar the daily posts have
  always had.
- Source blockquotes become a SIBLING `rich_text_quote` with `border: 1`
  (Slack's nested-quote idiom — `rich_text_quote` cannot be nested inside
  another `rich_text_quote`, the API rejects that).
- Anything deeper than two levels of nesting flattens to `border: 1` because
  Slack's own client only renders two levels.
- Headings have no rich_text equivalent; rendered as bold inline text.
- Multiple blocks chunked by approximate serialized size to respect Slack's
  per-block limit.
"""

from __future__ import annotations

import json

import mistune

_MAX_BLOCK_CHARS = 2800  # conservative vs Slack's 3000 char/block text limit


def markdown_to_rich_text_blocks(md_text: str) -> list[dict]:
    """Return a list of Block Kit `rich_text` blocks for the given Markdown."""
    parser = mistune.create_markdown(renderer=None)
    tokens = parser(md_text)
    # mistune's return type is `str | list[dict]`; renderer=None always gives the list
    assert isinstance(tokens, list)
    elements = _convert_body(tokens)
    return _chunk_into_blocks(elements)


# ---------- top level ----------


def _convert_body(tokens: list[dict]) -> list[dict]:
    """Walk top-level block tokens. Accumulate paragraphs/headings into an outer
    `rich_text_quote` (no border); emit source blockquotes as `border: 1` siblings.
    Very long outer runs are split across multiple outer quotes to stay under
    the Slack per-block size limit.
    """
    out: list[dict] = []
    outer: list[dict] = []

    def flush_outer() -> None:
        nonlocal outer
        if outer:
            out.append({"type": "rich_text_quote", "elements": _strip_trailing_ws(outer)})
            outer = []

    for tok in tokens:
        ttype = tok.get("type")

        if ttype == "paragraph":
            _append_paragraph(outer, tok)
        elif ttype == "heading":
            _append_heading(outer, tok)
        elif ttype == "block_quote":
            flush_outer()
            source = _flatten_source_quote(tok)
            if source:
                out.append(source)
        elif ttype in ("blank_line", "thematic_break"):
            continue
        elif ttype == "block_code":
            flush_outer()
            code_text = tok.get("raw", "")
            out.append(
                {
                    "type": "rich_text_preformatted",
                    "elements": [{"type": "text", "text": code_text}],
                }
            )
        elif ttype == "list":
            flush_outer()
            out.append(_convert_list(tok))
        else:
            # Unknown block — fall back to treating it like a paragraph if it has children
            children = tok.get("children")
            if children:
                _append_paragraph(outer, tok)

        # If the outer buffer is getting close to the per-block limit, flush it
        # so the chunker has a fresh element boundary to split on.
        if _approx_size({"type": "rich_text_quote", "elements": outer}) > _MAX_BLOCK_CHARS:
            flush_outer()

    flush_outer()
    return out


def _append_paragraph(outer: list[dict], tok: dict) -> None:
    if outer:
        outer.append({"type": "text", "text": "\n\n"})
    outer.extend(_convert_inline(tok.get("children", [])))


def _append_heading(outer: list[dict], tok: dict) -> None:
    if outer:
        outer.append({"type": "text", "text": "\n\n"})
    outer.extend(_bold(_convert_inline(tok.get("children", []))))


# ---------- source blockquotes ----------


def _flatten_source_quote(tok: dict) -> dict | None:
    """Collapse a source block_quote (and any nested block_quotes inside it) into
    a single `border: 1` `rich_text_quote`. Slack caps visual nesting at two
    levels, so there is nothing to gain from emitting separate siblings for
    depth ≥ 3.
    """
    buffer: list[dict] = []
    _collect_quote_inline(tok, buffer, first=True)
    buffer = _strip_trailing_ws(buffer)
    if not buffer:
        return None
    return {"type": "rich_text_quote", "border": 1, "elements": buffer}


def _collect_quote_inline(tok: dict, buffer: list[dict], first: bool) -> bool:
    """Walk a block_quote subtree, appending inline elements separated by blank
    lines. Returns the updated `first` flag (False once anything has been emitted).
    """
    for child in tok.get("children", []):
        ctype = child.get("type")
        if ctype == "paragraph":
            if not first:
                buffer.append({"type": "text", "text": "\n\n"})
            buffer.extend(_convert_inline(child.get("children", [])))
            first = False
        elif ctype == "heading":
            if not first:
                buffer.append({"type": "text", "text": "\n\n"})
            buffer.extend(_bold(_convert_inline(child.get("children", []))))
            first = False
        elif ctype == "block_quote":
            first = _collect_quote_inline(child, buffer, first=first)
        elif ctype in ("blank_line", "thematic_break"):
            continue
        elif ctype == "block_code":
            if not first:
                buffer.append({"type": "text", "text": "\n\n"})
            buffer.append({"type": "text", "text": child.get("raw", ""), "style": {"code": True}})
            first = False
        elif ctype == "list":
            # Inside a quote we have to inline the list as text — rich_text_list
            # can't live inside rich_text_quote.
            lines = _list_to_plaintext(child)
            if lines:
                if not first:
                    buffer.append({"type": "text", "text": "\n"})
                buffer.append({"type": "text", "text": lines})
                first = False
    return first


def _list_to_plaintext(tok: dict) -> str:
    """Minimal list flattener for lists that appear inside blockquotes."""
    ordered = (tok.get("attrs") or {}).get("ordered", False)
    lines: list[str] = []
    for i, item in enumerate(tok.get("children", []), start=1):
        marker = f"{i}. " if ordered else "• "
        text_parts: list[str] = []
        for child in item.get("children", []):
            if child.get("type") in ("block_text", "paragraph"):
                for inline in child.get("children", []):
                    text_parts.append(inline.get("raw", ""))
        lines.append(marker + "".join(text_parts))
    return "\n".join(lines)


# ---------- inline ----------


def _convert_inline(children: list[dict]) -> list[dict]:
    out: list[dict] = []
    for ch in children:
        ctype = ch.get("type")
        if ctype == "text":
            out.append({"type": "text", "text": ch.get("raw", "")})
        elif ctype == "strong":
            out.extend(_styled(_convert_inline(ch.get("children", [])), bold=True))
        elif ctype == "emphasis":
            out.extend(_styled(_convert_inline(ch.get("children", [])), italic=True))
        elif ctype == "strikethrough":
            out.extend(_styled(_convert_inline(ch.get("children", [])), strike=True))
        elif ctype == "codespan":
            out.append({"type": "text", "text": ch.get("raw", ""), "style": {"code": True}})
        elif ctype == "link":
            url = (ch.get("attrs") or {}).get("url", "")
            inner = _convert_inline(ch.get("children", []))
            text = "".join(el.get("text", "") for el in inner if el.get("type") == "text")
            if not text:
                text = url
            out.append({"type": "link", "url": url, "text": text})
        elif ctype == "image":
            # Rich text has no inline image element — fall back to link or alt text
            url = (ch.get("attrs") or {}).get("url", "")
            alt = "".join(c.get("raw", "") for c in ch.get("children", []) if c.get("type") == "text")
            if url:
                out.append({"type": "link", "url": url, "text": alt or url})
            elif alt:
                out.append({"type": "text", "text": alt})
        elif ctype in ("linebreak", "softbreak"):
            out.append({"type": "text", "text": "\n"})
        else:
            raw = ch.get("raw")
            if raw:
                out.append({"type": "text", "text": raw})
    return _merge_adjacent_text(out)


def _styled(elements: list[dict], **flags: bool) -> list[dict]:
    for el in elements:
        if el.get("type") == "text":
            style = dict(el.get("style") or {})
            style.update({k: v for k, v in flags.items() if v})
            el["style"] = style
    return elements


def _bold(elements: list[dict]) -> list[dict]:
    return _styled(elements, bold=True)


def _merge_adjacent_text(elements: list[dict]) -> list[dict]:
    """Merge consecutive `text` elements with identical style to reduce block size."""
    out: list[dict] = []
    for el in elements:
        if out and el.get("type") == "text" and out[-1].get("type") == "text":
            prev = out[-1]
            if prev.get("style") == el.get("style"):
                prev["text"] = prev.get("text", "") + el.get("text", "")
                continue
        out.append(el)
    return out


def _strip_trailing_ws(elements: list[dict]) -> list[dict]:
    while elements and elements[-1].get("type") == "text":
        text = elements[-1].get("text", "")
        if text.strip() == "":
            elements.pop()
        else:
            elements[-1]["text"] = text.rstrip()
            break
    return elements


# ---------- lists (top-level) ----------


def _convert_list(tok: dict) -> dict:
    ordered = (tok.get("attrs") or {}).get("ordered", False)
    items: list[dict] = []
    for item in tok.get("children", []):
        item_elements: list[dict] = []
        for child in item.get("children", []):
            ctype = child.get("type")
            if ctype in ("block_text", "paragraph"):
                item_elements.extend(_convert_inline(child.get("children", [])))
        items.append({"type": "rich_text_section", "elements": item_elements})
    block: dict = {
        "type": "rich_text_list",
        "style": "ordered" if ordered else "bullet",
        "elements": items,
    }
    return block


# ---------- chunking ----------


def _chunk_into_blocks(elements: list[dict]) -> list[dict]:
    if not elements:
        return []
    # First, split any element that is itself larger than the per-block limit
    # (a single paragraph of ~3k+ chars, etc.) into multiple same-kind siblings.
    split_elements: list[dict] = []
    for el in elements:
        split_elements.extend(_split_oversized(el))

    blocks: list[dict] = []
    current: list[dict] = []
    current_size = 0
    for el in split_elements:
        size = _approx_size(el)
        if current and current_size + size > _MAX_BLOCK_CHARS:
            blocks.append({"type": "rich_text", "elements": current})
            current = []
            current_size = 0
        current.append(el)
        current_size += size
    if current:
        blocks.append({"type": "rich_text", "elements": current})
    return blocks


def _split_oversized(el: dict) -> list[dict]:
    """If an element's serialized size exceeds the per-block limit, split it into
    multiple same-kind siblings by peeling inline children. Preserves `border`.
    """
    if _approx_size(el) <= _MAX_BLOCK_CHARS:
        return [el]

    if el.get("type") not in ("rich_text_quote", "rich_text_section"):
        # Can't easily split lists or code blocks; return as-is and hope for the best
        return [el]

    template: dict = {"type": el["type"]}
    if "border" in el:
        template["border"] = el["border"]

    children = el.get("elements", [])
    out: list[dict] = []
    bucket: list[dict] = []
    bucket_size = 0

    def flush() -> None:
        nonlocal bucket, bucket_size
        if bucket:
            out.append({**template, "elements": _strip_trailing_ws(bucket)})
            bucket = []
            bucket_size = 0

    for child in children:
        csize = _approx_size(child)
        # If a single inline child is itself too large, split its text at newline/space
        if csize > _MAX_BLOCK_CHARS and child.get("type") == "text":
            flush()
            out.extend({**template, "elements": [piece]} for piece in _split_text_element(child))
            continue
        if bucket and bucket_size + csize > _MAX_BLOCK_CHARS:
            flush()
        bucket.append(child)
        bucket_size += csize

    flush()
    return out or [el]


def _split_text_element(text_el: dict) -> list[dict]:
    """Break a too-long text element into pieces at paragraph/line/word boundaries."""
    text = text_el.get("text", "")
    style = text_el.get("style")
    limit = _MAX_BLOCK_CHARS - 200  # headroom for JSON overhead and quote wrapper
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # Prefer splitting at a paragraph break, then a line break, then a space
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)

    out: list[dict] = []
    for piece in pieces:
        part: dict = {"type": "text", "text": piece}
        if style:
            part["style"] = style
        out.append(part)
    return out


def _approx_size(el: object) -> int:
    """Serialized byte length — used only to decide when to chunk."""
    return len(json.dumps(el, ensure_ascii=False))
