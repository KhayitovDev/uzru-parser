"""PDF extraction with PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .models import Document, DocumentMetadata, Page, make_document_id
from .structure import RawBlock, build_blocks
from .text import detect_language

PYMUPDF_BOLD_FLAG = 16


def parse_pdf(path: str | Path) -> Document:
    path = Path(path)
    pages: list[Page] = []
    raw_blocks: list[RawBlock] = []

    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        meta = pdf.metadata or {}
        for number, page in enumerate(pdf, start=1):
            pages.append(Page(number=number, width=page.rect.width, height=page.rect.height))
            raw_blocks.extend(_raw_blocks(page, number))

    blocks = build_blocks(raw_blocks)
    for block in blocks:
        pages[block.page - 1].block_count += 1

    document = Document(
        metadata=DocumentMetadata(
            source=str(path),
            format="pdf",
            title=meta.get("title") or None,
            author=meta.get("author") or None,
            page_count=len(pages),
        ),
        pages=pages,
        blocks=blocks,
    )
    document.language = detect_language(document.text)
    document.document_id = make_document_id(path.name, document.text)
    return document


def _raw_blocks(page: pymupdf.Page, number: int) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    page_dict = page.get_text("dict", sort=True)  # type: ignore[no-untyped-call]
    for block in page_dict["blocks"]:
        if block["type"] != 0:
            continue
        lines: list[str] = []
        sizes: list[float] = []
        chars = bold_chars = 0
        for line in block["lines"]:
            spans = line["spans"]
            lines.append("".join(span["text"] for span in spans))
            for span in spans:
                length = len(span["text"].strip())
                chars += length
                sizes.extend([span["size"]] * length)
                if span["flags"] & PYMUPDF_BOLD_FLAG or "bold" in span["font"].lower():
                    bold_chars += length
        if not chars:
            continue
        blocks.append(
            RawBlock(
                text="\n".join(lines),
                page=number,
                bbox=tuple(block["bbox"]),
                font_size=max(sizes),
                bold=bold_chars / chars,
            )
        )
    return blocks
