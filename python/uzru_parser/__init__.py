"""uzru-parser: CPU-first document parsing for Russian and Uzbek."""

from ._core import __version__
from .chunking import Chunk, Chunker, chunk
from .models import (
    Block,
    BlockType,
    Document,
    DocumentMetadata,
    LanguageInfo,
    Page,
)
from .parser import DocumentError, Parser, parse

__all__ = [
    "Block",
    "Chunk",
    "Chunker",
    "BlockType",
    "Document",
    "DocumentError",
    "DocumentMetadata",
    "LanguageInfo",
    "Page",
    "Parser",
    "__version__",
    "chunk",
    "parse",
]
