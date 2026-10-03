"""Turn raw extracted text blocks into typed document blocks (headings, lists, paragraphs)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import Block, BlockType
from .text import detect_language, normalize, numbering_info, repair_hyphenation

MAX_HEADING_CHARS = 160
MAX_HEADING_LINES = 3
SHORT_UPPERCASE_CHARS = 80
LARGER_FONT_RATIO = 1.15
HEADING_SCORE = 2
BOLD_SHARE = 0.6
MIN_UPPERCASE_LETTERS = 4
MAX_LEVEL = 6


@dataclass
class RawBlock:
    """A text block as extracted from a format reader, before any interpretation."""

    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None
    font_size: float | None = None
    bold: float = 0.0  # share of characters set in a bold face


def build_blocks(raw_blocks: list[RawBlock]) -> list[Block]:
    """Classify raw blocks into headings, lists and paragraphs, in document order."""
    body_size = _body_font_size(raw_blocks)
    prepared = [(raw, normalize(repair_hyphenation(raw.text))) for raw in raw_blocks]

    kinds = [_is_heading(text, raw, body_size) if text else False for raw, text in prepared]
    heading_sizes = sorted(
        {
            raw.font_size
            for (raw, _), is_heading in zip(prepared, kinds, strict=True)
            if is_heading and raw.font_size
        },
        reverse=True,
    )

    blocks: list[Block] = []
    for (raw, text), is_heading in zip(prepared, kinds, strict=True):
        if not text:
            continue
        if is_heading:
            level = _heading_level(text, raw, heading_sizes)
            blocks.append(_block(BlockType.HEADING, " ".join(text.split()), raw, level=level))
            continue
        items = _list_items(text)
        if items:
            _append_list(blocks, items, raw)
        else:
            blocks.append(_block(BlockType.PARAGRAPH, " ".join(text.split()), raw))
    return blocks


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


def _body_font_size(raw_blocks: list[RawBlock]) -> float | None:
    weights: Counter[float] = Counter()
    for raw in raw_blocks:
        if raw.font_size:
            weights[round(raw.font_size * 2) / 2] += len(raw.text)
    return weights.most_common(1)[0][0] if weights else None


def _uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_UPPERCASE_LETTERS:
        return 0.0
    return sum(c.isupper() for c in letters) / len(letters)


def _is_heading(text: str, raw: RawBlock, body_size: float | None) -> bool:
    flat = " ".join(text.split())
    if len(flat) > MAX_HEADING_CHARS or text.count("\n") + 1 > MAX_HEADING_LINES:
        return False
    numbering = numbering_info(flat)
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
        return min(numbering[1], MAX_LEVEL)
    if raw.font_size and raw.font_size in heading_sizes:
        return min(heading_sizes.index(raw.font_size) + 1, MAX_LEVEL)
    return 1


def _list_items(text: str) -> list[str]:
    """Split a block into list items, or return ``[]`` when it does not start with a marker."""
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
