"""Page-level cleanup of raw blocks: running headers, footers and page numbers."""

from __future__ import annotations

import math
import re
from collections import defaultdict

from .structure import RawBlock

BAND_RATIO = 0.1
MIN_REPEAT_SHARE = 0.5

_DIGITS = re.compile(r"\d+")
_PAGE_NUMBER = re.compile(
    r"^(?:(?:стр\.?|страница|с\.|page|bet)\s*)?[-–—\s]*#(?:\s*(?:из|of|/|dan)\s*#)?[-–—\s]*$"
)


def _key(text: str) -> str:
    return _DIGITS.sub("#", " ".join(text.split()).lower())


def _in_margin(raw: RawBlock, page_height: float) -> bool:
    if raw.bbox is None or page_height <= 0:
        return False
    return raw.bbox[3] <= page_height * BAND_RATIO or raw.bbox[1] >= page_height * (1 - BAND_RATIO)


def strip_page_furniture(
    blocks: list[RawBlock], page_heights: dict[int, float]
) -> tuple[list[RawBlock], int]:
    """Drop page numbers and text repeated in the top or bottom margin of many pages.

    Returns the remaining blocks and the number of removed ones.
    """
    margin = [
        (index, _key(raw.text))
        for index, raw in enumerate(blocks)
        if raw.rows is None and _in_margin(raw, page_heights.get(raw.page, 0.0))
    ]
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for index, key in margin:
        pages_by_key[key].add(blocks[index].page)

    needed = max(2, math.ceil(len(page_heights) * MIN_REPEAT_SHARE))
    drop = {
        index
        for index, key in margin
        if _PAGE_NUMBER.match(key) or len(pages_by_key[key]) >= needed
    }
    kept = [raw for index, raw in enumerate(blocks) if index not in drop]
    return kept, len(drop)
