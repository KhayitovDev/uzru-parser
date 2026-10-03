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
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import config
from .structure import RawBlock
from .text import ends_with_abbreviation, numbering_info

BBox = tuple[float, float, float, float]

_ENDS_SENTENCE = re.compile(r"[.!?:…][\"'»”’)\]]*\s*$")
_NUMBER_TOKEN = re.compile(
    r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[IVXLC]{1,6}\.?|(?:\d{1,3}|[IVXLC]{1,6})\s*-\s*[^\W\d_]+[.:]?)\s*$"
)
#: A list marker standing alone: "1)", "a)", "•", "✓", "-".
_MARKER_TOKEN = re.compile(r"^\s*(?:\d{1,3}[.)]|[^\W\d_]\)|[•·▪●○■◦–—\-*✓✔➢➤►▶◆❖□])\s*$")
_LEADER_END = re.compile(r"(?:\.{3,}|…)\s*$")
_MATH_OPERATOR = re.compile(r"[=<>±×÷∑∏√∫≈≠≤≥]")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
FIGURE_SEPARATOR = " | "
RIGHT_EDGE_PERCENTILE = 0.9
LEFT_EDGE_PERCENTILE = 0.1


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
    """Put a lone section number ("1.1.", "II-BOB") or list marker ("1)", "•", "✓") and its
    text back on one line, a contents page number back after its leader ("Title …" +
    "7"), and an inline formula fragment back into the sentence on its row."""
    lines = _attach_inline_formulas(lines)
    merged: list[Line] = []
    formula_end = False  # the last merged line ends with a formula fragment
    for line in lines:
        previous = merged[-1] if merged else None
        if previous is not None and _same_row(previous, line):
            number_then_title = (
                _NUMBER_TOKEN.match(previous.text) is not None
                or _MARKER_TOKEN.match(previous.text) is not None
            )
            size = previous.size or line.size or 10.0
            near = line.bbox[0] - previous.bbox[2] <= config.INLINE_FORMULA_GAP * size
            debris = is_debris(line.text)
            inline_formula = near and (formula_end or is_debris(previous.text) or debris)
            leader_then_page = _LEADER_END.search(previous.text) and _PAGE_NUMBER.match(line.text)
            if number_then_title or leader_then_page or inline_formula:
                merged[-1] = _join_row(previous, line)
                formula_end = debris
                continue
        merged.append(line)
        formula_end = is_debris(line.text)
    return merged


def _attach_inline_formulas(lines: list[Line]) -> list[Line]:
    """Formula fragments (raised or lowered pieces: sub- and superscripts, operators) whose
    middle lies within a text line's height, give or take half a line, and that sit beside the
    line's pieces join that line, all pieces in reading order (x)."""
    debris = [is_debris(line.text) for line in lines]
    if not any(debris):
        return lines
    taken: set[int] = set()
    rows: dict[int, list[int]] = {}
    for index, line in enumerate(lines):
        if debris[index] or index in taken:
            continue
        height = line.bbox[3] - line.bbox[1]
        top, bottom = line.bbox[1] - 0.5 * height, line.bbox[3] + 0.5 * height
        members = [index]
        for other, piece in enumerate(lines):
            if other == index or other in taken:
                continue
            middle = (piece.bbox[1] + piece.bbox[3]) / 2
            same_band = top <= middle <= bottom
            side_text = not debris[other] and (_same_row(line, piece) or _same_row(piece, line))
            if same_band and (debris[other] or side_text):
                members.append(other)
        if len(members) > 1 and any(debris[m] for m in members) and _beside(lines, members):
            rows[index] = members
            taken.update(members)
    if not rows:
        return lines
    out: list[Line] = []
    for index, line in enumerate(lines):
        if index in rows:
            pieces = sorted((lines[m] for m in rows[index]), key=lambda piece: piece.bbox[0])
            joined = pieces[0]
            for piece in pieces[1:]:
                joined = _join_row(joined, piece)
            out.append(joined)
        elif index not in taken:
            out.append(line)
    return out


def _beside(lines: list[Line], members: list[int]) -> bool:
    """The pieces stand side by side with small gaps (one printed line), none overlapping."""
    pieces = sorted((lines[m] for m in members), key=lambda piece: piece.bbox[0])
    size = max((piece.size or 10.0) for piece in pieces)
    return all(
        -1.0 <= b.bbox[0] - a.bbox[2] <= config.INLINE_FORMULA_GAP * size
        for a, b in zip(pieces, pieces[1:], strict=False)
    )


def join_spread_lines(lines: list[Line], right_edge: float) -> list[Line]:
    """Put a justified line back together when the PDF stores its widely spaced words as
    separate lines: words of one size on one row that together run from the text's
    left edge to ``right_edge``, with running text (or another such row) right above or
    below. Diagram boxes hold several words each and stay apart."""
    if len(lines) < 2:
        return lines
    left_edge = min(line.bbox[0] for line in lines)

    def starts_at_edge(line: Line) -> bool:
        return line.bbox[0] <= left_edge + config.PARAGRAPH_MAX_INDENT * (line.size or 10.0)

    rows: list[list[Line]] = []
    for line in lines:
        row = rows[-1] if rows else None
        if row is not None and all(_on_row(other, line) for other in row):
            row.append(line)
        else:
            rows.append([line])
    ordered = [sorted(row, key=lambda line: line.bbox[0]) for row in rows]

    def spread(row: list[Line]) -> bool:
        size = row[0].size or 10.0
        # The first piece may carry a list marker or normally spaced words, the last one the
        # line's tail; the stretched middle holds one word per piece.
        multi_word = sum(1 for piece in row[1:-1] if len(piece.text.split()) > 1)
        return (
            len(row) > 1
            and _same_size(row)
            and multi_word == 0
            and all(
                b.bbox[0] - a.bbox[2] <= config.SPREAD_LINE_GAP * size
                for a, b in zip(row, row[1:], strict=False)
            )
            and starts_at_edge(row[0])
            and row[-1].bbox[2] >= right_edge - config.PARAGRAPH_SHORT_LINE * size
        )

    candidates = [spread(row) for row in ordered]

    def running_text_beside(index: int) -> bool:
        """A text line or another spread row of the same size directly above or below."""
        row = ordered[index]
        size = row[0].size or 10.0
        for other in (index - 1, index + 1):
            if not 0 <= other < len(rows):
                continue
            first = ordered[other][0]
            gap = max(first.bbox[1] - row[0].bbox[3], row[0].bbox[1] - first.bbox[3])
            text_line = len(rows[other]) == 1 and starts_at_edge(first)
            if _same_size([first, row[0]]) and gap <= size and (text_line or candidates[other]):
                return True
        return False

    joined: list[Line] = []
    for index, row in enumerate(rows):
        if candidates[index] and running_text_beside(index):
            pieces = ordered[index]
            line = pieces[0]
            for piece in pieces[1:]:
                line = _join_row(line, piece)
            # A bold lead word does not make the whole rebuilt line bold.
            line.bold = sum(p.bold * p.chars for p in pieces) / max(1, line.chars)
            joined.append(line)
        else:
            joined.extend(row)
    return joined


def _same_size(lines: list[Line]) -> bool:
    """Font sizes within ``SAME_SIZE_TOLERANCE``: a bold run may report a slightly other size."""
    sizes = [line.size or 0.0 for line in lines]
    return max(sizes) - min(sizes) <= config.SAME_SIZE_TOLERANCE * max(sizes)


def _on_row(a: Line, b: Line) -> bool:
    """``b`` sits on the same printed row as ``a``, beside it."""
    top, bottom = max(a.bbox[1], b.bbox[1]), min(a.bbox[3], b.bbox[3])
    smaller = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]) or 1.0
    beside = b.bbox[0] >= a.bbox[2] - 1.0 or b.bbox[2] <= a.bbox[0] + 1.0
    return bottom - top >= 0.5 * smaller and beside


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

    def paragraph_tail(index: int) -> bool:
        """A short line right under a full line that runs on into it ends that paragraph."""
        if index == 0:
            return False
        above, line = lines[index - 1], lines[index]
        size = line.size or body_size
        gap = line.bbox[1] - above.bbox[3]
        runs_on = not _ends_sentence(above.text) or _starts_lowercase(line.text)
        return (
            full(above)
            and abs((above.size or body_size) - size) <= 0.5
            and -0.5 * size <= gap <= size
            and runs_on
        )

    tails = {i for i in range(len(lines)) if paragraph_tail(i)}
    labels: set[int] = set()
    candidates = [
        i for i, line in enumerate(lines) if _is_label(line) and not full(line) and i not in tails
    ]
    margin = config.FIGURE_LABEL_MARGIN * body_size
    for x0, y0, x1, y1 in regions:
        region = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
        inside = [i for i in candidates if _center_in(lines[i].bbox, region)]
        if len(inside) >= config.FIGURE_MIN_LABELS:
            labels.update(inside)

    run: list[int] = []
    for i, line in enumerate([*lines, None]):
        if (
            line is not None
            and _is_free_label(line, body_size)
            and not full(line)
            and i not in tails
        ):
            run.append(i)
            continue
        if len(run) >= config.FIGURE_MIN_LABELS_WITHOUT_DRAWING:
            labels.update(run)
        run = []
    return labels


def _continues(paragraph: list[Line], line: Line, stats: LayoutStats, page_right: float) -> bool:
    """Does ``line`` belong to the paragraph whose lines are ``paragraph``?"""
    last, first = paragraph[-1], paragraph[0]
    if (
        line.chars
        and last.chars
        and _style(line) != _style(last)
        and not _after_run_in_lead(paragraph, line)
    ):
        return False
    size = last.size or line.size or stats.body_size
    gap = line.bbox[1] - last.bbox[3]
    if gap < -0.5 * size or gap > stats.line_gap + config.PARAGRAPH_GAP_SLACK * size:
        return False
    if not _overlaps_horizontally(line.bbox, last.bbox):
        return False
    if numbering_info(line.text) and not _dash_in_sentence(paragraph, line, page_right):
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


def _left_edge(lines: list[Line], body_size: float) -> float:
    """Left edge of the text: a low percentile of body lines' starts, or of all lines on a page
    set in another size (front matter, an annotation)."""
    body = [line.bbox[0] for line in lines if _is_body(line, body_size)]
    starts = sorted(
        body if len(body) >= config.MIN_COLUMN_LINES else [line.bbox[0] for line in lines]
    )
    return starts[int(LEFT_EDGE_PERCENTILE * (len(starts) - 1))] if starts else 0.0


def _dash_in_sentence(paragraph: list[Line], line: Line, page_right: float) -> bool:
    """A line opening with a dash continues the sentence ("... uchun 2" + "– semestrda") when
    the line above runs to the right edge without ending a sentence or a lead-in, the dash sits
    at the paragraph's left edge, and the paragraph is not a dash list itself."""
    last, first = paragraph[-1], paragraph[0]
    if line.text.lstrip()[:1] not in "–—-" or numbering_info(first.text):
        return False
    size = last.size or line.size or 10.0
    full = last.bbox[2] >= page_right - config.PARAGRAPH_SHORT_LINE * size
    left = min(other.bbox[0] for other in paragraph)
    aligned = line.bbox[0] <= left + config.PARAGRAPH_ALIGN_TOLERANCE * size
    return full and aligned and last.text.rstrip()[-1:] not in ".:;!?"


def _after_run_in_lead(paragraph: list[Line], line: Line) -> bool:
    """``line`` continues a first line that opens with a bold term ("**Term** – bu ..."):
    same size, the bold stops before the first line ends, and the sentence runs on."""
    first = paragraph[0]
    return (
        len(paragraph) == 1
        and _size_key(first.size) == _size_key(line.size)
        and config.BOLD_SHARE <= first.bold < config.RUN_IN_BOLD_SHARE
        and line.bold < config.BOLD_SHARE
        and (_starts_lowercase(line.text) or not _ends_sentence(first.text))
    )


def _starts_next_paragraph(
    members: list[Line], line: Line, left_edge: float, stats: LayoutStats, page_right: float
) -> bool:
    """A finished one-line paragraph took the indented first line of the next paragraph as
    its second line: ``line`` goes back to the left edge and continues that indented line."""
    if len(members) != 2:
        return False
    first, second = members
    size = second.size or stats.body_size
    tolerance = config.PARAGRAPH_ALIGN_TOLERANCE * size
    finished = _ends_sentence(first.text) or first.text.rstrip().endswith(";")
    return (
        finished
        and second.bbox[0] > left_edge + tolerance
        and abs(line.bbox[0] - left_edge) <= tolerance
        and _continues([second], line, stats, page_right)
    )


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

    def right_edge() -> float:
        body_right = [line.bbox[2] for line in lines if _is_body(line, stats.body_size)]
        if len(body_right) < 3:
            return stats.right_edge
        return _right_edge(body_right, stats.right_edge)

    lines = join_spread_lines(lines, right_edge())
    page_right = right_edge()
    labels = figure_labels(lines, regions or [], stats.body_size, page_right)

    left_edge = _left_edge(lines, stats.body_size)

    groups: list[tuple[str, int, list[Line]]] = []  # (kind, index of first line, lines)
    for index, line in enumerate(lines):
        kind = "figure" if index in labels else "paragraph"
        if groups and groups[-1][0] == kind:
            members = groups[-1][2]
            if kind == "figure" or _continues(members, line, stats, page_right):
                members.append(line)
                continue
            if kind == "paragraph" and _starts_next_paragraph(
                members, line, left_edge, stats, page_right
            ):
                groups.append((kind, index - 1, [members.pop(), line]))
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
    _mark_figure_text(blocks, regions or [])
    return blocks


def is_debris(text: str) -> bool:
    """A formula or chart fragment: a few characters without a real word ("=", "p&", "G &",
    "0"), or a math operator with hardly any real words."""
    flat = " ".join(text.split())
    if not flat:
        return False
    words = [w for w in re.findall(r"[^\W\d_]+", flat) if len(w) >= 4]
    if len(flat) <= config.DEBRIS_CHARS and not re.search(r"[^\W\d_]{3,}", flat):
        return True
    code = flat.endswith(":") or any(c in flat for c in "[]{};")  # "def f(x=[]):"
    return bool(_MATH_OPERATOR.search(flat)) and len(words) < config.FORMULA_MAX_WORDS and not code


def group_formula_debris(blocks: list[RawBlock]) -> list[RawBlock]:
    """Formula and chart fragments become ``role="formula"`` blocks; a run of them is one
    block, so a math page does not fall apart into hundreds of one-symbol paragraphs. Runs
    after page numbers are removed and contents pages marked."""
    grouped: list[RawBlock] = []
    for block in blocks:
        plain = block.role is None and block.rows is None and not block.footnote
        if not plain or not is_debris(block.text):
            grouped.append(block)
            continue
        previous = grouped[-1] if grouped else None
        if previous is not None and previous.role == "formula" and previous.page == block.page:
            previous.text = f"{previous.text} {' '.join(block.text.split())}"
            previous.original = f"{previous.original}\n{block.original}"
            if previous.bbox and block.bbox:
                previous.bbox = (
                    min(previous.bbox[0], block.bbox[0]),
                    min(previous.bbox[1], block.bbox[1]),
                    max(previous.bbox[2], block.bbox[2]),
                    max(previous.bbox[3], block.bbox[3]),
                )
            continue
        block.text = " ".join(block.text.split())
        block.role = "formula"
        grouped.append(block)
    return _absorb_figure_fragments(grouped)


def _absorb_figure_fragments(blocks: list[RawBlock]) -> list[RawBlock]:
    """A short fragment between two formula or figure blocks, with no body text between them,
    is one of their labels ("B FAM" between parts of a chart): it joins the block before it."""
    out: list[RawBlock] = []
    for index, block in enumerate(blocks):
        previous = out[-1] if out else None
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        between = (
            previous is not None
            and following is not None
            and previous.role in ("formula", "figure")
            and following.role in ("formula", "figure")
            and previous.page == block.page == following.page
        )
        fragment = (
            block.role is None
            and block.rows is None
            and not block.footnote
            and len(block.text.split()) <= config.FIGURE_FREE_LABEL_WORDS
            and not _ends_sentence(block.text)
        )
        both_formula = (
            previous is not None
            and previous.role == block.role == "formula"
            and previous.page == block.page
        )
        if previous is not None and ((between and fragment) or both_formula):
            previous.text = f"{previous.text} {' '.join(block.text.split())}"
            continue
        out.append(block)
    return out


def _mark_figure_text(blocks: list[RawBlock], regions: list[BBox]) -> None:
    """Text inside a drawing that holds figure labels belongs to the figure (a chart's title or
    axis name): it is never a heading."""
    for region in regions:
        inside = [b for b in blocks if b.bbox and _center_in(b.bbox, region)]
        if any(b.role == "figure" for b in inside):
            for block in inside:
                if block.role != "figure":
                    block.in_figure = True


def figure_regions(
    rects: list[BBox], page_box: BBox, body_size: float, lines: Sequence[Line] = ()
) -> list[BBox]:
    """Group drawing and image rectangles into figure regions.

    Thin rules (underlines, table borders), page-size frames and line shading (a rectangle
    about one line tall behind a single row of text, a common Word-export artifact) are
    ignored; drawings closer than a couple of font sizes belong together. A region holding
    mostly running text is a shaded or framed text area, not a figure.
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
            and not _is_shading(r, lines, body_size)
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
    boxes = [(r[0], r[1], r[2], r[3]) for r in regions]
    return [box for box in boxes if not _holds_running_text(box, lines, body_size)]


def _is_shading(rect: BBox, lines: Sequence[Line], body_size: float) -> bool:
    """A filled band about one line tall behind one row of text."""
    size = body_size or 10.0
    if rect[3] - rect[1] > config.SHADING_MAX_HEIGHT * size:
        return False
    tops = [line.bbox[1] for line in lines if _center_in(line.bbox, rect)]
    return bool(tops) and max(tops) - min(tops) < 0.5 * size


def _holds_running_text(region: BBox, lines: Sequence[Line], body_size: float) -> bool:
    """Most lines inside are long lines of body text: a shaded or framed text area."""
    inside = [line for line in lines if _center_in(line.bbox, region)]
    if len(inside) < config.MIN_COLUMN_LINES:
        return False
    width = region[2] - region[0]
    running = sum(
        1
        for line in inside
        if _is_body(line, body_size)
        and line.bbox[2] - line.bbox[0] >= config.FULL_LINE_SHARE * width
        and len(line.text.split()) >= config.FIGURE_FREE_LABEL_WORDS + 1
    )
    return running >= config.FIGURE_TEXT_SHARE * len(inside)
