from pathlib import Path

import pymupdf
from helpers import cyrillic_font
from uzru_parser import BlockType, parse
from uzru_parser.columns import reading_regions
from uzru_parser.paragraphs import Line

LEFT = " ".join(
    f"Chap ustundagi {i}-gap pul aylanmasi va bank tizimi haqida batafsil soʻzlaydi."
    for i in range(1, 9)
)
MIDDLE = " ".join(
    f"Средняя колонка, предложение {i}, рассказывает о кредитной политике банков."
    for i in range(1, 9)
)
RIGHT = " ".join(
    f"Oʻng ustundagi {i}-gap valyuta bozori va kredit siyosatini tushuntiradi." for i in range(1, 9)
)


def page_pdf(path: Path, boxes: list[tuple[tuple[float, float, float, float], str, float]]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="f", fontfile=cyrillic_font())
    for rect, text, size in boxes:
        page.insert_textbox(pymupdf.Rect(*rect), text, fontname="f", fontsize=size)
    doc.save(path)
    doc.close()
    return path


def paragraphs(path: Path) -> list[str]:
    return [b.text for b in parse(path).blocks if b.type is BlockType.PARAGRAPH]


def test_two_columns_are_read_one_after_the_other(tmp_path: Path) -> None:
    pdf = page_pdf(
        tmp_path / "two.pdf",
        [((50, 72, 290, 770), LEFT, 10), ((310, 72, 550, 770), RIGHT, 10)],
    )
    assert paragraphs(pdf) == [LEFT, RIGHT]


def test_three_columns(tmp_path: Path) -> None:
    pdf = page_pdf(
        tmp_path / "three.pdf",
        [
            ((40, 72, 205, 770), LEFT, 9),
            ((220, 72, 385, 770), MIDDLE, 9),
            ((400, 72, 565, 770), RIGHT, 9),
        ],
    )
    assert paragraphs(pdf) == [LEFT, MIDDLE, RIGHT]


def test_full_width_title_above_two_columns(tmp_path: Path) -> None:
    title = "Pul va kredit siyosatining asosiy yoʻnalishlari hamda ularning bank tizimiga taʼsiri"
    pdf = page_pdf(
        tmp_path / "title.pdf",
        [
            ((50, 60, 550, 110), title, 14),
            ((50, 130, 290, 770), LEFT, 10),
            ((310, 130, 550, 770), RIGHT, 10),
        ],
    )
    texts = [b.text for b in parse(pdf).blocks]
    assert texts[0] == title
    assert texts[1:] == [LEFT, RIGHT]


def test_side_box_is_read_after_the_main_text(tmp_path: Path) -> None:
    main = LEFT + " " + RIGHT
    box_text = "Tayanch iboralar: pul massasi, inflyatsiya, qayta moliyalash stavkasi."
    path = tmp_path / "box.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="f", fontfile=cyrillic_font())
    page.draw_rect(pymupdf.Rect(400, 100, 560, 260), color=None, fill=(0.85, 0.85, 0.85))
    page.insert_textbox(pymupdf.Rect(405, 105, 555, 255), box_text, fontname="f", fontsize=10)
    page.insert_textbox(pymupdf.Rect(50, 72, 380, 770), main, fontname="f", fontsize=10)
    doc.save(path)
    doc.close()
    assert paragraphs(path) == [main, box_text]


def line(text: str, x0: float, x1: float, y: float) -> Line:
    return Line(text=text, bbox=(x0, y, x1, y + 12), size=10.0, chars=len(text))


def test_single_column_page_keeps_its_line_order() -> None:
    lines = [line(f"qator {i} matni toʻliq kenglikda", 72, 520, 100 + 14 * i) for i in range(12)]
    regions = reading_regions(lines, [], 10.0)
    assert len(regions) == 1 and regions[0] is lines


def test_label_and_value_list_is_not_split_into_columns() -> None:
    labels = ["Ism:", "Familiya:", "Tugʻilgan sana:", "Manzil:", "Telefon:"]
    lines = [
        item
        for i, label in enumerate(labels)
        for item in (
            line(label, 72, 72 + 6 * len(label), 100 + 16 * i),
            line(f"qiymat {i} uzun matn bilan toʻldirilgan", 260, 520, 100 + 16 * i),
        )
    ]
    assert reading_regions(lines, [], 10.0) == [lines]


def test_long_single_column_page_with_many_gaps_stays_one_region() -> None:
    lines = [
        line(
            f"paragraf {i // 3} qatori {i}",
            72,
            300 if i % 3 == 2 else 520,
            60 + 14 * i + 8 * (i // 3),
        )
        for i in range(150)
    ]
    assert reading_regions(lines, [], 10.0) == [lines]


def sentences(name: str, count: int = 6) -> str:
    return " ".join(
        f"{name} qismidagi {i}-gap bank tizimi va pul muomalasi haqida soʻzlaydi."
        for i in range(1, count + 1)
    )


def test_two_columns_above_and_three_below_are_read_band_by_band(tmp_path: Path) -> None:
    top_left, top_right = sentences("Yuqori chap"), sentences("Yuqori oʻng")
    low_left, low_mid, low_right = (
        sentences("Quyi chap"),
        sentences("Quyi oʻrta"),
        sentences("Quyi oʻng"),
    )
    pdf = page_pdf(
        tmp_path / "bands.pdf",
        [
            ((50, 72, 290, 360), top_left, 9),
            ((310, 72, 550, 360), top_right, 9),
            ((40, 420, 205, 770), low_left, 9),
            ((220, 420, 385, 770), low_mid, 9),
            ((400, 420, 565, 770), low_right, 9),
        ],
    )
    # Narrow ragged columns may break into more paragraphs; the reading order is what counts.
    expected = [top_left, top_right, low_left, low_mid, low_right]
    assert " ".join(paragraphs(pdf)) == " ".join(expected)


def test_single_column_with_wide_gaps_keeps_its_order() -> None:
    lines = [
        line(f"paragraf {i // 4} qatori {i}", 72, 520, 60 + 14 * i + 30 * (i // 4))
        for i in range(24)
    ]
    assert reading_regions(lines, [], 10.0) == [lines]


def test_bands_with_different_gutters_are_cut_one_by_one() -> None:
    """Lines come sorted by height, as from producers that write one block per line: the
    columns of each band are interleaved until the band is cut."""
    top = [(50, 290, "tl"), (310, 550, "tr")]
    bottom = [(40, 205, "bl"), (220, 385, "bm"), (400, 565, "br")]
    lines: list[Line] = []
    for row in range(8):
        lines += [line(f"{name} qator {row} matni", x0, x1, 80 + 14 * row) for x0, x1, name in top]
    for row in range(8):
        lines += [
            line(f"{name} qator {row} matni", x0, x1, 300 + 14 * row) for x0, x1, name in bottom
        ]
    regions = reading_regions(lines, [], 10.0)
    assert [{text.text.split()[0] for text in region} for region in regions] == [
        {"tl"},
        {"tr"},
        {"bl"},
        {"bm"},
        {"br"},
    ]
    assert all(len(region) == 8 for region in regions)


def test_one_stretched_row_is_not_cut_into_columns() -> None:
    """A justified line stored word by word looks like narrow columns side by side; a
    column needs several rows, so the page keeps its order."""
    above = [
        line(f"qator {i} toʻliq kenglikdagi oddiy matn satri", 72, 520, 100 + 14 * i)
        for i in range(4)
    ]
    words = ["Aholi", "punktlari", "hududlari,", "shu", "jumladan", "bolalar"]
    row = [line(word, 72 + 76 * i, 72 + 76 * i + 60, 100 + 14 * 4) for i, word in enumerate(words)]
    below = [
        line(f"davomi {i} toʻliq kenglikdagi oddiy matn satri", 72, 520, 100 + 14 * (5 + i))
        for i in range(4)
    ]
    lines = above + row + below
    assert reading_regions(lines, [], 10.0) == [lines]
