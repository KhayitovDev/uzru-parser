"""Thin Python wrappers around the Rust core."""

from __future__ import annotations

from . import _core
from .models import LanguageInfo


def normalize(text: str) -> str:
    """NFC + invisible-char cleanup + Uzbek apostrophe normalization + whitespace."""
    return _core.normalize_text(text)


def repair_hyphenation(text: str) -> str:
    """Join words wrapped with a hyphen at line end; keep real hyphenated words."""
    return _core.repair_hyphenation(text)


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


def estimate_tokens(text: str) -> int:
    """Tokenizer-free estimate (about one token per four characters of each word)."""
    return _core.estimate_tokens(text)
