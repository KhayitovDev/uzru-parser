"""Normalized document model.

Parsing produces a :class:`Document`; chunking (a separate step) consumes it.
Every block keeps ``raw_text`` so the original extraction stays recoverable.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    QUOTE = "quote"
    FOOTNOTE = "footnote"


@dataclass
class LanguageInfo:
    language: str = "unknown"  # ru | uz | mixed | unknown
    script: str = "none"  # latin | cyrillic | mixed | none
    confidence: float = 0.0

    @property
    def locale(self) -> str | None:
        """``uz-Latn`` / ``uz-Cyrl`` for Uzbek, ``ru`` for Russian, else ``None``."""
        if self.language == "uz":
            return {"latin": "uz-Latn", "cyrillic": "uz-Cyrl"}.get(self.script, "uz")
        if self.language == "ru":
            return "ru"
        return None


@dataclass
class Block:
    type: BlockType
    text: str
    page: int  # 1-based
    raw_text: str = ""
    bbox: tuple[float, float, float, float] | None = None
    level: int | None = None  # heading level, when type == HEADING
    language: LanguageInfo = field(default_factory=LanguageInfo)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Page:
    number: int  # 1-based
    width: float = 0.0
    height: float = 0.0
    block_count: int = 0
    needs_ocr: bool = False
    #: Reader-specific facts, e.g. a PDF page's ``confidence`` and its ``issues``.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentMetadata:
    source: str = ""
    format: str = ""
    title: str | None = None
    author: str | None = None
    page_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    metadata: DocumentMetadata
    pages: list[Page]
    blocks: list[Block]
    language: LanguageInfo = field(default_factory=LanguageInfo)
    document_id: str = ""

    @property
    def needs_ocr(self) -> bool:
        """True when some page has images but (almost) no extractable text."""
        return any(page.needs_ocr for page in self.pages)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)

    def to_dict(self) -> dict[str, Any]:
        """The document as plain data; a page without extra facts has no ``extra`` key."""
        data = asdict(self)
        for page in data["pages"]:
            if not page["extra"]:
                del page["extra"]
        return data


def make_document_id(source: str, text: str) -> str:
    """Stable id derived from the file name and extracted text."""
    digest = hashlib.sha1(f"{source}\0{text}".encode()).hexdigest()
    return digest[:16]
