"""PDF extraction with PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .assemble import assemble_document
from .layout import strip_page_furniture
from .models import Document, Page
from .structure import RawBlock, build_blocks

BBox = tuple[float, float, float, float]

PYMUPDF_BOLD_FLAG = 16
IMAGE_BLOCK = 1
MIN_TEXT_CHARS = 25
MIN_TABLE_ROWS = 2
MIN_TABLE_COLUMNS = 2
MIN_RULING_PATHS = 4


@dataclass
class _PageContent:
    blocks: list[RawBlock] = field(default_factory=list)
    needs_ocr: bool = False


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
        raw = _text_block(block, number)
        if raw is None:
            continue
        chars += len(raw.text.strip())
        if not any(_inside(raw.bbox, table.bbox) for table in tables):
            blocks.append(raw)

    blocks = _merge_tables(blocks, tables)
    return _PageContent(blocks, needs_ocr=has_images and chars < MIN_TEXT_CHARS)


def _text_block(block: dict[str, object], number: int) -> RawBlock | None:
    lines: list[str] = []
    sizes: list[float] = []
    chars = bold_chars = 0
    for line in block["lines"]:  # type: ignore[attr-defined]
        spans = line["spans"]
        lines.append("".join(span["text"] for span in spans))
        for span in spans:
            length = len(span["text"].strip())
            chars += length
            sizes.extend([span["size"]] * length)
            if span["flags"] & PYMUPDF_BOLD_FLAG or "bold" in span["font"].lower():
                bold_chars += length
    if not chars:
        return None
    return RawBlock(
        text="\n".join(lines),
        page=number,
        bbox=tuple(block["bbox"]),  # type: ignore[arg-type]
        font_size=max(sizes),
        bold=bold_chars / chars,
    )


def _find_tables(page: pymupdf.Page, number: int) -> list[RawBlock]:
    if len(page.get_cdrawings()) < MIN_RULING_PATHS:  # type: ignore[no-untyped-call]
        return []
    tables: list[RawBlock] = []
    for table in page.find_tables().tables:  # type: ignore[no-untyped-call]
        rows = [[cell or "" for cell in row] for row in table.extract()]
        if len(rows) >= MIN_TABLE_ROWS and max(len(row) for row in rows) >= MIN_TABLE_COLUMNS:
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
