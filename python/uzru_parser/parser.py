"""Public parsing entry points."""

from __future__ import annotations

from pathlib import Path

from .models import Document
from .pdf import parse_pdf


class Parser:
    """Parse a file into a normalized :class:`Document`.

    Currently supports PDF. DOCX and TXT/Markdown are planned.
    """

    def parse(self, path: str | Path) -> Document:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return parse_pdf(path)
        raise ValueError(f"Unsupported file type: {suffix!r}")


def parse(path: str | Path) -> Document:
    """Shortcut for ``Parser().parse(path)``."""
    return Parser().parse(path)
