"""The document's own style sheet, rebuilt from a PDF ("virtual styles").

A DOCX file names its styles; a PDF only says which font, size and weight each line uses. One
pass over the whole document groups blocks by their look (font family, size, bold, italic,
capitals) and finds what the look is used for:

* the body style: the look holding the most characters;
* heading styles: looks more prominent than the body (bigger, or bold, italic or in capitals
  at about body size), used rarely, for short blocks that stand alone and are followed by
  body text. They are ranked by size, then weight, then frequency (rarer is higher);
* the footnote style: smaller than the body and mostly at the foot of the page.

Decisions are made once per document, so a heading style keeps one rank on every page.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:  # structure.py uses the profile
    from .structure import RawBlock

SIZE_STEP = 0.5


@dataclass(frozen=True)
class Style:
    """The look of a block."""

    font: str
    size: float  # rounded to SIZE_STEP
    bold: bool
    italic: bool
    caps: bool

    def describe(self) -> str:
        traits = [t for t, on in (("bold", self.bold), ("italic", self.italic)) if on]
        caps = " caps" if self.caps else ""
        return f"{self.font or '?'} {self.size:g}{caps} {' '.join(traits) or 'regular'}"


@dataclass
class _Use:
    blocks: int = 0
    chars: int = 0
    short: int = 0  # blocks a heading could be: few lines, few characters
    before_body: int = 0  # blocks followed by a body block
    bottom: int = 0  # blocks in the footnote zone of the page
    pages: set[int] = field(default_factory=set)


@dataclass
class StyleProfile:
    body: Style | None = None
    #: Heading styles with their rank (1 = most prominent).
    headings: dict[Style, int] = field(default_factory=dict)
    footnote: Style | None = None

    def rank(self, style: Style | None) -> int | None:
        return self.headings.get(style) if style is not None else None

    def summary(self) -> dict[str, object]:
        ordered = sorted(self.headings, key=self.headings.__getitem__)
        return {
            "body": self.body.describe() if self.body else None,
            "headings": [style.describe() for style in ordered],
        }


def _caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < config.MIN_UPPERCASE_LETTERS:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= config.UPPERCASE_SHARE


def style_of(raw: RawBlock) -> Style | None:
    """The look of a text block; ``None`` for tables and blocks without a font size."""
    if raw.rows is not None or not raw.font_size:
        return None
    return Style(
        font=raw.font or "",
        size=round(raw.font_size / SIZE_STEP) * SIZE_STEP,
        bold=raw.bold >= config.BOLD_SHARE,
        italic=raw.italic >= config.BOLD_SHARE,
        caps=_caps(raw.text),
    )


def _flow(raw: RawBlock) -> bool:
    """Running content: not a table, figure, formula, contents or page furniture."""
    return raw.rows is None and raw.role is None and bool(raw.text.strip())


def _short(raw: RawBlock) -> bool:
    flat = " ".join(raw.text.split())
    lines = raw.text.count("\n") + 1
    return lines <= config.MAX_HEADING_LINES and len(flat) <= config.MAX_KEYWORD_HEADING_CHARS


def _prominent(style: Style, body: Style) -> bool:
    """Bigger than the body, or at about body size with an emphasis the body lacks."""
    if style.size >= body.size * config.LARGER_FONT_RATIO:
        return True
    if style.size < body.size * config.PROFILE_SAME_SIZE:
        return False
    return (
        (style.bold and not body.bold)
        or (style.caps and not body.caps)
        or (style.italic and not body.italic)
    )


def build_profile(blocks: Sequence[RawBlock], page_heights: dict[int, float]) -> StyleProfile:
    """Group the document's flow blocks by style and find what each style is used for."""
    flow = [raw for raw in blocks if _flow(raw) and not raw.footnote]
    styles = [style_of(raw) for raw in flow]
    chars: Counter[Style] = Counter()
    for raw, style in zip(flow, styles, strict=True):
        if style is not None:
            chars[style] += len(raw.text)
    if not chars:
        return StyleProfile()
    body = chars.most_common(1)[0][0]
    total = sum(chars.values())

    uses: dict[Style, _Use] = {}
    for index, (raw, style) in enumerate(zip(flow, styles, strict=True)):
        if style is None:
            continue
        use = uses.setdefault(style, _Use())
        use.blocks += 1
        use.chars += len(raw.text)
        use.pages.add(raw.page)
        use.short += _short(raw)
        following = styles[index + 1] if index + 1 < len(styles) else None
        use.before_body += following == body
        height = page_heights.get(raw.page, 0.0)
        if raw.bbox and height and raw.bbox[1] >= height * config.FOOTNOTE_ZONE:
            use.bottom += 1

    headings = [
        style
        for style, use in uses.items()
        if style != body
        and _prominent(style, body)
        and use.chars <= config.PROFILE_HEADING_MAX_SHARE * total
        and use.short >= config.PROFILE_HEADING_SHORT_SHARE * use.blocks
        and use.before_body >= config.PROFILE_HEADING_BEFORE_BODY * use.blocks
        and (use.blocks >= config.PROFILE_MIN_EMPHASIS_BLOCKS or style.size > body.size)
    ]
    # Bigger first, then bold, capitals, italic, then the rarer style.
    headings.sort(
        key=lambda s: (-s.size, not s.bold, not s.caps, not s.italic, uses[s].blocks, s.font)
    )
    footnotes = [
        style
        for style, use in uses.items()
        if style.size < body.size and use.bottom >= config.PROFILE_FOOTNOTE_BOTTOM * use.blocks
    ]
    footnote = max(footnotes, key=lambda s: uses[s].chars) if footnotes else None
    return StyleProfile(
        body=body,
        headings={style: rank for rank, style in enumerate(headings, start=1)},
        footnote=footnote,
    )
