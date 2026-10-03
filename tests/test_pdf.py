from pathlib import Path

import pymupdf
import pytest
from uzru_parser import BlockType, Parser, parse

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


@pytest.fixture
def russian_pdf(tmp_path: Path) -> Path:
    return make_pdf(
        tmp_path / "ru.pdf",
        [
            "Настоящий договор является основанием для оказания услуг.\n\nВторой абзац страницы.",
            "Текст второй страницы.",
        ],
    )


def test_pages_and_blocks(russian_pdf: Path) -> None:
    doc = parse(russian_pdf)
    assert doc.metadata.format == "pdf"
    assert doc.metadata.page_count == 2
    assert [p.number for p in doc.pages] == [1, 2]
    assert {b.page for b in doc.blocks} == {1, 2}
    assert all(b.type is BlockType.PARAGRAPH and b.bbox for b in doc.blocks)
    assert doc.document_id


def test_language_detected(russian_pdf: Path) -> None:
    doc = Parser().parse(russian_pdf)
    assert doc.language.language == "ru"
    assert doc.language.script == "cyrillic"


def test_yo_preserved(tmp_path: Path) -> None:
    doc = parse(make_pdf(tmp_path / "yo.pdf", ["Всё это ёлка."]))
    assert "Всё" in doc.text and "ёлка" in doc.text


def test_uzbek_apostrophes_normalized_and_raw_kept(tmp_path: Path) -> None:
    doc = parse(make_pdf(tmp_path / "uz.pdf", ["O'zbekiston ma'lumot ushbu qoidalar va uchun."]))
    block = doc.blocks[0]
    assert "Oʻzbekiston" in block.text and "maʼlumot" in block.text
    assert "O'zbekiston" in block.raw_text  # original stays recoverable
    assert doc.language.locale == "uz-Latn"


def test_pdf_line_wrap_hyphenation(tmp_path: Path) -> None:
    # A narrow box forces a real wrap; we put the hyphen in the text ourselves.
    pdf_path = tmp_path / "wrap.pdf"
    d = pymupdf.open()
    page = d.new_page()
    page.insert_font(fontname="test", fontfile=cyrillic_font())
    page.insert_text((72, 100), "Настоя-", fontname="test", fontsize=11)
    page.insert_text((72, 114), "щим документом", fontname="test", fontsize=11)
    d.save(pdf_path)
    d.close()
    assert "Настоящим документом" in parse(pdf_path).text


def test_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        parse(tmp_path / "file.xyz")
