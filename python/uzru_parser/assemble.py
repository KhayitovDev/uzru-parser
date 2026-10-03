"""Shared construction of a :class:`Document` from the output of a format reader."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .models import (
    Block,
    BlockType,
    Document,
    DocumentMetadata,
    LanguageInfo,
    Page,
    make_document_id,
)
from .text import detect_language

KNOWN_LANGUAGES = ("ru", "uz", "mixed")


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
    document.language = _document_language(blocks, document.text)
    document.document_id = make_document_id(path.name, document.text)
    return document


def _document_language(blocks: list[Block], text: str) -> LanguageInfo:
    """Language of the whole document from its blocks, weighted by text length.

    Blocks with an unknown language (numbers, short fragments) do not vote. The confidence
    is the share of the voting text that carries the winning language.
    """
    language: Counter[str] = Counter()
    script: Counter[str] = Counter()
    for block in blocks:
        body = block.type is not BlockType.FOOTNOTE and not block.extra.get("role")
        if body and block.language.language in KNOWN_LANGUAGES:
            weight = len(block.text)
            language[block.language.language] += weight
            script[block.language.script] += weight
    if not language:
        return detect_language(text)
    winner, weight = language.most_common(1)[0]
    return LanguageInfo(
        language=winner,
        script=script.most_common(1)[0][0],
        confidence=weight / sum(language.values()),
    )
