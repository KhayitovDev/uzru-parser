"""Tagged PDFs: the structure tree gives headings, paragraphs, lists, tables and notes; broken or
useless tags fall back to the layout rules."""

from pathlib import Path

import pymupdf
import pytest
from helpers import bold_font, cyrillic_font
from tagged_pdf import Artifact, Tag, Text, Untagged, write_tagged_pdf
from uzru_parser import BlockType, Chunker, parse
from uzru_parser.tagged import STRUCTURE_FLAG, Node, _array_items, _unit_at

#: Tests of the tagged route need a PyMuPDF that reports the structure (1.26.6+).
needs_structure = pytest.mark.skipif(not STRUCTURE_FLAG, reason="PyMuPDF too old for tags")

BODY = (
    "Ushbu qonunning maqsadi fuqarolarning huquqlarini himoya qilishdan iborat",
    "bo‘lib, u davlat organlari faoliyatini tartibga soladi va jamiyat",
    "manfaatlarini ta’minlaydi hamda boshqa vazifalarni ham belgilaydi.",
)


def paragraph(page: int, top: float, lines: tuple[str, ...] = BODY) -> list[Text]:
    return [Text(line, page=page, y=top + 14 * i) for i, line in enumerate(lines)]


def headed_document(tmp_path: Path) -> Path:
    root = [
        Tag("H1", [Text("1-BOB. Umumiy qoidalar", y=80, size=16, bold=True)]),
        Tag("P", paragraph(0, 110)),
        Tag("H2", [Text("1.1. Asosiy tushunchalar", y=170, size=13, bold=True)]),
        Tag("P", paragraph(0, 200)),
        Tag("H1", [Text("Глава 2. Общие положения", page=1, y=80, size=16, bold=True)]),
        Tag("P", [Text("Настоящий закон регулирует отношения в сфере банков.", page=1, y=110)]),
    ]
    extra = [
        Artifact("Qonun hujjatlari to‘plami", page=0, y=40, size=9),
        Artifact("Qonun hujjatlari to‘plami", page=1, y=40, size=9),
        Artifact("1", page=0, y=810, size=9),
        Artifact("2", page=1, y=810, size=9),
    ]
    return write_tagged_pdf(tmp_path / "headed.pdf", root, extra=extra)


@needs_structure
def test_headings_and_paragraphs_come_from_the_tags(tmp_path: Path) -> None:
    document = parse(headed_document(tmp_path))
    headings = [(b.text, b.level) for b in document.blocks if b.type is BlockType.HEADING]
    assert headings == [
        ("1-BOB. Umumiy qoidalar", 1),
        ("1.1. Asosiy tushunchalar", 2),
        ("Глава 2. Общие положения", 1),
    ]
    paragraphs = [b for b in document.blocks if b.type is BlockType.PARAGRAPH]
    assert len(paragraphs) == 3
    assert paragraphs[0].text.startswith("Ushbu qonunning") and paragraphs[0].text.endswith(
        "belgilaydi."
    )
    assert document.metadata.extra["pdf_route"] == "tagged"
    assert document.metadata.extra["pdf_tags"]["used"] is True
    assert document.metadata.extra["heading_sources"] == {"tags": 3}


@needs_structure
def test_artifacts_never_reach_the_text(tmp_path: Path) -> None:
    document = parse(headed_document(tmp_path))
    assert "to‘plami" not in document.text and "to'plami" not in document.text
    assert not any(b.text in ("1", "2") for b in document.blocks)


@needs_structure
def test_role_map_names_custom_tags(tmp_path: Path) -> None:
    root = [
        Tag("Heading1", [Text("Kirish", y=80, size=16, bold=True)]),
        Tag("Normal", paragraph(0, 110)),
    ]
    path = write_tagged_pdf(
        tmp_path / "roles.pdf", root, role_map={"Heading1": "H1", "Normal": "P"}
    )
    blocks = parse(path).blocks
    assert (blocks[0].type, blocks[0].level, blocks[0].text) == (BlockType.HEADING, 1, "Kirish")
    assert blocks[1].type is BlockType.PARAGRAPH


def item(page: int, top: float, label: str, text: str) -> Tag:
    return Tag(
        "LI",
        [
            Tag("Lbl", [Text(label, page=page, y=top)]),
            Tag("LBody", [Text(text, page=page, x=95, y=top)]),
        ],
    )


@needs_structure
def test_list_items_keep_their_labels(tmp_path: Path) -> None:
    root = [
        Tag("P", [Text("Quyidagilar talab qilinadi:", y=80)]),
        Tag(
            "L",
            [
                item(0, 100, "1.", "pasport nusxasi;"),
                item(0, 115, "2.", "ariza va boshqa hujjatlar."),
            ],
        ),
    ]
    blocks = parse(write_tagged_pdf(tmp_path / "list.pdf", root)).blocks
    lists = [b for b in blocks if b.type is BlockType.LIST]
    assert len(lists) == 1
    assert lists[0].extra["items"] == ["1. pasport nusxasi;", "2. ariza va boshqa hujjatlar."]


def cell(name: str, text: str, x: float, y: float, attributes: str = "") -> Tag:
    return Tag(name, [Text(text, x=x, y=y)], attributes=attributes)


@needs_structure
def test_tables_get_rows_and_spanned_cells(tmp_path: Path) -> None:
    root = [
        Tag(
            "Table",
            [
                Tag("TR", [cell("TH", "Ko‘rsatkich", 72, 100), cell("TH", "Qiymat", 250, 100)]),
                Tag("TR", [cell("TD", "Daromad", 72, 120), cell("TD", "100", 250, 120)]),
                Tag(
                    "TR",
                    [cell("TD", "Jami summa", 72, 140, "/A <</O /Table /ColSpan 2>>")],
                ),
            ],
        ),
    ]
    blocks = parse(write_tagged_pdf(tmp_path / "table.pdf", root)).blocks
    tables = [b for b in blocks if b.type is BlockType.TABLE]
    assert len(tables) == 1
    assert tables[0].extra["rows"] == [
        ["Koʻrsatkich", "Qiymat"],
        ["Daromad", "100"],
        ["Jami summa", ""],
    ]


@needs_structure
def test_notes_are_footnotes_and_figures_keep_their_role(tmp_path: Path) -> None:
    root = [
        Tag("P", paragraph(0, 80)),
        Tag("Figure", [Text("Daromad", y=200, size=8), Text("Xarajat", y=215, size=8)]),
        Tag("Caption", [Text("1-rasm. Daromad va xarajat", y=240)]),
        Tag("Note", [Text("1 Qonun 2020-yilda qabul qilingan.", y=780, size=8)]),
    ]
    blocks = parse(write_tagged_pdf(tmp_path / "notes.pdf", root)).blocks
    footnotes = [b for b in blocks if b.type is BlockType.FOOTNOTE]
    assert [(f.extra.get("number"), f.text) for f in footnotes] == [
        ("1", "Qonun 2020-yilda qabul qilingan.")
    ]
    roles = {b.text: b.extra.get("role") for b in blocks}
    assert roles["Daromad | Xarajat"] == "figure"
    assert roles["1-rasm. Daromad va xarajat"] == "caption"


@needs_structure
def test_a_paragraph_going_on_on_the_next_page_is_one_block(tmp_path: Path) -> None:
    first = paragraph(0, 740, BODY[:2])
    rest = [Text(BODY[2], page=1, y=80)]
    root = [
        Tag("P", paragraph(0, 80)),
        Tag("P", [*first, *rest]),
        Tag("P", [Text("Keyingi xatboshi shu yerda boshlanadi.", page=1, y=110)]),
    ]
    blocks = parse(write_tagged_pdf(tmp_path / "pages.pdf", root)).blocks
    texts = [b.text for b in blocks if b.type is BlockType.PARAGRAPH]
    assert texts[1] == " ".join(BODY).replace("‘", "ʻ").replace("’", "ʼ")
    assert texts[2] == "Keyingi xatboshi shu yerda boshlanadi."


@needs_structure
def test_contents_entries_are_left_out_of_chunks(tmp_path: Path) -> None:
    root = [
        Tag(
            "TOC",
            [
                Tag("TOCI", [Text("1-BOB. Umumiy qoidalar ........ 3", y=80)]),
                Tag("TOCI", [Text("2-BOB. Yakuniy qoidalar ........ 9", y=95)]),
            ],
        ),
        Tag("H1", [Text("1-BOB. Umumiy qoidalar", page=1, y=80, size=16, bold=True)]),
        Tag("P", paragraph(1, 110)),
    ]
    document = parse(write_tagged_pdf(tmp_path / "toc.pdf", root))
    toc = [b for b in document.blocks if b.extra.get("role") == "toc"]
    assert len(toc) == 2
    chunks = Chunker().chunk(document)
    assert all("........" not in chunk.text for chunk in chunks)


# --- Tags that are not trusted ---------------------------------------------------------------


def plain_pdf(path: Path, lines: list[tuple[str, float]]) -> Path:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="F0", fontfile=cyrillic_font())
    page.insert_font(fontname="F1", fontfile=bold_font())
    for text, y in lines:
        page.insert_text((72, y), text, fontname="F0", fontsize=11)
    pdf.save(path)
    return path


@needs_structure
def test_mostly_untagged_text_uses_the_rules(tmp_path: Path) -> None:
    # MuPDF keeps the last element open, so untagged text drawn after tagged text counts as
    # tagged; untagged text drawn first stays outside the tree.
    tagged_line = Text("Faqat bitta qator belgilangan.", y=300)
    loose = [Untagged(line, y=80 + 14 * i) for i, line in enumerate(BODY * 3)]
    path = write_tagged_pdf(
        tmp_path / "sparse.pdf",
        [Tag("P", [tagged_line])],
        extra=loose,
        draw_order=[*loose, tagged_line],
    )
    document = parse(path)
    assert document.metadata.extra["pdf_route"] == "rules"
    assert document.metadata.extra["pdf_tags"]["used"] is False
    assert document.metadata.extra["pdf_tags"]["reason"] == "tags miss text"


@needs_structure
def test_one_element_per_page_uses_the_rules(tmp_path: Path) -> None:
    lines = [Text(f"{BODY[i % 3]} {i}", y=60 + 16 * i) for i in range(45)]
    document = parse(write_tagged_pdf(tmp_path / "page.pdf", [Tag("P", lines)]))
    assert document.metadata.extra["pdf_route"] == "rules"
    assert document.metadata.extra["pdf_tags"]["reason"] == "elements hold whole pages"


@needs_structure
def test_tags_against_the_page_order_use_the_rules(tmp_path: Path) -> None:
    tags = [Tag("P", paragraph(0, 80 + 60 * i)) for i in range(6)]
    path = write_tagged_pdf(tmp_path / "reversed.pdf", list(reversed(tags)))
    document = parse(path)
    assert document.metadata.extra["pdf_route"] == "rules"
    assert document.metadata.extra["pdf_tags"]["reason"] == "tag order runs against the page"


def test_a_slow_parent_tree_is_dropped(tmp_path: Path) -> None:
    lines = [Text(f"Satr {i}", x=72 + 60 * (i % 8), y=40 + 3 * (i // 8)) for i in range(240)]
    path = write_tagged_pdf(tmp_path / "slow.pdf", [Tag("P", [line]) for line in lines])
    pdf = pymupdf.open(path)
    tree = int(pdf.xref_get_key(pdf.pdf_catalog(), "StructTreeRoot")[1].split()[0])
    parent_tree = int(pdf.xref_get_key(tree, "ParentTree")[1].split()[0])
    nums = pdf.xref_get_key(parent_tree, "Nums")[1]
    refs = nums[nums.index("[", 1) + 1 : nums.rindex("]", 0, -1)].split(" 0 R")
    refs = [ref.strip() for ref in refs if ref.strip()]
    shuffled = refs[1:] + refs[:1]  # every id now finds another element at its position
    pdf.xref_set_key(parent_tree, "Nums", f"[0 [{' '.join(f'{r} 0 R' for r in shuffled)}]]")
    broken = tmp_path / "broken.pdf"
    pdf.save(broken)
    document = parse(broken)
    assert document.metadata.extra["pdf_route"] == "rules"
    assert document.metadata.extra["pdf_tags"]["reason"] == "too slow to follow"
    assert "Satr 239" in document.text


# --- Must not change ----------------------------------------------------------------------------


def test_untagged_pdfs_report_the_rules_route_only(tmp_path: Path) -> None:
    path = plain_pdf(tmp_path / "plain.pdf", [(line, 80 + 14 * i) for i, line in enumerate(BODY)])
    extra = parse(path).metadata.extra
    assert extra["pdf_route"] == "rules"
    assert "pdf_tags" not in extra


@needs_structure
def test_an_empty_tree_reads_like_an_untagged_pdf(tmp_path: Path) -> None:
    lines = [(line, 80 + 14 * i) for i, line in enumerate(BODY)]
    plain = parse(plain_pdf(tmp_path / "plain.pdf", lines))
    path = plain_pdf(tmp_path / "empty.pdf", lines)
    pdf = pymupdf.open(path)
    root = pdf.get_new_xref()
    pdf.update_object(root, "<</Type /StructTreeRoot /K []>>")
    pdf.xref_set_key(pdf.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
    tagged_path = tmp_path / "empty-tree.pdf"
    pdf.save(tagged_path)
    document = parse(tagged_path)
    assert document.metadata.extra["pdf_tags"]["reason"] == "no tagged text"
    assert [(b.type, b.text) for b in document.blocks] == [(b.type, b.text) for b in plain.blocks]


# --- Helpers ----------------------------------------------------------------------------------


def test_array_items_split_refs_numbers_and_dictionaries() -> None:
    assert _array_items("[1 0 R <</Type/MCR/Pg 18 0 R/MCID 0>> 4]") == [
        "1 0 R",
        "<< /Type/MCR/Pg 18 0 R /MCID 0 >>",
        "4",
    ]


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        (("Document", "P", "Span"), 1),  # the paragraph, not the inline span
        (("Document", "Table", "TR", "TD", "P"), 1),  # the whole table
        (("Document", "P", "Note"), 2),  # a note inside a paragraph stands apart
        (("Document", "L", "LI", "LBody", "L", "LI", "LBody"), 5),  # a nested item
        (("Document", "Sect"), None),  # text in a container is untagged
    ],
)
def test_the_unit_of_a_path(kinds: tuple[str, ...], expected: int | None) -> None:
    path = tuple(Node(kind, kind, 0) for kind in kinds)
    assert _unit_at(path) == expected


@needs_structure
def test_tagged_pdfs_do_not_need_the_layout_model(tmp_path: Path) -> None:
    from uzru_parser import Parser

    document = Parser(layout_model=tmp_path / "model.onnx").parse(headed_document(tmp_path))
    assert document.metadata.extra["pdf_route"] == "tagged"
    assert document.metadata.extra["layout_model"] == {"status": "not needed", "pages": []}


@needs_structure
def test_elements_missing_from_their_parent_use_the_rules(tmp_path: Path) -> None:
    path = headed_document(tmp_path)
    pdf = pymupdf.open(path)
    tree = int(pdf.xref_get_key(pdf.pdf_catalog(), "StructTreeRoot")[1].split()[0])
    document_element = int(pdf.xref_get_key(tree, "K")[1].split()[0])
    pdf.xref_set_key(document_element, "K", "[]")  # the kids still name it as their parent
    broken = tmp_path / "orphans.pdf"
    pdf.save(broken)
    document = parse(broken)
    assert document.metadata.extra["pdf_route"] == "rules"
    assert document.metadata.extra["pdf_tags"]["reason"] == "tags do not match the tree"
    assert "Ushbu qonunning" in document.text and "Глава 2" in document.text
