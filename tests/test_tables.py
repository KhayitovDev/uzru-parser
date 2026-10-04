"""PDF tables: ruled and unruled tables, merged cells, scoring, and look-alikes that stay text."""

from pathlib import Path

import pymupdf
from helpers import bold_font, cyrillic_font
from uzru_parser import BlockType, parse
from uzru_parser.tables import table_score

ROWS = [
    ("Koʻrsatkich", "2023", "2024"),
    ("Daromad", "1 250", "1 400"),
    ("Xarajat", "980", "1 020"),
    ("Foyda", "270", "380"),
    ("Soliq", "54", "76"),
]
PARAGRAPH = (
    "Bank hisoboti yil davomida daromad va xarajatlar qanday oʻzgarganini koʻrsatadi hamda "
    "keyingi yil uchun asosiy rejalarni belgilaydi."
)


def new_page() -> tuple[pymupdf.Document, pymupdf.Page]:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="R", fontfile=cyrillic_font())
    page.insert_font(fontname="B", fontfile=bold_font())
    return pdf, page


def text_paragraph(page: pymupdf.Page, y: float) -> None:
    page.insert_textbox(pymupdf.Rect(72, y, 523, y + 60), PARAGRAPH, fontname="R", fontsize=11)


def tables(path: Path) -> list[list[list[str]]]:
    return [b.extra["rows"] for b in parse(path).blocks if b.type is BlockType.TABLE]


def test_a_table_without_ruling_lines_is_found(tmp_path: Path) -> None:
    pdf, page = new_page()
    text_paragraph(page, 72)
    for i, row in enumerate(ROWS):
        for x, cell in zip((72, 280, 400), row, strict=True):
            page.insert_text((x, 180 + 18 * i), cell, fontname="B" if i == 0 else "R", fontsize=10)
    text_paragraph(page, 300)
    path = tmp_path / "unruled.pdf"
    pdf.save(path)
    found = tables(path)
    assert found == [[list(row) for row in ROWS]]
    paragraphs = [b.text for b in parse(path).blocks if b.type is BlockType.PARAGRAPH]
    assert len(paragraphs) == 2


def ruled_table(page: pymupdf.Page) -> None:
    """A ruled grid whose "Kredit portfeli" cell is merged over two rows and whose
    "Jami" cell is merged over two columns."""
    x = [72, 220, 340, 460]
    y = [100, 125, 150, 175, 200, 225]
    for top in (y[0], y[1], y[2], y[4], y[5]):
        page.draw_line((x[0], top), (x[3], top), color=(0, 0, 0), width=0.8)
    page.draw_line((x[1], y[3]), (x[3], y[3]), color=(0, 0, 0), width=0.8)
    for left in (x[0], x[2], x[3]):
        page.draw_line((left, y[0]), (left, y[5]), color=(0, 0, 0), width=0.8)
    page.draw_line((x[1], y[0]), (x[1], y[4]), color=(0, 0, 0), width=0.8)
    cells = {
        (0, 0): "Boʻlim",
        (0, 1): "2023",
        (0, 2): "2024",
        (1, 0): "Daromad",
        (1, 1): "5",
        (1, 2): "6",
        (2, 0): "Kredit portfeli",
        (2, 1): "10",
        (2, 2): "20",
        (3, 1): "30",
        (3, 2): "40",
        (4, 0): "Jami",
        (4, 2): "76",
    }
    for (row, column), text in cells.items():
        page.insert_text((x[column] + 4, y[row] + 17), text, fontname="R", fontsize=10)


def test_merged_cells_are_filled_down_and_recorded(tmp_path: Path) -> None:
    pdf, page = new_page()
    ruled_table(page)
    path = tmp_path / "merged.pdf"
    pdf.save(path)
    blocks = [b for b in parse(path).blocks if b.type is BlockType.TABLE]
    assert len(blocks) == 1
    assert blocks[0].extra["rows"] == [
        ["Boʻlim", "2023", "2024"],
        ["Daromad", "5", "6"],
        ["Kredit portfeli", "10", "20"],
        ["Kredit portfeli", "30", "40"],
        ["Jami", "", "76"],
    ]
    assert blocks[0].extra["spans"] == [
        {"row": 2, "col": 0, "rows": 2, "cols": 1},
        {"row": 4, "col": 0, "rows": 1, "cols": 2},
    ]


def test_two_text_columns_are_not_a_table(tmp_path: Path) -> None:
    pdf, page = new_page()
    left = " ".join([PARAGRAPH] * 3)
    page.insert_textbox(pymupdf.Rect(50, 72, 290, 400), left, fontname="R", fontsize=10)
    page.insert_textbox(pymupdf.Rect(310, 72, 550, 400), left, fontname="R", fontsize=10)
    path = tmp_path / "columns.pdf"
    pdf.save(path)
    assert tables(path) == []


def test_a_label_and_value_list_is_not_a_table(tmp_path: Path) -> None:
    pdf, page = new_page()
    for i, (label, value) in enumerate(
        [("Ism:", "Alisher"), ("Familiya:", "Navoiy"), ("Shahar:", "Hirot"), ("Kasb:", "shoir")]
    ):
        page.insert_text((72, 100 + 16 * i), label, fontname="R", fontsize=10)
        page.insert_text((260, 100 + 16 * i), value, fontname="R", fontsize=10)
    path = tmp_path / "form.pdf"
    pdf.save(path)
    assert tables(path) == []


def test_scores_prefer_consistent_grids() -> None:
    clean = [list(row) for row in ROWS]
    with_gaps = [list(ROWS[0]), ["", "", ""], list(ROWS[1]), ["", "", ""], list(ROWS[2])]
    cut = [["Jami daromad (birlashgan", ")", "500"], ["Kredit", "10", "20"]]
    assert table_score(clean) == 1.0
    assert table_score(with_gaps) < table_score(clean)
    assert table_score(cut) < table_score([["Jami daromad (birlashgan)", "500"], ["Kredit", "10"]])
    assert table_score([]) == -1.0
