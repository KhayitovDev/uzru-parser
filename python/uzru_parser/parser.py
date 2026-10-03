"""Public parsing entry points."""

from __future__ import annotations

from pathlib import Path

from .docx import parse_docx
from .models import Document
from .pdf import parse_pdf


class Parser:
    """Parse a file into a normalized :class:`Document`.

    Supports PDF and DOCX. ``detect_tables`` toggles PDF table detection.
    """

    def __init__(self, detect_tables: bool = True) -> None:
        self.detect_tables = detect_tables

    def parse(self, path: str | Path) -> Document:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return parse_pdf(path, detect_tables=self.detect_tables)
        if suffix == ".docx":
            return parse_docx(path)
        raise ValueError(f"Unsupported file type: {suffix!r}")


def parse(path: str | Path) -> Document:
    """Shortcut for ``Parser().parse(path)``."""
    return Parser().parse(path)
