"""Page-level analysis of raw blocks: running headers and footers, footnotes, title page,
contents and back matter."""

from __future__ import annotations

import math
import re
from collections import defaultdict

from . import config
from .structure import RawBlock

_DIGITS = re.compile(r"\d+")
_PAGE_NUMBER = re.compile(
    r"^(?:(?:стр\.?|страница|с\.|page|bet)\s*)?[-–—\s]*#(?:\s*(?:из|of|/|dan)\s*#)?[-–—\s]*$"
)
_FOOTNOTE_START = re.compile(r"^\s*(\d{1,3})(?:\s+\S|(?=[^\W\d_]))")
_TOC_TITLE = re.compile(
    rf"^\s*(?:{'|'.join(re.escape(t) for t in config.TOC_TITLES)})\s*[:.]?\s*$", re.IGNORECASE
)
_LEADER = re.compile(r"(?:\.{3,}|…+|(?:\s\.){3,})\s*(\d{1,4})?\s*$")
_TRAILING_PAGE = re.compile(r"([^\s\d.,:;!?])\s+(\d{1,4})\s*$")
_NUMBER_ONLY = re.compile(r"^\s*(\d{1,4})\s*$")
#: Only the end of a line can hold a leader and a page number.
_TAIL = 40


def _key(text: str) -> str:
    return _DIGITS.sub("#", " ".join(text.split()).lower())


def _in_margin(raw: RawBlock, page_height: float) -> bool:
    if raw.bbox is None or page_height <= 0:
        return False
    band = config.MARGIN_BAND
    return raw.bbox[3] <= page_height * band or raw.bbox[1] >= page_height * (1 - band)


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

    needed = max(2, math.ceil(len(page_heights) * config.MIN_REPEAT_SHARE))
    drop = {
        index
        for index, key in margin
        if _PAGE_NUMBER.match(key) or len(pages_by_key[key]) >= needed
    }
    kept = [raw for index, raw in enumerate(blocks) if index not in drop]
    return kept, len(drop)


def mark_footnotes(
    blocks: list[RawBlock], page_heights: dict[int, float], body_size: float | None
) -> None:
    """Flag footnote entries: numbered text at the foot of a page, in a smaller font or
    matching a reference mark of the page. The number may be glued to the text ("1И. ...")."""
    refs_by_page: dict[int, set[str]] = defaultdict(set)
    for raw in blocks:
        refs_by_page[raw.page].update(raw.footnote_refs)

    for raw in blocks:
        height = page_heights.get(raw.page, 0.0)
        match = _FOOTNOTE_START.match(raw.text)
        if raw.rows is not None or raw.bbox is None or not match or height <= 0:
            continue
        if raw.bbox[1] < height * config.FOOTNOTE_ZONE:
            continue
        smaller = bool(
            body_size and raw.font_size and raw.font_size <= body_size * config.FOOTNOTE_SIZE_RATIO
        )
        if smaller or match.group(1) in refs_by_page[raw.page]:
            raw.footnote = True


def mark_title_page(blocks: list[RawBlock], page_count: int) -> None:
    """Mark a short, text-poor first page as the title page so it builds no headings."""
    first = [raw for raw in blocks if raw.page == 1 and raw.rows is None and not raw.footnote]
    words = sum(len(raw.text.split()) for raw in first)
    if (
        page_count >= config.TITLE_PAGE_MIN_PAGES
        and len(first) >= config.TITLE_PAGE_MIN_BLOCKS
        and words <= config.TITLE_PAGE_MAX_WORDS
    ):
        for raw in first:
            raw.role = raw.role or "title_page"


def _entry(line: str, page_count: int) -> tuple[bool, int | None]:
    """Does ``line`` look like a contents entry, and which page number does it give?"""
    tail = line[-_TAIL:]
    if match := _LEADER.search(tail):
        return True, int(match.group(1)) if match.group(1) else None
    if match := _NUMBER_ONLY.match(line):
        number = int(match.group(1))
        return 0 < number <= page_count, number
    if (match := _TRAILING_PAGE.search(tail)) and any(c.isalpha() for c in line):
        number = int(match.group(2))
        if 0 < number <= page_count:
            return True, number
    return False, None


def _is_toc_page(
    blocks: list[RawBlock], page_count: int, min_entries: int
) -> tuple[bool, list[int]]:
    """Shape test of one page; returns the verdict and the indexes (within ``blocks``) of
    blocks holding entries."""
    lines = 0
    entries = 0
    numbers: list[int] = []
    holders: list[int] = []
    for index, raw in enumerate(blocks):
        held = False
        for line in raw.text.split("\n"):
            if not line.strip():
                continue
            lines += 1
            is_entry, number = _entry(line, page_count)
            if is_entry:
                entries += 1
                held = True
                if number is not None:
                    numbers.append(number)
        if held:
            holders.append(index)
    dense = entries >= config.TOC_LINE_SHARE * lines or len(
        holders
    ) >= config.TOC_BLOCK_SHARE * len(blocks)
    if entries < min_entries or not dense:
        return False, holders
    pairs = list(zip(numbers, numbers[1:], strict=False))
    ascending = sum(1 for a, b in pairs if b >= a)
    return not pairs or ascending >= config.TOC_ASCENDING_SHARE * len(pairs), holders


def mark_toc(blocks: list[RawBlock], page_count: int) -> None:
    """Mark the contents pages (``role="toc"``) and the back matter after a final contents.

    A contents page is recognised by its shape: many lines ending in a page number, with or
    without leaders, and page numbers that grow. It must carry a contents title or lie near
    either end of the book; the following pages with the same shape belong to it. A book can
    have several (one per language).
    """
    by_page: dict[int, list[int]] = defaultdict(list)
    for index, raw in enumerate(blocks):
        if raw.rows is None and not raw.footnote and raw.role is None:
            by_page[raw.page].append(index)
    edge = max(1, math.ceil(page_count * config.TOC_EDGE_SHARE))

    runs: list[list[int]] = []  # each run: block indexes of one contents section
    marked: list[int] = []
    previous_page: int | None = None
    for page in sorted(by_page):
        indexes = by_page[page]
        page_blocks = [blocks[i] for i in indexes]
        continuing = bool(marked) and previous_page is not None and page == previous_page + 1
        if marked and not continuing:
            runs.append(marked)  # a run ended; a later contents (another language) may follow
            marked = []
        min_entries = 1 if marked else config.TOC_MIN_ENTRIES  # the last page may hold few
        shaped, holders = _is_toc_page(page_blocks, page_count, min_entries)
        title_at = next(
            (n for n, raw in enumerate(page_blocks) if _TOC_TITLE.match(raw.text)), None
        )
        if not shaped:
            if marked:
                runs.append(marked)
                marked = []
            continue
        near_edge = page <= edge or page > page_count - edge
        # A first contents may rely on its position; a further one needs its own title.
        if not marked and title_at is None and (runs or not near_edge):
            continue
        start = title_at if title_at is not None and not marked else (0 if marked else holders[0])
        marked.extend(indexes[start : holders[-1] + 1] if holders else [])
        previous_page = page
    if marked:
        runs.append(marked)

    for run in runs:
        for index in run:
            blocks[index].role = "toc"
    final = runs[-1] if runs else None
    if final and blocks[final[0]].page >= page_count * config.BACK_MATTER_START:
        for raw in blocks[final[-1] + 1 :]:
            raw.role = raw.role or "back_matter"
