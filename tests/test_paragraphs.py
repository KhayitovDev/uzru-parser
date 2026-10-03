from uzru_parser.paragraphs import (
    LayoutStats,
    Line,
    build_paragraphs,
    figure_labels,
    figure_regions,
    layout_stats,
    merge_row_fragments,
)

SIZE = 11.0
PITCH = 14.2  # line height 13.2 + typical gap 1.0
STATS = LayoutStats(body_size=SIZE, line_gap=1.0, right_edge=500.0, line_blocks=True)


def line(
    text: str,
    y: float,
    x0: float = 72.0,
    x1: float = 500.0,
    size: float = SIZE,
    bold: float = 0.0,
    block: int = 0,
) -> Line:
    return Line(
        text=text,
        bbox=(x0, y, x1, y + size * 1.2),
        size=size,
        bold=bold,
        chars=len(text.replace(" ", "")),
        block=block,
    )


def texts(lines: list[Line], stats: LayoutStats = STATS) -> list[str]:
    return [b.text for b in build_paragraphs(lines, 1, stats)]


def test_one_line_per_block_is_rebuilt_into_a_paragraph() -> None:
    lines = [
        line("Pul aylanmasi iqtisodiyotda muhim oʻrin tutadi va", 100, block=0),
        line("markaziy bank uni boshqaradi, tijorat banklari esa", 100 + PITCH, block=1),
        line("kredit beradi.", 100 + 2 * PITCH, x1=160, block=2),
    ]
    assert texts(lines) == ["\n".join(item.text for item in lines)]


def test_larger_gap_starts_a_new_paragraph() -> None:
    lines = [
        line("Birinchi abzats matni davom etadi va", 100),
        line("tugaydi", 100 + PITCH, x1=150),
    ]
    lines.append(line("ikkinchi abzats boshqa joyda boshlanadi", 100 + 2 * PITCH + 20))
    assert len(texts(lines)) == 2


def test_first_line_indent_starts_and_belongs_to_a_paragraph() -> None:
    lines = [
        line("Birinchi abzatsning birinchi qatori", 100, x0=90),
        line("davomi shu yerda turibdi va yana davom", 100 + PITCH),
        line("Yangi abzats xatboshidan boshlanadi", 100 + 2 * PITCH, x0=90),
    ]
    assert texts(lines) == [f"{lines[0].text}\n{lines[1].text}", lines[2].text]


def test_short_line_with_full_stop_ends_the_paragraph() -> None:
    lines = [
        line("Bu gap shu qatorda tugadi.", 100, x1=250),
        line("Keyingi gap yangi abzatsda turibdi", 100 + PITCH),
    ]
    assert len(texts(lines)) == 2


def test_short_line_without_punctuation_continues_into_lowercase() -> None:
    lines = [line("Bu gap qisqa qatorda", 100, x1=250), line("davom etadi.", 100 + PITCH, x1=200)]
    assert len(texts(lines)) == 1


def test_new_item_or_style_change_starts_a_new_block() -> None:
    numbered = [line("Birinchi qism matni davom etadi", 100), line("2. Ikkinchi band", 100 + PITCH)]
    styled = [line("1.1. Banklar", 100, bold=1.0, x1=200), line("Matn shu yerda", 100 + PITCH)]
    assert len(texts(numbered)) == 2
    assert len(texts(styled)) == 2


def test_hanging_indent_of_a_list_item_stays_in_the_item() -> None:
    lines = [
        line("• uzun roʻyxat bandi bir qatorga sigʻmaydi va", 100),
        line("davom etadi", 100 + PITCH, x0=84),
    ]
    assert len(texts(lines)) == 1


def test_lines_in_different_columns_are_not_joined() -> None:
    lines = [
        line("chap ustundagi matn", 100, x0=72, x1=280),
        line("oʻng ustundagi matn", 100 + PITCH, x0=320),
    ]
    assert len(texts(lines)) == 2


def test_paragraph_blocks_from_the_producer_are_respected() -> None:
    stats = LayoutStats(body_size=SIZE, line_gap=1.0, right_edge=500.0, line_blocks=False)
    ended = [
        line("Gap tugadi.", 100, block=0),
        line("Yangi blok yangi abzats", 100 + PITCH, block=1),
    ]
    runs_on = [
        line("Gap davom etmoqda va", 100, block=0),
        line("keyingi blokda tugaydi.", 100 + PITCH, block=1),
    ]
    assert len(texts(ended, stats)) == 2
    assert len(texts(runs_on, stats)) == 1


def test_space_above_is_recorded() -> None:
    lines = [line("Oldingi abzats.", 100, x1=200), line("Sarlavha", 100 + PITCH + 20, x1=150)]
    blocks = build_paragraphs(lines, 1, STATS)
    assert [b.spaced for b in blocks] == [False, True]


def test_layout_statistics_come_from_the_document() -> None:
    page = [line(f"qator {i} matni", 100 + i * 16, block=i) for i in range(10)]
    page.append(line("SARLAVHA", 300, size=16))
    stats = layout_stats([page])
    assert stats.body_size == SIZE
    assert round(stats.line_gap, 1) == round(16 - SIZE * 1.2, 1)
    assert stats.line_blocks


def test_number_and_title_on_one_row_are_merged() -> None:
    merged = merge_row_fragments(
        [line("1.1.", 100, x1=95), line("Banklarning turlari", 100, x0=110, x1=300, bold=1.0)]
    )
    assert [m.text for m in merged] == ["1.1. Banklarning turlari"]
    assert merged[0].bold == 1.0
    toc = merge_row_fragments([line("Banklarning turlari …", 100, x1=400), line("37", 100, x0=480)])
    assert [m.text for m in toc] == ["Banklarning turlari … 37"]
    chapter = merge_row_fragments([line("II-BOB", 100, x1=130), line("PUL VA KREDIT", 100, x0=140)])
    assert [m.text for m in chapter] == ["II-BOB PUL VA KREDIT"]


def test_words_on_one_row_that_are_not_numbers_stay_apart() -> None:
    merged = merge_row_fragments([line("Ustun bir", 100, x1=200), line("Ustun ikki", 100, x0=300)])
    assert len(merged) == 2


def test_labels_inside_a_drawing_become_one_figure_block() -> None:
    region = (100.0, 400.0, 500.0, 600.0)
    lines = [
        line("Matn grafikdan oldin turibdi va davom etadi", 100),
        line("Risklar", 450, x0=120, x1=170),
        line("Kredit", 450, x0=250, x1=300),
        line("Foiz", 520, x0=400, x1=430),
    ]
    blocks = build_paragraphs(lines, 1, STATS, [region])
    assert [(b.text, b.role) for b in blocks] == [
        (lines[0].text, None),
        ("Risklar | Kredit | Foiz", "figure"),
    ]


def test_one_short_line_in_a_frame_is_not_a_figure() -> None:
    region = (60.0, 90.0, 510.0, 130.0)
    lines = [line("Tayanch iboralar", 100, x1=200)]
    assert figure_labels(lines, [region], SIZE) == set()


def test_runs_of_short_plain_lines_are_a_figure_without_drawings() -> None:
    labels = [
        line(word, 100 + i * PITCH, x1=150)
        for i, word in enumerate(["Risklar", "Ekologiya", "Siyosiy", "Moliyaviy"])
    ]
    assert figure_labels(labels, [], SIZE) == {0, 1, 2, 3}
    assert figure_labels(labels[:3], [], SIZE) == set()


def test_bold_or_numbered_short_lines_are_not_free_labels() -> None:
    lines = [line(f"{i}. Band", 100 + i * PITCH, x1=150) for i in range(1, 6)]
    lines += [line("SARLAVHA", 300, x1=150, bold=1.0)]
    assert figure_labels(lines, [], SIZE) == set()


def test_figure_regions_group_drawings_and_ignore_rules_and_frames() -> None:
    page = (0.0, 0.0, 595.0, 842.0)
    bars = [(100.0 + i * 30, 500.0, 120.0 + i * 30, 600.0) for i in range(5)]
    rule = (50.0, 300.0, 545.0, 300.5)
    frame = (10.0, 10.0, 585.0, 832.0)
    far = (100.0, 100.0, 140.0, 140.0)
    regions = figure_regions([*bars, rule, frame, far], page, SIZE)
    assert sorted(regions) == [(100.0, 100.0, 140.0, 140.0), (100.0, 500.0, 240.0, 600.0)]


def test_line_ending_with_an_abbreviation_runs_on_before_a_capital() -> None:
    stats = LayoutStats(body_size=SIZE, line_gap=1.0, right_edge=500.0, line_blocks=False)
    lines = [
        line("Отзыв на работу дал проф.", 100, x1=300, block=0),
        line("Иванов из Московского университета.", 100 + PITCH, block=1),
    ]
    assert len(texts(lines, stats)) == 1


def test_short_line_ending_a_sentence_still_ends_the_paragraph() -> None:
    lines = [
        line("Работа завершена.", 100, x1=250),
        line("Иванов начал новую главу", 100 + PITCH),
    ]
    assert len(texts(lines)) == 2
