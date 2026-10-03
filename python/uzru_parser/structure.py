"""Turn raw extracted blocks into typed document blocks.

Heading decisions use sources in this order of trust: PDF bookmarks, the document's own
contents page, numbering ("3-MAVZU", "5.3."), then font style. Levels come from the kind of
heading (chapter word, "N.N", "N.N.N", font size) so a child is never ranked above its parent.
"""

from __future__ import annotations

import bisect
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import config
from .models import Block, BlockType, LanguageInfo
from .text import (
    CleanStats,
    Hyphenator,
    clean,
    detect_language,
    ends_with_abbreviation,
    is_known_word,
    numbering_info,
)

CELL_SEPARATOR = " | "
SENTENCE_END = ".?!:…;"
LIST_KINDS = ("bullet", "ordered")
SECTION_KINDS = ("decimal", "keyword")
#: Material set apart from the running text: a sentence may run on across it.
OUT_OF_FLOW_ROLES = ("figure", "formula")

PLAN_LINE = re.compile(rf"^\s*(?:{'|'.join(config.PLAN_WORDS)})\s*:", re.IGNORECASE)
FOOTNOTE_NUMBER = re.compile(r"^\s*(\d{1,3})(?:\s+|(?=[^\W\d_]))")
QUOTE_MARK = re.compile("[“”„«»]")
#: End of a possible "5-modda." / "Статья 5." marker: a full stop followed by text.
MARKER_END = re.compile(r"\.\s+(?=\S)")
LEADING_NUMBER = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3})*)")
LEADING_ROMAN = re.compile(r"^\s*([IVXLC\u0406\u0425]{1,6})\b")
TOC_ENTRY = re.compile(r"^(?P<title>.*?)(?:\s*(?:…|\.{3,}))?\s*(?P<page>\d{1,4})?\s*$")
REAL_WORD = re.compile(r"[^\W\d_]{3,}")
HEADING_WORD = re.compile(rf"[^\W\d_]{{{config.HEADING_MIN_WORD_LETTERS},}}")
FORMULA_OPERATOR = re.compile(r"[=<>±×÷∑∏√∫≈≠≤≥]")
#: "Key terms: ...": a label of a few words and a colon opening a line.
LABEL_START = re.compile(r"^\s*([^\W\d_]+(?:\s+[^\W\d_]+){0,3})\s*:(?:\s|$)")
#: "IV. Title": a section number, never a list item.
ROMAN_SECTION = re.compile(r"^\s*[IVXLC\u0406\u0425]{1,6}\.\s")
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "\u0406": 1, "\u0425": 10}

Repair = Callable[[str], str]


@dataclass
class RawBlock:
    """A block as produced by a format reader, before any interpretation.

    ``heading_level``, ``list_item`` and ``rows`` let a reader state what it already knows
    (for example from DOCX styles or detected PDF tables); the rest is inferred.
    ``role`` marks material that is not body text (``toc``, ``title_page``, ``back_matter``,
    ``figure``), ``footnote`` a footnote entry, and ``footnote_refs`` the reference marks that
    were removed from the text. ``original`` is the text as extracted, ``spaced`` says the
    block has clearly more space above it than a normal line, ``in_figure`` that it lies
    inside a figure (a drawing with labels).
    """

    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None
    font_size: float | None = None
    bold: float = 0.0  # share of characters set in a bold face
    heading_level: int | None = None
    list_item: bool = False
    rows: list[list[str]] | None = None
    role: str | None = None
    footnote: bool = False
    footnote_refs: list[str] = field(default_factory=list)
    original: str = ""
    spaced: bool = False
    heading_source: str | None = None
    in_figure: bool = False  # lies inside a drawing together with its labels


@dataclass
class OutlineEntry:
    """One PDF bookmark: level, cleaned title and 1-based page."""

    level: int
    title: str
    page: int


@dataclass
class _Title:
    key: str
    source: str  # "bookmarks" or "contents"
    level: int | None
    page: int | None


@dataclass
class _Heading:
    source: str  # bookmarks | contents | numbering | font | style
    kind: tuple[object, ...]  # level class: ("kw", rank), ("dec", depth), ("font", size, bold)
    size: float
    level: int | None = None  # fixed level (bookmarks, DOCX styles)


def build_blocks(
    raw_blocks: list[RawBlock],
    outline: list[OutlineEntry] | None = None,
    compounds: Iterable[str] = (),
    stats: CleanStats | None = None,
    text_is_clean: bool = False,
    page_layout: bool = True,
) -> list[Block]:
    """Classify raw blocks into headings, lists, tables, footnotes and paragraphs.

    ``text_is_clean`` says the reader already cleaned and hyphen-repaired block text (PDF);
    table cells are always cleaned here. Without ``page_layout`` (DOCX) a sentence broken
    over two paragraphs is joined again, not only one broken by a page break.
    """
    repair = Hyphenator(sorted(compounds)).repair
    titles = _TitleIndex(outline or [], raw_blocks)
    raws = [part for raw in raw_blocks for part in _split_raw(raw, titles)]
    body_size = body_font_size(raws) or 0.0
    prepared = [(raw, _clean(raw, repair, stats, text_is_clean)) for raw in raws]
    headings = _decide_headings(prepared, body_size, titles, _quoted(prepared))
    _assign_levels(headings, prepared)

    blocks: list[Block] = []
    extended: list[Block] = []
    previous: RawBlock | None = None
    for (raw, text), heading in zip(prepared, headings, strict=True):
        if not text:
            continue
        if raw.rows is not None:
            blocks.append(_table_block(raw, raw.rows, repair, stats))
        elif raw.footnote:
            blocks.append(_footnote_block(raw, text))
        elif heading is not None:
            # A reader without page layout (DOCX) gives each paragraph on its own: two
            # headings in a row are two headings.
            if (
                page_layout
                and previous is not None
                and _continues_heading(blocks[-1], previous, raw, text)
            ):
                blocks[-1].text = f"{blocks[-1].text} {_flatten(text)}"
                blocks[-1].language = detect_language(blocks[-1].text)
            else:
                level = min(heading.level or 1, config.MAX_LEVEL)
                block = _block(BlockType.HEADING, _flatten(text), raw, level)
                block.extra["heading_source"] = heading.source
                blocks.append(block)
        elif (
            previous is not None
            and _continues_heading(blocks[-1], previous, raw, text)
            and _title_runs_on(blocks[-1].text, previous, raw, text)
        ):
            blocks[-1].text = f"{blocks[-1].text} {_flatten(text)}"
            blocks[-1].language = detect_language(blocks[-1].text)
        elif items := _list_items(text, raw.list_item):
            if _append_list(blocks, items, raw):
                extended.append(blocks[-1])
        else:
            blocks.append(_block(BlockType.PARAGRAPH, _flatten(text), raw))
        previous = raw
    for block in {id(b): b for b in extended}.values():  # first item alone decided it
        block.language = detect_language(block.text)
    blocks = _join_split_paragraphs(blocks, repair, page_layout)
    _inherit_short_languages(blocks)
    return blocks


def body_font_size(raw_blocks: list[RawBlock]) -> float | None:
    """The most common font size, weighted by text length: the body text size."""
    weights: Counter[float] = Counter()
    for raw in raw_blocks:
        if raw.font_size and raw.rows is None and not raw.footnote:
            weights[_size_key(raw.font_size)] += len(raw.text)
    return weights.most_common(1)[0][0] if weights else None


def _clean(raw: RawBlock, repair: Repair, stats: CleanStats | None, done: bool = False) -> str:
    if raw.rows is not None:
        return _rows_text(_clean_rows(raw.rows, repair, stats))
    return raw.text if done else clean(repair(raw.text), stats)


def _flatten(text: str) -> str:
    return " ".join(text.split())


def _size_key(size: float) -> float:
    return round(size * 2) / 2


def _key(text: str) -> str:
    """Comparison key for titles: lowercase letters and digits only."""
    return "".join(c for c in text.lower() if c.isalnum())


# --- Tables -------------------------------------------------------------------------------


def _clean_rows(
    rows: list[list[str]], repair: Repair, stats: CleanStats | None = None
) -> list[list[str]]:
    """Normalize cells, merge a header split over rows, drop empty rows and columns."""
    cleaned = [[_flatten(clean(repair(cell or ""), stats)) for cell in row] for row in rows]
    cleaned = _blank_repeated_header_cells(_merge_header_rows(cleaned))
    cleaned = [row for row in cleaned if any(row)]
    used = [
        index
        for index in range(max((len(row) for row in cleaned), default=0))
        if any(index < len(row) and row[index] for row in cleaned)
    ]
    return [[row[index] if index < len(row) else "" for index in used] for row in cleaned]


def _starts_lowercase(text: str) -> bool:
    letter = next((c for c in text if c.isalpha()), "")
    return letter.islower()


def _merge_header_rows(rows: list[list[str]]) -> list[list[str]]:
    """Join header rows that are one header written over several lines ("Ish" / "bosqichlari").

    The continuation row has fewer filled cells than the row above, all starting lowercase;
    an ordinary data row fills its cells.
    """
    rows = [list(row) for row in rows]
    index = 0
    while index + 1 < min(len(rows), config.HEADER_ROWS):
        upper, lower = rows[index], rows[index + 1]
        filled = [c for c, cell in enumerate(lower) if cell]
        fewer = len(filled) < sum(1 for cell in upper if cell)
        continues = (
            bool(filled)
            and fewer
            and all(_starts_lowercase(lower[c]) and c < len(upper) and upper[c] for c in filled)
        )
        if not continues:
            index += 1
            continue
        for c in filled:
            upper[c] = f"{upper[c]} {lower[c]}"
        del rows[index + 1]
    return rows


def _blank_repeated_header_cells(rows: list[list[str]]) -> list[list[str]]:
    """A merged header cell is extracted once per spanned column; keep the first copy."""
    for row in rows[: config.HEADER_ROWS]:
        for c in range(len(row) - 1, 0, -1):
            if row[c] and row[c] == row[c - 1] and any(ch.isalpha() for ch in row[c]):
                row[c] = ""
    return rows


def _rows_text(rows: list[list[str]]) -> str:
    return "\n".join(CELL_SEPARATOR.join(cell for cell in row if cell) for row in rows)


def _table_block(
    raw: RawBlock, rows: list[list[str]], repair: Repair, stats: CleanStats | None
) -> Block:
    rows = _clean_rows(rows, repair, stats)
    block = _block(BlockType.TABLE, _rows_text(rows), raw)
    block.extra["rows"] = rows
    return block


# --- Blocks -------------------------------------------------------------------------------


def _block(block_type: BlockType, text: str, raw: RawBlock, level: int | None = None) -> Block:
    block = Block(
        type=block_type,
        text=text,
        raw_text=raw.original or raw.text,
        page=raw.page,
        bbox=raw.bbox,
        level=level,
        language=detect_language(text),
    )
    if raw.role:
        block.extra["role"] = raw.role
    if raw.footnote_refs:
        block.extra["footnote_refs"] = list(raw.footnote_refs)
    return block


def _footnote_block(raw: RawBlock, text: str) -> Block:
    """Footnote number in ``extra["number"]``, its text without the number."""
    flat = _flatten(text)
    match = FOOTNOTE_NUMBER.match(flat)
    block = _block(BlockType.FOOTNOTE, flat[match.end() :] if match else flat, raw)
    if match:
        block.extra["number"] = match.group(1)
    return block


def _list_items(text: str, forced: bool) -> list[str]:
    """Split a block into list items, or return ``[]`` when it is not a list."""
    if forced:
        return [_flatten(text)]
    items: list[str] = []
    for line in text.split("\n"):
        if _is_item_marker(numbering_info(line)) and not ROMAN_SECTION.match(line):
            items.append(line.strip())
        elif items:
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            return []
    return items


def _is_item_marker(marker: tuple[str, int] | None) -> bool:
    """Bullets, "a)", "1)" and plain "1." start list items."""
    return marker is not None and (
        marker[0] in LIST_KINDS or (marker[0] == "decimal" and marker[1] == 1)
    )


def _append_list(blocks: list[Block], items: list[str], raw: RawBlock) -> bool:
    """Add list items, to the list just before when there is one; ``True`` if extended."""
    previous = blocks[-1] if blocks else None
    same_role = previous is not None and previous.extra.get("role") == raw.role
    if previous is not None and previous.type is BlockType.LIST and same_role:
        previous.extra["items"].extend(items)
        previous.text = "\n".join(previous.extra["items"])
        previous.raw_text = f"{previous.raw_text}\n{raw.original or raw.text}"
        return True
    block = _block(BlockType.LIST, "\n".join(items), raw)
    block.extra["items"] = list(items)
    blocks.append(block)
    return False


# --- Known titles (bookmarks, contents page) ----------------------------------------------


class _TitleIndex:
    """Heading titles the document states itself: bookmarks, else its contents page."""

    def __init__(self, outline: list[OutlineEntry], raw_blocks: list[RawBlock]) -> None:
        if outline:
            self.titles = [
                _Title(_key(e.title), "bookmarks", e.level, e.page)
                for e in outline
                if _key(e.title)
            ]
        else:
            self.titles = [
                _Title(key, "contents", None, None)
                for key in _contents_titles(raw_blocks)
                if len(key) >= 4
            ]
        self.by_start: dict[str, list[_Title]] = defaultdict(list)
        for title in self.titles:
            self.by_start[title.key[:4]].append(title)

    def __bool__(self) -> bool:
        return bool(self.titles)

    def match(self, text: str, page: int) -> _Title | None:
        """The known title that ``text`` is (or begins, when the title wraps on)."""
        key = _key(text)
        for title in self.by_start.get(key[:4], []):
            if title.page is not None and abs(title.page - page) > 1:
                continue
            if key == title.key or (
                title.key.startswith(key) and len(key) >= config.TITLE_MATCH_SHARE * len(title.key)
            ):
                return title
        return None

    def title_end(self, lines: list[str], page: int) -> int:
        """Number of leading ``lines`` that form a known title, if the block goes on after it."""
        for end in range(1, min(len(lines) - 1, config.MAX_TITLE_LINES) + 1):
            key = _key(" ".join(lines[:end]))
            if any(
                t.key == key and (t.page is None or abs(t.page - page) <= 1)
                for t in self.by_start.get(key[:4], [])
            ):
                return end
        return 0


def _contents_titles(raw_blocks: list[RawBlock]) -> list[str]:
    """Title keys of the contents page entries ("1.1. Title … 7", wrapped titles joined)."""
    keys: list[str] = []
    pending = ""
    for raw in raw_blocks:
        if raw.role != "toc":
            continue
        for line in raw.text.split("\n"):
            match = TOC_ENTRY.match(line.strip())
            if not match or not any(c.isalpha() for c in line):
                continue
            pending = f"{pending} {match.group('title')}".strip()
            if match.group("page"):
                keys.append(_key(pending))
                pending = ""
    if pending:
        keys.append(_key(pending))
    return keys


# --- Splitting blocks ---------------------------------------------------------------------


def _piece(raw: RawBlock, lines: list[str], **changes: object) -> RawBlock:
    """A part of ``raw`` with the same geometry and style."""
    part = RawBlock(
        text="\n".join(lines),
        page=raw.page,
        bbox=raw.bbox,
        font_size=raw.font_size,
        bold=raw.bold,
        spaced=raw.spaced,
    )
    for name, value in changes.items():
        setattr(part, name, value)
    return part


def _split_raw(raw: RawBlock, titles: _TitleIndex) -> list[RawBlock]:
    """Separate a title from its plan ("Reja:") or body, and list items from what follows."""
    fixed = raw.rows is not None or raw.role or raw.footnote or raw.list_item
    if fixed or raw.heading_level is not None:
        return [raw]
    groups = _line_groups(raw.text)
    if len(groups) > 1:
        parts = [_piece(raw, group, **_lone_title(group)) for group in groups]
        parts[0].footnote_refs = raw.footnote_refs
        parts[0].original = raw.original
        return [piece for part in parts for piece in _split_raw(part, titles)]
    lines = groups[0] if groups else []
    if lines and PLAN_LINE.match(lines[0]):
        return _plan_blocks(raw, lines)
    if len(lines) < 2:
        return _split_untitled_article(raw, lines) or [raw]
    if titles and (end := titles.title_end(lines, raw.page)):
        return [_piece(raw, lines[:end]), *_split_raw(_piece(raw, lines[end:]), titles)]
    if cut := _list_end(lines):
        parts = [_piece(raw, lines[:cut]), _piece(raw, lines[cut:])]
        parts[0].footnote_refs = raw.footnote_refs
        return [piece for part in parts for piece in _split_raw(part, titles)]
    first = numbering_info(lines[0])
    if first is None or first[0] not in SECTION_KINDS:
        return [raw]

    plan_at = next((i for i, line in enumerate(lines) if PLAN_LINE.match(line)), None)
    if plan_at:
        return [_piece(raw, lines[:plan_at]), *_plan_blocks(raw, lines[plan_at:])]
    if not _may_start_with_title(first, lines):
        return [raw]
    split_at = _title_end(lines)
    if split_at:
        title = _piece(raw, lines[:split_at], heading_level=first[1], heading_source="numbering")
        return [title, _piece(raw, lines[split_at:])]
    return _split_untitled_article(raw, lines) or [raw]


def _split_untitled_article(raw: RawBlock, lines: list[str]) -> list[RawBlock] | None:
    """ "5-modda. Ushbu Qonun ... kuchga kiradi." as the heading "5-modda." and its text."""
    if not lines:
        return None
    first = lines[0]
    for match in MARKER_END.finditer(first):
        marker = first[: match.start() + 1].strip()
        if len(marker.split()) > config.MAX_KEYWORD_MARKER_WORDS:
            return None
        numbering = numbering_info(marker)
        if numbering is None or numbering[0] != "keyword":
            continue
        body = [first[match.end() :], *lines[1:]]
        if not _is_article_text(_flatten(" ".join(body))):
            return None
        heading = _piece(raw, [marker], heading_level=numbering[1], heading_source="numbering")
        return [heading, _piece(raw, body)]
    return None


def _is_article_text(text: str) -> bool:
    """Text after an article number that is the article itself, not its title."""
    if not text or _uppercase(text):
        return False
    long_sentence = text[-1] == "." and len(text.split()) > config.MAX_TITLE_WORDS
    return text[-1] in ":;" or long_sentence


def _line_groups(text: str) -> list[list[str]]:
    """Lines of ``text`` separated by blank lines."""
    groups: list[list[str]] = [[]]
    for line in text.split("\n"):
        if line.strip():
            groups[-1].append(line)
        elif groups[-1]:
            groups.append([])
    return [group for group in groups if group]


def _lone_title(group: list[str]) -> dict[str, object]:
    """A single numbered line set apart by blank lines, e.g. "1.1. Title", is a title."""
    if len(group) != 1:
        return {}
    marker = numbering_info(group[0])
    is_section = marker is not None and (marker[0] == "keyword" or marker[1] >= 2)
    title_like = group[0].strip()[-1] not in SENTENCE_END + ","
    if marker and is_section and title_like and len(group[0]) <= config.MAX_HEADING_CHARS:
        return {"heading_level": marker[1], "heading_source": "numbering"}
    return {}


def _list_end(lines: list[str]) -> int:
    """Index of the first numbered section line after list items, or 0.

    "- item" followed by "3.3. Next section" is a list and a new paragraph, not one item.
    """
    if not _is_item_marker(numbering_info(lines[0])):
        return 0
    for index, line in enumerate(lines[1:], start=1):
        marker = numbering_info(line)
        if marker and marker[0] in SECTION_KINDS and not _is_item_marker(marker):
            return index
    return 0


def _may_start_with_title(first: tuple[str, int], lines: list[str]) -> bool:
    """A "1." line is a list item, and several numbered lines are plan items, not a title."""
    kind, depth = first
    numbered_lines = sum(1 for line in lines if numbering_info(line))
    return numbered_lines == 1 and (kind == "keyword" or depth >= 2)


def _plan_blocks(raw: RawBlock, lines: list[str]) -> list[RawBlock]:
    """ "Reja:" as a paragraph followed by its numbered items as list items."""
    head = lines[0].split(":", 1)
    parts = [_piece(raw, [f"{head[0]}:"])]
    rest = [head[1].strip()] if head[1].strip() else []
    items: list[list[str]] = []
    body = [*rest, *lines[1:]]
    for position, line in enumerate(body):
        if items and _starts_with_label(line):
            parts.extend(_piece(raw, [_flatten(" ".join(item))], list_item=True) for item in items)
            return [*parts, _piece(raw, body[position:])]
        marker = numbering_info(line)
        if marker or not items:
            items.append([line])
        else:
            items[-1].append(line)
    parts.extend(_piece(raw, [_flatten(" ".join(item))], list_item=True) for item in items)
    return parts


def _starts_with_label(line: str) -> bool:
    """The line opens with a capitalized label and a colon ("Key terms: ...")."""
    match = LABEL_START.match(line)
    return match is not None and match.group(1)[0].isupper()


def _title_end(lines: list[str]) -> int:
    """Index where the body starts after a short numbered title, or 0 when there is none.

    A title ends on a line that is clearly shorter than the full-width body lines and is
    followed by a line starting a new sentence.
    """
    longest = max(len(line) for line in lines)
    for end in range(1, min(len(lines) - 1, config.MAX_TITLE_LINES) + 1):
        if lines[end][0].islower():  # the title wraps onto this line
            continue
        title = " ".join(lines[:end])
        ends_like_title = title[-1] not in SENTENCE_END + ","
        short_last_line = len(lines[end - 1]) <= config.TITLE_LINE_RATIO * longest
        starts_sentence = lines[end][0].isupper() or lines[end][0].isdigit()
        fits = len(title) <= config.MAX_HEADING_CHARS
        return end if ends_like_title and short_last_line and starts_sentence and fits else 0
    return 0


# --- Headings -----------------------------------------------------------------------------


def _uppercase(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < config.MIN_UPPERCASE_LETTERS:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= config.UPPERCASE_SHARE


def has_real_words(text: str) -> bool:
    """At least one word of 3+ letters, and mostly letters (not a formula or a label)."""
    letters = sum(1 for c in text if c.isalpha())
    visible = sum(1 for c in text if not c.isspace())
    return bool(REAL_WORD.search(text)) and letters >= config.MIN_LETTER_SHARE * visible


def _is_candidate(raw: RawBlock) -> bool:
    """Only plain body-flow text can be a heading."""
    return not (raw.list_item or raw.footnote or raw.role or raw.rows is not None or raw.in_figure)


def _is_formula(text: str) -> bool:
    """ "M = APS x I": a math operator and hardly any real words."""
    if not FORMULA_OPERATOR.search(text):
        return False
    words = sum(1 for word in text.split() if len(re.sub(r"\W", "", word)) >= 4)
    return words < config.FORMULA_MAX_WORDS


def _signals(text: str, raw: RawBlock, body_size: float) -> set[str] | None:
    """Heading signals of a block, or ``None`` when it cannot be a heading at all."""
    flat = _flatten(text)
    numbering = numbering_info(flat)
    keyword = numbering is not None and numbering[0] == "keyword"
    limit = config.MAX_KEYWORD_HEADING_CHARS if keyword else config.MAX_HEADING_CHARS
    if len(flat) > limit or text.count("\n") + 1 > config.MAX_HEADING_LINES:
        return None
    if numbering and numbering[0] == "bullet":
        return None
    if (not numbering and _starts_lowercase(flat)) or not has_real_words(flat):
        return None
    if not numbering and not HEADING_WORD.search(flat):  # "B FAM": a chart's letters
        return None
    if _is_formula(flat):
        return None
    uppercase = _uppercase(flat)
    section = keyword or (numbering is not None and numbering[0] == "decimal" and numbering[1] >= 2)
    wrapped_keyword = section and flat[-1] == ","  # a long section title wraps on
    if (flat[-1] in ",;" and not wrapped_keyword) or (
        flat[-1] == "." and not uppercase and not numbering
    ):
        return None

    signals: set[str] = set()
    if numbering:
        signals.add("number")
    if keyword:
        signals.add("keyword")
    if body_size and raw.font_size and raw.font_size >= body_size * config.LARGER_FONT_RATIO:
        signals.add("bigger")
    if raw.bold >= config.BOLD_SHARE:
        signals.add("bold")
    if uppercase:
        signals.add("uppercase")
    if raw.spaced:
        signals.add("spaced")
    return signals


def _kind(text: str, raw: RawBlock) -> tuple[object, ...]:
    """Level class of a heading: chapter word rank, numbering depth, or font."""
    numbering = numbering_info(_flatten(text))
    if numbering and numbering[0] == "keyword":
        return ("kw", numbering[1])
    if numbering and numbering[0] in ("decimal", "ordered"):
        return ("dec", numbering[1])
    return ("font", _size_key(raw.font_size or 0.0), raw.bold >= config.BOLD_SHARE)


def _is_plain_item(text: str) -> bool:
    """ "4. ..." / "4) ..." / "IV. ...": numbered like a list item."""
    numbering = numbering_info(_flatten(text))
    return numbering is not None and (numbering[0] == "ordered" or numbering == ("decimal", 1))


def _item_number(text: str) -> int | None:
    if match := LEADING_NUMBER.match(text):
        return int(match.group(1).split(".")[0])
    if match := LEADING_ROMAN.match(text):
        values = [ROMAN[c] for c in match.group(1)]
        return sum(
            -v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values)
        )
    return None


def _decide_headings(
    prepared: list[tuple[RawBlock, str]],
    body_size: float,
    titles: _TitleIndex,
    quoted: set[int],
) -> list[_Heading | None]:
    headings: list[_Heading | None] = []
    plain_items: list[int] = []
    for index, (raw, text) in enumerate(prepared):
        size = raw.font_size or 0.0
        styled = raw.heading_level is not None and raw.heading_source != "numbering"
        if not text or not _is_candidate(raw) or (index in quoted and not styled):
            headings.append(None)
            continue
        if raw.heading_source == "subheading" and raw.heading_level is None:
            # A reader's subheading (a bold DOCX paragraph): one level below what it follows.
            headings.append(_Heading("style", ("below",), size))
            continue
        if raw.heading_level is not None and raw.heading_source == "numbering":
            headings.append(_Heading("numbering", _kind(text, raw), size))
            continue
        if raw.heading_level is not None:
            source = raw.heading_source or "style"
            headings.append(_Heading(source, ("fixed", raw.heading_level), size, raw.heading_level))
            continue
        known = titles.match(text, raw.page) if titles else None
        if known is not None and has_real_words(text):
            headings.append(_Heading(known.source, _kind(text, raw), size, known.level))
            continue
        signals = _signals(text, raw, body_size)
        if signals is None or len(signals) < config.MIN_HEADING_SIGNALS:
            headings.append(None)
            continue
        source = "numbering" if "number" in signals else "font"
        headings.append(_Heading(source, _kind(text, raw), size))
        if _is_plain_item(text):
            plain_items.append(index)
    _keep_heading_sequences(headings, prepared, plain_items, body_size)
    _drop_outline_entries(headings, prepared)
    _drop_lead_in_labels(headings, prepared)
    _drop_captions(headings, prepared, body_size)
    _drop_run_in_titles(headings, prepared)
    _drop_inside_tables(headings, prepared)
    _repeat_heading_decisions(headings, prepared)
    return headings


def _repeat_heading_decisions(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]
) -> None:
    """A short line accepted as a heading makes every other line with the same text (trailing
    punctuation aside) and the same look a heading too: a book's recurring "Review questions"
    gets one decision, not one per page."""
    accepted: dict[tuple[str, tuple[float, bool, bool]], _Heading] = {}
    for heading, (raw, text) in zip(headings, prepared, strict=True):
        if heading is not None and len(_flatten(text).split()) <= config.MAX_TITLE_WORDS:
            accepted.setdefault((_bare_title(text), _style_of(raw, text)), heading)
    if not accepted:
        return
    for index, (raw, text) in enumerate(prepared):
        if headings[index] is not None or not text or not _is_candidate(raw):
            continue
        model = accepted.get((_bare_title(text), _style_of(raw, text)))
        if model is not None and not numbering_info(_flatten(text)):
            headings[index] = _Heading(model.source, model.kind, raw.font_size or 0.0)


def _bare_title(text: str) -> str:
    return _key(_flatten(text).rstrip(".:;!?… "))


def _next_block(prepared: list[tuple[RawBlock, str]], index: int) -> tuple[RawBlock, str] | None:
    return next(((raw, text) for raw, text in prepared[index + 1 :] if text.strip()), None)


def _drop_captions(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]], body_size: float
) -> None:
    """A short unnumbered line right above a table (in body size) or a figure or formula is
    its caption: marked ``role="caption"``, kept out of the heading tree. A bigger or numbered
    heading above a table stays a heading."""
    for index, heading in enumerate(headings):
        if heading is None or heading.kind[0] != "font":
            continue
        raw, _ = prepared[index]
        following = _next_block(prepared, index)
        if following is None:
            continue
        below = following[0]
        if below.rows is None and below.role not in OUT_OF_FLOW_ROLES:
            continue
        bigger = body_size and (raw.font_size or 0) >= body_size * config.LARGER_FONT_RATIO
        if (bigger and below.rows is not None) or below.page != raw.page:
            continue
        if raw.bbox and below.bbox:
            gap = below.bbox[1] - raw.bbox[3]
            if gap > config.CAPTION_GAP * (raw.font_size or body_size or 12.0):
                continue
        headings[index] = None
        raw.role = "caption"


def _drop_run_in_titles(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]
) -> None:
    """A "title" whose sentence runs on into a plain paragraph ("2. Term. Text" + "goes on
    ...", or a broken word "tamoyil-") is that paragraph's first line, not a heading."""
    for index, heading in enumerate(headings):
        if heading is None or heading.kind[0] == "kw":
            continue
        raw, text = prepared[index]
        flat = _flatten(text)
        following = _next_block(prepared, index)
        if following is None or flat[-1:] in ".!?:;":
            continue
        below, below_text = following
        runs_on = (
            _starts_lowercase(_flatten(below_text))
            and below.bold < config.BOLD_SHARE
            and len(_flatten(below_text)) > config.MAX_CONTINUATION_CHARS
        )
        if runs_on or (flat.endswith("-") and _starts_lowercase(_flatten(below_text))):
            headings[index] = None


def _drop_inside_tables(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]
) -> None:
    """Text lying inside a table's frame (a merged last row) is never a heading."""
    tables: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
    for raw, _ in prepared:
        if raw.rows is not None and raw.bbox:
            tables[raw.page].append(raw.bbox)
    if not tables:
        return
    for index, heading in enumerate(headings):
        raw = prepared[index][0]
        if heading is None or not raw.bbox:
            continue
        x, y = (raw.bbox[0] + raw.bbox[2]) / 2, (raw.bbox[1] + raw.bbox[3]) / 2
        if any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in tables.get(raw.page, [])):
            headings[index] = None


def _section_number(text: str) -> str | None:
    """ "3.2" of "3.2. Title" or "3-MAVZU" of a chapter line: a section's own number."""
    numbering = numbering_info(text)
    if numbering is None or numbering[0] not in SECTION_KINDS:
        return None
    if numbering[0] == "decimal" and numbering[1] < 2:
        return None
    return text.split()[0].rstrip(".:").lower() if text.split() else None


def _title_key(text: str) -> str:
    """The title after the section number, normalized for comparing two occurrences."""
    words = text.split()[1:]
    return _key(" ".join(words))[: config.OUTLINE_TITLE_CHARS]


def _drop_outline_entries(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]
) -> None:
    """Numbered titles that the document repeats later as headings, standing next to each
    other with no text between them, are outline entries (a chapter's plan or a contents
    list): list items, not headings. Every numbered line counts for the run, heading
    candidate or not, so the plan's last item goes with the others. A repeated title on its
    own ("1-§. General provisions" in every chapter) stays a heading."""
    entries = [_numbered_lines(text) for _, text in prepared]
    as_heading: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for index, heading in enumerate(headings):
        if heading is not None:
            for number, key in entries[index][:1]:
                as_heading[number].append((index, key))

    def repeated_later(index: int) -> bool:
        return any(
            later > index and key and later_key and _similar_titles(key, later_key)
            for number, key in entries[index]
            for later, later_key in as_heading.get(number, [])
        )

    repeated = {index for index in range(len(prepared)) if repeated_later(index)}
    for index in repeated:
        several = sum(1 for number, _ in entries[index] if number) > 1
        if several or index - 1 in repeated or index + 1 in repeated:
            headings[index] = None
            prepared[index][0].list_item = True


def _numbered_lines(text: str) -> list[tuple[str, str]]:
    """(section number, title key) of each numbered line of a block."""
    found: list[tuple[str, str]] = []
    for line in text.split("\n") if text else []:
        flat = _flatten(line)
        if number := _section_number(flat):
            found.append((number, _title_key(flat)))
    return found


def _similar_titles(a: str, b: str) -> bool:
    shorter, longer = sorted((a, b), key=len)
    return longer.startswith(shorter[: max(1, int(config.TITLE_MATCH_SHARE * len(shorter)))])


def _drop_lead_in_labels(
    headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]
) -> None:
    """A short line ending with ":" that introduces numbered items, or that has no body text
    after it before the next heading, is a label, not a heading."""
    for index, heading in enumerate(headings):
        text = _flatten(prepared[index][1])
        if heading is None or not text.endswith(":") or numbering_info(text):
            continue
        position = next(
            (i for i in range(index + 1, len(prepared)) if prepared[i][1].strip()), None
        )
        following = _flatten(prepared[position][1]) if position is not None else ""
        if numbering_info(following) or position is None or headings[position] is not None:
            headings[index] = None


def _quoted(prepared: list[tuple[RawBlock, str]]) -> set[int]:
    """Indexes of blocks that start inside a quotation opened in an earlier block, such as
    new articles quoted by an amending law ("“131-modda. ..." up to the closing "”")."""
    quoted: set[int] = set()
    stack: list[tuple[str, int]] = []
    for index, (raw, text) in enumerate(prepared):
        if raw.rows is not None or raw.footnote:
            continue
        for match in QUOTE_MARK.finditer(text):
            mark = match.group()
            if mark in "«„" or (mark == "“" and not (stack and stack[-1][0] == "„")):
                stack.append((mark, index))
                continue
            if not stack or (mark == "»") != (stack[-1][0] == "«"):
                continue  # a stray closing mark
            start = stack.pop()[1]
            if 0 < index - start <= config.MAX_QUOTED_BLOCKS:
                quoted.update(range(start + 1, index + 1))
    return quoted


def _keep_heading_sequences(
    headings: list[_Heading | None],
    prepared: list[tuple[RawBlock, str]],
    plain_items: list[int],
    body_size: float,
) -> None:
    """A plain "N." item stays a heading only with heading styling and as part of a numbered
    sequence with text between its members (1., then content, then 2., ...)."""
    groups: dict[tuple[float, bool, bool], list[int]] = defaultdict(list)
    for index in plain_items:
        raw, text = prepared[index]
        groups[
            (_size_key(raw.font_size or 0), raw.bold >= config.BOLD_SHARE, _uppercase(text))
        ].append(index)

    keep: set[int] = set()
    for (size, bold, uppercase), members in groups.items():
        bigger = bool(body_size) and size >= body_size * config.LARGER_FONT_RATIO
        if not (bigger or bold or uppercase):
            continue
        if bigger and (bold or uppercase):
            keep.update(members)
            continue
        for a, b in zip(members, members[1:], strict=False):
            first, second = _item_number(prepared[a][1]), _item_number(prepared[b][1])
            if first is not None and second == first + 1 and b - a > 1:
                keep.update((a, b))
    for index in plain_items:
        if index not in keep:
            headings[index] = None


def _assign_levels(headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]) -> None:
    """Turn heading kinds into levels, so a child can never sit above its parent."""
    present = [h for h in headings if h is not None and h.kind[0] not in ("fixed", "below")]
    numbered = sorted({h.kind for h in present if h.kind[0] in ("kw", "dec")}, key=_kind_order)
    fonts = sorted({h.kind for h in present if h.kind[0] == "font"}, key=_font_order)
    sizes = {k: statistics.median(h.size for h in present if h.kind == k) for k in numbered}
    fixed_levels: dict[tuple[object, ...], Counter[int]] = defaultdict(Counter)
    for h in present:
        if h.level is not None:
            fixed_levels[h.kind][h.level] += 1

    levels: dict[tuple[object, ...], int] = {}
    current = 0
    nests = _nesting_keywords(headings)
    previous: tuple[object, ...] | None = None
    for kind in numbered:
        rival = previous is not None and previous[0] == kind[0] == "kw" and kind not in nests
        if fixed_levels[kind]:
            current = fixed_levels[kind].most_common(1)[0][0]
        elif not rival:  # a chapter word that never appears under the one above ranks with it
            current += 1
        levels[kind] = current
        previous = kind
    deepest = current
    for kind in fonts:
        if fixed_levels[kind]:
            levels[kind] = fixed_levels[kind].most_common(1)[0][0]
            continue
        size = kind[1]
        peer = next((k for k in numbered if sizes[k] <= size), None)  # type: ignore[operator]
        if peer is not None:
            # An unnumbered heading ranks with a chapter only when it is bigger than the
            # chapter titles or matches their style (below); otherwise it sits inside one.
            bigger = size > sizes[peer]  # type: ignore[operator]
            levels[kind] = levels[peer] + (0 if peer[0] != "kw" or bigger else 1)
        else:
            deepest += 1
            levels[kind] = deepest
    styles = _numbered_styles(headings, prepared, levels)
    for heading, (raw, text) in zip(headings, prepared, strict=True):
        if heading is None or heading.kind[0] in ("fixed", "below") or heading.level is not None:
            continue
        heading.level = levels[heading.kind]
        style = _style_of(raw, text)
        if heading.kind[0] == "font" and (match := styles.get(style)) is not None:
            heading.level = match
    _enforce_parents(headings, prepared)
    _place_subheadings(headings)
    _close_level_gaps(headings)


def _place_subheadings(headings: list[_Heading | None]) -> None:
    """A reader's subheading sits one level below the last other heading before it."""
    parent = 0
    for heading in headings:
        if heading is None:
            continue
        if heading.kind[0] == "below":
            heading.level = parent + 1
        elif heading.level is not None:
            parent = heading.level


def _nesting_keywords(headings: list[_Heading | None]) -> set[tuple[object, ...]]:
    """Chapter-word kinds that appear after a higher-ranked one ("1-bob" after "I BOʻLIM"),
    so they really sit inside it."""
    seen: set[int] = set()
    nested: set[tuple[object, ...]] = set()
    for heading in headings:
        if heading is None or heading.kind[0] != "kw":
            continue
        rank = int(heading.kind[1])  # type: ignore[call-overload]
        if any(higher < rank for higher in seen):
            nested.add(heading.kind)
        seen.add(rank)
    return nested


def _style_of(raw: RawBlock, text: str) -> tuple[float, bool, bool]:
    return (_size_key(raw.font_size or 0.0), raw.bold >= config.BOLD_SHARE, _uppercase(text))


def _numbered_styles(
    headings: list[_Heading | None],
    prepared: list[tuple[RawBlock, str]],
    levels: dict[tuple[object, ...], int],
) -> dict[tuple[float, bool, bool], int]:
    """Look of each numbered heading level (size, bold, capitals) -> the deepest level with
    that look, so an unnumbered heading styled like "3.1. ..." joins that level."""
    styles: dict[tuple[float, bool, bool], int] = {}
    for h, (raw, text) in zip(headings, prepared, strict=True):
        if h is None or h.kind[0] not in ("kw", "dec") or h.kind not in levels:
            continue
        style = _style_of(raw, text)
        styles[style] = max(styles.get(style, 0), levels[h.kind])
    return styles


def _close_level_gaps(headings: list[_Heading | None]) -> None:
    """Number the levels in use 1, 2, 3 ... in their order (1, 3, 4 -> 1, 2, 3)."""
    used = sorted({h.level for h in headings if h is not None and h.level is not None})
    rank = {level: position for position, level in enumerate(used, start=1)}
    for h in headings:
        if h is not None and h.level is not None:
            h.level = rank[h.level]


def _font_order(kind: tuple[object, ...]) -> tuple[float, bool]:
    """Bigger first, bold before regular."""
    size, bold = float(kind[1]), bool(kind[2])  # type: ignore[arg-type]
    return (-size, not bold)


def _kind_order(kind: tuple[object, ...]) -> tuple[int, int]:
    return (0 if kind[0] == "kw" else 1, int(kind[1]))  # type: ignore[call-overload]


def _enforce_parents(headings: list[_Heading | None], prepared: list[tuple[RawBlock, str]]) -> None:
    """ "5.3" sits below "5" or the chapter it follows; never above it."""
    last_chapter: int | None = None
    numbered: dict[str, int] = {}
    section: int | None = None  # level of the last "N.M" section, while it lasts
    restarted = False  # a "1." run started inside that section
    for heading, (_, text) in zip(headings, prepared, strict=True):
        if heading is None or heading.level is None:
            continue
        if heading.kind[0] == "kw":
            last_chapter = heading.level
            numbered.clear()
            section, restarted = None, False
            continue
        if heading.kind[0] != "dec":
            continue
        match = LEADING_NUMBER.match(text)
        parts = match.group(1).split(".") if match else []
        if len(parts) == 1 and section is not None and (restarted or parts[0] == "1"):
            # "1.", "2." restarting inside section "6.2" are its items, not new sections.
            restarted = True
            if heading.level <= section:
                heading.level = section + 1
            continue
        parent = (
            numbered.get(".".join(parts[:-1]), last_chapter) if len(parts) > 1 else last_chapter
        )
        if parent is not None and heading.level <= parent:
            heading.level = parent + 1
        if parts:
            numbered[".".join(parts)] = heading.level
        section, restarted = (heading.level, False) if len(parts) > 1 else (None, False)


def _title_runs_on(title: str, title_raw: RawBlock, raw: RawBlock, text: str) -> bool:
    """The heading visibly goes on into ``text``, the next line of the same style: it starts
    lowercase, the title is left open (a comma, an open bracket, a hyphen, a joining word),
    or both are set in capitals."""
    flat = _flatten(text)
    if not flat or raw.rows is not None or raw.footnote or raw.role or raw.list_item:
        return False
    capitals = _uppercase(title) and _uppercase(flat)
    return _starts_lowercase(flat) or _open_title(title) or capitals


def _same_style(a: RawBlock, b: RawBlock) -> bool:
    sizes_match = (a.font_size is None and b.font_size is None) or (
        a.font_size is not None
        and b.font_size is not None
        and abs(a.font_size - b.font_size) <= 0.5
    )
    return sizes_match and abs(a.bold - b.bold) <= 0.3


def _continues_heading(heading: Block, heading_raw: RawBlock, raw: RawBlock, text: str) -> bool:
    """True when ``raw`` is the wrapped second half of the heading just emitted."""
    if heading.type is not BlockType.HEADING or heading_raw.page != raw.page:
        return False
    flat = _flatten(text)
    if numbering_info(flat) or len(flat) > config.MAX_CONTINUATION_CHARS:
        return False
    if flat.endswith(":"):  # a label introducing what follows ("Plan:"), not the title's end
        return False
    # A title left open ("... va", "...,") must go on: its next line may differ a little in
    # style (a regular word, another font size) and sit a little further down.
    open_title = _open_title(heading.text)
    if heading.text[-1] in ".?!":
        return False
    if not (_same_style(heading_raw, raw) or (open_title and _close_style(heading_raw, raw))):
        return False
    if heading_raw.bbox and raw.bbox:
        gap = raw.bbox[1] - heading_raw.bbox[3]
        limit = config.CONTINUATION_GAP * (config.OPEN_TITLE_GAP_FACTOR if open_title else 1)
        if gap > limit * (raw.font_size or 12.0):
            return False
    return True


def _open_title(title: str) -> bool:
    """The title cannot end here: a comma, a hyphen, an open bracket or a joining word."""
    words = title.split()
    return (
        title[-1:] in ",-–("
        or title.count("(") > title.count(")")
        or (bool(words) and words[-1].lower() in config.JOINING_WORDS)
    )


def _close_style(a: RawBlock, b: RawBlock) -> bool:
    """Nearly the same look: sizes within ``LARGER_FONT_RATIO`` of each other, either bold."""
    if a.font_size is None or b.font_size is None:
        return a.font_size == b.font_size
    small, large = sorted((a.font_size, b.font_size))
    return large <= small * config.LARGER_FONT_RATIO and max(a.bold, b.bold) >= config.BOLD_SHARE


# --- Joining across pages, language of short blocks ----------------------------------------


def _join_split_paragraphs(blocks: list[Block], repair: Repair, page_layout: bool) -> list[Block]:
    """Merge a paragraph split in two by a page break, a footnote or a figure, and merge
    orphan fragments ("tengdir.") back into the sentence they end."""
    joined: list[Block] = []
    for block in blocks:
        position = next(
            (i for i in range(len(joined) - 1, -1, -1) if not _out_of_flow(joined[i])), None
        )
        flow = joined[position] if position is not None else None
        across_figure = position is not None and any(
            b.extra.get("role") in OUT_OF_FLOW_ROLES for b in joined[position + 1 :]
        )
        if flow is not None and (
            _is_continuation(flow, block, page_layout)
            or _is_orphan(flow, block)
            or (across_figure and _runs_on(flow, block))
        ):
            _merge_into(flow, block, repair)
        else:
            joined.append(block)
    return joined


def _out_of_flow(block: Block) -> bool:
    return block.type is BlockType.FOOTNOTE or block.extra.get("role") in OUT_OF_FLOW_ROLES


def _runs_on(previous: Block, block: Block) -> bool:
    """Plain text that visibly continues: no sentence end before, a small letter after, on
    the same or the next page."""
    if previous.type not in (BlockType.PARAGRAPH, BlockType.LIST):
        return False
    if block.type is not BlockType.PARAGRAPH or block.extra.get("role") or not block.text:
        return False
    if previous.extra.get("role") or not previous.text:
        return False
    last_page = previous.extra.get("page_end", previous.page)
    last = previous.text[-1]
    open_sentence = last.isalpha() or last in ",-"
    return block.page in (last_page, last_page + 1) and open_sentence and block.text[0].islower()


def _is_orphan(previous: Block, block: Block) -> bool:
    """A one- or two-word fragment ("tengdir.") whose first word is a real word, ending the
    sentence the previous block leaves open."""
    words = block.text.split()
    if not words or len(words) > config.ORPHAN_WORDS or not _runs_on(previous, block):
        return False
    return is_known_word(words[0].strip(".,;:!?…»”)"))


def _merge_into(previous: Block, block: Block, repair: Repair) -> None:
    """Append ``block`` to ``previous``; for a list it extends the last item."""
    if previous.type is BlockType.LIST:
        items = previous.extra["items"]
        items[-1] = _flatten(repair(f"{items[-1]}\n{block.text}"))
        previous.text = "\n".join(items)
    else:
        previous.text = _flatten(repair(f"{previous.text}\n{block.text}"))
    previous.raw_text = f"{previous.raw_text}\n{block.raw_text}"
    previous.extra["page_end"] = block.page
    previous.language = detect_language(previous.text)


def _is_continuation(previous: Block, block: Block, page_layout: bool) -> bool:
    """``block`` goes on with the sentence ``previous`` leaves open, across a page break or,
    in a source without page layout (DOCX made by OCR), across a paragraph break."""
    if previous.type not in (BlockType.PARAGRAPH, BlockType.LIST):
        return False
    tail = _is_sentence_tail(previous, block)
    if block.type is not BlockType.PARAGRAPH and not tail:
        return False
    if previous.extra.get("role") or block.extra.get("role") or not block.text:
        return False
    last_page = previous.extra.get("page_end", previous.page)
    same_flow = not page_layout and block.page == last_page
    if block.page != last_page + 1 and not same_flow:
        return False
    last = previous.text[-1]
    # A page break may fall anywhere; a paragraph break only inside an unfinished sentence.
    open_sentence = (last.isalpha() or last in ",-") if same_flow else last not in SENTENCE_END
    return (
        tail or (open_sentence and block.text[0].islower()) or ends_with_abbreviation(previous.text)
    )


def _is_sentence_tail(previous: Block, block: Block) -> bool:
    """A short line in capitals ending the sentence ``previous`` leaves unfinished, e.g.
    "основные" + "ПОНЯТИЯ:" (OCR sets a paragraph's last line in capitals)."""
    if block.type not in (BlockType.PARAGRAPH, BlockType.HEADING):
        return False
    if block.type is BlockType.HEADING and block.extra.get("heading_source") != "font":
        return False
    text = block.text
    return (
        previous.text[-1].isalpha()
        and text[-1] in ".:;"
        and len(text.split()) <= config.MAX_SENTENCE_TAIL_WORDS
        and _uppercase(text)
    )


def _inherit_short_languages(blocks: list[Block]) -> None:
    """Blocks whose own language is unsure take their neighbours' language: very short blocks
    without one ("Reja:", numbers), short blocks below ``SHORT_LANGUAGE_CONFIDENCE`` and any
    block below ``LOW_LANGUAGE_CONFIDENCE``. A block with a language only looks at neighbours
    in its own script; when the two neighbours disagree, the language the document mostly
    uses in that script wins. A block of one or two words ("Эквайринг", a loanword both languages
    share) also follows its neighbours below ``TINY_LANGUAGE_CONFIDENCE``, if they agree."""

    def tiny(block: Block) -> bool:
        return len(block.text.split()) <= config.TINY_BLOCK_WORDS

    def unsure(block: Block) -> bool:
        info = block.language
        if info.language in ("uz", "ru") and tiny(block):
            return info.confidence < config.TINY_LANGUAGE_CONFIDENCE
        short = len(block.text.split()) < config.SHORT_BLOCK_WORDS
        if info.language == "unknown":
            return short
        if info.language == "mixed":
            return False
        limit = config.SHORT_LANGUAGE_CONFIDENCE if short else config.LOW_LANGUAGE_CONFIDENCE
        return info.confidence < limit

    flow = [i for i, block in enumerate(blocks) if block.type is not BlockType.FOOTNOTE]
    usable = [i for i in flow if blocks[i].language.language in ("uz", "ru")]
    known = [i for i in usable if not unsure(blocks[i])] or usable
    if not known:
        return
    dominant: dict[str, Counter[str]] = defaultdict(Counter)
    for i in known:
        info = blocks[i].language
        dominant[info.script][info.language] += len(blocks[i].text)

    for index, block in enumerate(blocks):
        if block.type is BlockType.FOOTNOTE or not unsure(block):
            continue
        position = bisect.bisect_left(known, index)
        following = position + 1 if position < len(known) and known[position] == index else position
        neighbours = [blocks[known[p]] for p in (position - 1, following) if 0 <= p < len(known)]
        if block.language.language != "unknown":
            neighbours = [b for b in neighbours if b.language.script == block.language.script]
        if not neighbours:
            continue
        source = neighbours[0]
        agree = len({b.language.language for b in neighbours}) == 1
        weak = block.language.confidence < config.SHORT_LANGUAGE_CONFIDENCE
        if block.language.language != "unknown" and tiny(block) and not agree and not weak:
            continue
        if len(neighbours) == 2 and not agree:
            script = source.language.script
            preferred = dominant[script].most_common(1)[0][0]
            source = next((b for b in neighbours if b.language.language == preferred), source)
        block.language = LanguageInfo(
            source.language.language, source.language.script, source.language.confidence
        )
