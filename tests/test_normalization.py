import pytest
from uzru_parser import BlockType
from uzru_parser.structure import RawBlock, build_blocks
from uzru_parser.text import (
    CleanStats,
    clean,
    compound_pairs,
    map_symbol_font,
    normalize,
    repair_hyphenation,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Статья 5 ........ 12", "Статья 5 … 12"),
        ("Bo‘lim 2 . . . . . 7", "Boʻlim 2 … 7"),
        ("Продолжение...", "Продолжение..."),
        ("т.е. и т.д.", "т.е. и т.д."),
    ],
)
def test_dot_leaders(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_yo_is_never_replaced() -> None:
    assert normalize("Ёж ещё всё") == "Ёж ещё всё"


@pytest.mark.parametrize("apostrophe", ["'", "’", "ʻ", "ʼ", "`", "‘"])
def test_uzbek_apostrophe_variants_unified(apostrophe: str) -> None:
    assert normalize(f"o{apostrophe}zbek g{apostrophe}or ma{apostrophe}no") == "oʻzbek gʻor maʼno"


def test_apostrophes_outside_words_untouched() -> None:
    assert normalize("'цитата' и 'quote'") == "'цитата' и 'quote'"


def test_hyphenation_keeps_legitimate_compounds() -> None:
    assert repair_hyphenation("кто-\nто") == "кто-то"
    assert repair_hyphenation("Настоя-\nщим") == "Настоящим"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("по-\nрусски", "по-русски"),
        ("BMT-\nning qarori", "BMT-ning qarori"),
        ("когда-\nнибудь", "когда-нибудь"),
    ],
)
def test_hyphenation_keeps_prefix_adverbs_and_acronym_suffixes(text: str, expected: str) -> None:
    assert repair_hyphenation(text) == expected


# --- Look-alike letters, symbol fonts, apostrophes (section 1-3) ---------------------------


@pytest.mark.parametrize(
    ("mixed", "fixed"),
    [
        ("vаlyutа bozori", "valyuta bozori"),  # Cyrillic "а" inside a Latin word
        ("MUNDАRIJА", "MUNDARIJA"),
        ("II-BОB", "II-BOB"),
        ("Пoлитика бaнка", "Политика банка"),  # Latin "o", "a" inside Russian words
        ("ўқувчилaр", "ўқувчилар"),
    ],
)
def test_mixed_alphabet_words_become_single_alphabet(mixed: str, fixed: str) -> None:
    stats = CleanStats()
    assert clean(mixed, stats) == fixed
    assert stats.mixed_script_words_fixed >= 1


@pytest.mark.parametrize(
    "text",
    [
        "Банковская система обеспечивает расчёты между предприятиями.",
        "Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик қилади.",
        "Oʻzbekiston Respublikasi valyuta bozori rivojlanmoqda.",
        "XIX век, глава IV, формула MV=PY и ООО «Ромашка».",
    ],
)
def test_single_alphabet_text_is_never_touched(text: str) -> None:
    stats = CleanStats()
    assert clean(text, stats) == text
    assert stats == CleanStats()


def test_words_without_twins_are_left_mixed() -> None:
    assert clean("bankиш") == "bankиш"


def test_apostrophe_is_fixed_after_the_alphabet() -> None:
    assert clean("TА’LIM va MА’NAVIYAT") == "TAʼLIM va MAʼNAVIYAT"


@pytest.mark.parametrize("apostrophe", ["'", "‘", "’", "`", "´", "′", "＇", "ʻ", "ʼ"])
def test_nine_apostrophes_are_unified(apostrophe: str) -> None:
    assert normalize(f"O{apostrophe}zbekiston ma{apostrophe}lumot") == "Oʻzbekiston maʼlumot"


def test_quotes_around_words_are_kept() -> None:
    assert normalize("‘bank’ va 'kredit'") == "‘bank’ va 'kredit'"


def test_symbol_font_characters_are_mapped_and_none_survive() -> None:
    stats = CleanStats()
    text = clean("a  b  c  d  e  f  g ", stats)
    assert text == "a + b = c × d > e ⋅ f g"
    assert not any(0xE000 <= ord(c) <= 0xF8FF for c in text)
    assert (stats.symbol_chars_mapped, stats.symbol_chars_removed) == (5, 2)


def test_symbol_font_name_picks_the_table() -> None:
    assert map_symbol_font(" + ", "SymbolMT") == "α + β"
    assert map_symbol_font(" band", "Wingdings-Regular") == "• band"
    assert map_symbol_font("", "TimesNewRoman") == ""  # decided per line later


def test_line_starting_with_a_symbol_bullet_becomes_a_list_item() -> None:
    blocks = build_blocks([RawBlock(text=" birinchi\n ikkinchi", page=1)])
    assert blocks[0].type is BlockType.LIST
    assert blocks[0].extra["items"] == ["• birinchi", "• ikkinchi"]


# --- Hyphens that the document itself writes as compounds (section 5) ----------------------


def test_compounds_are_collected_from_the_document() -> None:
    pairs = compound_pairs(["pul-kredit siyosati", "qoʻllab-quvvatlash va oltin-valyuta-kredit"])
    assert pairs == {"pul-kredit", "qoʻllab-quvvatlash", "oltin-valyuta", "valyuta-kredit"}


def test_document_compounds_keep_their_hyphen_at_a_line_break() -> None:
    raw = [
        RawBlock(
            text="Markaziy bank pul-\nkredit siyosatini va boshqa-\nrish usulini belgilaydi.",
            page=1,
        )
    ]
    with_compound = build_blocks(raw, compounds={"pul-kredit"})[0].text
    without = build_blocks(raw)[0].text
    assert with_compound == "Markaziy bank pul-kredit siyosatini va boshqarish usulini belgilaydi."
    assert without == "Markaziy bank pulkredit siyosatini va boshqarish usulini belgilaydi."


@pytest.mark.parametrize(
    "text", ["1978-\nyillarda", "pul –\nkredit", "Otamurodov-\ni.f.n., dotsent"]
)
def test_numbers_dashes_and_initials_are_never_joined(text: str) -> None:
    assert repair_hyphenation(text) == text
