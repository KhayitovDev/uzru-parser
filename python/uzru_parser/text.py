"""Thin Python wrappers around the Rust core."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from . import _core, config
from .models import LanguageInfo

_core.set_heading_keywords(list(config.HEADING_KEYWORDS))

_COMPOUND = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)+")


@dataclass
class CleanStats:
    """What character cleanup changed in one document."""

    mixed_script_words_fixed: int = 0
    symbol_chars_mapped: int = 0
    symbol_chars_removed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    def add(self, other: CleanStats) -> None:
        self.mixed_script_words_fixed += other.mixed_script_words_fixed
        self.symbol_chars_mapped += other.symbol_chars_mapped
        self.symbol_chars_removed += other.symbol_chars_removed


def normalize(text: str) -> str:
    """Symbol fonts, look-alike letters, apostrophes, spaces (see ``clean`` for counts)."""
    return _core.normalize_text(text)


def clean(text: str, stats: CleanStats | None = None) -> str:
    """``normalize`` that adds what it fixed to ``stats``."""
    out, mixed, mapped, removed = _core.normalize_text_stats(text)
    if stats is not None:
        stats.mixed_script_words_fixed += mixed
        stats.symbol_chars_mapped += mapped
        stats.symbol_chars_removed += removed
    return out


def map_symbol_font(text: str, font_name: str, stats: CleanStats | None = None) -> str:
    """Translate symbol-font characters of a span whose font is Symbol- or Wingdings-like."""
    out, mapped, removed = _core.map_symbol_font(text, font_name)
    if stats is not None:
        stats.symbol_chars_mapped += mapped
        stats.symbol_chars_removed += removed
    return out


def repair_hyphenation(text: str) -> str:
    """Join words wrapped with a hyphen at line end; keep real hyphenated words."""
    return _core.repair_hyphenation(text)


Hyphenator = _core.Hyphenator


def compound_pairs(texts: Iterable[str]) -> set[str]:
    """Lowercase "left-right" pairs of the hyphenated words written in one piece in ``texts``.

    A hyphen at a line break is kept when the same document writes that compound whole.
    """
    pairs: set[str] = set()
    for text in texts:
        if "-" not in text:
            continue
        for compound in _COMPOUND.findall(text):
            parts = compound.lower().split("-")
            pairs.update(f"{a}-{b}" for a, b in zip(parts, parts[1:], strict=False))
    return pairs


def detect_language(text: str) -> LanguageInfo:
    language, script, confidence = _core.detect_language(text)
    return LanguageInfo(language=language, script=script, confidence=confidence)


def numbering_info(line: str) -> tuple[str, int] | None:
    """Return ``(kind, depth)`` for a leading section number or list marker, else ``None``.

    ``kind`` is one of ``decimal``, ``keyword``, ``bullet``, ``ordered``.
    """
    return _core.numbering_info(line)


def split_sentences(text: str) -> list[str]:
    return _core.split_sentences(text)


def is_sentence_break(left: str, right: str) -> bool:
    """Does a sentence end between ``left`` and ``right``? Abbreviations ("ст.", "prof."),
    initials and list numbers do not end one; text without a final delimiter runs on."""
    return _core.is_sentence_break(left, right)


def is_known_word(word: str) -> bool:
    """Is ``word`` a known Uzbek (Latin or Cyrillic) or Russian word, inflected forms too?"""
    return _core.is_known_word(word)


def ends_with_abbreviation(text: str) -> bool:
    """Does ``text`` end with an abbreviation or an initial ("ст.", "prof.", "Л. В.") that
    leaves the sentence open even before a capital letter?"""
    return text.rstrip().endswith(".") and not _core.is_sentence_break(text, "A")


def estimate_tokens(text: str) -> int:
    """Tokenizer-free estimate (about one token per four characters of each word)."""
    return _core.estimate_tokens(text)
