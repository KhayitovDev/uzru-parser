import pytest
from uzru_parser import BlockType
from uzru_parser.structure import OutlineEntry, RawBlock, build_blocks
from uzru_parser.text import numbering_info, split_sentences


def heading(text: str, size: float = 14.0, bold: float = 1.0) -> RawBlock:
    return RawBlock(text=text, page=1, font_size=size, bold=bold)


def body(text: str, size: float = 11.0) -> RawBlock:
    return RawBlock(text=text, page=1, font_size=size, bold=0.0)


PARAGRAPH = "Настоящий договор является основанием для оказания услуг по настоящему договору."


@pytest.mark.parametrize(
    "text",
    [
        "1.1. Основные понятия",
        "Статья 5. Права сторон",
        "1.1. Asosiy tushunchalar",
        "1.2. Асосий тушунчалар",
        "МОДДА 4. ҲУҚУҚЛАР ВА МАЖБУРИЯТЛАР",
        "1-modda. Ushbu Kodeks bilan tartibga solinadigan munosabatlar",
        "1-bob. Asosiy qoidalar",
        "I BOʻLIM. UMUMIY QOIDALAR",
        "1-§. Yakka tartibdagi munosabatlar",
        "ПРИЛОЖЕНИЕ № 1",
        "I-BOB. PUL VA KREDIT",
    ],
)
def test_headings_with_font_signals(text: str) -> None:
    blocks = build_blocks([body(PARAGRAPH), heading(text), body(PARAGRAPH)])
    assert [b.type for b in blocks] == [
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]
    assert blocks[1].level == 1  # the only kind of heading in the document is its top level


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (
            ["I-BOB. PUL", "1.1. Pul tushunchasi", "1.1.1. Pulning turlari", "II-BOB. KREDIT"],
            [1, 2, 3, 1],
        ),
        (["3-MAVZU: BANK", "3.1. Banklarning turlari", "4-MAVZU: RISKLAR"], [1, 2, 1]),
        (
            ["I BOʻLIM. UMUMIY", "1-bob. Asosiy", "1-§. Yakka", "1-modda. Munosabatlar"],
            [1, 2, 3, 4],
        ),
        (["Глава 1. Общие", "1.1. Понятия", "1.1.1. Термины", "Глава 2. Права"], [1, 2, 3, 1]),
    ],
)
def test_levels_follow_the_heading_kinds_present(texts: list[str], expected: list[int]) -> None:
    raw = [part for text in texts for part in (heading(text), body(PARAGRAPH))]
    assert [b.level for b in build_blocks(raw) if b.type is BlockType.HEADING] == expected


def test_chapter_is_never_below_its_subsection() -> None:
    raw = [
        heading("1.1. Pul tushunchasi", size=14, bold=1.0),
        body(PARAGRAPH),
        heading("II-BOB. KREDIT", size=12, bold=1.0),
        body(PARAGRAPH),
        heading("2.1. Kredit turlari", size=14, bold=1.0),
        body(PARAGRAPH),
    ]
    levels = {b.text: b.level for b in build_blocks(raw) if b.type is BlockType.HEADING}
    assert levels["II-BOB. KREDIT"] < levels["2.1. Kredit turlari"]


def test_numbered_headings_in_a_sequence_with_text_between() -> None:
    raw = [
        RawBlock(text="1. ОБЩИЕ ПОЛОЖЕНИЯ", page=1),
        RawBlock(text=PARAGRAPH, page=1),
        RawBlock(text="2. ПРЕДМЕТ ДОГОВОРА", page=1),
        RawBlock(text=PARAGRAPH, page=1),
    ]
    assert [b.type for b in build_blocks(raw)] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]


def test_lone_numbered_item_is_a_list_item_not_a_heading() -> None:
    raw = [body(PARAGRAPH), RawBlock(text="4. Pul muomalasi qonuni", page=1, font_size=11, bold=1)]
    assert block_types(raw) == [BlockType.PARAGRAPH, BlockType.LIST]


def test_consecutive_numbered_items_are_a_list() -> None:
    raw = [
        body(PARAGRAPH),
        RawBlock(text="1. Birinchi talab", page=1, font_size=11, bold=1),
        RawBlock(text="2. Ikkinchi talab", page=1, font_size=11, bold=1),
    ]
    blocks = build_blocks(raw)
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.LIST]
    assert blocks[1].extra["items"] == ["1. Birinchi talab", "2. Ikkinchi talab"]


@pytest.mark.parametrize("label", ["B", "Sˆ", "0 = p", "MV=PY", "x + y", "12.5 %"])
def test_labels_and_formulas_are_never_headings(label: str) -> None:
    raw = [body(PARAGRAPH), RawBlock(text=label, page=1, font_size=16, bold=1.0, spaced=True)]
    assert BlockType.HEADING not in block_types(raw)


def test_one_signal_is_not_enough() -> None:
    bigger_only = RawBlock(text="Pul va kredit tizimi", page=1, font_size=16)
    bigger_and_bold = RawBlock(text="Pul va kredit tizimi", page=1, font_size=16, bold=1.0)
    assert block_types([body(PARAGRAPH), bigger_only])[1] is BlockType.PARAGRAPH
    assert block_types([body(PARAGRAPH), bigger_and_bold])[1] is BlockType.HEADING


def test_numbered_clause_is_paragraph() -> None:
    clause = "1.1. Стороны обязуются выполнять условия договора в полном объёме и в срок."
    assert build_blocks([body(clause)])[0].type is BlockType.PARAGRAPH


def test_font_size_ranks_unnumbered_headings() -> None:
    raw = [body(PARAGRAPH), heading("Первый уровень", 18), heading("Второй уровень", 14)]
    blocks = build_blocks(raw)
    assert [b.level for b in blocks[1:]] == [1, 2]


def test_sentence_like_text_is_not_heading() -> None:
    assert build_blocks([heading("Стороны договорились о следующем, а именно,")])[0].type is (
        BlockType.PARAGRAPH
    )


def test_list_items_merge_across_blocks() -> None:
    raw = [body("• первый пункт"), body("• второй пункт\nпродолжение"), body(PARAGRAPH)]
    blocks = build_blocks(raw)
    assert [b.type for b in blocks] == [BlockType.LIST, BlockType.PARAGRAPH]
    assert blocks[0].extra["items"] == ["• первый пункт", "• второй пункт продолжение"]


def test_text_normalized_and_raw_kept() -> None:
    block = build_blocks([body("O'zbekiston ma'lumot\nko'rsa-\ntish")])[0]
    assert block.text == "Oʻzbekiston maʼlumot ko‘rsatish".replace("‘", "ʻ")
    assert "ko'rsa-\ntish" in block.raw_text


def test_empty_blocks_dropped() -> None:
    assert len(build_blocks([body("  \n "), body(PARAGRAPH)])) == 1


def test_numbering_info_wrapper() -> None:
    assert numbering_info("1.1. Основные понятия") == ("decimal", 2)
    assert numbering_info("обычный текст") is None


def test_split_sentences_wrapper() -> None:
    assert split_sentences("Первое. Второе.") == ["Первое.", "Второе."]


def test_long_article_title_is_still_a_heading() -> None:
    title = "12-modda. " + "Mehnat munosabatlarini tartibga solish va ularning asoslari " * 3
    assert len(title) > 160
    assert build_blocks([body(PARAGRAPH), heading(title.strip(), bold=0.0)])[1].type is (
        BlockType.HEADING
    )


def block_types(raw: list[RawBlock]) -> list[BlockType]:
    return [b.type for b in build_blocks(raw)]


@pytest.mark.parametrize(
    "title",
    [
        "3-MAVZU: BANK OPERATSIYALARI",
        "4 - MAVZU: BANK RISKLARI VA ULARNI BOSHQARISH",
        "10-mavzu: Guruhlarda ishlash va taqdimotlar tayyorlash",
    ],
)
def test_topic_title_is_level_one_heading(title: str) -> None:
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=title, page=1, font_size=11, bold=0)])
    assert (blocks[1].type, blocks[1].level) == (BlockType.HEADING, 1)


def test_topic_title_and_plan_in_one_block_are_split() -> None:
    text = (
        "3-MAVZU: BANK OPERATSIYALARI\n\nReja:\n"
        "3.1. Banklarning turlari.\n3.2. Markaziy bank\nfaoliyati."
    )
    blocks = build_blocks([RawBlock(text=text, page=37, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.PARAGRAPH, BlockType.LIST]
    assert blocks[0].text == "3-MAVZU: BANK OPERATSIYALARI"
    assert blocks[1].text == "Reja:"
    assert blocks[2].extra["items"] == [
        "3.1. Banklarning turlari.",
        "3.2. Markaziy bank faoliyati.",
    ]


def test_wrapped_topic_title_is_one_heading() -> None:
    first = RawBlock(
        text="1-MAVZU: KIRISH (BANK ISHI VA MOLIYA ASOSLARI FANINING ASOSIY VAZIFALARI,",
        page=3,
        bbox=(70, 100, 500, 130),
        font_size=14,
        bold=1.0,
    )
    second = RawBlock(
        text="PREDMETI VA OBYEKTI)", page=3, bbox=(70, 132, 300, 150), font_size=14, bold=1.0
    )
    blocks = build_blocks([body(PARAGRAPH), first, second, body(PARAGRAPH)])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.HEADING, BlockType.PARAGRAPH]
    assert blocks[1].text.endswith("VAZIFALARI, PREDMETI VA OBYEKTI)")


def test_heading_continuation_must_match_style_and_stay_close() -> None:
    def headings(second: RawBlock) -> list[str]:
        first = RawBlock(
            text="2-MAVZU: PUL VA BANK ISHI", page=1, bbox=(0, 100, 300, 120), font_size=14, bold=1
        )
        blocks = build_blocks([body(PARAGRAPH), first, second])
        return [b.text for b in blocks if b.type is BlockType.HEADING]

    near = RawBlock(text="VA NAZARIYA", page=1, bbox=(0, 122, 300, 140), font_size=14, bold=1)
    far = RawBlock(text="KEYINGI BOʻLIM", page=1, bbox=(0, 400, 300, 420), font_size=14, bold=1)
    smaller = RawBlock(text="IZOH", page=1, bbox=(0, 122, 300, 135), font_size=9, bold=0)
    assert headings(near) == ["2-MAVZU: PUL VA BANK ISHI VA NAZARIYA"]
    assert headings(far) == ["2-MAVZU: PUL VA BANK ISHI", "KEYINGI BOʻLIM"]
    assert headings(smaller) == ["2-MAVZU: PUL VA BANK ISHI"]  # one signal only: a paragraph


def test_numbered_title_inside_a_body_block_is_split_off() -> None:
    text = (
        "1.1. Banklarning paydo boʻlish sabablari\n"
        "Pul – mahsulot, tovarlarni ishlab chiqarish va xaridorlarga kerakli vaqtda yetkazib\n"
        "berish uchun zarur boʻlgan vosita sifatida paydo boʻldi va rivojlandi."
    )
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=text, page=3, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.HEADING, BlockType.PARAGRAPH]
    assert blocks[1].text == "1.1. Banklarning paydo boʻlish sabablari"
    assert blocks[1].extra["heading_source"] == "numbering"


def test_wrapped_numbered_title_inside_a_body_block_is_split_off() -> None:
    text = (
        "1.2. Pulning mohiyati va uning namoyon boʻlish\n"
        "shakllari\n"
        "Har bir iqtisodiy kategoriyada amal qiluvchi hamda mavjud boʻlgan qonuniyatlarga\n"
        "asoslangan holda uning mohiyati namoyon boʻladi."
    )
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=text, page=6, font_size=11)])
    assert blocks[1].text == "1.2. Pulning mohiyati va uning namoyon boʻlish shakllari"
    assert blocks[2].type is BlockType.PARAGRAPH


def test_numbered_clause_with_a_proper_noun_line_start_is_not_split() -> None:
    text = (
        "1.1. Stороны обязуются выполнять условия договора в полном объёме и в сроки, а также в\n"
        "Республике Узбекистан соблюдать требования законодательства по настоящему договору."
    )
    assert block_types([RawBlock(text=text, page=1, font_size=11)]) == [BlockType.PARAGRAPH]


def test_symbol_bullet_font_does_not_make_a_heading() -> None:
    items = [
        RawBlock(text="dollar (11%) va dollar", page=5, font_size=11),
        RawBlock(text="RUR, GBP", page=5, font_size=11),
    ]
    blocks = build_blocks([body(PARAGRAPH), *items])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.LIST]
    assert blocks[1].extra["items"] == ["• dollar (11%) va dollar", "• RUR, GBP"]
    assert "" not in blocks[1].text


def test_lowercase_fragment_with_percent_is_never_a_heading() -> None:
    fragment = RawBlock(text="dollar (11%) va dollar", page=5, font_size=14, bold=0.0)
    assert block_types([body(PARAGRAPH), fragment])[1] is BlockType.PARAGRAPH


def test_paragraph_split_by_page_break_is_joined() -> None:
    first = RawBlock(text="Markaziy bank pul-kredit siyosatini yuritadi va emission bank", page=49)
    second = RawBlock(text="vazifasini bajaradi. Keyingi gap shu yerda.", page=50)
    blocks = build_blocks([first, second])
    assert len(blocks) == 1
    assert blocks[0].text.endswith("emission bank vazifasini bajaradi. Keyingi gap shu yerda.")
    assert (blocks[0].page, blocks[0].extra["page_end"]) == (49, 50)
    assert blocks[0].language.language == "uz"


def test_page_break_join_skips_the_footnote_between() -> None:
    first = RawBlock(text="Markaziy bank emission bank", page=49)
    note = RawBlock(text="2 Nemetskiy bank. Spetsialnoe izdanie", page=49, footnote=True)
    second = RawBlock(text="vazifasini bajaradi.", page=50)
    blocks = build_blocks([first, note, second])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.FOOTNOTE]
    assert blocks[0].text == "Markaziy bank emission bank vazifasini bajaradi."
    assert blocks[1].extra["number"] == "2"


@pytest.mark.parametrize(
    ("previous", "following"),
    [
        ("Birinchi gap tugadi.", "keyingi gap kichik harf bilan"),
        ("Gap tugamadi", "Yangi gap bosh harf bilan"),
        ("Gap tugamadi", "keyingi sahifa emas"),
    ],
)
def test_paragraphs_are_not_joined_without_the_page_break_signals(
    previous: str, following: str
) -> None:
    page = 2 if following.endswith("emas") is False else 1
    raws = [RawBlock(text=previous, page=1), RawBlock(text=following, page=page)]
    assert len(build_blocks(raws)) == 2


def test_word_hyphenated_across_a_block_break_is_rejoined() -> None:
    first = RawBlock(text="Bu masala iqtisodchi-", page=10)
    second = RawBlock(text="lari tomonidan hal etildi.", page=11)
    assert build_blocks([first, second])[0].text == "Bu masala iqtisodchilari tomonidan hal etildi."


def test_table_cells_are_hyphen_repaired_and_empty_columns_dropped() -> None:
    rows = [["Xizmat", "", "Operatsiya"], ["baho-\nlash", "", "bogʻliq- liklarni"]]
    block = build_blocks([RawBlock(text="", page=1, rows=rows)])[0]
    assert block.extra["rows"] == [["Xizmat", "Operatsiya"], ["baholash", "bogʻliqliklarni"]]
    assert block.text == "Xizmat | Operatsiya\nbaholash | bogʻliqliklarni"


def test_table_text_has_no_double_spaces_for_empty_cells() -> None:
    rows = [["a", "", "b"], ["", "c", ""], ["d", "e", "f"]]
    block = build_blocks([RawBlock(text="", page=1, rows=rows)])[0]
    assert "  " not in block.text
    assert block.extra["rows"][1] == ["", "c", ""]


def test_roles_block_heading_and_list_detection() -> None:
    raw = [
        RawBlock(text="MUNDARIJA", page=236, font_size=14, bold=1, role="toc"),
        RawBlock(text="4-MAVZU: BANK RISKLARI … 55", page=237, font_size=14, bold=1, role="toc"),
        RawBlock(
            text="TOSHKENT DAVLAT IQTISODIYOT UNIVERSITETI",
            page=1,
            font_size=16,
            bold=1,
            role="title_page",
        ),
    ]
    blocks = build_blocks(raw)
    assert all(b.type is BlockType.PARAGRAPH for b in blocks)
    assert [b.extra["role"] for b in blocks] == ["toc", "toc", "title_page"]


def test_numbered_list_item_lines_are_not_split_into_a_title() -> None:
    text = (
        "1. Kalendar ketma-ketlik\nUshbu bosqichda barcha harakatlar kalendar tartibida bajariladi."
    )
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=text, page=19, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.LIST]
    assert len(blocks[1].extra["items"]) == 1


def test_continued_plan_items_in_one_block_are_not_split_into_a_title() -> None:
    text = (
        "7.2. Valyuta bozori tushunchasi va tarkibi\n"
        "7.3. Tijorat banklarining valyuta operatsiyalari\n"
        "7.4. Valyuta munosabatlari"
    )
    kinds = block_types([body(PARAGRAPH), RawBlock(text=text, page=154, font_size=11)])
    assert BlockType.HEADING not in kinds


def test_numbered_section_after_list_items_is_a_new_paragraph() -> None:
    text = (
        "- ochiq bozor siyosati,\n- targetlash va boshqalar.\n"
        "3.3. Markaziy bankning funksiyalari: emission funksiya;\nrasmiy oltin zaxiralari."
    )
    blocks = build_blocks([RawBlock(text=text, page=48, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.LIST, BlockType.PARAGRAPH]
    assert blocks[0].extra["items"] == ["- ochiq bozor siyosati,", "- targetlash va boshqalar."]
    assert all("  " not in b.text for b in blocks)


def test_blank_lines_separate_paragraphs_inside_a_block() -> None:
    text = "Birinchi abzats tugadi.\n \nIkkinchi abzats boshlandi."
    blocks = build_blocks([RawBlock(text=text, page=1, font_size=11)])
    assert [b.text for b in blocks] == ["Birinchi abzats tugadi.", "Ikkinchi abzats boshlandi."]


def test_list_item_split_by_a_page_break_is_joined() -> None:
    items = RawBlock(text="- tangalar, asosan, oltindan", page=9, font_size=11)
    rest = RawBlock(text="zarb qilingan va kumush bilan.", page=10, font_size=11)
    blocks = build_blocks([items, rest])
    assert len(blocks) == 1 and blocks[0].type is BlockType.LIST
    assert blocks[0].extra["items"] == [
        "- tangalar, asosan, oltindan zarb qilingan va kumush bilan."
    ]
    assert blocks[0].extra["page_end"] == 10


def test_numbered_title_set_apart_by_blank_lines_is_a_heading() -> None:
    text = (
        "1.1. Banklarning paydo boʻlish sabablari\n \n"
        "Pul – mahsulot va tovarlar ishlab chiqarish vositasi."
    )
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=text, page=3, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.HEADING, BlockType.PARAGRAPH]
    assert blocks[1].text == "1.1. Banklarning paydo boʻlish sabablari"


def test_numbered_plan_item_set_apart_by_blank_lines_is_not_a_heading() -> None:
    text = (
        "3.2. Markaziy bank faoliyatining maqsadi va vazifalari.\n \n"
        "Ikkinchi abzats matni shu yerda."
    )
    kinds = block_types([body(PARAGRAPH), RawBlock(text=text, page=37, font_size=11)])
    assert BlockType.HEADING not in kinds


@pytest.mark.parametrize("text", ["ISBN 978-9943-7423-2-1", "UOʻK: 336.5(07) KBK 65.262.1"])
def test_capitals_with_mostly_digits_are_not_headings(text: str) -> None:
    assert block_types([body(PARAGRAPH), RawBlock(text=text, page=2, font_size=11)])[1] is (
        BlockType.PARAGRAPH
    )


# --- Bookmarks and contents confirm headings (section 6) ------------------------------------


def plain(text: str, page: int = 1) -> RawBlock:
    return RawBlock(text=text, page=page, font_size=11.0)


def test_bookmarks_make_headings_and_give_their_levels() -> None:
    outline = [OutlineEntry(1, "KIRISH", 1), OutlineEntry(2, "Banklarning turlari", 2)]
    raw = [
        plain("Kirish", 1),
        plain(PARAGRAPH, 1),
        plain("Banklarning turlari", 2),
        plain(PARAGRAPH, 2),
    ]
    blocks = build_blocks(raw, outline=outline)
    headings = [
        (b.text, b.level, b.extra["heading_source"]) for b in blocks if b.type is BlockType.HEADING
    ]
    assert headings == [("Kirish", 1, "bookmarks"), ("Banklarning turlari", 2, "bookmarks")]


def test_bookmark_title_glued_to_its_text_is_split_off() -> None:
    outline = [OutlineEntry(1, "Banklarning turlari", 2)]
    raw = [plain("Banklarning turlari\nPul – mahsulot va tovarlar ishlab chiqarish vositasi.", 2)]
    blocks = build_blocks(raw, outline=outline)
    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.PARAGRAPH]


def test_bookmark_on_a_distant_page_does_not_match() -> None:
    outline = [OutlineEntry(1, "Kirish", 50)]
    assert BlockType.HEADING not in [
        b.type for b in build_blocks([plain("Kirish", 2)], outline=outline)
    ]


def test_contents_entries_confirm_headings_without_bookmarks() -> None:
    toc = RawBlock(text="KIRISH … 3\nXULOSA … 230", page=2, role="toc")
    raw = [toc, plain("Kirish", 3), plain(PARAGRAPH, 3), plain("4. Ushbu band oddiy roʻyxat", 4)]
    blocks = build_blocks(raw)
    assert [(b.type, b.extra.get("heading_source")) for b in blocks[1:]] == [
        (BlockType.HEADING, "contents"),
        (BlockType.PARAGRAPH, None),
        (BlockType.LIST, None),
    ]


# --- Footnotes, tables, language (sections 8-10) --------------------------------------------


def test_footnote_number_glued_to_cyrillic_is_split_from_the_text() -> None:
    note = RawBlock(text="1И. Каримов. Ўзбекистон мустақилликка", page=3, footnote=True)
    block = build_blocks([note])[0]
    assert (block.extra["number"], block.text) == ("1", "И. Каримов. Ўзбекистон мустақилликка")


def test_header_split_over_two_rows_is_merged() -> None:
    rows = [["Ish", "Natija", "Muddat"], ["bosqichlari", "", ""], ["Rejalash", "Reja", "1 oy"]]
    block = build_blocks([RawBlock(text="", page=1, rows=rows)])[0]
    assert block.extra["rows"][0] == ["Ish bosqichlari", "Natija", "Muddat"]
    assert len(block.extra["rows"]) == 2


def test_lowercase_data_rows_are_not_merged_into_the_header() -> None:
    rows = [["Xizmat", "Operatsiya"], ["kredit", "berish"], ["omonat", "qabul"]]
    assert build_blocks([RawBlock(text="", page=1, rows=rows)])[0].extra["rows"] == rows


def test_repeated_merged_header_cells_are_kept_once() -> None:
    rows = [["Harakatlar", "Yakka", "Yakka", "Guruh"], ["Tahlil", "1", "2", "3"]]
    block = build_blocks([RawBlock(text="", page=1, rows=rows)])[0]
    assert block.extra["rows"][0] == ["Harakatlar", "Yakka", "", "Guruh"]
    assert block.extra["rows"][1] == ["Tahlil", "1", "2", "3"]


def test_short_blocks_take_their_neighbours_language() -> None:
    raw = [
        plain("Ushbu qoidalar xizmat koʻrsatish tartibini va uchun belgilaydi."),
        plain("Reja:"),
        plain("12.5"),
    ]
    blocks = build_blocks(raw)
    assert [b.language.language for b in blocks] == ["uz", "uz", "uz"]


def test_long_unknown_blocks_keep_their_own_language() -> None:
    raw = [
        plain("Ushbu qoidalar xizmat koʻrsatish tartibini va uchun belgilaydi."),
        plain("Python uses reference counting for memory management in CPython."),
    ]
    assert build_blocks(raw)[1].language.language == "unknown"


def test_weak_cyrillic_guess_takes_its_uzbek_neighbours_language() -> None:
    raw = [
        plain("Иқтисодиётнинг бошланғич мувозанат ҳолати ва унинг ўзгариши кўрсатилган."),
        plain("Пул таклифи:"),
    ]
    assert [b.language.language for b in build_blocks(raw)] == ["uz", "uz"]


def test_weak_guess_does_not_take_a_neighbour_in_another_script() -> None:
    raw = [
        plain("Ushbu qoidalar xizmat koʻrsatish tartibini va uchun belgilaydi."),
        plain("Москва Петербург"),
    ]
    language = build_blocks(raw)[1].language
    assert (language.language, language.script) == ("ru", "cyrillic")


def test_list_language_covers_all_its_items() -> None:
    raw = [
        plain("1. Quyidagilar:"),
        plain(
            "2. Oʻzbekiston Respublikasi Hukumati bilan sheriklik toʻgʻrisidagi bitim tasdiqlansin."
        ),
    ]
    block = build_blocks(raw)[0]
    assert block.type is BlockType.LIST
    assert block.language.language == "uz"


@pytest.mark.parametrize(
    ("text", "title", "rest"),
    [
        ("4-modda. Oʻzbekiston Respublikasi Vazirlar Mahkamasi:", "4-modda.", "Oʻzbekiston"),
        (
            "5-modda. Ushbu Qonun rasmiy eʼlon qilingan kundan eʼtiboran uch oy oʻtgach "
            "kuchga kiradi.",
            "5-modda.",
            "Ushbu Qonun",
        ),
        (
            "Статья 7. Настоящий закон вступает в силу со дня его официального "
            "опубликования в печати.",
            "Статья 7.",
            "Настоящий",
        ),
    ],
)
def test_untitled_article_is_split_into_heading_and_text(text: str, title: str, rest: str) -> None:
    blocks = build_blocks([plain(text), plain("Matn davom etadi.")])
    assert (blocks[0].type, blocks[0].text) == (BlockType.HEADING, title)
    assert blocks[1].type is BlockType.PARAGRAPH and blocks[1].text.startswith(rest)


@pytest.mark.parametrize(
    "text",
    [
        "1-bob. Umumiy qoidalar",
        "3-modda. Yakka tartibdagi mehnatga oid munosabatlarni va ular bilan bevosita bogʻliq "
        "boʻlgan ijtimoiy munosabatlarni huquqiy tartibga solishning asosiy prinsiplari va "
        "vazifalari hamda mehnat toʻgʻrisidagi qonunchilik hujjatlarining amal qilish doirasi",
        "Статья 5. Вступление в силу.",
        "3-MAVZU. PUL MUOMALASI VA UNING QONUNLARI HAMDA ULARNING AMAL QILISH SHARTLARI.",
    ],
)
def test_article_titles_are_not_split(text: str) -> None:
    blocks = build_blocks([plain(text), plain("Matn davom etadi.")])
    assert blocks[0].type is BlockType.HEADING
    assert blocks[0].text == text


def test_articles_quoted_by_an_amending_law_are_not_headings() -> None:
    raw = [
        plain("2-modda. Qonunga quyidagi oʻzgartirishlar kiritilsin:"),
        plain("“131-modda. Buyurtmalar agregatori operatorining huquqlari"),
        plain("Operator xizmat koʻrsatish qoidalarini belgilaydi."),
        plain("132-modda. Raqamli striming xizmati operatorining majburiyatlari"),
        plain("Operator kontentni qonunchilikka muvofiq tarqatadi”."),
        plain("3-modda. Vazirlar Mahkamasi ushbu Qonunning ijrosini taʼminlasin."),
    ]
    headings = [b.text for b in build_blocks(raw) if b.type is BlockType.HEADING]
    assert headings == [
        "2-modda.",
        "3-modda. Vazirlar Mahkamasi ushbu Qonunning ijrosini taʼminlasin.",
    ]


def test_quotes_closed_in_the_same_block_or_never_closed_change_nothing() -> None:
    raw = [
        plain("“Elektron tijorat toʻgʻrisida”gi Qonun va «Bank» atamasi qoʻllaniladi."),
        plain("1-bob. Umumiy qoidalar"),
        plain("Bu yerda “yopilmagan iqtibos boshlanadi."),
        plain("2-bob. Yakunlovchi qoidalar"),
    ]
    headings = [b.text for b in build_blocks(raw) if b.type is BlockType.HEADING]
    assert headings == ["1-bob. Umumiy qoidalar", "2-bob. Yakunlovchi qoidalar"]


def test_capital_sentence_tail_after_an_open_page_break_is_joined() -> None:
    raws = [
        RawBlock(text="В настоящей Доктрине используются следующие основные", page=1),
        RawBlock(text="ПОНЯТИЯ:", page=2, bold=1.0, font_size=11.0),
    ]
    blocks = build_blocks(raws)
    assert [b.text for b in blocks] == [
        "В настоящей Доктрине используются следующие основные ПОНЯТИЯ:"
    ]


def test_capital_heading_after_a_finished_sentence_stays_a_heading() -> None:
    raws = [
        RawBlock(text="Matn shu yerda tugadi.", page=1),
        RawBlock(text="UMUMIY QOIDALAR:", page=2, bold=1.0, font_size=11.0),
        RawBlock(text="Ushbu qoidalar xizmat tartibini belgilaydi.", page=2),
    ]
    assert build_blocks(raws)[1].type is BlockType.HEADING


@pytest.mark.parametrize("text", ["І. Общие положения", "IV. UMUMIY QOIDALAR"])
def test_roman_numbered_section_is_not_a_list_item(text: str) -> None:
    blocks = build_blocks([plain(text), plain("Matn shu yerda davom etadi.")])
    assert blocks[0].type is BlockType.PARAGRAPH
    assert blocks[0].text == text


UZ_CYRILLIC = "Иқтисодиётнинг бошланғич мувозанат ҳолати ва унинг ўзгариши кўрсатилган."
RUSSIAN = "Правительство Российской Федерации приняло постановление о налогах и сборах."


def test_unsure_short_block_takes_the_language_of_its_neighbours() -> None:
    raw = [plain(UZ_CYRILLIC), plain("Банк"), plain(UZ_CYRILLIC)]
    assert [b.language.language for b in build_blocks(raw)] == ["uz", "uz", "uz"]


def test_disagreeing_neighbours_resolve_to_the_documents_language() -> None:
    raw = [plain(UZ_CYRILLIC), plain(UZ_CYRILLIC), plain("Банк"), plain(RUSSIAN)]
    assert build_blocks(raw)[2].language.language == "uz"


def test_confident_short_russian_line_keeps_its_language() -> None:
    raw = [plain(UZ_CYRILLIC), plain("Рецензенты:"), plain(UZ_CYRILLIC)]
    assert [b.language.language for b in build_blocks(raw)] == ["uz", "ru", "uz"]


def test_page_break_after_an_abbreviation_joins_the_paragraph() -> None:
    raws = [
        RawBlock(text="Порядок определяется в соответствии со ст.", page=1),
        RawBlock(text="5 Закона о банках и банковской деятельности.", page=2),
    ]
    blocks = build_blocks(raws)
    assert [b.text for b in blocks] == [
        "Порядок определяется в соответствии со ст. 5 Закона о банках и банковской деятельности."
    ]


def test_page_break_after_a_sentence_end_keeps_paragraphs_apart() -> None:
    raws = [
        RawBlock(text="Порядок определён законом.", page=1),
        RawBlock(text="Банки обязаны соблюдать его.", page=2),
    ]
    assert len(build_blocks(raws)) == 2


def test_orphan_fragment_is_merged_into_its_sentence() -> None:
    raw = [plain("Foiz stavkasi berilgan qarz miqdoriga"), plain("tengdir.")]
    assert [b.text for b in build_blocks(raw)] == ["Foiz stavkasi berilgan qarz miqdoriga tengdir."]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Bu bosqich shu yerda tugadi.", "tengdir."),
        ("Formula quyidagicha yoziladi", "tt"),
        ("Foiz stavkasi berilgan qarz miqdoriga", "tengdir va boshqa holatlarda ham shunday."),
    ],
)
def test_fragments_that_do_not_end_the_sentence_stay_apart(first: str, second: str) -> None:
    assert len(build_blocks([plain(first), plain(second)])) == 2


def test_paragraph_continues_across_a_figure() -> None:
    raw = [
        plain("Bank xizmatlari nazariyasi evolyutsiyasi qator rivojlanish"),
        RawBlock(text="Risklar | Kredit | Foiz", page=1, role="figure"),
        plain("bosqichlarini oʻz ichiga oladi."),
    ]
    blocks = build_blocks(raw)
    assert [b.text for b in blocks] == [
        "Bank xizmatlari nazariyasi evolyutsiyasi qator rivojlanish "
        "bosqichlarini oʻz ichiga oladi.",
        "Risklar | Kredit | Foiz",
    ]


def test_one_word_loanword_follows_agreeing_neighbours() -> None:
    raw = [plain(RUSSIAN), plain("Эквайринг"), plain(RUSSIAN)]
    assert [b.language.language for b in build_blocks(raw)] == ["ru", "ru", "ru"]


def test_one_word_loanword_between_disagreeing_neighbours_keeps_its_language() -> None:
    raw = [plain(UZ_CYRILLIC), plain("Лизинг"), plain(RUSSIAN)]
    assert build_blocks(raw)[1].language.language == "uz"


UZ_BODY = "Bu boʻlimda bank tizimining asosiy tushunchalari batafsil koʻrib chiqiladi."
SECTIONS = ["3.1. Banklarning turlari", "3.2. Markaziy bank vazifalari", "3.3. Bank operatsiyalari"]


def chapter_with_outline() -> list[RawBlock]:
    return [
        heading("3-MAVZU: BANK OPERATSIYALARI"),
        heading("Mavzu tuzilishi:", size=11.0),
        *[heading(title, size=11.0) for title in SECTIONS],
        body("Tayanch tushunchalar: bank, kredit, depozit."),
        *[block for title in SECTIONS for block in (heading(title, size=11.0), body(UZ_BODY))],
    ]


def test_outline_entries_become_a_list_and_sections_stay_headings() -> None:
    blocks = build_blocks(chapter_with_outline())
    assert [b.text for b in blocks if b.type is BlockType.HEADING] == [
        "3-MAVZU: BANK OPERATSIYALARI",
        *SECTIONS,
    ]
    lists = [b for b in blocks if b.type is BlockType.LIST]
    assert len(lists) == 1 and lists[0].extra["items"] == SECTIONS
    assert blocks[1].type is BlockType.PARAGRAPH and blocks[1].text == "Mavzu tuzilishi:"


def test_numbered_list_whose_items_never_return_stays_a_list() -> None:
    raws = [
        body("Bank quyidagi vazifalarni bajaradi:"),
        body("1. Omonatlarni qabul qiladi."),
        body("2. Kredit beradi."),
        body(UZ_BODY),
    ]
    blocks = build_blocks(raws)
    assert not [b for b in blocks if b.type is BlockType.HEADING]


def test_same_number_and_title_in_body_text_stays_a_heading() -> None:
    raws = [
        heading("3.1. Banklarning turlari", size=11.0),
        body(UZ_BODY),
        heading("3.1. Banklarning turlari", size=11.0),
        body(UZ_BODY),
    ]
    headings = [b for b in build_blocks(raws) if b.type is BlockType.HEADING]
    assert len(headings) == 2


def test_colon_label_is_not_glued_to_the_heading_before_it() -> None:
    raws = [
        heading("3-MAVZU: BANK OPERATSIYALARI"),
        heading("Mavzu tuzilishi:"),
        body("1. Banklarning turlari."),
        body("2. Bank operatsiyalari."),
    ]
    blocks = build_blocks(raws)
    assert blocks[0].text == "3-MAVZU: BANK OPERATSIYALARI"
    assert blocks[1].text == "Mavzu tuzilishi:" and blocks[1].type is BlockType.PARAGRAPH


def test_label_line_after_plan_items_is_its_own_paragraph() -> None:
    raw = plain(
        "Reja:\n2.1. Pul aylanmasi\n2.2. Naqd pul muomalasi\n"
        "Tayanch iboralar: pul aylanmasi, toʻlov, naqd pul."
    )
    blocks = build_blocks([raw])
    assert blocks[-1].type is BlockType.PARAGRAPH
    assert blocks[-1].text.startswith("Tayanch iboralar:")
    assert blocks[-2].extra["items"][-1] == "2.2. Naqd pul muomalasi"


def test_repeated_section_title_before_a_unique_article_stays_a_heading() -> None:
    raws = []
    for chapter, article in ((1, 1), (2, 7)):
        raws += [
            heading(f"{chapter}-bob. Bob nomi {chapter}"),
            heading("1-§. Umumiy qoidalar", size=11.0),
            heading(f"{article}-modda. Modda nomi {article}", size=11.0),
            body(UZ_BODY),
        ]
    headings = [b.text for b in build_blocks(raws) if b.type is BlockType.HEADING]
    assert headings.count("1-§. Umumiy qoidalar") == 2


def spaced(raw: RawBlock) -> RawBlock:
    raw.spaced = True
    return raw


def levels_of(raws: list[RawBlock]) -> list[tuple[str, int | None]]:
    return [(b.text, b.level) for b in build_blocks(raws) if b.type is BlockType.HEADING]


def test_unnumbered_heading_styled_like_sections_nests_under_the_chapter() -> None:
    raws = [
        heading("1-MAVZU: PUL VA KREDIT"),
        heading("1.1. Pulning mohiyati", size=11.0),
        body(UZ_BODY),
        spaced(heading("Nazorat savollari", size=11.0)),
        body(UZ_BODY),
        heading("2-MAVZU: BANK TIZIMI"),
        body(UZ_BODY),
    ]
    assert levels_of(raws) == [
        ("1-MAVZU: PUL VA KREDIT", 1),
        ("1.1. Pulning mohiyati", 2),
        ("Nazorat savollari", 2),
        ("2-MAVZU: BANK TIZIMI", 1),
    ]


def test_unnumbered_heading_of_an_unknown_style_sits_inside_the_chapter() -> None:
    raws = [
        heading("1-MAVZU: PUL VA KREDIT"),
        body(UZ_BODY),
        spaced(heading("Tayanch tushunchalar", size=12.0)),
        body(UZ_BODY),
    ]
    assert levels_of(raws) == [("1-MAVZU: PUL VA KREDIT", 1), ("Tayanch tushunchalar", 2)]


def test_unnumbered_chapter_like_heading_stays_at_the_top() -> None:
    raws = [
        heading("KIRISH"),
        body(UZ_BODY),
        heading("1-MAVZU: PUL VA KREDIT"),
        body(UZ_BODY),
    ]
    assert levels_of(raws) == [("KIRISH", 1), ("1-MAVZU: PUL VA KREDIT", 1)]


def test_numbers_restarting_inside_a_section_nest_under_it() -> None:
    raws = [
        heading("6-MAVZU: VALYUTA SIYOSATI"),
        heading("6.2. Valyuta risklari", size=11.0),
        body(UZ_BODY),
        heading("1. Valyuta risklarini baholash", size=11.0),
        body(UZ_BODY),
        heading("2. Valyuta risklarini kamaytirish", size=11.0),
        body(UZ_BODY),
    ]
    levels = dict(levels_of(raws))
    assert levels["1. Valyuta risklarini baholash"] == levels["6.2. Valyuta risklari"] + 1
    assert levels["2. Valyuta risklarini kamaytirish"] == levels["6.2. Valyuta risklari"] + 1


def test_levels_have_no_gaps() -> None:
    raws = [
        heading("1-MAVZU: PUL VA KREDIT"),
        heading("1.1.1. Pulning paydo boʻlishi", size=11.0),
        body(UZ_BODY),
    ]
    assert [level for _, level in levels_of(raws)] == [1, 2]


def test_unnumbered_heading_as_big_as_the_chapters_but_unlike_them_nests_inside() -> None:
    raws = [
        heading("5-MAVZU: QIMMATLI QOGʻOZLAR BOZORI"),
        body(UZ_BODY),
        spaced(heading("Tayanch iboralar")),
        body(UZ_BODY),
        heading("6-MAVZU: MASOFAVIY BANK XIZMATLARI"),
    ]
    assert dict(levels_of(raws))["Tayanch iboralar"] == 2


def table(page: int = 1, bbox: tuple[float, float, float, float] = (70, 340, 530, 640)) -> RawBlock:
    return RawBlock(
        text="", page=page, bbox=bbox, rows=[["Davlat", "Valyuta"], ["Armaniston", "Rubl"]]
    )


def at(raw: RawBlock, y0: float, y1: float) -> RawBlock:
    raw.bbox = (100.0, y0, 500.0, y1)
    return raw


def kinds(raws: list[RawBlock]) -> list[tuple[str, str | None]]:
    return [(b.type.value, b.extra.get("role")) for b in build_blocks(raws)]


def test_formula_is_not_a_heading() -> None:
    raws = [spaced(heading("M = APS x I", size=11.0)), body(UZ_BODY)]
    assert kinds(raws)[0] == ("paragraph", None)


def test_heading_with_an_equals_sign_in_words_stays_a_heading() -> None:
    raws = [heading("Foiz marjasi = daromadlar va xarajatlar farqi"), body(UZ_BODY)]
    assert kinds(raws)[0] == ("heading", None)


def test_line_right_above_a_table_is_its_caption() -> None:
    raws = [
        at(spaced(heading("Sobiq ittifoq davlatlari valyutalari, 1993-yil", size=11.0)), 300, 318),
        table(),
        body(UZ_BODY),
    ]
    assert kinds(raws)[0] == ("paragraph", "caption")


def test_line_right_above_a_figure_is_its_caption() -> None:
    figure = RawBlock(
        text="Xalqaro daraja | Milliy daraja", page=1, bbox=(85, 392, 400, 620), role="figure"
    )
    raws = [at(spaced(heading("Valyuta munosabatlari darajalari", size=11.0)), 348, 365), figure]
    assert kinds(raws)[0] == ("paragraph", "caption")


def test_big_heading_above_a_table_stays_a_heading() -> None:
    raws = [at(heading("KIRISH"), 300, 318), table(), body(UZ_BODY)]
    assert kinds(raws)[0] == ("heading", None)


def test_heading_followed_by_body_text_is_not_a_caption() -> None:
    raws = [spaced(heading("Valyuta munosabatlari darajalari", size=11.0)), body(UZ_BODY), table()]
    assert kinds(raws)[0] == ("heading", None)


def test_text_inside_a_table_frame_is_not_a_heading() -> None:
    raws = [table(), at(spaced(heading("Xulosa", size=11.0)), 600, 615), body(UZ_BODY)]
    assert kinds(raws)[1] == ("paragraph", None)


def test_numbered_run_in_title_is_the_first_line_of_its_paragraph() -> None:
    raws = [
        heading("2. Tadbirkorlikni ragʻbatlantirish. Soliq", size=11.0),
        body(
            "tizimi xoʻjalik yurituvchi subyektlarni, jumladan, chet el subyektlarini ham ishlab "
            "chiqarishni rivojlantirishga undashi lozim."
        ),
        heading("3. Adolatlilik tamoyili. Adolat tamoyil-", size=11.0),
        body("lariga muvofiq soliqlar jamiyat tomonidan adolatli deb tan olinadi."),
    ]
    assert not [t for t, _ in kinds(raws) if t == "heading"]


def test_short_heading_before_a_capitalized_paragraph_stays_a_heading() -> None:
    raws = [spaced(heading("2.1. Pul aylanmasi", size=11.0)), body(UZ_BODY)]
    assert kinds(raws)[0] == ("heading", None)


def stacked(
    texts: list[str], size: float = 14.0, bold: float = 1.0, top: float = 100.0
) -> list[RawBlock]:
    """Lines one under another, centered, each its own block."""
    return [
        RawBlock(
            text=t,
            page=1,
            font_size=size,
            bold=bold,
            bbox=(150.0, top + 18 * i, 450.0, top + 18 * i + 15),
        )
        for i, t in enumerate(texts)
    ]


@pytest.mark.parametrize(
    "lines",
    [
        ["5.3. Banklarning qimmatli qogʻozlar boʻyicha tijorat va", "investitsiya faoliyati"],
        [
            "1-MAVZU: KIRISH (BANK ISHI VA MOLIYA ASOSLARI",
            "FANINING ASOSIY VAZIFALARI,",
            "PREDMETI VA OBYEKTI)",
        ],
        [
            "3.3. Markaziy bankning funksiyalari: emission funksiya,",
            "banklarning banki funksiyasi,",
            "hukumatning banki funksiyasi va",
            "pul-kredit siyosati",
        ],
    ],
)
def test_heading_over_several_lines_is_one_heading(lines: list[str]) -> None:
    raws = [*stacked(lines), body(UZ_BODY)]
    blocks = build_blocks(raws)
    assert blocks[0].type is BlockType.HEADING and blocks[0].text == " ".join(lines)
    assert blocks[1].text == UZ_BODY


def test_bold_first_body_line_is_not_joined_to_the_heading() -> None:
    raws = [
        *stacked(["2.1. Pul aylanmasi"]),
        *stacked(["Pul aylanmasi muhim jarayon."], top=118.0),
        body(UZ_BODY),
    ]
    blocks = build_blocks(raws)
    assert blocks[0].text == "2.1. Pul aylanmasi"


def test_title_above_formula_debris_is_a_caption() -> None:
    formula = RawBlock(
        text="A Sˆ C = 0", page=1, font_size=11.0, role="formula", bbox=(60, 214, 300, 266)
    )
    raws = [at(spaced(heading("FAM", size=14.0)), 181, 201), formula, body(UZ_BODY)]
    blocks = build_blocks(raws)
    assert not [b for b in blocks if b.type is BlockType.HEADING]


def test_sentence_split_by_a_displayed_formula_is_joined() -> None:
    formula = RawBlock(text="Y = C + I + G", page=1, font_size=11.0, role="formula")
    raws = [
        body("Yalpi talab quyidagi formula orqali"),
        formula,
        body("hisoblanadi va tahlil qilinadi."),
    ]
    texts = [b.text for b in build_blocks(raws)]
    assert "Yalpi talab quyidagi formula orqali hisoblanadi va tahlil qilinadi." in texts


@pytest.mark.parametrize("text", ["B FAM", "FAM’’", "Sˆ C", "G &"])
def test_letters_and_short_tokens_are_never_a_heading(text: str) -> None:
    raws = [spaced(heading(text)), body(UZ_BODY)]
    assert kinds(raws)[0][0] != "heading"


@pytest.mark.parametrize("text", ["KIRISH", "XULOSA", "ВВЕДЕНИЕ", "II-BOB. PUL"])
def test_short_real_headings_stay_headings(text: str) -> None:
    raws = [spaced(heading(text)), body(UZ_BODY)]
    assert kinds(raws)[0] == ("heading", None)


PLAN_TITLES = ["4.1. Bank risklari tizimi", "4.2. Kredit riski mazmuni", "4.3. Foiz riski"]


@pytest.mark.parametrize("together", [False, True])
def test_last_plan_item_goes_with_the_plain_ones_before_it(together: bool) -> None:
    plan = [body("\n".join(PLAN_TITLES[:2]))] if together else [body(t) for t in PLAN_TITLES[:2]]
    raws = [
        heading("4-MAVZU: BANK RISKLARI"),
        *plan,
        spaced(heading(PLAN_TITLES[2], size=11.0)),
        *[
            block
            for title in PLAN_TITLES
            for block in (spaced(heading(title, size=11.0)), body(UZ_BODY))
        ],
    ]
    headings = [b.text for b in build_blocks(raws) if b.type is BlockType.HEADING]
    assert headings == ["4-MAVZU: BANK RISKLARI", *PLAN_TITLES]


def test_colon_label_without_text_before_the_next_heading_is_not_a_heading() -> None:
    raws = [
        spaced(heading("Xulosa:", size=11.0)),
        spaced(heading("9.2. Keyingi boʻlim", size=11.0)),
        body(UZ_BODY),
    ]
    assert kinds(raws)[0] == ("paragraph", None)


def test_colon_heading_followed_by_its_text_stays_a_heading() -> None:
    raws = [heading("UMUMIY QOIDALAR:"), body(UZ_BODY)]
    assert kinds(raws)[0] == ("heading", None)


def test_open_title_joins_its_next_line_despite_a_small_style_difference() -> None:
    first = RawBlock(
        text="6.2. Masofaviy bank xizmatlarining vujudga kelishi va",
        page=1,
        font_size=14.0,
        bold=1.0,
        bbox=(100, 100, 500, 116),
    )
    second = RawBlock(
        text="rivojlanish bosqichlari", page=1, font_size=13.0, bold=0.7, bbox=(200, 136, 400, 151)
    )
    blocks = build_blocks([first, second, body(UZ_BODY)])
    assert (
        blocks[0].text
        == "6.2. Masofaviy bank xizmatlarining vujudga kelishi va rivojlanish bosqichlari"
    )


def test_finished_title_does_not_take_a_differently_styled_next_line() -> None:
    first = RawBlock(
        text="6.2. Masofaviy bank xizmatlari",
        page=1,
        font_size=14.0,
        bold=1.0,
        bbox=(100, 100, 500, 116),
    )
    second = RawBlock(
        text="Bank xizmatlari turlari", page=1, font_size=13.0, bold=0.7, bbox=(200, 136, 400, 151)
    )
    blocks = build_blocks([first, second, body(UZ_BODY)])
    assert blocks[0].text == "6.2. Masofaviy bank xizmatlari"


def test_recurring_heading_text_gets_one_decision() -> None:
    raws = [
        spaced(heading("Nazorat uchun savollar", size=11.0)),
        body(UZ_BODY),
        heading("Nazorat uchun savollar.", size=11.0),  # no space above on this page
        body(UZ_BODY),
    ]
    assert [t for t, _ in kinds(raws)] == ["heading", "paragraph", "heading", "paragraph"]


def test_same_words_in_plain_body_style_stay_a_paragraph() -> None:
    raws = [
        spaced(heading("Nazorat uchun savollar", size=11.0)),
        body(UZ_BODY),
        body("Nazorat uchun savollar."),
        body(UZ_BODY),
    ]
    assert [t for t, _ in kinds(raws)] == ["heading", "paragraph", "paragraph", "paragraph"]


def test_rival_chapter_words_share_the_top_level() -> None:
    raws = [
        heading("I-BOB. PUL NAZARIYASI"),
        heading("1.1. Pulning kelib chiqishi", size=11.0),
        body(UZ_BODY),
        heading("II-BOB. MARKAZIY BANK"),
        body(UZ_BODY),
        heading("8-МАВЗУ. МАТЕМАТИК ИЛОВА"),
        body(UZ_BODY),
    ]
    levels = dict(levels_of(raws))
    assert levels["I-BOB. PUL NAZARIYASI"] == levels["8-МАВЗУ. МАТЕМАТИК ИЛОВА"] == 1
    assert levels["1.1. Pulning kelib chiqishi"] == 2


def test_chapter_words_that_nest_keep_their_order() -> None:
    raws = [
        heading("I BOʻLIM. UMUMIY"),
        heading("1-bob. Asosiy"),
        body(UZ_BODY),
        heading("2-bob. Qoʻshimcha"),
        body(UZ_BODY),
    ]
    assert [level for _, level in levels_of(raws)] == [1, 2, 2]


def test_sentence_left_open_at_a_page_end_goes_on_before_a_capital() -> None:
    """A paragraph ending a page with a word goes on onto the next page even when that page
    starts with a capital ("... tenglashtirilgan, Oʻzbekiston" + "Respublikasi ...")."""
    first = RawBlock(
        text="Diplomatik vakolatxonalarga hamda ularga tenglashtirilgan, Oʻzbekiston",
        page=1,
        font_size=11.0,
        bbox=(72, 760, 520, 774),
    )
    rest = RawBlock(
        text="Respublikasi hududida joylashgan xalqaro tashkilotlarga beriladi.",
        page=2,
        font_size=11.0,
        bbox=(72, 80, 520, 94),
    )
    blocks = build_blocks([first, rest])
    assert len(blocks) == 1 and blocks[0].text.endswith("tashkilotlarga beriladi.")
    finished = RawBlock(text=first.text + ".", page=1, font_size=11.0, bbox=first.bbox)
    assert len(build_blocks([finished, rest])) == 2
