from pathlib import Path

import pymupdf
import pytest
from helpers import bold_font, cyrillic_font, make_pdf
from uzru_parser import BlockType, Parser, chunk, parse, pdf
from uzru_parser.text import CleanStats


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


def new_page(doc: pymupdf.Document, bold: bool = False) -> pymupdf.Page:
    page = doc.new_page()
    page.insert_font(fontname="regular", fontfile=cyrillic_font())
    if bold:
        page.insert_font(fontname="bold", fontfile=bold_font())
    return page


def test_footnote_mark_and_entry_are_separated_from_the_text(tmp_path: Path) -> None:
    font = pymupdf.Font(fontfile=cyrillic_font())
    doc = pymupdf.open()
    first = new_page(doc)
    lines = [
        "Bu masala boʻyicha koʻplab ilmiy ishlar",
        "yozilgan va ular orasida mashhur",
        "mualliflar",
    ]
    for i, text in enumerate(lines):
        first.insert_text((72, 100 + 14 * i), text, fontname="regular", fontsize=11)
    width = font.text_length("mualliflar", fontsize=11)
    first.insert_text((72 + width, 123), "5", fontname="regular", fontsize=7)
    first.insert_text(
        (72, 180), "Markaziy bank emission bank yaratgan", fontname="regular", fontsize=11
    )
    first.insert_text(
        (72, 790), "5 Sevruk V.T. Bank riskleri. M.: Delo, 1995", fontname="regular", fontsize=8
    )
    second = new_page(doc)
    second.insert_text(
        (72, 100), "vazifasini bajaradi. Keyingi gap.", fontname="regular", fontsize=11
    )
    path = tmp_path / "footnote.pdf"
    doc.save(path)
    doc.close()

    document = parse(path)
    kinds = [b.type for b in document.blocks]
    assert kinds.count(BlockType.FOOTNOTE) == 1
    note = next(b for b in document.blocks if b.type is BlockType.FOOTNOTE)
    assert (note.extra["number"], note.text) == ("5", "Sevruk V.T. Bank riskleri. M.: Delo, 1995")
    texts = [b.text for b in document.blocks if b.type is BlockType.PARAGRAPH]
    assert " ".join(lines) in texts
    assert not any("mualliflar5" in t for t in texts)
    joined = next(t for t in texts if t.startswith("Markaziy"))
    assert joined == "Markaziy bank emission bank yaratgan vazifasini bajaradi. Keyingi gap."
    assert next(b for b in document.blocks if b.text == joined).extra["page_end"] == 2
    chunks = chunk(document)
    assert chunks[0].metadata["footnotes"] == [note.text]
    assert "Sevruk" not in chunks[0].text


def test_title_and_body_in_one_pdf_block_become_heading_and_paragraph(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = new_page(doc, bold=True)
    page.insert_text(
        (72, 100), "1.1. Banklarning paydo boʻlish sabablari", fontname="bold", fontsize=11
    )
    for i, line in enumerate(
        [
            "Pul – mahsulot va tovarlarni ishlab chiqarish uchun",
            "zarur vosita sifatida paydo boʻldi.",
        ]
    ):
        page.insert_text((72, 114 + 14 * i), line, fontname="regular", fontsize=11)
    path = tmp_path / "title.pdf"
    doc.save(path)
    doc.close()

    blocks = parse(path).blocks
    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.PARAGRAPH]
    assert blocks[0].text == "1.1. Banklarning paydo boʻlish sabablari"
    assert (
        blocks[1].text
        == "Pul – mahsulot va tovarlarni ishlab chiqarish uchun zarur vosita sifatida paydo boʻldi."
    )


def test_prose_in_a_ruled_grid_is_not_a_table(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = new_page(doc)
    lines = [
        "Bunday boʻlmasligi uchun slaydga kam matn",
        "qoʻyish kerak. Esda tuting, slaydlar",
        "spikerga matnni eslatish emas",
        "auditoriyaga gapirish uchun",
    ]
    for r, line in enumerate(lines):
        for c in range(4):
            page.draw_rect(
                pymupdf.Rect(72 + c * 110, 100 + r * 24, 182 + c * 110, 124 + r * 24),
                color=(0, 0, 0),
            )
        page.insert_text((76, 116 + r * 24), line[:14], fontname="regular", fontsize=7)
    path = tmp_path / "grid.pdf"
    doc.save(path)
    doc.close()
    assert all(b.type is not BlockType.TABLE for b in parse(path).blocks)


def span(
    text: str, size: float = 11.0, font: str = "Arial", flags: int = 0, y: float = 100.0
) -> dict:
    return {"text": text, "size": size, "font": font, "flags": flags, "origin": (0.0, y)}


def test_symbol_font_glyph_does_not_set_the_line_font_size() -> None:
    raw_line = {
        "bbox": (0, 90, 200, 105),
        "spans": [span("\uf02f", 14, "Symbol"), span("dollar (11%) va dollar")],
    }
    line = pdf._line(raw_line, 0, CleanStats())
    assert line.size == 11.0
    assert line.text == "• dollar (11%) va dollar"


def test_superscript_flag_and_raised_small_digits_are_reference_marks() -> None:
    flagged = {"bbox": (0, 90, 200, 105), "spans": [span("tizimi"), span("19", flags=1)]}
    raised = {"bbox": (0, 90, 200, 105), "spans": [span("atalgan"), span("8", size=7, y=95.0)]}
    plain_digits = {"bbox": (0, 90, 200, 105), "spans": [span("Model "), span("2")]}
    results = [pdf._line(line, 0, CleanStats()) for line in (flagged, raised, plain_digits)]
    assert [(r.text, r.refs) for r in results] == [
        ("tizimi", ["19"]),
        ("atalgan", ["8"]),
        ("Model 2", []),
    ]


def test_subscript_digits_are_kept() -> None:
    lowered = {
        "bbox": (0, 90, 200, 105),
        "spans": [span("H"), span("2", size=7, y=104.0), span("O")],
    }
    assert pdf._line(lowered, 0, CleanStats()).text == "H2O"


def test_bookmarks_set_heading_levels(tmp_path: Path) -> None:
    doc = pymupdf.open()
    for title, text in [
        ("Kirish", "Kirish qismi matni shu yerda."),
        ("Banklarning turlari", "Banklar haqida matn."),
    ]:
        page = new_page(doc)
        page.insert_text((72, 100), title, fontname="regular", fontsize=11)
        page.insert_text((72, 140), text, fontname="regular", fontsize=11)
    doc.set_toc([[1, "KIRISH", 1], [2, "Banklarning turlari", 2]])
    path = tmp_path / "outline.pdf"
    doc.save(path)
    doc.close()

    document = parse(path)
    headings = [(b.text, b.level) for b in document.blocks if b.type is BlockType.HEADING]
    assert headings == [("Kirish", 1), ("Banklarning turlari", 2)]
    assert document.metadata.extra["heading_sources"] == {"bookmarks": 2}


def test_chart_labels_become_one_figure_block(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = new_page(doc)
    page.insert_text(
        (72, 100), "Quyidagi grafikda risklar koʻrsatilgan.", fontname="regular", fontsize=11
    )
    for i in range(5):
        page.draw_rect(
            pymupdf.Rect(100 + i * 40, 300 - i * 20, 125 + i * 40, 400),
            color=(0, 0, 0),
            fill=(0.5, 0.5, 0.5),
        )
    for i, label in enumerate(["Risklar", "Kredit", "Foiz"]):
        page.insert_text((100 + i * 80, 415), label, fontname="regular", fontsize=8)
    path = tmp_path / "chart.pdf"
    doc.save(path)
    doc.close()

    document = parse(path)
    figures = [b for b in document.blocks if b.extra.get("role") == "figure"]
    assert [f.text for f in figures] == ["Risklar | Kredit | Foiz"]
    assert BlockType.HEADING not in [b.type for b in document.blocks]
    assert len(chunk(document)) == 1


def test_mixed_alphabet_words_are_fixed_and_counted(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "mixed.pdf", ["Vаlyutа bozori vа TА’LIM tizimi haqida."])
    document = parse(path)
    assert document.blocks[0].text == "Valyuta bozori va TAʼLIM tizimi haqida."
    assert document.metadata.extra["mixed_script_words_fixed"] == 3
    assert document.blocks[0].raw_text.startswith("Vаlyutа")  # the original stays recoverable


def test_scan_with_a_text_stamp_is_flagged_for_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "stamped_scan.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
        pixmap.clear_with(200)
        page.insert_image(page.rect, pixmap=pixmap)
        page.insert_text((40, 30), "QMMB: 09/26/518/0986-son 30.09.2026-y.", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    assert all(page.needs_ocr for page in parse(pdf_path).pages)


def test_text_page_with_a_large_picture_is_not_flagged_for_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "picture.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
    pixmap.clear_with(200)
    page.insert_image(pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.6), pixmap=pixmap)
    text = "Pul aylanmasi iqtisodiyotda muhim oʻrin tutadi va markaziy bank uni boshqaradi."
    for i in range(6):
        page.insert_text((72, 540 + i * 16), text, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    assert not parse(pdf_path).needs_ocr


SHADED_TEXT = [
    ("bold", "10.1. Guruhlarda ishlash tamoyillari"),
    ("body", "Guruhda ishlash talabalarning faolligini oshiradi va har bir ishtirokchi"),
    ("body", "oʻz fikrini erkin bildirishi uchun qulay sharoit yaratadi. Bu jarayon"),
    ("body", "taqdimot garovidir."),
    ("body", "Taqdimotga tayyorlanishda quyidagi bosqichlarni ajratish"),
    ("body", "mumkin:"),
    ("bold", "10.2. Taqdimotga tayyorlanish bosqichlari"),
    ("body", "Har bir bosqichda maqsad aniq belgilanadi va natijalar tahlil qilinadi."),
]


def shaded_pdf(path: Path) -> Path:
    """Every line has a filled band behind it, as Word exports often draw."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="f", fontfile=cyrillic_font())
    page.insert_font(fontname="b", fontfile=bold_font())
    y = 100.0
    for style, text in SHADED_TEXT:
        if style == "bold":
            y += 12
        page.draw_rect(pymupdf.Rect(70, y - 11, 525, y + 4), color=None, fill=(0.95, 0.95, 0.95))
        page.insert_text((72, y), text, fontname="b" if style == "bold" else "f", fontsize=11)
        y += 16 if style == "bold" else 15
    doc.save(path)
    doc.close()
    return path


def test_line_shading_is_not_a_figure(tmp_path: Path) -> None:
    blocks = parse(shaded_pdf(tmp_path / "shaded.pdf")).blocks
    headings = [b.text for b in blocks if b.type is BlockType.HEADING]
    assert headings == [
        "10.1. Guruhlarda ishlash tamoyillari",
        "10.2. Taqdimotga tayyorlanish bosqichlari",
    ]
    assert not [b for b in blocks if b.extra.get("role") == "figure"]
    assert any(b.text.endswith("Bu jarayon taqdimot garovidir.") for b in blocks)


def test_chart_with_bars_and_labels_is_still_a_figure(tmp_path: Path) -> None:
    path = tmp_path / "chart.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="f", fontfile=cyrillic_font())
    page.insert_textbox(
        pymupdf.Rect(72, 72, 523, 200), " ".join([SHADED_TEXT[1][1]] * 4), fontname="f", fontsize=11
    )
    for i, label in enumerate(["Risklar", "Kredit", "Foiz", "Valyuta"]):
        page.draw_rect(
            pymupdf.Rect(120 + i * 90, 400 - 40 * i, 170 + i * 90, 500),
            color=(0, 0, 0),
            fill=(0.3, 0.3, 0.8),
        )
        page.insert_text((120 + i * 90, 515), label, fontname="f", fontsize=9)
    doc.save(path)
    doc.close()
    figures = [b for b in parse(path).blocks if b.extra.get("role") == "figure"]
    assert figures and "Risklar" in figures[0].text


def ruled_tables_pdf(path: Path, pages: int = 6) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_font(fontname="f", fontfile=cyrillic_font())
        page.insert_textbox(
            pymupdf.Rect(72, 60, 523, 140), SHADED_TEXT[1][1], fontname="f", fontsize=11
        )
        for row in range(5):
            for col in range(3):
                cell = pymupdf.Rect(72 + col * 150, 160 + row * 22, 222 + col * 150, 182 + row * 22)
                page.draw_rect(cell, color=(0, 0, 0), width=0.7)
                page.insert_text(
                    (cell.x0 + 4, cell.y1 - 7), f"Qator {row} ustun {col}", fontname="f", fontsize=9
                )
        page.insert_textbox(
            pymupdf.Rect(72, 300, 523, 400), SHADED_TEXT[2][1], fontname="f", fontsize=11
        )
    doc.save(path)
    doc.close()
    return path


def test_parsing_in_threads_gives_the_same_result(tmp_path: Path) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor

    path = ruled_tables_pdf(tmp_path / "tables.pdf")
    alone = json.dumps(parse(path).to_dict(), ensure_ascii=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: json.dumps(parse(path).to_dict(), ensure_ascii=False), range(8))
        )
    assert all(result == alone for result in results)


def table_block(rows: int = 3) -> "pdf.RawBlock":
    data = [["Harakat", "Baho"]] + [[f"Band {i}", str(i)] for i in range(rows - 1)]
    return pdf.RawBlock(text="", page=1, bbox=(70.0, 100.0, 530.0, 160.0), rows=data)


def text_line(text: str, y: float) -> "pdf.Line":
    return pdf.Line(text=text, bbox=(100.0, y, 300.0, y + 12.0), size=11.0, chars=len(text))


def test_merged_last_row_closed_by_the_tables_ruling_joins_the_table() -> None:
    table = table_block()
    rules = [(70.0, 100.0, 70.5, 200.0), (530.0, 100.0, 530.5, 200.0), (70.0, 200.0, 530.0, 200.5)]
    lines = [text_line("Xulosa:", 175.0), text_line("Jadvaldan keyingi matn.", 230.0)]
    remaining = pdf._extend_table(table, rules, lines)
    assert [line.text for line in remaining] == ["Jadvaldan keyingi matn."]
    assert table.rows is not None and table.rows[-1][0] == "Xulosa:"


def test_text_below_a_closed_table_stays_outside_it() -> None:
    table = table_block()
    rules = [(70.0, 100.0, 70.5, 160.0), (530.0, 100.0, 530.5, 160.0)]
    lines = [text_line("Xulosa:", 175.0)]
    assert pdf._extend_table(table, rules, lines) == lines
    assert table.bbox == (70.0, 100.0, 530.0, 160.0)


def test_title_page_gives_the_title_when_the_file_has_none(tmp_path: Path) -> None:
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    cover = doc.new_page()
    cover.insert_font(fontname="f", fontfile=cyrillic_font())
    cover.insert_text((150, 200), "TOSHKENT DAVLAT UNIVERSITETI", fontname="f", fontsize=12)
    cover.insert_text((150, 300), "BANK ISHI ASOSLARI", fontname="f", fontsize=24)
    cover.insert_text((250, 700), "Toshkent – 2021", fontname="f", fontsize=12)
    for _ in range(2):  # a title page is looked for in books of a few pages
        page = doc.new_page()
        page.insert_font(fontname="f", fontfile=cyrillic_font())
        text = " ".join([SHADED_TEXT[1][1]] * 20)
        page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontname="f", fontsize=11)
    doc.set_metadata({})
    doc.save(path)
    doc.close()
    assert parse(path).metadata.title == "BANK ISHI ASOSLARI"
