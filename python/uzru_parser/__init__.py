"""uzru-parser: CPU-first document parsing for Russian and Uzbek."""

from ._core import __version__
from .models import (
    Block,
    BlockType,
    Document,
    DocumentMetadata,
    LanguageInfo,
    Page,
)
from .parser import Parser, parse

__all__ = [
    "Block",
    "BlockType",
    "Document",
    "DocumentMetadata",
    "LanguageInfo",
    "Page",
    "Parser",
    "__version__",
    "parse",
]
