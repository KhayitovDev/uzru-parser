"""Shared helpers for generating test documents."""

from pathlib import Path

import pymupdf

FONTS = Path(__file__).parent / "fonts"


def cyrillic_font() -> str:
    """PyMuPDF's built-in fonts have no Cyrillic; the tests bundle DejaVu Sans so generated
    PDFs are the same on every platform."""
    return str(FONTS / "DejaVuSans.ttf")


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
    return str(FONTS / "DejaVuSans-Bold.ttf")
