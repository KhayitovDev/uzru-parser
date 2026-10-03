"""Shared construction of a :class:`Document` from the output of a format reader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Block, Document, DocumentMetadata, Page, make_document_id
from .text import detect_language


def assemble_document(
    path: Path,
    format: str,
    pages: list[Page],
    blocks: list[Block],
    title: str | None = None,
    author: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Document:
    for block in blocks:
        pages[block.page - 1].block_count += 1
    document = Document(
        metadata=DocumentMetadata(
            source=str(path),
            format=format,
            title=title or None,
            author=author or None,
            page_count=len(pages),
            extra=extra or {},
        ),
        pages=pages,
        blocks=blocks,
    )
    document.language = detect_language(document.text)
    document.document_id = make_document_id(path.name, document.text)
    return document
