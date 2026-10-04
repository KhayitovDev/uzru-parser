"""How sure the parser is about each PDF page.

Every check gives a penalty from 0 (fine) to 1 (bad); the page's confidence is 1 minus the
largest penalty, and the checks that cost confidence are listed as issues:

* ``columns``: text side by side within one reading region (columns read as one);
* ``tables``: tables with inconsistent columns or many empty cells;
* ``headings``: prominent short blocks whose style is not one of the document's heading
  styles (headings the style profile cannot place);
* ``short_lines``: mostly very short lines (charts, diagrams, formulas);
* ``text_layer``: unknown-glyph marks or words the lexicons do not know (a broken encoding).

Low-confidence pages are where an optional layout model can help.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from . import config
from .paragraphs import Line
from .profile import StyleProfile, style_of
from .structure import RawBlock
from .tables import table_score
from .text import is_known_word

_WORD = re.compile(r"[^\W\d_]{4,}")
_BROKEN = re.compile(r"�|\(cid:\d+\)")


def page_confidence(
    regions: Sequence[Sequence[Line]],
    tables: Sequence[list[list[str]]],
    blocks: Sequence[RawBlock],
    profile: StyleProfile | None,
) -> tuple[float, list[str]]:
    """Confidence (0-1) of one page and the issues behind it."""
    lines = [line for region in regions for line in region]
    if not lines:
        return 1.0, []
    penalties = {
        "columns": _side_by_side(regions),
        "tables": _tables(tables),
        "headings": _heading_conflicts(blocks, profile),
        "short_lines": _short_lines(lines),
        "text_layer": _text_layer(lines),
    }
    issues = [name for name, value in penalties.items() if value >= config.CONFIDENCE_ISSUE]
    return round(1.0 - max(penalties.values()), 3), issues


def _side_by_side(regions: Sequence[Sequence[Line]]) -> float:
    """Share of a region's lines with another line beside them across a gutter, scaled so
    that CONFIDENCE_SIDE_SHARE of such lines is a full penalty."""
    lines = sum(len(region) for region in regions)
    beside = 0
    for region in regions:
        ordered = sorted(region, key=lambda line: line.bbox[1])
        for index, line in enumerate(ordered):
            size = line.size or 10.0
            for other in ordered[index + 1 :]:
                if other.bbox[1] > line.bbox[3]:
                    break
                apart = other.bbox[0] - line.bbox[2] >= config.COLUMN_GUTTER * size or (
                    line.bbox[0] - other.bbox[2] >= config.COLUMN_GUTTER * size
                )
                if apart and _long(line) and _long(other):
                    beside += 1
                    break
    return min(1.0, beside / (lines * config.CONFIDENCE_SIDE_SHARE)) if lines else 0.0


def _long(line: Line) -> bool:
    """A line of running text rather than a label or a table cell."""
    return len(line.text.split()) >= config.FIGURE_LABEL_WORDS


def _tables(tables: Sequence[list[list[str]]]) -> float:
    """The worst table: a score of CONFIDENCE_TABLE_SCORE or more costs nothing, -1 all."""
    if not tables:
        return 0.0
    worst = min(table_score(rows) for rows in tables)
    good = config.CONFIDENCE_TABLE_SCORE
    return max(0.0, min(1.0, (good - worst) / (good + 1.0)))


def _heading_conflicts(blocks: Sequence[RawBlock], profile: StyleProfile | None) -> float:
    """Short blocks bigger or bolder than the body whose style the profile did not rank."""
    if profile is None or profile.body is None:
        return 0.0
    body = profile.body
    conflicts = 0
    for raw in blocks:
        style = style_of(raw)
        if style is None or raw.role or raw.footnote or raw.text.count("\n") > 1:
            continue
        prominent = style.size >= body.size * config.LARGER_FONT_RATIO or (
            style.bold and not body.bold
        )
        if prominent and style not in profile.headings and len(raw.text.split()) >= 2:
            conflicts += 1
    return min(1.0, conflicts / config.CONFIDENCE_HEADING_CONFLICTS)


def _short_lines(lines: Sequence[Line]) -> float:
    """Share of lines with at most CONFIDENCE_SHORT_LINE_CHARS characters, above
    CONFIDENCE_SHORT_SHARE (pages of chart labels and formula pieces)."""
    if len(lines) < config.MIN_COLUMN_LINES:
        return 0.0
    short = sum(1 for line in lines if line.chars <= config.CONFIDENCE_SHORT_LINE_CHARS)
    share = short / len(lines)
    floor = config.CONFIDENCE_SHORT_SHARE
    return max(0.0, min(1.0, (share - floor) / (1.0 - floor)))


def _text_layer(lines: Sequence[Line]) -> float:
    """Unknown-glyph marks, or a page whose words the lexicons mostly do not know."""
    text = " ".join(line.text for line in lines)
    if _BROKEN.search(text):
        return 1.0
    words = _WORD.findall(text)
    if len(words) < config.CONFIDENCE_MIN_WORDS:
        return 0.0
    words = words[:: max(1, len(words) // config.CONFIDENCE_SAMPLE_WORDS)]
    unknown = sum(1 for word in words if not is_known_word(word)) / len(words)
    floor = config.CONFIDENCE_UNKNOWN_SHARE
    return max(0.0, min(1.0, (unknown - floor) / (1.0 - floor)))
