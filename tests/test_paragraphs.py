from uzru_parser.paragraphs import (
    LayoutStats,
    Line,
    build_paragraphs,
    figure_labels,
    figure_regions,
    group_formula_debris,
    join_spread_lines,
    layout_stats,
    merge_row_fragments,
    rejoin_spread_rows,
)
from uzru_parser.structure import RawBlock

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


def spread_row(words: list[tuple[str, float, float]], y: float) -> list[Line]:
    return [line(word, y, x0=x0, x1=x1) for word, x0, x1 in words]


def test_justified_line_stored_word_by_word_is_rebuilt() -> None:
    row = spread_row(
        [
            ("desak", 72, 105),
            ("Tadqiqotlar", 160, 230),
            ("koʻp", 300, 340),
            ("boʻlishiga", 420, 500),
        ],
        100 + PITCH,
    )
    lines = [
        line("Agar biz, hozirgi kunda pul toʻgʻrisida yozilgan adabiyotlar", 100),
        *row,
        line(
            "qaramasdan, pul va uning xususiyatlari haqida koʻp yozilgan.", 100 + 2 * PITCH, x1=400
        ),
    ]
    assert texts(lines) == [
        "Agar biz, hozirgi kunda pul toʻgʻrisida yozilgan adabiyotlar\n"
        "desak Tadqiqotlar koʻp boʻlishiga\n"
        "qaramasdan, pul va uning xususiyatlari haqida koʻp yozilgan."
    ]


def test_widely_spaced_labels_on_one_row_stay_apart() -> None:
    labels = spread_row(
        [("Risklar", 72, 130), ("Kredit", 260, 300), ("Foiz", 460, 500)], 100 + PITCH
    )
    lines = [line("Matn grafikdan oldin turibdi va davom etadi", 100), *labels]
    assert join_spread_lines(lines, 500.0) == lines


def test_row_pieces_that_do_not_fill_the_line_stay_apart() -> None:
    cells = spread_row([("Ism:", 72, 100), ("Ali", 140, 170), ("Valiyev", 200, 260)], 100 + PITCH)
    lines = [line("Matn jadvaldan oldin turibdi va davom etadi", 100), *cells]
    assert join_spread_lines(lines, 500.0) == lines


def test_spread_row_without_running_text_around_it_stays_apart() -> None:
    row = spread_row([("Birinchi", 72, 140), ("Ikkinchi", 230, 300), ("Uchinchi", 430, 500)], 100)
    assert join_spread_lines(row, 500.0) == row


def test_spread_first_line_before_a_short_last_line_is_rebuilt() -> None:
    row = spread_row(
        [
            ("Kreditning", 100, 160),
            ("toʻlovliligi", 210, 280),
            ("nafaqat", 330, 390),
            ("balki", 450, 500),
        ],
        100,
    )
    lines = [*row, line("korxonalarning foydasiga bogʻliq boʻladi.", 100 + PITCH, x1=300)]
    assert [x.text for x in join_spread_lines(lines, 500.0)] == [
        "Kreditning toʻlovliligi nafaqat balki",
        lines[-1].text,
    ]


def test_two_spread_lines_in_a_row_are_both_rebuilt() -> None:
    first = spread_row(
        [
            ("boshlanishi", 72, 140),
            ("deb", 200, 220),
            ("hisoblash,", 290, 360),
            ("hamda", 440, 500),
        ],
        100,
    )
    second = spread_row(
        [("yoki", 72, 100), ("pullik", 170, 210), ("asosida", 290, 350), ("binoan", 430, 500)],
        114.2,
    )
    joined = join_spread_lines([*first, *second], 500.0)
    assert [x.text for x in joined] == [
        "boshlanishi deb hisoblash, hamda",
        "yoki pullik asosida binoan",
    ]


def test_diagram_boxes_with_several_words_stay_apart() -> None:
    boxes = spread_row(
        [("Milliy oltin", 72, 150), ("Maxsus fondlar", 230, 330), ("XVFdagi zahira", 420, 500)],
        100 + PITCH,
    )
    lines = [line("Matn diagrammadan oldin turibdi va davom etadi", 100), *boxes]
    assert join_spread_lines(lines, 500.0) == lines


def test_spread_first_line_of_a_list_item_is_rebuilt() -> None:
    row = spread_row(
        [
            ("5. Shartnoma", 72, 150),
            ("yoki", 200, 225),
            ("pullik", 275, 390),
            ("asosida", 440, 500),
        ],
        100,
    )
    lines = [*row, line("topshirigʻiga binoan taʼminlash:", 100 + PITCH, x0=90, x1=300)]
    assert [x.text for x in join_spread_lines(lines, 500.0)][
        0
    ] == "5. Shartnoma yoki pullik asosida"


def test_indented_first_line_after_a_one_line_paragraph_starts_a_new_paragraph() -> None:
    lines = [
        line("Darslik oliy taʼlim muassasalari talabalari uchun tayyorlangan.", 100, x0=100),
        line(
            "Darslikda bank ishiga taalluqli savollar va javoblar bilan birgalikda har", 114.2, 100
        ),
        line("bir boʻlim boʻyicha tayanch iboralar keltirilgan.", 128.4, x1=350),
    ]
    assert texts(lines) == [
        lines[0].text,
        lines[1].text + "\n" + lines[2].text,
    ]


def test_indented_block_quote_stays_one_paragraph() -> None:
    lines = [
        line("Birinchi qator iqtibos matni shu yerda boshlanadi.", 100, x0=100),
        line("ikkinchi qator ham xuddi shunday chekinish bilan davom etadi va", 114.2, x0=100),
        line("uchinchi qator ham shu chekinishda tugaydi.", 128.4, x0=100, x1=350),
    ]
    assert len(texts(lines)) == 1


def test_bold_run_in_term_stays_with_its_plain_continuation() -> None:
    lines = [
        line("Naqdsiz pul aylanmasi – bu pul mablagʻlarining", 100, x0=100, bold=0.8),
        line("hisobvaraqlar orqali harakatlanishidir.", 114.2, x1=300),
    ]
    assert len(texts(lines)) == 1


def test_fully_bold_line_does_not_run_into_plain_text() -> None:
    lines = [
        line("NAQDSIZ PUL AYLANMASI VA UNING TURLARI", 100, x0=100, bold=1.0),
        line("hisobvaraqlar orqali harakatlanishidir.", 114.2, x1=300),
    ]
    assert len(texts(lines)) == 2


def test_text_inside_a_labelled_drawing_belongs_to_the_figure() -> None:
    region = (100.0, 400.0, 500.0, 600.0)
    lines = [
        line("Matn grafikdan oldin turibdi va davom etadi", 100),
        line("Foiz marjasining yillar boʻyicha oʻzgarishi va uning asosiy omillari", 410, x0=110),
        line("Risklar", 450, x0=120, x1=170),
        line("Kredit", 450, x0=250, x1=300),
        line("Foiz", 520, x0=400, x1=430),
    ]
    blocks = build_paragraphs(lines, 1, STATS, [region])
    title = next(b for b in blocks if b.text.startswith("Foiz marjasining"))
    assert title.in_figure and not blocks[0].in_figure


def test_lone_list_marker_is_joined_to_its_text() -> None:
    merged = merge_row_fragments(
        [line("1)", 100, x0=72, x1=85), line("toʻlovchi hisobidan", 100, x0=110)]
    )
    assert [m.text for m in merged] == ["1) toʻlovchi hisobidan"]
    checks = merge_row_fragments([line("✓", 100, x0=72, x1=80), line("Valyuta riski", 100, x0=95)])
    assert [m.text for m in checks] == ["✓ Valyuta riski"]


def test_marker_inside_a_sentence_is_not_joined_across_rows() -> None:
    merged = merge_row_fragments([line("1)", 100, x0=72, x1=85), line("keyingi qator", 130, x0=72)])
    assert len(merged) == 2


def test_dash_continuing_a_sentence_is_not_a_list_item() -> None:
    lines = [
        line("Fan bank ishi taʼlim yoʻnalishi talabalari uchun 2", 100),
        line("– semestrda oʻqitiladi va yakuniy nazorat bilan tugaydi.", 100 + PITCH, x1=420),
    ]
    assert len(texts(lines)) == 1


def test_dash_list_after_a_lead_in_stays_a_list() -> None:
    lines = [
        line("Bank quyidagi vazifalarni bajaradi:", 100, x1=300),
        line("– omonatlarni qabul qiladi;", 100 + PITCH, x1=250),
        line("– kredit beradi.", 100 + 2 * PITCH, x1=200),
    ]
    assert len(texts(lines)) == 3


def raw(text: str, page: int = 1) -> RawBlock:
    return RawBlock(text=text, page=page, font_size=SIZE)


def test_formula_fragments_become_one_formula_block() -> None:
    blocks = [
        raw("Grafikda talab egri chizigʻi koʻrsatilgan."),
        raw("="),
        raw("p&"),
        raw("0"),
        raw("G &"),
    ]
    grouped = group_formula_debris(blocks)
    assert [(b.text, b.role) for b in grouped] == [
        ("Grafikda talab egri chizigʻi koʻrsatilgan.", None),
        ("= p& 0 G &", "formula"),
    ]


def test_short_words_and_sentences_are_not_formula_debris() -> None:
    blocks = [
        raw("Xulosa."),
        raw("Ha, albatta."),
        raw("Foiz stavkasi = 12 foiz, inflyatsiya = 8 foiz"),
    ]
    assert [b.role for b in group_formula_debris(blocks)] == [None, None, None]


def test_inline_formula_stays_in_its_sentence() -> None:
    merged = merge_row_fragments(
        [
            line("Bunda tenglama", 100, x0=72, x1=170),
            line("x = 5", 100, x0=180, x1=215),
            line("boʻlganda bajariladi.", 100, x0=225, x1=360),
        ]
    )
    assert [m.text for m in merged] == ["Bunda tenglama x = 5 boʻlganda bajariladi."]


def test_code_lines_are_not_formulas() -> None:
    assert [b.role for b in group_formula_debris([raw("def f(x=[]):"), raw("a = {1: 2};")])] == [
        None,
        None,
    ]


def test_chart_fragment_between_formula_blocks_joins_them() -> None:
    blocks = [raw("Matn grafikdan oldin."), raw("= 0"), raw("B FAM"), raw("p& G")]
    grouped = group_formula_debris(blocks)
    assert [(b.text, b.role) for b in grouped] == [
        ("Matn grafikdan oldin.", None),
        ("= 0 B FAM p& G", "formula"),
    ]


def test_sentence_between_formula_blocks_stays_a_paragraph() -> None:
    blocks = [raw("= 0"), raw("Bu yerda talab egri chizigʻi siljiydi."), raw("p& G")]
    assert [b.role for b in group_formula_debris(blocks)] == ["formula", None, "formula"]


def test_justified_line_opening_with_bold_words_is_rebuilt_and_kept_with_its_paragraph() -> None:
    row = [
        line("Naqdsiz pul", 100 + PITCH, x0=100, x1=175, bold=1.0, size=SIZE + 0.3),
        line("aylanmasi", 100 + PITCH, x0=215, x1=275),
        line("–", 100 + PITCH, x0=315, x1=322),
        line("bu pul mablagʻlarining", 100 + PITCH, x0=362, x1=500),
    ]
    lines = [
        line(
            "Pul aylanmasi haqida gapirganda quyidagi tushunchalarni ajratish lozim.", 100, x1=480
        ),
        *row,
        line(
            "toʻlovchining hisobvaragʻidan oluvchining hisobiga oʻtkazilishidir.",
            100 + 2 * PITCH,
            x1=420,
        ),
    ]
    assert texts(lines)[1] == (
        "Naqdsiz pul aylanmasi – bu pul mablagʻlarining\n"
        "toʻlovchining hisobvaragʻidan oluvchining hisobiga oʻtkazilishidir."
    )


def test_first_line_rule_works_on_a_page_in_a_smaller_font() -> None:
    small = SIZE - 2
    lines = [
        line(
            "Darslik oliy taʼlim muassasalari talabalari uchun tayyorlangan.",
            100,
            x0=100,
            size=small,
        ),
        line(
            "Darslikda bank ishiga taalluqli savollar va javoblar bilan har",
            112,
            x0=100,
            size=small,
        ),
        line("bir boʻlim boʻyicha tayanch iboralar keltirilgan.", 124, x1=350, size=small),
        line(
            "Ushbu darslik oʻquv rejasi asosida tuzilgan boʻlib, unda nazariy",
            136,
            x0=100,
            size=small,
        ),
        line("va amaliy masalalar birgalikda yoritilgan.", 148, x1=330, size=small),
    ]
    assert texts(lines) == [
        lines[0].text,
        lines[1].text + "\n" + lines[2].text,
        lines[3].text + "\n" + lines[4].text,
    ]


def test_raised_formula_pieces_join_the_sentence_in_reading_order() -> None:
    lines = [
        line("0 = R C", 96, x0=262, x1=300, size=SIZE - 2),  # raised and sorted first
        line("Bu yerda va keyin muvozanat chizigʻi FAM", 100, x0=72, x1=255),
        line("G &", 104, x0=306, x1=322, size=SIZE - 2),
        line("holati uchun chizilgan.", 100, x0=328, x1=450),
    ]
    merged = merge_row_fragments(lines)
    assert [m.text for m in merged] == [
        "Bu yerda va keyin muvozanat chizigʻi FAM 0 = R C G & holati uchun chizilgan."
    ]


def test_formula_on_its_own_line_below_a_sentence_stays_apart() -> None:
    lines = [
        line("Bu yerda muvozanat chizigʻi quyidagicha yoziladi:", 100, x1=360),
        line("Y = C + I", 100 + 2 * PITCH, x0=200, x1=260),
    ]
    assert [m.text for m in merge_row_fragments(lines)] == [lines[0].text, lines[1].text]


def test_short_last_line_of_a_paragraph_is_never_a_label() -> None:
    region = (60.0, 90.0, 510.0, 400.0)
    lines = [
        line("M0 – Markaziy bank tomonidan muomalaga chiqarilgan jami", 100),
        line("naqd pullar", 100 + PITCH, x1=150),
        line("Germaniya", 200, x0=100, x1=160),
        line("Fransiya", 200, x0=250, x1=310),
        line("Rossiya", 260, x0=100, x1=160),
    ]
    labels = figure_labels(lines, [region], SIZE, 500.0)
    assert 1 not in labels and {2, 3, 4} <= labels


def test_short_line_after_a_finished_sentence_can_still_be_a_label() -> None:
    region = (60.0, 90.0, 510.0, 400.0)
    lines = [
        line("Quyidagi chizmada mamlakatlar boʻyicha koʻrsatkichlar berilgan.", 100),
        line("Germaniya", 100 + PITCH, x1=150),
        line("Fransiya", 200, x0=250, x1=310),
    ]
    assert 1 in figure_labels(lines, [region], SIZE, 500.0)


def test_short_lines_ending_with_a_semicolon_are_separate_items() -> None:
    lead = [
        line("Markaziy bankning asosiy maqsadi quyidagilarning barqarorligini taʼminlash", 72),
        line("va mamlakat iqtisodiyotini rivojlantirish hamda moliya tizimini mustahkamlash:", 86),
    ]
    items = [
        line("narxlarning;", 100, x0=92, x1=160),
        line("bank tizimining;", 100 + PITCH, x0=92, x1=180),
        line("toʻlov tizimlari barqarorligini taʼminlashdan iboratdir.", 100 + 2 * PITCH, x0=92),
    ]
    assert texts(lead + items)[-3:] == [item.text for item in items]


def test_ragged_line_broken_before_a_long_capitalised_word_runs_on() -> None:
    """The next word did not fit at the end of the line, so the line is not a paragraph end
    even though the next line starts with a capital."""
    lines = [
        line("faoliyatini amalga oshirishni nazorat qiladi va Oʻzbekiston", 100, x1=470),
        line("Respublikasining qonunlariga muvofiq ish yuritadi.", 100 + PITCH, x1=380),
    ]
    assert len(texts(lines)) == 1
    room = [line("Bu qator ancha qisqa va Oʻzbekiston", 100, x1=260), lines[1]]
    assert len(texts(room)) == 2  # the next word would have fitted: a real break


def test_stretched_first_line_of_an_item_stays_in_place_next_to_a_margin_stamp() -> None:
    """The item number and the stretched words of an item's first line come as separate
    lines; a small stamp sits left of the text. The row is rebuilt before the reading order
    is found, so the item reads in order and keeps its number."""
    stamp = line("QMMB: 10/26/3886", 30, x0=20, x1=120, size=7.0)
    first = spread_row(
        [
            ("10.", 108, 122),
            ("Aholi", 140, 170),
            ("punktlari", 190, 240),
            ("hududlari,", 262, 320),
            ("shu", 342, 360),
            ("jumladan", 382, 430),
            ("bolalar", 452, 480),
            ("oʻyin", 488, 500),
        ],
        100,
    )
    rest = [
        line(
            "maydonchalarining tuprogʻi qoʻrgʻoshin va boshqa zararli moddalar bilan", 100 + PITCH
        ),
        line("ifloslanishiga yoʻl qoʻyilmaydi.", 100 + 2 * PITCH, x1=260),
    ]
    lines = rejoin_spread_rows([stamp, *first, *rest], STATS)
    assert any(
        text.startswith(
            "10. Aholi punktlari hududlari, shu jumladan bolalar oʻyin\nmaydonchalarining"
        )
        for text in texts(lines)
    )


def test_a_centred_title_over_two_lines_is_one_block() -> None:
    lines = [
        line(
            "Aholi punktlari hududlari tuprogʻining sanitariya-gigiyenik",
            100,
            x0=140,
            x1=498,
            bold=1.0,
        ),
        line("holatini baholash koʻrsatkichlari", 100 + PITCH, x0=221, x1=417, bold=1.0),
        line("Jadvalda koʻrsatkichlar keltirilgan.", 100 + 3 * PITCH),
    ]
    assert texts(lines)[0] == (
        "Aholi punktlari hududlari tuprogʻining sanitariya-gigiyenik\n"
        "holatini baholash koʻrsatkichlari"
    )


def test_an_indented_first_line_is_not_taken_for_a_centred_block() -> None:
    lines = [
        line("Birinchi xatboshi qisqa satr bilan tugaydi.", 100, x1=320),
        line("Ikkinchi xatboshi xat boshidan boshlanib, toʻliq", 100 + PITCH, x0=108),
        line("satrlar bilan davom etadi va shu yerda tugaydi.", 100 + 2 * PITCH, x1=360),
    ]
    assert texts(lines)[0] == "Birinchi xatboshi qisqa satr bilan tugaydi."


def test_bullet_glued_to_its_text_keeps_its_hanging_lines() -> None:
    lines = [
        line("■Always put import statements (including from x import y) at the", 100),
        line("top of a file.", 100 + PITCH, x0=84, x1=160),
        line("■Always use absolute names for modules when importing them", 100 + 2 * PITCH),
    ]
    assert texts(lines) == [
        "■Always put import statements (including from x import y) at the\ntop of a file.",
        "■Always use absolute names for modules when importing them",
    ]
