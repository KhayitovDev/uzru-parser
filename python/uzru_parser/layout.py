"""Page-level analysis of raw blocks: running headers and footers, footnotes, contents."""

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


FOOTNOTE_ZONE = 0.75
FOOTNOTE_SIZE_RATIO = 0.92
TITLE_PAGE_MAX_WORDS = 80
TITLE_PAGE_MIN_BLOCKS = 3
TITLE_PAGE_MIN_PAGES = 3
TOC_GAP = 2
TOC_TITLE_LOOKAHEAD = 10
TOC_MIN_ENTRIES = 3
BACK_MATTER_START = 0.85

_FOOTNOTE_START = re.compile(r"^\s*(\d{1,3})\s+\S")
_TOC_TITLE = re.compile(
    r"^\s*(?:mundarija(?:si)?|мундарижа|оглавление|содержание|tarkib|contents|"
    r"table\s+of\s+contents)\s*[:.]?\s*$",
    re.IGNORECASE,
)
_LEADER_LINE = re.compile(r"(?:\.{3,}|…+|(?:\s\.){3,})\s*\d{0,4}\s*$")
_PAGE_NUMBER_BLOCK = re.compile(r"^\s*\d{1,4}\s*$")


def mark_footnotes(
    blocks: list[RawBlock], page_heights: dict[int, float], body_size: float | None
) -> None:
    """Flag footnote entries: numbered text at the foot of a page, in a smaller font."""
    refs_by_page: dict[int, set[str]] = defaultdict(set)
    for raw in blocks:
        refs_by_page[raw.page].update(raw.footnote_refs)

    for raw in blocks:
        height = page_heights.get(raw.page, 0.0)
        match = _FOOTNOTE_START.match(raw.text)
        if raw.rows is not None or raw.bbox is None or not match or height <= 0:
            continue
        if raw.bbox[1] < height * FOOTNOTE_ZONE:
            continue
        smaller = bool(
            body_size and raw.font_size and raw.font_size <= body_size * FOOTNOTE_SIZE_RATIO
        )
        if smaller or match.group(1) in refs_by_page[raw.page]:
            raw.footnote = True


def mark_title_page(blocks: list[RawBlock], page_count: int) -> None:
    """Mark a short, text-poor first page as the title page so it builds no headings."""
    first = [raw for raw in blocks if raw.page == 1 and raw.rows is None and not raw.footnote]
    words = sum(len(raw.text.split()) for raw in first)
    if (
        page_count >= TITLE_PAGE_MIN_PAGES
        and len(first) >= TITLE_PAGE_MIN_BLOCKS
        and words <= TITLE_PAGE_MAX_WORDS
    ):
        for raw in first:
            raw.role = raw.role or "title_page"


def _has_leader(raw: RawBlock) -> bool:
    return any(_LEADER_LINE.search(line) for line in raw.text.split("\n"))


def mark_toc(blocks: list[RawBlock], page_count: int) -> None:
    """Mark table-of-contents blocks, and the back matter that follows a contents at the end.

    A contents is a run of blocks whose lines end in leaders ("Статья 5 ........ 12"),
    optionally introduced by a "Mundarija"/"Содержание" title. A right-aligned page-number
    column may be extracted as separate number-only blocks; those belong to the contents.
    """
    flow = [i for i, raw in enumerate(blocks) if raw.rows is None]
    leaders = [i for i in flow if _has_leader(blocks[i])]
    if len(leaders) < TOC_MIN_ENTRIES:
        return

    start = next(
        (
            i
            for i in flow
            if _TOC_TITLE.match(blocks[i].text)
            and sum(1 for j in leaders if i < j <= i + TOC_TITLE_LOOKAHEAD) >= 2
        ),
        None,
    )
    if start is None:
        start = next(
            (
                i
                for i in leaders
                if sum(1 for j in leaders if i <= j <= i + TOC_GAP * TOC_MIN_ENTRIES)
                >= TOC_MIN_ENTRIES
            ),
            None,
        )
    if start is None:
        return

    order = {index: n for n, index in enumerate(flow)}
    leader_set = set(leaders) | {i for i in flow if _PAGE_NUMBER_BLOCK.match(blocks[i].text)}
    end = last = start
    for index in flow[order[start] :]:
        if index in leader_set:
            end = last = index
        elif order[index] - order[last] > TOC_GAP:
            break
    for raw in blocks[start : end + 1]:
        raw.role = "toc"
    if blocks[start].page >= page_count * BACK_MATTER_START:
        for raw in blocks[end + 1 :]:
            raw.role = raw.role or "back_matter"
