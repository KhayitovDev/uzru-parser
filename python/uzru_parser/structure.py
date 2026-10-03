"""Turn raw extracted text blocks into typed document blocks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

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
MAX_LEVEL = 6
CELL_SEPARATOR = " | "


@dataclass
class RawBlock:
    """A block as produced by a format reader, before any interpretation.

    ``heading_level``, ``list_item`` and ``rows`` let a reader state what it already knows
    (for example from DOCX styles or detected PDF tables); the rest is inferred.
    """

    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None
    font_size: float | None = None
    bold: float = 0.0  # share of characters set in a bold face
    heading_level: int | None = None
    list_item: bool = False
    rows: list[list[str]] | None = None


def build_blocks(raw_blocks: list[RawBlock]) -> list[Block]:
    """Classify raw blocks into headings, lists, tables and paragraphs, in document order."""
    body_size = _body_font_size(raw_blocks)
    prepared = [(raw, _clean(raw)) for raw in raw_blocks]
    heading = [
        raw.heading_level is not None
        or (
            not raw.list_item
            and raw.rows is None
            and bool(text)
            and _is_heading(text, raw, body_size)
        )
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
    for (raw, text), is_heading in zip(prepared, heading, strict=True):
        if not text:
            continue
        if raw.rows is not None:
            blocks.append(_table_block(raw, raw.rows))
        elif is_heading:
            level = raw.heading_level or _heading_level(text, raw, heading_sizes)
            blocks.append(_block(BlockType.HEADING, _flatten(text), raw, min(level, MAX_LEVEL)))
        elif items := _list_items(text, raw.list_item):
            _append_list(blocks, items, raw)
        else:
            blocks.append(_block(BlockType.PARAGRAPH, _flatten(text), raw))
    return blocks


def _clean(raw: RawBlock) -> str:
    if raw.rows is not None:
        return "\n".join(CELL_SEPARATOR.join(row) for row in _clean_rows(raw.rows))
    return normalize(repair_hyphenation(raw.text))


def _clean_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned = [[_flatten(normalize(cell or "")) for cell in row] for row in rows]
    return [row for row in cleaned if any(row)]


def _flatten(text: str) -> str:
    return " ".join(text.split())


def _size_key(size: float) -> float:
    return round(size * 2) / 2


def _block(block_type: BlockType, text: str, raw: RawBlock, level: int | None = None) -> Block:
    return Block(
        type=block_type,
        text=text,
        raw_text=raw.text,
        page=raw.page,
        bbox=raw.bbox,
        level=level,
        language=detect_language(text),
    )


def _table_block(raw: RawBlock, rows: list[list[str]]) -> Block:
    rows = _clean_rows(rows)
    block = _block(BlockType.TABLE, "\n".join(CELL_SEPARATOR.join(row) for row in rows), raw)
    block.extra["rows"] = rows
    return block


def _body_font_size(raw_blocks: list[RawBlock]) -> float | None:
    weights: Counter[float] = Counter()
    for raw in raw_blocks:
        if raw.font_size and raw.rows is None:
            weights[_size_key(raw.font_size)] += len(raw.text)
    return weights.most_common(1)[0][0] if weights else None


def _uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_UPPERCASE_LETTERS:
        return 0.0
    return sum(c.isupper() for c in letters) / len(letters)


def _is_heading(text: str, raw: RawBlock, body_size: float | None) -> bool:
    flat = _flatten(text)
    numbering = numbering_info(flat)
    limit = (
        MAX_KEYWORD_HEADING_CHARS if numbering and numbering[0] == "keyword" else MAX_HEADING_CHARS
    )
    if len(flat) > limit or text.count("\n") + 1 > MAX_HEADING_LINES:
        return False
    if numbering and numbering[0] in ("bullet", "ordered"):
        return False
    uppercase = _uppercase_ratio(flat) >= 0.9
    if flat[-1] in ",;" or (flat[-1] == "." and not uppercase and not numbering):
        return False

    score = 0
    if body_size and raw.font_size and raw.font_size >= body_size * LARGER_FONT_RATIO:
        score += 2
    if raw.bold >= BOLD_SHARE:
        score += 1
    if uppercase:
        score += 2 if len(flat) <= SHORT_UPPERCASE_CHARS else 1
    if numbering:
        score += 2 if numbering[0] == "keyword" else 1
    return score >= HEADING_SCORE


def _heading_level(text: str, raw: RawBlock, heading_sizes: list[float]) -> int:
    numbering = numbering_info(text)
    if numbering:
        return numbering[1]
    if raw.font_size and _size_key(raw.font_size) in heading_sizes:
        return heading_sizes.index(_size_key(raw.font_size)) + 1
    return 1


def _list_items(text: str, forced: bool) -> list[str]:
    """Split a block into list items, or return ``[]`` when it is not a list."""
    if forced:
        return [_flatten(text)]
    items: list[str] = []
    for line in text.split("\n"):
        marker = numbering_info(line)
        if marker and marker[0] in ("bullet", "ordered"):
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
