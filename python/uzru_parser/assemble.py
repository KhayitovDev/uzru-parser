"""Shared construction of a :class:`Document` from the output of a format reader."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from . import config
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
#: Below this many characters a document is too short to judge its language.
MIN_LANGUAGE_TEXT = 200
LOW_PAGE_CONFIDENCE = config.LOW_PAGE_CONFIDENCE


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
    sources = Counter(
        str(block.extra.get("heading_source", "unknown"))
        for block in blocks
        if block.type is BlockType.HEADING
    )
    extra = {**(extra or {}), "heading_sources": dict(sources)}
    document = Document(
        metadata=DocumentMetadata(
            source=str(path),
            format=format,
            title=title or None,
            author=author or None,
            page_count=len(pages),
            extra=extra,
        ),
        pages=pages,
        blocks=blocks,
    )
    document.language = _document_language(blocks, document.text)
    document.document_id = make_document_id(path.name, document.text)
    warnings = quality_warnings(document)
    if warnings:
        document.metadata.extra["quality"] = {"warnings": warnings}
    return document


def quality_warnings(document: Document) -> list[dict[str, Any]]:
    """What the parser knows it could not read well, so a large collection can be checked
    without opening every file: pages without a text layer, pages the rules are unsure about,
    pictures whose content is missing, a language it could not tell."""
    warnings: list[dict[str, Any]] = []
    scanned = [page.number for page in document.pages if page.needs_ocr]
    if scanned:
        warnings.append({"code": "no_text_layer", "pages": scanned})
    unsure = [
        page.number
        for page in document.pages
        if not page.needs_ocr
        and isinstance(page.extra.get("confidence"), (int, float))
        and page.extra["confidence"] < LOW_PAGE_CONFIDENCE
    ]
    if unsure:
        warnings.append({"code": "low_confidence_pages", "pages": unsure})
    pictures = sorted({b.page for b in document.blocks if b.extra.get("role") == "image"})
    if pictures:
        warnings.append({"code": "pictures_not_read", "pages": pictures})
    text_chars = sum(len(b.text) for b in document.blocks)
    if document.language.language == "unknown" and text_chars >= MIN_LANGUAGE_TEXT:
        warnings.append({"code": "language_uncertain"})
    if not document.blocks or text_chars < MIN_LANGUAGE_TEXT:
        warnings.append({"code": "little_or_no_text", "chars": text_chars})
    return warnings


def _document_language(blocks: list[Block], text: str) -> LanguageInfo:
    """Language of the whole document from its blocks, weighted by text length.

    Blocks with an unknown language do not vote. The confidence is the share of the voting
    text that carries the winning language. When most of the written text (letters, not
    numbers) is in no known language, the document is not in one either: an English book
    with a few Uzbek-looking lines is "unknown", not "uz".
    """
    language: Counter[str] = Counter()
    script: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    for block in blocks:
        if block.type is BlockType.FOOTNOTE or block.extra.get("role"):
            continue
        weight = len(block.text)
        if block.language.language in KNOWN_LANGUAGES:
            language[block.language.language] += weight
            script[block.language.script] += weight
        elif block.language.script != "none":
            unknown[block.language.script] += weight
    if not language:
        return detect_language(text)
    known = sum(language.values())
    if known < config.DOCUMENT_LANGUAGE_MIN_SHARE * (known + sum(unknown.values())):
        return LanguageInfo(language="unknown", script=(script + unknown).most_common(1)[0][0])
    winner, weight = language.most_common(1)[0]
    return LanguageInfo(
        language=winner,
        script=script.most_common(1)[0][0],
        confidence=weight / sum(language.values()),
    )
