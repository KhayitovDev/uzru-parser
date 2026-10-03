"""PDF extraction with PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from .assemble import assemble_document
from .layout import mark_footnotes, mark_title_page, mark_toc, strip_page_furniture
from .models import Document, Page
from .structure import RawBlock, body_font_size, build_blocks

BBox = tuple[float, float, float, float]

PYMUPDF_BOLD_FLAG = 16
PYMUPDF_SUPERSCRIPT_FLAG = 1
IMAGE_BLOCK = 1
MIN_TEXT_CHARS = 25
MIN_TABLE_ROWS = 2
MIN_TABLE_COLUMNS = 2
MIN_RULING_PATHS = 4
MIN_MULTI_CELL_ROWS = 0.3
SYMBOL_FONTS = ("symbol", "wingding", "webding", "dingbats")
PRIVATE_USE = range(0xE000, 0xF900)
MAX_MARK_CHARS = 3
MARK_SIZE_RATIO = 0.8
MARK_RAISE_RATIO = 0.15
BOLD_SHARE = 0.6


@dataclass
class _PageContent:
    blocks: list[RawBlock] = field(default_factory=list)
    needs_ocr: bool = False


@dataclass
class _Line:
    text: str
    size: float | None
    bold: float
    chars: int
    bbox: BBox
    refs: list[str]


def parse_pdf(path: str | Path, detect_tables: bool = True) -> Document:
    path = Path(path)
    pages: list[Page] = []
    raw_blocks: list[RawBlock] = []

    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        meta = pdf.metadata or {}
        for number, page in enumerate(pdf, start=1):
            content = _extract_page(page, number, detect_tables)
            pages.append(
                Page(
                    number=number,
                    width=page.rect.width,
                    height=page.rect.height,
                    needs_ocr=content.needs_ocr,
                )
            )
            raw_blocks.extend(content.blocks)

    heights = {page.number: page.height for page in pages}
    raw_blocks, removed = strip_page_furniture(raw_blocks, heights)
    mark_footnotes(raw_blocks, heights, body_font_size(raw_blocks))
    mark_title_page(raw_blocks, len(pages))
    mark_toc(raw_blocks, len(pages))
    return assemble_document(
        path,
        "pdf",
        pages,
        build_blocks(raw_blocks),
        title=meta.get("title"),
        author=meta.get("author"),
        extra={"removed_page_furniture": removed},
    )


def _extract_page(page: pymupdf.Page, number: int, detect_tables: bool) -> _PageContent:
    tables = _find_tables(page, number) if detect_tables else []
    page_dict = page.get_text("dict", sort=True)  # type: ignore[no-untyped-call]
    blocks: list[RawBlock] = []
    has_images = False
    chars = 0

    for block in page_dict["blocks"]:
        if block["type"] == IMAGE_BLOCK:
            has_images = True
            continue
        for raw in _text_blocks(block, number):
            chars += len(raw.text.strip())
            if not any(_inside(raw.bbox, table.bbox) for table in tables):
                blocks.append(raw)

    blocks = _merge_tables(blocks, tables)
    return _PageContent(blocks, needs_ocr=has_images and chars < MIN_TEXT_CHARS)


def _is_symbol_span(span: dict[str, Any]) -> bool:
    text = span["text"].strip()
    private = bool(text) and all(ord(c) in PRIVATE_USE for c in text)
    return private or any(name in span["font"].lower() for name in SYMBOL_FONTS)


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


def _line(raw_line: dict[str, Any]) -> _Line:
    spans = raw_line["spans"]
    plain = [s for s in spans if not _is_symbol_span(s) and s["text"].strip()]
    line_size = max((s["size"] for s in plain), default=None)
    baseline = max((s["origin"][1] for s in spans), default=0.0)

    kept: list[str] = []
    refs: list[str] = []
    sizes: list[float] = []
    chars = bold_chars = 0
    for span in spans:
        if _is_reference_mark(span, kept, line_size, baseline):
            refs.append(span["text"].strip())
            continue
        kept.append(span["text"])
        if _is_symbol_span(span):
            continue
        length = len(span["text"].strip())
        chars += length
        if length:
            sizes.append(span["size"])
        if span["flags"] & PYMUPDF_BOLD_FLAG or "bold" in span["font"].lower():
            bold_chars += length
    return _Line(
        text="".join(kept),
        size=max(sizes, default=None),
        bold=bold_chars / chars if chars else 0.0,
        chars=chars,
        bbox=tuple(raw_line["bbox"]),
        refs=refs,
    )


def _style(line: _Line) -> tuple[float, bool]:
    return round((line.size or 0.0) * 2) / 2, line.bold >= BOLD_SHARE


def _text_blocks(block: dict[str, Any], number: int) -> list[RawBlock]:
    """One raw block per run of lines with the same font size and boldness.

    PDF producers often put a title and the text below it into one block; splitting on a
    style change keeps the title separate.
    """
    groups: list[list[_Line]] = []
    styles: list[tuple[float, bool]] = []
    for line in map(_line, block["lines"]):
        if not line.text.strip():
            continue
        if line.chars == 0 and groups:  # e.g. a lone bullet glyph: stays with its neighbours
            groups[-1].append(line)
        elif groups and styles[-1] == _style(line):
            groups[-1].append(line)
        else:
            groups.append([line])
            styles.append(_style(line))
    return [_raw_block(group, number) for group in groups if any(line.chars for line in group)]


def _raw_block(lines: list[_Line], number: int) -> RawBlock:
    chars = sum(line.chars for line in lines)
    boxes = [line.bbox for line in lines]
    return RawBlock(
        text="\n".join(line.text for line in lines),
        page=number,
        bbox=(
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        ),
        font_size=max((line.size for line in lines if line.size), default=None),
        bold=sum(line.bold * line.chars for line in lines) / chars,
        footnote_refs=[ref for line in lines for ref in line.refs],
    )


def _is_table(rows: list[list[str]]) -> bool:
    """Reject layouts that merely look like tables: single filled column or prose lines."""
    filled = [[bool(cell.strip()) for cell in row] for row in rows]
    columns = max(len(row) for row in filled)
    used = [i for i in range(columns) if any(i < len(row) and row[i] for row in filled)]
    multi_cell = sum(1 for row in filled if sum(row) >= 2)
    return len(used) >= MIN_TABLE_COLUMNS and multi_cell / len(rows) >= MIN_MULTI_CELL_ROWS


def _find_tables(page: pymupdf.Page, number: int) -> list[RawBlock]:
    if len(page.get_cdrawings()) < MIN_RULING_PATHS:  # type: ignore[no-untyped-call]
        return []
    tables: list[RawBlock] = []
    for table in page.find_tables().tables:  # type: ignore[no-untyped-call]
        rows = [[cell or "" for cell in row] for row in table.extract()]
        if len(rows) >= MIN_TABLE_ROWS and _is_table(rows):
            tables.append(RawBlock(text="", page=number, bbox=tuple(table.bbox), rows=rows))
    return tables


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
