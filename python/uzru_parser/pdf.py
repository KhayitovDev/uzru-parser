"""PDF extraction with PyMuPDF. Produces paragraph blocks; structure detection comes later."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .models import Block, BlockType, Document, DocumentMetadata, Page, make_document_id
from .text import detect_language, normalize, repair_hyphenation


def parse_pdf(path: str | Path) -> Document:
    path = Path(path)
    pages: list[Page] = []
    blocks: list[Block] = []

    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        meta = pdf.metadata or {}
        for index, page in enumerate(pdf, start=1):
            page_blocks = 0
            # sort=True gives reading order (top-to-bottom, left-to-right).
            for x0, y0, x1, y1, raw, _no, kind in page.get_text("blocks", sort=True):
                if kind != 0:  # 0 = text, 1 = image
                    continue
                text = normalize(repair_hyphenation(raw))
                if not text:
                    continue
                blocks.append(
                    Block(
                        type=BlockType.PARAGRAPH,
                        text=text.replace("\n", " "),
                        raw_text=raw,
                        page=index,
                        bbox=(x0, y0, x1, y1),
                        language=detect_language(text),
                    )
                )
                page_blocks += 1
            pages.append(
                Page(
                    number=index,
                    width=page.rect.width,
                    height=page.rect.height,
                    block_count=page_blocks,
                )
            )

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
