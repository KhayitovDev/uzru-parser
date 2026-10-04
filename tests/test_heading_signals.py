"""Headings with a style profile (PDF): a heading style plus a second signal; levels follow
numbering first and style rank after."""

from uzru_parser.profile import build_profile
from uzru_parser.structure import RawBlock, build_blocks

BODY = (
    "Bank tizimi davlat iqtisodiyotining muhim qismi bo'lib, u pul muomalasini tartibga\n"
    "soladi va mijozlarga xizmat ko'rsatadi hamda boshqa ko'plab vazifalarni bajaradi."
)
HEIGHTS = {page: 800.0 for page in range(1, 12)}


def raw(
    text: str,
    page: int,
    y: float,
    size: float = 11.0,
    bold: float = 0.0,
    italic: float = 0.0,
    spaced: bool = False,
) -> RawBlock:
    lines = text.count("\n") + 1
    return RawBlock(
        text=text,
        page=page,
        bbox=(50, y, 500, y + 13 * lines),
        font_size=size,
        bold=bold,
        italic=italic,
        font="times",
        spaced=spaced,
    )


def parse(blocks: list[RawBlock], profile: bool = True) -> list[tuple[str, int | None, str]]:
    found = build_profile(blocks, HEIGHTS) if profile else None
    built = build_blocks(blocks, text_is_clean=True, profile=found)
    return [(b.type.value, b.level, b.text) for b in built]


def chapter(page: int) -> list[RawBlock]:
    """A chapter page: chapter title, a numbered section, an italic subheading ending with a
    full stop, body text in between."""
    return [
        raw(f"{page}-BOB. Bank tizimi", page, 60, size=16, bold=1.0),
        raw(BODY, page, 90, spaced=True),
        raw(f"{page}.1. Tijorat banklari", page, 150, bold=1.0, spaced=True),
        raw(BODY, page, 170),
        raw("Bank operatsiyalari turlari.", page, 230, italic=1.0, spaced=True),
        raw(BODY, page, 250),
    ]


def test_italic_subheadings_ending_with_a_full_stop_nest_under_sections() -> None:
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    headings = [(level, text) for kind, level, text in parse(blocks) if kind == "heading"]
    assert headings[:3] == [
        (1, "1-BOB. Bank tizimi"),
        (2, "1.1. Tijorat banklari"),
        (3, "Bank operatsiyalari turlari."),
    ]
    assert len(headings) == 9


def test_without_a_profile_the_full_stop_line_stays_a_paragraph() -> None:
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    texts = [text for kind, _, text in parse(blocks, profile=False) if kind == "heading"]
    assert "Bank operatsiyalari turlari." not in texts


def test_a_heading_style_line_inside_running_text_is_no_heading() -> None:
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    # The italic look, but squeezed between two body paragraphs without any space.
    blocks += [
        raw(BODY, 4, 100),
        raw("Kredit siyosati muhim.", 4, 130, italic=1.0),
        raw(BODY, 4, 145),
    ]
    rows = parse(blocks)
    squeezed = [row for row in rows if row[2] == "Kredit siyosati muhim."]
    assert squeezed and squeezed[0][0] == "paragraph"


def test_numbered_paragraphs_in_body_style_are_not_headings() -> None:
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    blocks += [
        raw("4. Markaziy bank pul-kredit siyosatini olib boradi", 5, 100, spaced=True),
        raw(BODY, 5, 120),
    ]
    rows = parse(blocks)
    numbered = [row for row in rows if "Markaziy bank pul-kredit" in row[2]]
    assert numbered and numbered[0][0] != "heading"


def test_chart_labels_in_bold_are_not_headings() -> None:
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    blocks += [raw(label, 6, 100 + 20 * i, bold=1.0) for i, label in enumerate(("Aktiv", "Passiv"))]
    blocks.append(raw(BODY, 6, 200))
    texts = [text for kind, _, text in parse(blocks) if kind == "heading"]
    assert "Aktiv" not in texts and "Passiv" not in texts


def test_annex_labels_in_the_body_font_and_wrapped_titles_are_headings() -> None:
    """An annex label set like the body text ("2-ILOVA") is a heading by its numbered heading
    word; a bold title wrapped into two blocks stands apart from the text as one title, even
    when bold is also used inside the text."""
    blocks = [block for page in (1, 2, 3) for block in chapter(page)]
    blocks += [raw(BODY.replace("\n", " ") * 2, 4, 60 + 40 * i, bold=1.0) for i in range(3)]
    blocks += [
        raw("2-ILOVA", 5, 40),
        raw("Normativ hujjatlarning narx", 5, 80, bold=1.0, spaced=True),
        raw("MEʼYORLARI", 5, 95, bold=1.0),
        raw(BODY, 5, 130, spaced=True),
    ]
    texts = [text for kind, _, text in parse(blocks) if kind == "heading"]
    assert "2-ILOVA" in texts
    assert any(text.startswith("Normativ hujjatlarning narx") for text in texts)
