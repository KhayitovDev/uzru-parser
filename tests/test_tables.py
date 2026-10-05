"""PDF tables: ruled and unruled tables, merged cells, scoring, and look-alikes that stay text."""

from pathlib import Path

import pymupdf
import pytest
from helpers import bold_font, cyrillic_font
from uzru_parser import BlockType, parse
from uzru_parser.pdf import _rulings
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


def test_only_thin_bars_and_stroked_paths_count_as_table_rules() -> None:
    """Boxes behind highlighted lines are no table rules; a grid needs rules both ways."""
    highlight = [{"type": "f", "rect": (80, 100 + 20 * i, 550, 116 + 20 * i)} for i in range(8)]
    underlines = [{"type": "f", "rect": (80, 120 + 20 * i, 300, 121 + 20 * i)} for i in range(6)]
    grid = [{"type": "s", "rect": (80, 100 + 20 * i, 500, 100 + 20 * i)} for i in range(4)]
    grid += [{"type": "s", "rect": (80 + 140 * i, 100, 80 + 140 * i, 160)} for i in range(4)]
    assert _rulings(highlight) == 0
    assert _rulings(underlines) == 0
    assert _rulings(grid) == 4


def test_values_starting_lowercase_are_not_words_cut_between_cells() -> None:
    rows = [
        ["Umumiy xavflilik indeksi (KΣ)", "Xavflilik darajasi", "Xavflilik sinfi"],
        ["2,0 dan kam", "oʻta xavfli", "I"],
        ["2,0 dan 16,0 gacha", "yuqori xavfli", "II"],
        ["30,0 dan ortiq", "kam xavfli", "IV"],
    ]
    assert table_score(rows) == 1.0
    assert table_score([["tashki", "lot", "5"], ["Kredit", "10", "20"]]) < 1.0


def test_a_page_number_inside_a_table_frame_is_not_a_row() -> None:
    from uzru_parser.pdf import _page_number_row

    assert _page_number_row(["", "14", ""]) and _page_number_row(["- 7 -", ""])
    assert not _page_number_row(["14", "Ammoniy azoti", "mg/kg"])
    assert not _page_number_row(["Jami", "125", ""])


# A scoring table as browsers print it: rows enclosed by thin rules, a long indicator wrapping
# inside its cell with a filled box drawn behind each of its lines, the number and points
# centred in the row, a last column left blank, and the table going on onto the next page.
INDICATORS = [
    (
        "1.",
        "Xususiy bandlik agentligi taʼsischilari tarkibida sudlanganligi tugallanmagan "
        "shaxslar mavjudligi va ular bilan shartnomalar tuzilganligi",
        "5",
    ),
    (
        "2.",
        "Ish qidirayotgan shaxsdan xizmatlar uchun olinadigan haqni bankdagi maxsus "
        "depozitga qoʻyilishi toʻgʻrisidagi qoidaga amal qilmasdan pul mablagʻlari olinganligi",
        "10",
    ),
    (
        "3.",
        "Xususiy bandlik agentligi, shuningdek uning filiallari va (yoki) vakolatxonalari "
        "haqidagi maʼlumotlar oʻzgarganligi toʻgʻrisida Migratsiya agentligini yetti ish kuni "
        "ichida xabardor qilinmaganligi",
        "15",
    ),
    (
        "4.",
        "Migratsiya agentligining soʻroviga koʻra oʻz faoliyati haqidagi maʼlumotlarni "
        "taqdim etmaganligi",
        "10",
    ),
]
HEADER = ("T/r", "Xavf darajasini baholash koʻrsatkichlari", "Ball", "Qoʻyilgan ball")
EDGES = (63.0, 92.0, 454.0, 510.0, 581.0)


def scoring_table(path: Path) -> Path:
    font = pymupdf.Font(fontfile=cyrillic_font())
    pdf = pymupdf.open()

    def wrap(text: str) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            joined = f"{line} {word}".strip()
            if font.text_length(joined, 11) > EDGES[2] - EDGES[1] - 10 and line:
                lines.append(line)
                line = word
            else:
                line = joined
        return [*lines, line]

    def rule(page: pymupdf.Page, y: float) -> None:
        page.draw_rect(pymupdf.Rect(EDGES[0], y, EDGES[-1], y + 0.7), color=None, fill=(0, 0, 0))

    def frame(page: pymupdf.Page, top: float, bottom: float) -> None:
        for x in EDGES:
            page.draw_rect(pymupdf.Rect(x, top, x + 0.7, bottom), color=None, fill=(0, 0, 0))

    rows = (
        [(HEADER[0], HEADER[1], HEADER[2]), *INDICATORS[:2]],
        [*INDICATORS[2:], ("", "Jami ballar yigʻindisi", "40")],
    )
    for number, part in enumerate(rows):
        page = pdf.new_page()
        page.insert_font(fontname="R", fontfile=cyrillic_font())
        if number == 0:
            text_paragraph(page, 60)
        y = top = 140.0 if number == 0 else 57.0
        rule(page, y)
        for first, indicator, ball in part:
            lines = wrap(indicator)
            height = 16 * len(lines)
            middle = y + height / 2 + 4
            for k, line in enumerate(lines):
                # The boxes fill the cell from rule to rule, one per line.
                box = pymupdf.Rect(EDGES[1] + 5, y + 16 * k, EDGES[2] - 4, y + 16 * (k + 1))
                page.draw_rect(box, color=None, fill=(1, 1, 1))
                page.insert_text((EDGES[1] + 5, y + 12 + 16 * k), line, fontname="R", fontsize=11)
            page.insert_text((EDGES[0] + 4, middle), first, fontname="R", fontsize=11)
            page.insert_text((EDGES[2] + 4, middle), ball, fontname="R", fontsize=11)
            if first == HEADER[0]:
                page.insert_text((EDGES[3] + 4, middle), HEADER[3], fontname="R", fontsize=8)
            y += height
            rule(page, y)
        frame(page, top, y)
    pdf.save(path)
    return path


def test_wrapped_cell_lines_on_filled_boxes_are_one_row(tmp_path: Path) -> None:
    found = tables(scoring_table(tmp_path / "scoring.pdf"))
    assert len(found) == 1  # one table over both pages
    rows = found[0]
    assert rows[0] == list(HEADER)
    numbers = [row[0] for row in rows[1:-1]]
    assert numbers == ["1.", "2.", "3.", "4."]  # each number once, one row per indicator
    assert rows[2][1] == " ".join(INDICATORS[1][1].split())
    assert sum(int(row[2]) for row in rows[1:-1]) == int(rows[-1][2])


def test_every_chunk_of_a_continued_table_starts_with_its_header(tmp_path: Path) -> None:
    from uzru_parser import Chunker

    document = parse(scoring_table(tmp_path / "scoring.pdf"))
    header = " | ".join(HEADER)
    for chunk in Chunker(max_tokens=60, overlap=10).chunk(document):
        table_lines = [line for line in chunk.text.split("\n") if " | " in line]
        if table_lines:
            assert table_lines[0] == header


#: The real regulation behind the two tests above (pages 6-7 hold the scoring table). The tests
#: run when the file is in tests/fixtures/.
SCORING_PDF = Path(__file__).parent / "fixtures" / "1.pdf"
needs_scoring_pdf = pytest.mark.skipif(not SCORING_PDF.is_file(), reason="fixture 1.pdf missing")
ROW_6 = (
    "6. | Ish qidirayotgan shaxsdan xizmatlar uchun olinadigan haqni bankdagi maxsus depozitga "
    "qoʻyilishi toʻgʻrisidagi qoidaga amal qilmasdan pul mablagʻlari olinganligi | 10"
)
ROW_7 = (
    "7. | Xususiy bandlik agentligi, shuningdek uning filiallari va (yoki) vakolatxonalari "
    "haqidagi maʼlumotlar oʻzgarganligi toʻgʻrisida Migratsiya agentligini yetti ish kuni ichida "
    "xabardor qilinmaganligi | 15"
)


@needs_scoring_pdf
def test_the_scoring_table_has_one_row_per_indicator() -> None:
    found = tables(SCORING_PDF)
    scoring = [rows for rows in found if rows[0][0] == "T/r"]
    assert len(scoring) == 1
    rows = scoring[0]
    indicators, total = rows[1:-1], rows[-1]
    assert [row[0] for row in indicators] == [f"{n}." for n in range(1, 11)]
    assert total[0] == "Jami ballar yigʻindisi" and total[2] == "100"
    lines = {" | ".join(cell for cell in row if cell) for row in indicators}
    assert ROW_6 in lines and ROW_7 in lines
    assert sum(int(row[2]) for row in indicators) == 100


@needs_scoring_pdf
def test_every_chunk_of_the_scoring_table_starts_with_its_header() -> None:
    from uzru_parser import Chunker

    document = parse(SCORING_PDF)
    for chunk in Chunker(max_tokens=400, overlap=50).chunk(document):
        table_lines = [line for line in chunk.text.split("\n") if " | " in line]
        if any(line.split(" | ")[0].rstrip(".").isdigit() for line in table_lines):
            assert table_lines[0].startswith("T/r | Xavf darajasini baholash koʻrsatkichlari")
