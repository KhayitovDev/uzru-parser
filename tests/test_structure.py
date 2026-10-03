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
        ("Статья 5. Права сторон", 3),
        ("1. UMUMIY QOIDALAR", 1),
        ("1.1. Asosiy tushunchalar", 2),
        ("2. XIZMAT KO‘RSATISH TARTIBI", 1),
        ("1. УМУМИЙ ҚОИДАЛАР", 1),
        ("1.2. Асосий тушунчалар", 2),
        ("МОДДА 4. ҲУҚУҚЛАР ВА МАЖБУРИЯТЛАР", 3),
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
