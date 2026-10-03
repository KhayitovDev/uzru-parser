"""Shared helpers for generating test documents."""

from pathlib import Path

import pymupdf
import pytest

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def cyrillic_font() -> str:
    """PyMuPDF's built-in fonts have no Cyrillic, so tests borrow a system font."""
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    pytest.skip("no Cyrillic-capable system font found for generating test PDFs")


def make_pdf(path: Path, pages: list[str]) -> Path:
    """Create a small text PDF containing Cyrillic/Latin text."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_font(fontname="test", fontfile=cyrillic_font())
        page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontname="test", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def bold_font() -> str:
    path = cyrillic_font().replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
    if not Path(path).exists():
        pytest.skip("bold font not available")
    return path
