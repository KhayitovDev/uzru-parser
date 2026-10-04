"""The document style profile: body style, heading styles and their ranks, footnote style."""

from uzru_parser.profile import Style, build_profile, style_of
from uzru_parser.structure import RawBlock

HEIGHTS = {page: 800.0 for page in range(1, 11)}
BODY = (
    "Bank tizimi davlat iqtisodiyotining muhim qismi bo'lib, u pul muomalasini tartibga\n"
    "soladi va mijozlarga xizmat ko'rsatadi hamda boshqa ko'plab vazifalarni bajaradi."
)


def raw(
    text: str,
    page: int = 1,
    y: float = 100.0,
    size: float = 11.0,
    bold: float = 0.0,
    italic: float = 0.0,
    font: str = "times",
) -> RawBlock:
    return RawBlock(
        text=text,
        page=page,
        bbox=(50, y, 500, y + 12 * (text.count("\n") + 1)),
        font_size=size,
        bold=bold,
        italic=italic,
        font=font,
    )


def book() -> list[RawBlock]:
    """Chapters (16 pt bold), sections (11 pt bold), italic subheadings, body paragraphs."""
    blocks: list[RawBlock] = []
    for page in range(1, 6):
        blocks.append(raw(f"{page}-BOB. Bank tizimi", page, 60, size=16, bold=1.0))
        blocks.append(raw(BODY, page, 90))
        blocks.append(raw(f"{page}.1. Tijorat banklari", page, 140, bold=1.0))
        blocks.append(raw(BODY, page, 160))
        blocks.append(raw("Bank operatsiyalari turlari.", page, 220, italic=1.0))
        blocks.append(raw(BODY, page, 240))
        blocks.append(raw(BODY, page, 300))
    return blocks


def test_body_style_holds_the_most_text() -> None:
    profile = build_profile(book(), HEIGHTS)
    assert profile.body == Style("times", 11.0, False, False, False)


def test_heading_styles_are_ranked_by_size_then_weight() -> None:
    profile = build_profile(book(), HEIGHTS)
    ranked = sorted(profile.headings, key=profile.headings.__getitem__)
    assert ranked == [
        Style("times", 16.0, True, False, False),
        Style("times", 11.0, True, False, False),
        Style("times", 11.0, False, True, False),
    ]


def test_chart_labels_are_not_a_heading_style() -> None:
    blocks = book()
    labels = [raw(label, 6, 400 + 15 * i, size=11, bold=1.0) for i, label in enumerate("ABCDE")]
    blocks += [*labels, raw(BODY, 6, 600)]
    profile = build_profile(blocks, HEIGHTS)
    label_style = style_of(labels[0])
    assert label_style is not None and label_style.caps is False
    # The bold body-size style still serves the "N.1." sections, followed by body text.
    assert profile.rank(Style("times", 11.0, True, False, False)) is not None
    only_labels = build_profile([*labels, raw(BODY, 6, 600), raw(BODY, 7, 100)], HEIGHTS)
    assert only_labels.rank(label_style) is None


def test_bold_paragraphs_are_not_a_heading_style() -> None:
    blocks = [raw(BODY, page, 100) for page in range(1, 5)]
    blocks += [raw(BODY, page, 300, bold=1.0) for page in range(1, 4)]
    profile = build_profile(blocks, HEIGHTS)
    assert profile.headings == {}


def test_bigger_titles_make_a_heading_style_but_a_single_bold_line_does_not() -> None:
    titles = ["Kirish", "Asosiy qism", "Xulosa"]
    blocks = [
        b
        for p, t in enumerate(titles, 1)
        for b in (raw(t, p, 60, size=14, bold=1.0), raw(BODY, p, 90))
    ]
    blocks += [raw("Muhim eslatma", 4, 60, bold=1.0), raw(BODY, 4, 90), raw(BODY, 5, 90)]
    profile = build_profile(blocks, HEIGHTS)
    assert list(profile.headings) == [Style("times", 14.0, True, False, False)]


def test_a_lone_title_makes_no_profile() -> None:
    """One big title says nothing about the other headings: the rules without a profile apply."""
    blocks = [raw("Kirish", 1, 60, size=14, bold=1.0), raw(BODY, 1, 90), raw(BODY, 2, 90)]
    assert build_profile(blocks, HEIGHTS).headings == {}


def test_small_text_at_the_foot_of_pages_is_the_footnote_style() -> None:
    blocks = book() + [raw("1 Manba: Markaziy bank hisoboti.", p, 760, size=8) for p in (1, 2)]
    profile = build_profile(blocks, HEIGHTS)
    assert profile.footnote == Style("times", 8.0, False, False, False)


def test_an_empty_document_has_no_profile() -> None:
    profile = build_profile([], HEIGHTS)
    assert profile.body is None and profile.headings == {}
