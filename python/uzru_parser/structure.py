"""Turn raw extracted text blocks into typed document blocks."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Block, BlockType
from .text import detect_language, normalize, numbering_info, repair_hyphenation

MAX_HEADING_CHARS = 160
MAX_KEYWORD_HEADING_CHARS = 300
MAX_HEADING_LINES = 3
SHORT_UPPERCASE_CHARS = 80
LARGER_FONT_RATIO = 1.15
HEADING_SCORE = 2
BOLD_SHARE = 0.6
MIN_UPPERCASE_LETTERS = 4
MIN_LETTER_SHARE = 0.5
MAX_LEVEL = 6
CELL_SEPARATOR = " | "
MAX_CONTINUATION_CHARS = 100
SIZE_TOLERANCE = 0.5
LINE_GAP_RATIO = 1.5
MAX_TITLE_LINES = 3
SENTENCE_END = ".?!:…;"
TITLE_LINE_RATIO = 0.75

PLAN_LINE = re.compile(r"^\s*(?:reja|режа|план)\s*:", re.IGNORECASE)
FOOTNOTE_NUMBER = re.compile(r"^\s*(\d{1,3})\b")
LIST_KINDS = ("bullet", "ordered")


@dataclass
class RawBlock:
    """A block as produced by a format reader, before any interpretation.

    ``heading_level``, ``list_item`` and ``rows`` let a reader state what it already knows
    (for example from DOCX styles or detected PDF tables); the rest is inferred.
    ``role`` marks material that is not body text (``toc``, ``title_page``, ``back_matter``),
    ``footnote`` a footnote entry, and ``footnote_refs`` the reference marks that were
    removed from the text.
    """

    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None
    font_size: float | None = None
    bold: float = 0.0  # share of characters set in a bold face
    heading_level: int | None = None
    list_item: bool = False
    rows: list[list[str]] | None = None
    role: str | None = None
    footnote: bool = False
    footnote_refs: list[str] = field(default_factory=list)


def build_blocks(raw_blocks: list[RawBlock]) -> list[Block]:
    """Classify raw blocks into headings, lists, tables and paragraphs, in document order."""
    raws = [part for raw in raw_blocks for part in _split_raw(raw)]
    body_size = body_font_size(raws)
    prepared = [(raw, _clean(raw)) for raw in raws]
    heading = [
        raw.heading_level is not None
        or (_is_candidate(raw, text) and _is_heading(text, raw, body_size))
        for raw, text in prepared
    ]
    heading_sizes = sorted(
        {
            _size_key(raw.font_size)
            for (raw, _), is_heading in zip(prepared, heading, strict=True)
            if is_heading and raw.font_size and raw.heading_level is None
        },
        reverse=True,
    )

    blocks: list[Block] = []
    previous: RawBlock | None = None
    for (raw, text), is_heading in zip(prepared, heading, strict=True):
        if not text:
            continue
        if raw.rows is not None:
            blocks.append(_table_block(raw, raw.rows))
        elif raw.footnote:
            blocks.append(_footnote_block(raw, text))
        elif is_heading:
            if previous is not None and _continues_heading(blocks[-1], previous, raw, text):
                blocks[-1].text = f"{blocks[-1].text} {_flatten(text)}"
                blocks[-1].language = detect_language(blocks[-1].text)
            else:
                level = raw.heading_level or _heading_level(text, raw, heading_sizes)
                blocks.append(_block(BlockType.HEADING, _flatten(text), raw, min(level, MAX_LEVEL)))
        elif items := _list_items(text, raw.list_item):
            _append_list(blocks, items, raw)
        else:
            blocks.append(_block(BlockType.PARAGRAPH, _flatten(text), raw))
        previous = raw
    return _join_split_paragraphs(blocks)


def body_font_size(raw_blocks: list[RawBlock]) -> float | None:
    weights: Counter[float] = Counter()
    for raw in raw_blocks:
        if raw.font_size and raw.rows is None and not raw.footnote:
            weights[_size_key(raw.font_size)] += len(raw.text)
    return weights.most_common(1)[0][0] if weights else None


def _is_candidate(raw: RawBlock, text: str) -> bool:
    """Only plain body-flow text can be a heading."""
    plain = not (raw.list_item or raw.footnote or raw.role or raw.rows is not None)
    return plain and bool(text)


def _clean(raw: RawBlock) -> str:
    if raw.rows is not None:
        return _rows_text(_clean_rows(raw.rows))
    return normalize(repair_hyphenation(raw.text))


def _clean_rows(rows: list[list[str]]) -> list[list[str]]:
    """Normalize cells, then drop empty rows and columns that are empty in every row."""
    cleaned = [
        [_flatten(normalize(repair_hyphenation(cell or ""))) for cell in row] for row in rows
    ]
    cleaned = [row for row in cleaned if any(row)]
    used = [
        index
        for index in range(max((len(row) for row in cleaned), default=0))
        if any(index < len(row) and row[index] for row in cleaned)
    ]
    return [[row[index] if index < len(row) else "" for index in used] for row in cleaned]


def _rows_text(rows: list[list[str]]) -> str:
    return "\n".join(CELL_SEPARATOR.join(cell for cell in row if cell) for row in rows)


def _flatten(text: str) -> str:
    return " ".join(text.split())


def _size_key(size: float) -> float:
    return round(size * 2) / 2


def _block(block_type: BlockType, text: str, raw: RawBlock, level: int | None = None) -> Block:
    block = Block(
        type=block_type,
        text=text,
        raw_text=raw.text,
        page=raw.page,
        bbox=raw.bbox,
        level=level,
        language=detect_language(text),
    )
    if raw.role:
        block.extra["role"] = raw.role
    if raw.footnote_refs:
        block.extra["footnote_refs"] = list(raw.footnote_refs)
    return block


def _table_block(raw: RawBlock, rows: list[list[str]]) -> Block:
    rows = _clean_rows(rows)
    block = _block(BlockType.TABLE, _rows_text(rows), raw)
    block.extra["rows"] = rows
    return block


def _footnote_block(raw: RawBlock, text: str) -> Block:
    block = _block(BlockType.FOOTNOTE, _flatten(text), raw)
    if match := FOOTNOTE_NUMBER.match(text):
        block.extra["number"] = match.group(1)
    return block


def _uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    visible = sum(1 for c in text if not c.isspace())
    if len(letters) < MIN_UPPERCASE_LETTERS or len(letters) < MIN_LETTER_SHARE * visible:
        return 0.0
    return sum(c.isupper() for c in letters) / len(letters)


def _is_heading(text: str, raw: RawBlock, body_size: float | None) -> bool:
    flat = _flatten(text)
    numbering = numbering_info(flat)
    keyword = numbering is not None and numbering[0] == "keyword"
    limit = MAX_KEYWORD_HEADING_CHARS if keyword else MAX_HEADING_CHARS
    if len(flat) > limit or text.count("\n") + 1 > MAX_HEADING_LINES:
        return False
    if numbering and numbering[0] in LIST_KINDS:
        return False
    if not numbering and flat[0].islower():  # a sentence fragment, not a title
        return False
    uppercase = _uppercase_ratio(flat) >= 0.9
    wrapped_keyword = keyword and flat[-1] == ","
    if (flat[-1] in ",;" and not wrapped_keyword) or (
        flat[-1] == "." and not uppercase and not numbering
    ):
        return False

    score = 0
    if body_size and raw.font_size and raw.font_size >= body_size * LARGER_FONT_RATIO:
        score += 2
    if raw.bold >= BOLD_SHARE:
        score += 1
    if uppercase:
        score += 2 if len(flat) <= SHORT_UPPERCASE_CHARS else 1
    if numbering:
        score += 2 if keyword else 1
    return score >= HEADING_SCORE


def _heading_level(text: str, raw: RawBlock, heading_sizes: list[float]) -> int:
    numbering = numbering_info(text)
    if numbering:
        return numbering[1]
    if raw.font_size and _size_key(raw.font_size) in heading_sizes:
        return heading_sizes.index(_size_key(raw.font_size)) + 1
    return 1


def _same_style(a: RawBlock, b: RawBlock) -> bool:
    sizes_match = (a.font_size is None and b.font_size is None) or (
        a.font_size is not None
        and b.font_size is not None
        and abs(a.font_size - b.font_size) <= SIZE_TOLERANCE
    )
    return sizes_match and abs(a.bold - b.bold) <= 0.3


def _continues_heading(heading: Block, heading_raw: RawBlock, raw: RawBlock, text: str) -> bool:
    """True when ``raw`` is the wrapped second half of the heading just emitted."""
    if heading.type is not BlockType.HEADING or heading_raw.page != raw.page:
        return False
    flat = _flatten(text)
    if numbering_info(flat) or len(flat) > MAX_CONTINUATION_CHARS:
        return False
    if heading.text[-1] in ".?!" or not _same_style(heading_raw, raw):
        return False
    if heading_raw.bbox and raw.bbox:
        gap = raw.bbox[1] - heading_raw.bbox[3]
        if gap > LINE_GAP_RATIO * (raw.font_size or 12.0):
            return False
    return True


def _list_items(text: str, forced: bool) -> list[str]:
    """Split a block into list items, or return ``[]`` when it is not a list."""
    if forced:
        return [_flatten(text)]
    items: list[str] = []
    for line in text.split("\n"):
        marker = numbering_info(line)
        if marker and marker[0] in LIST_KINDS:
            items.append(line.strip())
        elif items:
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            return []
    return items


def _append_list(blocks: list[Block], items: list[str], raw: RawBlock) -> None:
    previous = blocks[-1] if blocks else None
    if previous is not None and previous.type is BlockType.LIST:
        previous.extra["items"].extend(items)
        previous.text = "\n".join(previous.extra["items"])
        previous.raw_text = f"{previous.raw_text}\n{raw.text}"
        return
    block = _block(BlockType.LIST, "\n".join(items), raw)
    block.extra["items"] = list(items)
    blocks.append(block)


def _piece(raw: RawBlock, lines: list[str], **changes: object) -> RawBlock:
    """A part of ``raw`` with the same geometry and style."""
    part = RawBlock(
        text="\n".join(lines),
        page=raw.page,
        bbox=raw.bbox,
        font_size=raw.font_size,
        bold=raw.bold,
    )
    for name, value in changes.items():
        setattr(part, name, value)
    return part


def _split_raw(raw: RawBlock) -> list[RawBlock]:
    """Separate a topic title from its plan ("Reja:") and a numbered title from its body."""
    fixed = raw.rows is not None or raw.role or raw.footnote or raw.list_item
    if fixed or raw.heading_level is not None:
        return [raw]
    groups = _line_groups(raw.text)
    if len(groups) > 1:
        parts = [_piece(raw, group, heading_level=_lone_title_level(group)) for group in groups]
        parts[0].footnote_refs = raw.footnote_refs
        return [piece for part in parts for piece in _split_raw(part)]
    lines = groups[0] if groups else []
    if lines and PLAN_LINE.match(lines[0]):
        return _plan_blocks(raw, lines)
    if len(lines) < 2:
        return [raw]
    if cut := _list_end(lines):
        parts = [_piece(raw, lines[:cut]), _piece(raw, lines[cut:])]
        parts[0].footnote_refs = raw.footnote_refs
        return [piece for part in parts for piece in _split_raw(part)]
    first = numbering_info(lines[0])
    if first is None or first[0] not in ("keyword", "decimal"):
        return [raw]

    plan_at = next((i for i, line in enumerate(lines) if PLAN_LINE.match(line)), None)
    if plan_at:
        return [_piece(raw, lines[:plan_at]), *_plan_blocks(raw, lines[plan_at:])]
    if not _may_start_with_title(first, lines):
        return [raw]
    split_at = _title_end(lines)
    if split_at:
        title = _piece(raw, lines[:split_at], heading_level=first[1])
        return [title, _piece(raw, lines[split_at:])]
    return [raw]


def _line_groups(text: str) -> list[list[str]]:
    """Lines of ``text`` separated by blank lines."""
    groups: list[list[str]] = [[]]
    for line in text.split("\n"):
        if line.strip():
            groups[-1].append(line)
        elif groups[-1]:
            groups.append([])
    return [group for group in groups if group]


def _lone_title_level(group: list[str]) -> int | None:
    """Heading level of a single numbered line set apart by blank lines, e.g. "1.1. Title"."""
    if len(group) != 1:
        return None
    marker = numbering_info(group[0])
    is_section = marker is not None and (marker[0] == "keyword" or marker[1] >= 2)
    title_like = group[0].strip()[-1] not in SENTENCE_END + ","
    if marker and is_section and marker[0] != "bullet" and title_like:
        return marker[1] if len(group[0]) <= MAX_HEADING_CHARS else None
    return None


def _list_end(lines: list[str]) -> int:
    """Index of the first numbered section line after list items, or 0.

    "- item" followed by "3.3. Next section" is a list and a new paragraph, not one item.
    """
    first = numbering_info(lines[0])
    if first is None or first[0] not in LIST_KINDS:
        return 0
    for index, line in enumerate(lines[1:], start=1):
        marker = numbering_info(line)
        if marker and marker[0] in ("decimal", "keyword"):
            return index
    return 0


def _may_start_with_title(first: tuple[str, int], lines: list[str]) -> bool:
    """A "1." line is a list item, and several numbered lines are plan items, not a title."""
    kind, depth = first
    numbered_lines = sum(1 for line in lines if numbering_info(line))
    return numbered_lines == 1 and (kind == "keyword" or depth >= 2)


def _plan_blocks(raw: RawBlock, lines: list[str]) -> list[RawBlock]:
    """ "Reja:" as a paragraph followed by its numbered items as list items."""
    head = lines[0].split(":", 1)
    parts = [_piece(raw, [f"{head[0]}:"])]
    rest = [head[1].strip()] if head[1].strip() else []
    items: list[list[str]] = []
    for line in [*rest, *lines[1:]]:
        marker = numbering_info(line)
        if marker or not items:
            items.append([line])
        else:
            items[-1].append(line)
    parts.extend(_piece(raw, [_flatten(" ".join(item))], list_item=True) for item in items)
    return parts


def _title_end(lines: list[str]) -> int:
    """Index where the body starts after a short numbered title, or 0 when there is none.

    A title ends on a line that is clearly shorter than the full-width body lines and is
    followed by a line starting a new sentence.
    """
    longest = max(len(line) for line in lines)
    for end in range(1, min(len(lines) - 1, MAX_TITLE_LINES) + 1):
        if lines[end][0].islower():  # the title wraps onto this line
            continue
        title = " ".join(lines[:end])
        ends_like_title = title[-1] not in SENTENCE_END + ","
        short_last_line = len(lines[end - 1]) <= TITLE_LINE_RATIO * longest
        starts_sentence = lines[end][0].isupper() or lines[end][0].isdigit()
        fits = len(title) <= MAX_HEADING_CHARS
        return end if ends_like_title and short_last_line and starts_sentence and fits else 0
    return 0


def _join_split_paragraphs(blocks: list[Block]) -> list[Block]:
    """Merge a paragraph that a page break (or an in-between footnote) split in two."""
    joined: list[Block] = []
    for block in blocks:
        flow = next((b for b in reversed(joined) if b.type is not BlockType.FOOTNOTE), None)
        if flow is not None and _is_continuation(flow, block):
            _merge_into(flow, block)
        else:
            joined.append(block)
    return joined


def _merge_into(previous: Block, block: Block) -> None:
    """Append ``block`` to ``previous``; for a list it extends the last item."""
    if previous.type is BlockType.LIST:
        items = previous.extra["items"]
        items[-1] = _flatten(repair_hyphenation(f"{items[-1]}\n{block.text}"))
        previous.text = "\n".join(items)
    else:
        previous.text = _flatten(repair_hyphenation(f"{previous.text}\n{block.text}"))
    previous.raw_text = f"{previous.raw_text}\n{block.raw_text}"
    previous.extra["page_end"] = block.page
    previous.language = detect_language(previous.text)


def _is_continuation(previous: Block, block: Block) -> bool:
    if previous.type not in (BlockType.PARAGRAPH, BlockType.LIST):
        return False
    if block.type is not BlockType.PARAGRAPH:
        return False
    if previous.extra.get("role") or block.extra.get("role") or not block.text:
        return False
    next_page = previous.extra.get("page_end", previous.page) + 1
    return (
        block.page == next_page
        and block.text[0].islower()
        and previous.text[-1] not in SENTENCE_END
    )
