import pytest
from uzru_parser import BlockType
from uzru_parser.structure import RawBlock, build_blocks
from uzru_parser.text import numbering_info, split_sentences


def heading(text: str, size: float = 14.0, bold: float = 1.0) -> RawBlock:
    return RawBlock(text=text, page=1, font_size=size, bold=bold)


def body(text: str, size: float = 11.0) -> RawBlock:
    return RawBlock(text=text, page=1, font_size=size, bold=0.0)


PARAGRAPH = "Настоящий договор является основанием для оказания услуг по настоящему договору."


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1),
        ("1.1. Основные понятия", 2),
        ("Статья 5. Права сторон", 4),
        ("1. UMUMIY QOIDALAR", 1),
        ("1.1. Asosiy tushunchalar", 2),
        ("2. XIZMAT KO‘RSATISH TARTIBI", 1),
        ("1. УМУМИЙ ҚОИДАЛАР", 1),
        ("1.2. Асосий тушунчалар", 2),
        ("МОДДА 4. ҲУҚУҚЛАР ВА МАЖБУРИЯТЛАР", 4),
        ("1-modda. Ushbu Kodeks bilan tartibga solinadigan munosabatlar", 4),
        ("1-bob. Asosiy qoidalar", 2),
        ("I BOʻLIM. UMUMIY QOIDALAR", 1),
        ("1-§. Yakka tartibdagi munosabatlar", 3),
        ("ПРИЛОЖЕНИЕ № 1", 1),
        ("I. Общие положения", 1),
    ],
)
def test_headings_with_font_signals(text: str, level: int) -> None:
    blocks = build_blocks([body(PARAGRAPH), heading(text), body(PARAGRAPH)])
    assert [b.type for b in blocks] == [
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]
    assert blocks[1].level == level


def test_uppercase_numbered_heading_without_font_info() -> None:
    raw = [RawBlock(text="1. ОБЩИЕ ПОЛОЖЕНИЯ", page=1), RawBlock(text=PARAGRAPH, page=1)]
    assert [b.type for b in build_blocks(raw)] == [BlockType.HEADING, BlockType.PARAGRAPH]


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
    assert headings(smaller) == ["2-MAVZU: PUL VA BANK ISHI", "IZOH"]


def test_numbered_title_inside_a_body_block_is_split_off() -> None:
    text = (
        "1.1. Banklarning paydo boʻlish sabablari\n"
        "Pul – mahsulot, tovarlarni ishlab chiqarish va xaridorlarga kerakli vaqtda yetkazib\n"
        "berish uchun zarur boʻlgan vosita sifatida paydo boʻldi va rivojlandi."
    )
    blocks = build_blocks([body(PARAGRAPH), RawBlock(text=text, page=3, font_size=11)])
    assert [b.type for b in blocks] == [BlockType.PARAGRAPH, BlockType.HEADING, BlockType.PARAGRAPH]
    assert (blocks[1].text, blocks[1].level) == ("1.1. Banklarning paydo boʻlish sabablari", 2)


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
    assert block_types([body(PARAGRAPH), RawBlock(text=text, page=19, font_size=11)]) == [
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
    ]


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
    assert blocks[1].level == 2


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
