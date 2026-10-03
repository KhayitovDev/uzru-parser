"""PDF extraction with PyMuPDF.

Order of work: characters are cleaned per span and line (symbol fonts, look-alike letters,
apostrophes, spaces), lines are rebuilt into paragraphs, hyphens are rejoined, page
furniture / footnotes / title page / contents are marked, then headings, language and
blocks are built.
"""

from __future__ import annotations

import functools
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from . import config
from .assemble import assemble_document
from .columns import reading_regions
from .layout import mark_footnotes, mark_title_page, mark_toc, strip_page_furniture
from .models import Document, Page
from .paragraphs import (
    BBox,
    Line,
    build_paragraphs,
    figure_regions,
    group_formula_debris,
    layout_stats,
)
from .structure import OutlineEntry, RawBlock, build_blocks
from .text import CleanStats, Hyphenator, clean, compound_pairs, map_symbol_font

PYMUPDF_BOLD_FLAG = 16
PYMUPDF_SUPERSCRIPT_FLAG = 1
IMAGE_BLOCK = 1
SYMBOL_FONTS = ("symbol", "wingding", "webding", "dingbats")
MAX_MARK_CHARS = 3
MARK_SIZE_RATIO = 0.8
MARK_RAISE_RATIO = 0.15
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
_ONLY_PRIVATE_USE = re.compile(r"\s*[\ue000-\uf8ff]+\s*")
_SENTENCE_END = re.compile(r"[.!?:…;]\s*$")
#: PyMuPDF is not thread-safe, and ``Page.find_tables`` flips a process-wide setting that
#: changes later text boxes; one document is read at a time, in any thread.
_PYMUPDF_LOCK = threading.Lock()


@dataclass
class _PageContent:
    number: int
    lines: list[Line]
    tables: list[RawBlock]
    drawings: list[BBox]  # vector drawings and images, grouped into figures later
    boxes: list[BBox]  # filled rectangles that may hold side boxes of text
    page_box: BBox
    needs_ocr: bool


def parse_pdf(path: str | Path, detect_tables: bool = True) -> Document:
    path = Path(path)
    stats = CleanStats()
    pages: list[Page] = []
    contents: list[_PageContent] = []

    with _PYMUPDF_LOCK, pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        meta = pdf.metadata or {}
        outline = [
            OutlineEntry(level=entry[0], title=clean(entry[1]), page=entry[2])
            for entry in pdf.get_toc(simple=True)
        ]
        for number, page in enumerate(pdf, start=1):
            content = _read_page(page, number, detect_tables, stats)
            pages.append(
                Page(
                    number=number,
                    width=page.rect.width,
                    height=page.rect.height,
                    needs_ocr=content.needs_ocr,
                )
            )
            contents.append(content)

    layout = layout_stats([content.lines for content in contents])
    compounds = compound_pairs(line.text for content in contents for line in content.lines)
    hyphenator = Hyphenator(sorted(compounds))
    raw_blocks: list[RawBlock] = []
    for content in contents:
        regions = figure_regions(
            content.drawings, content.page_box, layout.body_size, content.lines
        )
        blocks = [
            block
            for part in reading_regions(content.lines, content.boxes, layout.body_size)
            for block in build_paragraphs(part, content.number, layout, regions)
        ]
        for block in blocks:
            block.text = hyphenator.repair(block.text)
        raw_blocks.extend(_merge_tables(blocks, content.tables))

    heights = {page.number: page.height for page in pages}
    raw_blocks, removed = strip_page_furniture(raw_blocks, heights)
    mark_footnotes(raw_blocks, heights, layout.body_size)
    mark_title_page(raw_blocks, len(pages))
    mark_toc(raw_blocks, len(pages))
    raw_blocks = group_formula_debris(raw_blocks)
    document_blocks = build_blocks(
        raw_blocks, outline=outline, compounds=compounds, stats=stats, text_is_clean=True
    )
    return assemble_document(
        path,
        "pdf",
        pages,
        document_blocks,
        title=meta.get("title") or _title_page_title(raw_blocks),
        author=meta.get("author"),
        extra={"removed_page_furniture": removed, **stats.as_dict()},
    )


def _title_page_title(blocks: list[RawBlock]) -> str | None:
    """The title page's largest lines, in reading order, when the file names no title."""
    page = [b for b in blocks if b.role == "title_page" and b.font_size and b.text.strip()]
    if not page:
        return None
    largest = max(b.font_size or 0.0 for b in page)
    title = [
        " ".join(b.text.split())
        for b in page
        if (b.font_size or 0.0) >= largest / config.LARGER_FONT_RATIO
    ]
    return " ".join(title) or None


def _read_page(
    page: pymupdf.Page, number: int, detect_tables: bool, stats: CleanStats
) -> _PageContent:
    drawings = page.get_cdrawings()  # type: ignore[no-untyped-call]
    tables = _find_tables(page, number, len(drawings)) if detect_tables else []
    page_dict = page.get_text("dict", sort=True)  # type: ignore[no-untyped-call]
    lines: list[Line] = []
    images: list[BBox] = []
    chars = 0

    for block_number, block in enumerate(page_dict["blocks"]):
        if block["type"] == IMAGE_BLOCK:
            images.append(tuple(block["bbox"]))
            continue
        block_lines = [_line(raw, block_number, stats, clean_text=False) for raw in block["lines"]]
        block_lines = [line for line in block_lines if line.text.strip()]
        _clean_lines(block_lines, stats)
        for line in block_lines:
            if not line.text.strip():
                continue
            chars += line.chars
            if not any(_inside(line.bbox, table.bbox) for table in tables):
                lines.append(line)

    rects: list[BBox] = [tuple(d["rect"]) for d in drawings]
    for table in tables:
        lines = _extend_table(table, rects, lines)

    return _PageContent(
        number=number,
        lines=lines,
        tables=tables,
        drawings=[tuple(d["rect"]) for d in drawings] + images,
        boxes=[tuple(d["rect"]) for d in drawings if d.get("fill") is not None],
        page_box=tuple(page.rect),
        needs_ocr=_is_scanned(images, tuple(page.rect), chars),
    )


def _is_scanned(images: list[BBox], page_box: BBox, chars: int) -> bool:
    """A page whose text is in pictures: images and almost no text, or images covering most
    of the page with only a stamp or a page number as text."""
    if not images:
        return False
    if chars < config.MIN_TEXT_CHARS:
        return True
    x0, y0, x1, y1 = page_box
    area = (x1 - x0) * (y1 - y0)
    covered = sum(
        max(0.0, min(b[2], x1) - max(b[0], x0)) * max(0.0, min(b[3], y1) - max(b[1], y0))
        for b in images
    )
    mostly_images = area > 0 and covered >= config.SCAN_IMAGE_COVER * area
    return mostly_images and chars < config.SCAN_MAX_TEXT_CHARS


def _clean_lines(lines: list[Line], stats: CleanStats) -> None:
    """Clean the text of one block's lines with a single call; per line only when a line
    vanishes in cleaning and the lines no longer line up."""
    if not lines:
        return
    batch = CleanStats()
    parts = clean("\n".join(line.text for line in lines), batch).split("\n")
    if len(parts) == len(lines):
        stats.add(batch)
        for line, part in zip(lines, parts, strict=True):
            line.text = part
        return
    for line in lines:
        line.text = clean(line.text, stats)


@functools.lru_cache(maxsize=256)
def _symbol_font(font: str) -> bool:
    name = font.lower()
    return any(symbol in name for symbol in SYMBOL_FONTS)


@functools.lru_cache(maxsize=256)
def _bold_font(font: str) -> bool:
    return "bold" in font.lower()


def _is_symbol_span(span: dict[str, Any]) -> bool:
    return _symbol_font(span["font"]) or bool(_ONLY_PRIVATE_USE.fullmatch(span["text"]))


def _is_reference_mark(
    span: dict[str, Any], kept: list[str], line_size: float | None, baseline: float
) -> bool:
    """A small raised number glued to the end of a word: a footnote reference mark."""
    text = span["text"].strip()
    if not text.isdigit() or len(text) > MAX_MARK_CHARS or not "".join(kept).strip():
        return False
    if span["flags"] & PYMUPDF_SUPERSCRIPT_FLAG:
        return True
    if not line_size:
        return False
    small = span["size"] <= MARK_SIZE_RATIO * line_size
    raised = span["origin"][1] <= baseline - MARK_RAISE_RATIO * line_size
    return bool(small and raised)


def _line(
    raw_line: dict[str, Any], block_number: int, stats: CleanStats, clean_text: bool = True
) -> Line:
    """One printed line with cleaned text, its style and its footnote reference marks."""
    spans = raw_line["spans"]
    symbol = [_is_symbol_span(s) for s in spans]
    line_size = max(
        (s["size"] for s, sym in zip(spans, symbol, strict=True) if not sym and s["text"].strip()),
        default=None,
    )
    baseline = max((s["origin"][1] for s in spans), default=0.0)

    kept: list[str] = []
    original: list[str] = []
    refs: list[str] = []
    sizes: list[float] = []
    chars = bold_chars = 0
    for span, is_symbol in zip(spans, symbol, strict=True):
        original.append(span["text"])
        if _is_reference_mark(span, kept, line_size, baseline):
            refs.append(span["text"].strip())
            continue
        text = span["text"]
        if _PRIVATE_USE.search(text):
            text = map_symbol_font(text, span["font"], stats)
        kept.append(text)
        if is_symbol:
            continue
        length = len(span["text"].strip())
        chars += length
        if length:
            sizes.append(span["size"])
        if span["flags"] & PYMUPDF_BOLD_FLAG or _bold_font(span["font"]):
            bold_chars += length
    text = "".join(kept)
    return Line(
        text=clean(text, stats) if clean_text else text,
        bbox=tuple(raw_line["bbox"]),
        size=max(sizes, default=None),
        bold=bold_chars / chars if chars else 0.0,
        chars=chars,
        original="".join(original),
        refs=refs,
        block=block_number,
    )


def _is_table(rows: list[list[str]]) -> bool:
    """Reject layouts that merely look like tables: one filled column, prose lines, or
    rows that continue each other's sentences."""
    filled = [[bool(cell.strip()) for cell in row] for row in rows]
    columns = max(len(row) for row in filled)
    used = [i for i in range(columns) if any(i < len(row) and row[i] for row in filled)]
    multi_cell = sum(1 for row in filled if sum(row) >= 2)
    if len(used) < config.MIN_TABLE_COLUMNS or multi_cell / len(rows) < config.MIN_MULTI_CELL_ROWS:
        return False
    main = max(used, key=lambda i: sum(1 for row in filled if i < len(row) and row[i]))
    cells = [row[main].strip() if main < len(row) else "" for row in rows]
    pairs = [(a, b) for a, b in zip(cells, cells[1:], strict=False) if a and b]
    running = sum(1 for a, b in pairs if not _SENTENCE_END.search(a) and b[:1].islower())
    return not pairs or running < config.RUNNING_TEXT_ROWS * len(pairs)


def _find_tables(page: pymupdf.Page, number: int, drawings: int) -> list[RawBlock]:
    if drawings < config.MIN_RULING_PATHS:
        return []
    tables: list[RawBlock] = []
    for table in page.find_tables().tables:  # type: ignore[no-untyped-call]
        rows = [[cell or "" for cell in row] for row in table.extract()]
        if len(rows) >= config.MIN_TABLE_ROWS and _is_table(rows):
            tables.append(RawBlock(text="", page=number, bbox=tuple(table.bbox), rows=rows))
    return tables


def _extend_table(table: RawBlock, rects: list[BBox], lines: list[Line]) -> list[Line]:
    """Grow a table over the rows its own ruling closes below the detected box (a merged last
    row): vertical rules or a full-width cell starting inside the table and reaching further
    down. Text in the added part becomes the table's last row; the remaining lines return."""
    if table.bbox is None or table.rows is None:
        return lines
    x0, y0, x1, y1 = table.bbox
    slack = config.TABLE_RULE_SLACK * (y1 - y0)
    continuing = [
        r
        for r in rects
        if r[0] >= x0 - slack
        and r[2] <= x1 + slack
        and y0 - slack <= r[1] <= y1 + slack
        and r[3] > y1 + slack
        and (r[2] - r[0] <= slack or r[2] - r[0] >= 0.5 * (x1 - x0))
    ]
    if len(continuing) < 2 and not any(r[2] - r[0] >= 0.5 * (x1 - x0) for r in continuing):
        return lines
    bottom = max(r[3] for r in continuing)
    extended = (x0, y0, x1, bottom)
    added = [line for line in lines if _inside(line.bbox, extended)]
    if added:
        columns = max(len(row) for row in table.rows)
        text = " ".join(line.text for line in added)
        table.rows.append([text] + [""] * (columns - 1))
    table.bbox = extended
    return [line for line in lines if not any(line is other for other in added)]


def _inside(box: BBox | None, container: BBox | None) -> bool:
    """True when the centre of ``box`` lies within ``container``."""
    if box is None or container is None:
        return False
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return container[0] <= cx <= container[2] and container[1] <= cy <= container[3]


def _merge_tables(blocks: list[RawBlock], tables: list[RawBlock]) -> list[RawBlock]:
    """Insert each table before the first text block that starts below it."""
    merged = list(blocks)
    for table in sorted(tables, key=lambda t: t.bbox[1] if t.bbox else 0.0):
        top = table.bbox[1] if table.bbox else 0.0
        position = next(
            (i for i, b in enumerate(merged) if b.bbox and b.bbox[1] >= top), len(merged)
        )
        merged.insert(position, table)
    return merged
