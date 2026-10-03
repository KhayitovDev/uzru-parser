"""Proves Python can call the Rust core."""

from uzru_parser import _core
from uzru_parser.text import detect_language, normalize, repair_hyphenation


def test_rust_module_loads() -> None:
    assert isinstance(_core.__version__, str)


def test_normalize_calls_rust() -> None:
    assert normalize("O'zbekiston") == "Oʻzbekiston"


def test_hyphenation_calls_rust() -> None:
    assert repair_hyphenation("Настоя-\nщим документом") == "Настоящим документом"


def test_language_calls_rust() -> None:
    info = detect_language("Настоящий договор является основанием для оказания услуг.")
    assert (info.language, info.script, info.locale) == ("ru", "cyrillic", "ru")


def test_english_text_is_not_mistaken_for_uzbek() -> None:
    english = (
        "Circular imports and meaning reasoning about modules. "
        "Python uses reference counting for memory management, which is not thread-safe. "
        "Threads share memory and are lightweight, but are limited by the interpreter lock."
    )
    assert detect_language(english).language == "unknown"
