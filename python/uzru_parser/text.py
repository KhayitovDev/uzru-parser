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
