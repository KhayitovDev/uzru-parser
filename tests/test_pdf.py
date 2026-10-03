from pathlib import Path

import pymupdf
import pytest
from helpers import cyrillic_font, make_pdf
from uzru_parser import BlockType, Parser, chunk, parse


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


def test_headings_lists_and_chunks_from_pdf(tmp_path: Path) -> None:
    regular, bold = (
        cyrillic_font(),
        cyrillic_font().replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    )
    if not Path(bold).exists():
        pytest.skip("bold font not available")
    pdf_path = tmp_path / "structured.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="regular", fontfile=regular)
    page.insert_font(fontname="bold", fontfile=bold)
    page.insert_text((72, 80), "1. ОБЩИЕ ПОЛОЖЕНИЯ", fontname="bold", fontsize=14)
    page.insert_textbox(
        pymupdf.Rect(72, 100, 523, 200),
        "Настоящий договор является основанием для оказания услуг по договору.",
        fontname="regular",
        fontsize=11,
    )
    page.insert_text((72, 220), "1.1. Основные понятия", fontname="bold", fontsize=11)
    page.insert_text((72, 240), "• первый пункт списка", fontname="regular", fontsize=11)
    page.insert_text((72, 255), "• второй пункт списка", fontname="regular", fontsize=11)
    doc.save(pdf_path)
    doc.close()

    document = parse(pdf_path)
    assert [b.type for b in document.blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.LIST,
    ]
    assert [b.level for b in document.blocks if b.type is BlockType.HEADING] == [1, 2]
    chunks = chunk(document)
    assert chunks[-1].heading_path == ["1. ОБЩИЕ ПОЛОЖЕНИЯ", "1.1. Основные понятия"]


def test_repeated_headers_footers_and_page_numbers_removed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "furniture.pdf"
    doc = pymupdf.open()
    for number in range(1, 4):
        page = doc.new_page()
        page.insert_font(fontname="test", fontfile=cyrillic_font())
        page.insert_text((72, 40), "ДОГОВОР № 15 об оказании услуг", fontname="test", fontsize=9)
        page.insert_textbox(
            pymupdf.Rect(72, 100, 523, 300),
            f"Уникальный текст страницы номер {number}.",
            fontname="test",
            fontsize=11,
        )
        page.insert_text((290, 810), f"Стр. {number}", fontname="test", fontsize=9)
    doc.save(pdf_path)
    doc.close()

    document = parse(pdf_path)
    assert [b.text for b in document.blocks] == [
        f"Уникальный текст страницы номер {n}." for n in range(1, 4)
    ]
    assert document.metadata.extra["removed_page_furniture"] == 6


def test_ruled_table_extracted(tmp_path: Path) -> None:
    pdf_path = tmp_path / "table.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="test", fontfile=cyrillic_font())
    page.insert_text((72, 60), "Перед таблицей", fontname="test", fontsize=11)
    cells = [["Услуга", "Цена"], ["Хлеб", "100"], ["Молоко", "250"]]
    for r, row in enumerate(cells):
        for c, value in enumerate(row):
            rect = pymupdf.Rect(72 + c * 150, 100 + r * 30, 222 + c * 150, 130 + r * 30)
            page.draw_rect(rect, color=(0, 0, 0), width=1)
            page.insert_text((rect.x0 + 5, rect.y0 + 20), value, fontname="test", fontsize=11)
    page.insert_text((72, 260), "После таблицы", fontname="test", fontsize=11)
    doc.save(pdf_path)
    doc.close()

    document = parse(pdf_path)
    assert [b.type for b in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert document.blocks[1].extra["rows"] == cells
    assert document.blocks[1].text == "Услуга | Цена\nХлеб | 100\nМолоко | 250"
    assert all(
        b.type is not BlockType.TABLE for b in Parser(detect_tables=False).parse(pdf_path).blocks
    )


def test_scanned_page_flagged_for_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
    pixmap.clear_with(200)
    page.insert_image(page.rect, pixmap=pixmap)
    doc.save(pdf_path)
    doc.close()

    document = parse(pdf_path)
    assert document.pages[0].needs_ocr
    assert document.needs_ocr


def test_text_pdf_not_flagged_for_ocr(russian_pdf: Path) -> None:
    assert not parse(russian_pdf).needs_ocr
