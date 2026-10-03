"""Rebuild paragraphs from PDF lines and group figure labels, using document statistics.

PDF producers differ a lot: some put a whole paragraph in one text block, others one line
per block. Lines are therefore joined by geometry (same column, typical line gap, same
style) rather than by the producer's blocks; the thresholds scale with the document's own
body font size, line gap and page edges.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from . import config
from .structure import RawBlock
from .text import ends_with_abbreviation, numbering_info

BBox = tuple[float, float, float, float]

_ENDS_SENTENCE = re.compile(r"[.!?:…][\"'»”’)\]]*\s*$")
_NUMBER_TOKEN = re.compile(
    r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[IVXLC]{1,6}\.?|(?:\d{1,3}|[IVXLC]{1,6})\s*-\s*[^\W\d_]+[.:]?)\s*$"
)
_LEADER_END = re.compile(r"(?:\.{3,}|…)\s*$")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
FIGURE_SEPARATOR = " | "
RIGHT_EDGE_PERCENTILE = 0.9


@dataclass
class Line:
    """One printed line: cleaned text plus the geometry and style the decisions need."""

    text: str
    bbox: BBox
    size: float | None = None
    bold: float = 0.0
    chars: int = 0
    original: str = ""
    refs: list[str] = field(default_factory=list)
    block: int = 0  # PyMuPDF block number on the page


@dataclass
class LayoutStats:
    """Typical values of one document."""

    body_size: float = 11.0
    line_gap: float = 2.0  # vertical gap between two lines of one paragraph
    right_edge: float = 0.0  # most common right end of body lines
    line_blocks: bool = False  # the producer put each line in its own block


def _size_key(size: float | None) -> float:
    return round((size or 0.0) * 2) / 2


def _style(line: Line) -> tuple[float, bool]:
    return _size_key(line.size), line.bold >= config.BOLD_SHARE


def _is_body(line: Line, body_size: float) -> bool:
    return line.size is not None and abs(line.size - body_size) <= 0.5


def _overlaps_horizontally(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2]


def _right_edge(values: list[float], default: float) -> float:
    """The column's right edge: a high percentile of line ends (the longest lines reach it,
    in justified and in ragged text alike)."""
    if not values:
        return default
    ordered = sorted(values)
    return ordered[int(RIGHT_EDGE_PERCENTILE * (len(ordered) - 1))]


def layout_stats(pages: list[list[Line]]) -> LayoutStats:
    """Body font size, typical line gap, right edge and block style of a document."""
    sizes: Counter[float] = Counter()
    for lines in pages:
        for line in lines:
            if line.size and line.chars:
                sizes[_size_key(line.size)] += line.chars
    if not sizes:
        return LayoutStats()
    body = sizes.most_common(1)[0][0]

    gaps: list[float] = []
    right: list[float] = []
    block_lines: Counter[tuple[int, int]] = Counter()
    for page, lines in enumerate(pages):
        body_lines = [line for line in lines if _is_body(line, body)]
        right.extend(line.bbox[2] for line in body_lines)
        block_lines.update((page, line.block) for line in body_lines)
        for a, b in zip(body_lines, body_lines[1:], strict=False):
            gap = b.bbox[1] - a.bbox[3]
            if _overlaps_horizontally(a.bbox, b.bbox) and -0.5 * body <= gap < 2 * body:
                gaps.append(gap)
    single = sum(1 for count in block_lines.values() if count == 1)
    return LayoutStats(
        body_size=body,
        line_gap=statistics.median(gaps) if gaps else 0.2 * body,
        right_edge=_right_edge(right, 0.0),
        line_blocks=bool(block_lines) and single / len(block_lines) > config.LINE_LEVEL_BLOCKS,
    )


def _ends_sentence(text: str) -> bool:
    return bool(_ENDS_SENTENCE.search(text))


def _starts_lowercase(text: str) -> bool:
    letter = next((c for c in text if c.isalpha()), "")
    return letter.islower()


def _same_row(a: Line, b: Line) -> bool:
    top, bottom = max(a.bbox[1], b.bbox[1]), min(a.bbox[3], b.bbox[3])
    smaller = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]) or 1.0
    return bottom - top >= 0.5 * smaller and b.bbox[0] >= a.bbox[2] - 1.0


def _join_row(a: Line, b: Line) -> Line:
    """``b`` continues ``a`` on the same row; the title part decides the style."""
    style_from = b if b.chars >= a.chars else a
    return Line(
        text=f"{a.text} {b.text}",
        bbox=(
            min(a.bbox[0], b.bbox[0]),
            min(a.bbox[1], b.bbox[1]),
            b.bbox[2],
            max(a.bbox[3], b.bbox[3]),
        ),
        size=style_from.size,
        bold=style_from.bold,
        chars=a.chars + b.chars,
        original=f"{a.original} {b.original}",
        refs=a.refs + b.refs,
        block=a.block,
    )


def merge_row_fragments(lines: list[Line]) -> list[Line]:
    """Put a lone section number ("1.1.", "II-BOB") and its title back on one line, and a
    contents page number back after its leader ("Title …" + "7")."""
    merged: list[Line] = []
    for line in lines:
        previous = merged[-1] if merged else None
        if previous is not None and _same_row(previous, line):
            number_then_title = _NUMBER_TOKEN.match(previous.text) is not None
            leader_then_page = _LEADER_END.search(previous.text) and _PAGE_NUMBER.match(line.text)
            if number_then_title or leader_then_page:
                merged[-1] = _join_row(previous, line)
                continue
        merged.append(line)
    return merged


def _center_in(box: BBox, region: BBox) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _is_label(line: Line) -> bool:
    words = len(line.text.split())
    marker = numbering_info(line.text)
    is_item = marker is not None and marker[0] in ("bullet", "ordered", "decimal")
    return (
        words <= config.FIGURE_LABEL_WORDS
        and len(line.text) <= config.FIGURE_LABEL_CHARS
        and not is_item
    )


def _is_free_label(line: Line, body_size: float) -> bool:
    """A label outside any drawing: a few words, plain style, not a sentence or an item."""
    styled = (
        line.size or 0
    ) > body_size * config.LARGER_FONT_RATIO or line.bold >= config.BOLD_SHARE
    return (
        len(line.text.split()) <= config.FIGURE_FREE_LABEL_WORDS
        and not styled
        and not _ends_sentence(line.text)
        and numbering_info(line.text) is None
    )


def figure_labels(
    lines: list[Line], regions: list[BBox], body_size: float, right_edge: float | None = None
) -> set[int]:
    """Indexes of lines that are labels of a figure (chart, diagram, scheme). Lines reaching
    the text's ``right_edge`` are running text (a narrow column, a text box), never labels."""

    left_edge = min((line.bbox[0] for line in lines), default=0.0)

    def full(line: Line) -> bool:
        """Reaches the right edge and spans at least half of the text width."""
        if right_edge is None:
            return False
        size = line.size or body_size
        wide = line.bbox[2] - line.bbox[0] >= config.FULL_LINE_SHARE * (right_edge - left_edge)
        return wide and line.bbox[2] >= right_edge - config.PARAGRAPH_SHORT_LINE * size

    labels: set[int] = set()
    candidates = [i for i, line in enumerate(lines) if _is_label(line) and not full(line)]
    margin = config.FIGURE_LABEL_MARGIN * body_size
    for x0, y0, x1, y1 in regions:
        region = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
        inside = [i for i in candidates if _center_in(lines[i].bbox, region)]
        if len(inside) >= config.FIGURE_MIN_LABELS:
            labels.update(inside)

    run: list[int] = []
    for i, line in enumerate([*lines, None]):
        if line is not None and _is_free_label(line, body_size) and not full(line):
            run.append(i)
            continue
        if len(run) >= config.FIGURE_MIN_LABELS_WITHOUT_DRAWING:
            labels.update(run)
        run = []
    return labels


def _continues(paragraph: list[Line], line: Line, stats: LayoutStats, page_right: float) -> bool:
    """Does ``line`` belong to the paragraph whose lines are ``paragraph``?"""
    last, first = paragraph[-1], paragraph[0]
    if line.chars and last.chars and _style(line) != _style(last):
        return False
    size = last.size or line.size or stats.body_size
    gap = line.bbox[1] - last.bbox[3]
    if gap < -0.5 * size or gap > stats.line_gap + config.PARAGRAPH_GAP_SLACK * size:
        return False
    if not _overlaps_horizontally(line.bbox, last.bbox) or numbering_info(line.text):
        return False

    tolerance = config.PARAGRAPH_ALIGN_TOLERANCE * size
    if len(paragraph) == 1:
        # Second line: the first may be indented (paragraph) or carry a list marker (hanging).
        hanging = numbering_info(first.text) is not None
        deepest = first.bbox[0] + (config.PARAGRAPH_MAX_INDENT * size if hanging else tolerance)
        if not first.bbox[0] - config.PARAGRAPH_MAX_INDENT * size <= line.bbox[0] <= deepest:
            return False
    elif abs(line.bbox[0] - min(other.bbox[0] for other in paragraph[1:])) > tolerance:
        return False

    open_after = ends_with_abbreviation(last.text)
    sentence_break = not open_after and (
        _ends_sentence(last.text) or not _starts_lowercase(line.text)
    )
    short_last = last.bbox[2] < page_right - config.PARAGRAPH_SHORT_LINE * size
    if short_last and sentence_break:
        return False
    # Producers that write whole paragraphs as blocks: a new block is a new paragraph
    # unless the sentence visibly runs on.
    return stats.line_blocks or line.block == last.block or not sentence_break


def _block_from(lines: list[Line], page: int, spaced: bool, role: str | None = None) -> RawBlock:
    chars = sum(line.chars for line in lines) or 1
    separator = FIGURE_SEPARATOR if role == "figure" else "\n"
    return RawBlock(
        text=separator.join(line.text for line in lines),
        original="\n".join(line.original or line.text for line in lines),
        page=page,
        bbox=(
            min(line.bbox[0] for line in lines),
            min(line.bbox[1] for line in lines),
            max(line.bbox[2] for line in lines),
            max(line.bbox[3] for line in lines),
        ),
        font_size=max((line.size for line in lines if line.size), default=None),
        bold=sum(line.bold * line.chars for line in lines) / chars,
        footnote_refs=[ref for line in lines for ref in line.refs],
        role=role,
        spaced=spaced,
    )


def build_paragraphs(
    lines: list[Line], page: int, stats: LayoutStats, regions: list[BBox] | None = None
) -> list[RawBlock]:
    """Raw blocks of one page in reading order: paragraphs and figure label groups."""
    lines = [line for line in merge_row_fragments(lines) if line.text.strip()]
    if not lines:
        return []
    body_right = [line.bbox[2] for line in lines if _is_body(line, stats.body_size)]
    page_right = (
        _right_edge(body_right, stats.right_edge) if len(body_right) >= 3 else stats.right_edge
    )
    labels = figure_labels(lines, regions or [], stats.body_size, page_right)

    groups: list[tuple[str, int, list[Line]]] = []  # (kind, index of first line, lines)
    for index, line in enumerate(lines):
        kind = "figure" if index in labels else "paragraph"
        if groups and groups[-1][0] == kind:
            members = groups[-1][2]
            if kind == "figure" or _continues(members, line, stats, page_right):
                members.append(line)
                continue
        groups.append((kind, index, [line]))

    blocks: list[RawBlock] = []
    for kind, first, members in groups:
        if kind == "figure":
            blocks.append(_block_from(members, page, spaced=False, role="figure"))
            continue
        size = members[0].size or stats.body_size
        gap_above = members[0].bbox[1] - lines[first - 1].bbox[3] if first else 0.0
        spaced = gap_above > stats.line_gap + config.HEADING_SPACE_ABOVE * size
        blocks.append(_block_from(members, page, spaced))
    return blocks


def figure_regions(rects: list[BBox], page_box: BBox, body_size: float) -> list[BBox]:
    """Group drawing and image rectangles into figure regions.

    Thin rules (underlines, table borders) and page-size frames are ignored; drawings closer
    than a couple of font sizes belong together.
    """
    width, height = page_box[2] - page_box[0], page_box[3] - page_box[1]
    gap = config.FIGURE_MERGE_GAP * body_size
    useful = sorted(
        (
            r
            for r in rects
            if r[2] - r[0] >= 2
            and r[3] - r[1] >= 2
            and (r[2] - r[0]) * (r[3] - r[1]) < 0.5 * width * height
        ),
        key=lambda r: r[1],
    )
    regions: list[list[float]] = []
    for r in useful:
        for region in regions:
            if (
                r[0] <= region[2] + gap
                and region[0] <= r[2] + gap
                and r[1] <= region[3] + gap
                and region[1] <= r[3] + gap
            ):
                region[0], region[1] = min(region[0], r[0]), min(region[1], r[1])
                region[2], region[3] = max(region[2], r[2]), max(region[3], r[3])
                break
        else:
            regions.append(list(r))
    merged = True
    while merged:
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i], regions[j]
                if (
                    a[0] <= b[2] + gap
                    and b[0] <= a[2] + gap
                    and a[1] <= b[3] + gap
                    and b[1] <= a[3] + gap
                ):
                    regions[i] = [
                        min(a[0], b[0]),
                        min(a[1], b[1]),
                        max(a[2], b[2]),
                        max(a[3], b[3]),
                    ]
                    del regions[j]
                    merged = True
                    break
            if merged:
                break
    return [(r[0], r[1], r[2], r[3]) for r in regions]
