import pytest
from uzru_parser.text import normalize, repair_hyphenation


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
    assert repair_hyphenation("кто-\nто") == "кто-\nто"
    assert repair_hyphenation("Настоя-\nщим") == "Настоящим"


@pytest.mark.parametrize("text", ["по-\nрусски", "BMT-\nning qarori", "когда-\nнибудь"])
def test_hyphenation_keeps_prefix_adverbs_and_acronym_suffixes(text: str) -> None:
    assert repair_hyphenation(text) == text
