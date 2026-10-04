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
#: Decorated page numbers ("[12]", "(12)", "- 12 -", "12-bet") and Roman ones up to 89, the
#: front matter's ("xiv", "- iv -").
_DECORATED_PAGE_NUMBER = re.compile(
    r"^[-–—\s]*[\[(]?\s*(?:#|(?=[ivxl])(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))\s*[\])]?"
    r"(?:\s*-?\s*(?:bet|бет))?[-–—\s]*$"
)
_FOOTNOTE_START = re.compile(r"^\s*(\d{1,3})(?:\s+\S|(?=[^\W\d_]))")
_TOC_TITLE = re.compile(
    rf"^\s*(?:{'|'.join(re.escape(t) for t in config.TOC_TITLES)})\s*[:.]?\s*$", re.IGNORECASE
)
_ISBN = re.compile(r"\bISBN[\s:]*(?:97[89][-\s]?)?\d[\d\s-]{8,}[\dXx]\b")
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

    page_count = len(page_heights)
    needed = max(2, math.ceil(page_count * config.MIN_REPEAT_SHARE))
    drop = {
        index
        for index, key in margin
        if _is_page_number(key)
        or len(pages_by_key[key]) >= needed
        or _alternating(pages_by_key[key], page_count)
    }
    running = _running_titles(blocks, margin, page_heights)
    drop |= running | _in_running_title_place(blocks, margin, running, page_heights)
    kept = [raw for index, raw in enumerate(blocks) if index not in drop]
    return kept, len(drop)


def _is_page_number(key: str) -> bool:
    return bool(_PAGE_NUMBER.match(key) or _DECORATED_PAGE_NUMBER.match(key))


def _alternating(pages: set[int], page_count: int) -> bool:
    """On most even pages, or on most odd pages: a book's left- or right-hand header."""
    for parity in (0, 1):
        total = (page_count + parity) // 2  # pages of that parity
        on = sum(1 for page in pages if page % 2 == parity)
        if on >= max(2, math.ceil(total * config.PARITY_REPEAT_SHARE)):
            return True
    return False


def _running_titles(
    blocks: list[RawBlock], margin: list[tuple[int, str]], page_heights: dict[int, float]
) -> set[int]:
    """Margin texts repeated on consecutive pages at the same height and size (a running
    chapter title that changes with the chapter). A book prints them on every other page
    (the chapter on the left, the section on the right), so one page may lie between."""
    by_key: dict[str, list[int]] = defaultdict(list)
    for index, key in margin:
        by_key[key].append(index)
    drop: set[int] = set()
    for indexes in by_key.values():
        if len(indexes) < config.FURNITURE_RUN_PAGES:
            continue
        run: list[int] = []
        for index in sorted(indexes, key=lambda i: blocks[i].page):
            step = blocks[index].page - blocks[run[-1]].page if run else 0
            if run and (
                not 1 <= step <= config.FURNITURE_PAGE_STEP
                or not _same_place(blocks[run[-1]], blocks[index], page_heights)
            ):
                if len(run) >= config.FURNITURE_RUN_PAGES:
                    drop.update(run)
                run = []
            if not run or blocks[index].page != blocks[run[-1]].page:
                run.append(index)
        if len(run) >= config.FURNITURE_RUN_PAGES:
            drop.update(run)
    return drop


def _in_running_title_place(
    blocks: list[RawBlock],
    margin: list[tuple[int, str]],
    running: set[int],
    page_heights: dict[int, float],
) -> set[int]:
    """Single margin lines printed where the running titles stand on other pages (same height,
    same size): the running title of a section too short to repeat it on several pages.
    Only page headers with words count: the bottom margin also holds footnotes."""

    def header(raw: RawBlock) -> bool:
        height = page_heights.get(raw.page, 0.0)
        return raw.bbox is not None and raw.bbox[3] <= height * config.MARGIN_BAND

    known = [
        blocks[index]
        for index in running
        if header(blocks[index]) and any(c.isalpha() for c in blocks[index].text)
    ]
    found: set[int] = set()
    if len(known) < config.FURNITURE_RUN_PAGES:
        return found
    for index, _ in margin:
        raw = blocks[index]
        if index in running or "\n" in raw.text.strip() or not header(raw):
            continue
        places = sum(1 for other in known if _same_place(other, raw, page_heights))
        if places >= config.FURNITURE_RUN_PAGES:
            found.add(index)
    return found


def _same_place(a: RawBlock, b: RawBlock, page_heights: dict[int, float]) -> bool:
    """Same height on the page and the same font size."""
    if a.bbox is None or b.bbox is None:
        return False
    height = page_heights.get(b.page, 0.0) or page_heights.get(a.page, 0.0)
    near = abs(a.bbox[1] - b.bbox[1]) <= config.FURNITURE_Y_TOLERANCE * height
    sizes = (a.font_size or 0.0, b.font_size or 0.0)
    same_size = max(sizes) - min(sizes) <= config.SAME_SIZE_TOLERANCE * max(max(sizes), 1.0)
    return near and same_size


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
        if raw.list_item or raw.heading_level is not None:  # a tagged item or heading
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


def mark_imprint_page(blocks: list[RawBlock]) -> None:
    """The imprint page of a book (the page near the front with its ISBN): its short lines
    (codes, authors, publisher) are front matter and build no headings; a longer paragraph
    there (the book's abstract) stays text."""
    pages = {
        raw.page
        for raw in blocks
        if raw.page <= config.IMPRINT_MAX_PAGE and raw.rows is None and _ISBN.search(raw.text)
    }
    for raw in blocks:
        if raw.page in pages and raw.rows is None and not raw.footnote:
            if len(raw.text.split()) <= config.IMPRINT_LINE_WORDS:
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


def _mark_contents_title(blocks: list[RawBlock], first: int) -> None:
    """The short title line right above a contents run ("CONTENTS", "Оглавление") belongs to
    it, also when it is not in the list of known titles."""
    above = first - 1
    while above >= 0 and blocks[above].footnote:
        above -= 1
    if above < 0:
        return
    raw = blocks[above]
    words = raw.text.split()
    same_page = raw.page == blocks[first].page
    title_like = 0 < len(words) <= config.TOC_TITLE_WORDS and raw.text.rstrip()[-1:] not in ".;,"
    if same_page and title_like and raw.role is None and raw.rows is None:
        raw.role = "toc"


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
        _mark_contents_title(blocks, run[0])
    final = runs[-1] if runs else None
    if final and blocks[final[0]].page >= page_count * config.BACK_MATTER_START:
        for raw in blocks[final[-1] + 1 :]:
            raw.role = raw.role or "back_matter"
