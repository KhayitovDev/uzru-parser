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


def test_package_versions_match() -> None:
    import re
    from pathlib import Path

    import uzru_parser

    root = Path(__file__).resolve().parent.parent
    version = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
    pyproject = version.search((root / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = version.search((root / "Cargo.toml").read_text(encoding="utf-8"))
    assert pyproject and cargo
    assert pyproject.group(1) == cargo.group(1) == uzru_parser.__version__
