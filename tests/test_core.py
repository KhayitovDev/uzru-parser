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
