"""Tagged PDFs: the author's own structure.

Word processors that save accessible PDFs ("document structure tags") also write a structure
tree: every heading, paragraph, list item, table cell and note is an element pointing at its
text on the page through marked-content ids. MuPDF links the tree to the page text while it
extracts the text (``TEXT_COLLECT_STRUCTURE``). This module turns the tagged elements into raw
blocks carrying what DOCX styles give: headings with their levels, paragraphs as the author
wrote them, list items, table cells, footnotes, captions, figures and contents entries.

Tags are checked before they are trusted (:func:`check`): they must cover most of the text,
run down the page and hold paragraphs, not whole pages. Text outside the tree (page headers
and footers marked as artifacts, untagged text) is rebuilt from its lines like an untagged
page and placed by its position.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pymupdf

from . import config
from .paragraphs import FIGURE_SEPARATOR, LayoutStats, Line, main_font
from .structure import RawBlock
from .text import numbering_info

#: PyMuPDF returns structure elements in its "dict" output from 1.26.6 on; older versions have
#: the flag but return no text with it.
STRUCTURE_SINCE = (1, 26, 6)


def _version(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text)
    return tuple(int(part) for part in parts[:3])


#: MuPDF links marked content to the structure tree with this text flag; 0 when the installed
#: PyMuPDF cannot report the structure (the tagged route is then off).
STRUCTURE_FLAG = (
    int(getattr(pymupdf, "TEXT_COLLECT_STRUCTURE", 0))
    if _version(str(getattr(pymupdf, "VersionBind", "0"))) >= STRUCTURE_SINCE
    else 0
)
#: Block type of a structure element in PyMuPDF's "dict" output.
STRUCT_BLOCK = 2

HEADING_LEVELS = {f"H{level}": level for level in range(1, 7)}
#: Elements that make one raw block of everything below them.
UNITS = frozenset(
    {
        *HEADING_LEVELS,
        "H",
        "Title",
        "P",
        "LI",
        "Lbl",
        "LBody",
        "Table",
        "TR",
        "TH",
        "TD",
        "TOCI",
        "Formula",
        "BlockQuote",
        "Code",
        "Quote",
        "BibEntry",
    }
)
#: Elements that stand apart wherever they sit: a note placed at its reference inside a
#: paragraph, a figure inside a paragraph, a caption inside a table.
DETACHED = frozenset({"Note", "FENote", "Figure", "Caption", "Artifact"})
#: Containers whose nesting gives a plain "H" heading its level.
SECTIONS = frozenset({"Sect", "Part", "Art"})
ROW = "TR"
CELLS = frozenset({"TH", "TD"})
ROLES = {"Figure": "figure", "Formula": "formula", "Caption": "caption", "TOCI": "toc"}
_SPAN = re.compile(r"/(ColSpan|RowSpan)\s+(\d+)")
_REF = re.compile(r"^\s*(\d+)\s+\d+\s+R")


def _get(pdf: pymupdf.Document, xref: int, key: str) -> tuple[str, str]:
    """``(type, value)`` of a dictionary entry ("null" when missing); ``key`` may be a path."""
    kind, value = pdf.xref_get_key(xref, key)  # type: ignore[no-untyped-call]
    return str(kind), str(value)


def _object(pdf: pymupdf.Document, xref: int) -> str:
    return str(pdf.xref_object(xref, compressed=True))  # type: ignore[no-untyped-call]


def _catalog(pdf: pymupdf.Document) -> int:
    return int(pdf.pdf_catalog())  # type: ignore[no-untyped-call]


def pages(pdf: pymupdf.Document) -> Iterator[pymupdf.Page]:
    for number in range(pdf.page_count):
        yield pdf.load_page(number)  # type: ignore[no-untyped-call]


@dataclass(frozen=True)
class Node:
    """One structure element on the way down to a piece of text."""

    kind: str  # standard type after the role map ("H1", "P", "TD", ...)
    raw: str  # the tag as written ("Heading1")
    index: int  # position among the parent's children


Path = tuple[Node, ...]
Key = tuple[tuple[str, int], ...]


@dataclass
class TaggedLine:
    line: Line
    path: Path  # empty: text outside the structure tree


@dataclass
class TagSummary:
    """What the document says about its tags."""

    tree: bool = False  # the catalog has a structure tree
    marked: bool = False  # MarkInfo /Marked true: the producer claims tagged content
    slow: bool = False  # MuPDF would look up marked content slowly (see :func:`detach`)

    @property
    def usable(self) -> bool:
        return self.tree and not self.slow and STRUCTURE_FLAG != 0

    def as_dict(self) -> dict[str, Any]:
        return {"tree": self.tree, "marked": self.marked}


@dataclass
class Unit:
    """The lines of one element on one page, in structure order."""

    key: Key
    kind: str
    path: Path  # down to the element itself
    lines: list[TaggedLine] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(tagged.line.chars for tagged in self.lines)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [tagged.line.bbox for tagged in self.lines]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


@dataclass
class Check:
    """Verdict on a document's tags."""

    ok: bool
    reason: str = ""
    coverage: float = 0.0


def inspect(pdf: pymupdf.Document) -> TagSummary:
    """Find the structure tree and check that MuPDF can follow it quickly."""
    catalog = _catalog(pdf)
    kind, _ = _get(pdf, catalog, "StructTreeRoot")
    summary = TagSummary(tree=kind in ("xref", "dict"))
    if not summary.tree:
        return summary
    summary.marked = _get(pdf, catalog, "MarkInfo/Marked")[1] == "true"
    tree = _ParentTree(pdf)
    for page in pages(pdf):
        count = page.read_contents().count(b"/MCID")  # type: ignore[no-untyped-call]
        if count > config.TAGGED_MAX_PAGE_MCIDS:
            summary.slow = True
        elif count > config.TAGGED_CHECK_PAGE_MCIDS:
            summary.slow = not tree.consistent(page, count)
        if summary.slow:
            break
    return summary


def detach(pdf: pymupdf.Document) -> None:
    """Forget the structure tree in memory. For each marked-content id on a page MuPDF looks
    up its element; when the parent tree lists the elements at the wrong places it searches
    the whole list each time, and pages with hundreds of ids take seconds or minutes (PyMuPDF
    issue 5125). Without the tree the text comes out the same, at normal speed."""
    pdf.xref_set_key(_catalog(pdf), "StructTreeRoot", "null")  # type: ignore[no-untyped-call]


class _ParentTree:
    """The structure tree's parent tree: for each page, the element of each marked-content
    id, listed at the id's position."""

    def __init__(self, pdf: pymupdf.Document) -> None:
        self.pdf = pdf
        kind, value = _get(pdf, _catalog(pdf), "StructTreeRoot/ParentTree")
        self.root = int(match.group(1)) if kind == "xref" and (match := _REF.match(value)) else None

    def consistent(self, page: pymupdf.Page, count: int) -> bool:
        """Do sampled ids of the page find their element at their own position?"""
        kind, value = _get(self.pdf, page.xref, "StructParents")
        if self.root is None or kind != "int":
            return True
        items = self._array(self._lookup(self.root, int(value)))
        if not items:
            return True
        step = max(1, min(len(items), count) // config.TAGGED_MCID_SAMPLE)
        sample = range(0, min(len(items), count), step)
        misses = sum(1 for mcid in sample if not self._owns(items[mcid], mcid))
        return misses <= len(sample) // 2

    def _owns(self, item: str, mcid: int) -> bool:
        match = _REF.match(item)
        if match is None:
            return False
        kind, value = _get(self.pdf, int(match.group(1)), "K")
        kids = _array_items(value) if kind == "array" else [value]
        return any(kid.strip() == str(mcid) or re.search(rf"/MCID\s+{mcid}\b", kid) for kid in kids)

    def _array(self, value: str | None) -> list[str]:
        if value is None:
            return []
        if match := _REF.match(value):
            value = _object(self.pdf, int(match.group(1)))
        return _array_items(value) if value.strip().startswith("[") else []

    def _lookup(self, xref: int, key: int, depth: int = 0) -> str | None:
        """Value of ``key`` in the number tree node ``xref``."""
        kind, value = _get(self.pdf, xref, "Nums")
        if kind == "array":
            items = _array_items(value)
            for number, entry in zip(items[::2], items[1::2], strict=False):
                if number.strip() == str(key):
                    return entry
            return None
        kind, value = _get(self.pdf, xref, "Kids")
        if kind != "array" or depth > config.TAGGED_MAX_TREE_DEPTH:
            return None
        for kid in _array_items(value):
            match = _REF.match(kid)
            if match is None:
                continue
            child = int(match.group(1))
            limits = _array_items(_get(self.pdf, child, "Limits")[1] or "[]")
            if len(limits) == 2 and limits[0].isdigit() and limits[1].isdigit():
                if not int(limits[0]) <= key <= int(limits[1]):
                    continue
            found = self._lookup(child, key, depth + 1)
            if found is not None:
                return found
        return None


def text_blocks(page_dict: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    """The page's text and image blocks in structure order, each with its structure path."""
    out: list[tuple[Path, dict[str, Any]]] = []

    def walk(blocks: Iterable[dict[str, Any]], path: Path) -> None:
        for block in blocks:
            if block.get("type") == STRUCT_BLOCK:
                node = Node(
                    str(block.get("std") or ""),
                    str(block.get("raw") or ""),
                    int(block.get("index", -1)),
                )
                walk(block.get("blocks", ()), (*path, node))
            else:
                out.append((path, block))

    walk(page_dict.get("blocks", ()), ())
    return out


def _unit_at(path: Path) -> int | None:
    """Position in ``path`` of the element that makes the block, or ``None`` (untagged or an
    artifact). A detached element (note, figure, caption) wins wherever it sits; otherwise
    the outermost block element, except that a list nested in an item has items of its own."""
    for position, node in enumerate(path):
        if node.kind in DETACHED:
            return position
    unit: int | None = None
    for position, node in enumerate(path):
        if unit is None:
            if node.kind in UNITS:
                unit = position
        elif path[unit].kind == "LI" and node.kind == "L":
            unit = None
    return unit


def _key(path: Path) -> Key:
    return tuple((node.kind, node.index) for node in path)


def page_units(lines: Sequence[TaggedLine], page_height: float) -> tuple[list[Unit], list[Line]]:
    """Group a page's tagged lines into units, in structure order, and return the lines left
    outside the tree. MuPDF keeps an element open until the next one starts, so a page footer
    drawn after the last paragraph lands inside it: a text block in the top or bottom margin
    band of a unit that otherwise lies outside the band is page furniture, not the unit."""
    units: dict[Key, Unit] = {}
    loose: list[Line] = []
    for tagged in lines:
        position = _unit_at(tagged.path)
        if position is None:
            if not tagged.path or tagged.path[-1].kind != "Artifact":
                loose.append(tagged.line)
            continue
        unit_path = tagged.path[: position + 1]
        key = _key(unit_path)
        unit = units.get(key)
        if unit is None:
            unit = units[key] = Unit(key=key, kind=unit_path[-1].kind, path=unit_path)
        unit.lines.append(tagged)
    kept: list[Unit] = []
    for unit in units.values():
        if unit.kind == "Artifact":
            continue
        inside, margin = _split_margin(unit, page_height)
        loose.extend(margin)
        if inside:
            unit.lines = inside
            kept.append(unit)
    return kept, loose


def _in_band(bbox: tuple[float, float, float, float], page_height: float) -> bool:
    band = config.MARGIN_BAND * page_height
    return page_height > 0 and (bbox[3] <= band or bbox[1] >= page_height - band)


def _split_margin(unit: Unit, page_height: float) -> tuple[list[TaggedLine], list[Line]]:
    """The unit's lines, without text blocks in the margin band when the unit's first block
    lies outside it."""
    first = unit.lines[0].line.block
    first_lines = [t.line for t in unit.lines if t.line.block == first]
    if any(_in_band(line.bbox, page_height) for line in first_lines):
        return unit.lines, []
    inside: list[TaggedLine] = []
    margin: list[Line] = []
    for tagged in unit.lines:
        if tagged.line.block != first and _in_band(tagged.line.bbox, page_height):
            margin.append(tagged.line)
        else:
            inside.append(tagged)
    return inside, margin


def check(pages: Sequence[Sequence[Unit]], total_chars: int, line_gap: float) -> Check:
    """Trust the tags only when they cover most of the text, put the page's elements in
    top-to-bottom order within a column, and hold paragraphs rather than whole pages."""
    tagged_chars = sum(unit.chars for units in pages for unit in units)
    coverage = tagged_chars / total_chars if total_chars else 0.0
    if not tagged_chars:
        return Check(False, "no tagged text", coverage)
    if any(index < 0 for units in pages for unit in units for _, index in unit.key):
        # An element missing from its parent's kids: MuPDF gives all such elements the same
        # position and runs their text together.
        return Check(False, "tags do not match the tree", coverage)
    if coverage < config.TAGGED_MIN_COVERAGE:
        return Check(False, "tags miss text", coverage)
    long_chars = sum(
        unit.chars
        for units in pages
        for unit in units
        if unit.kind not in ("Table", "TR", "TH", "TD")
        and len(unit.lines) > config.TAGGED_LONG_UNIT_LINES
    )
    if long_chars > config.TAGGED_MAX_LONG_SHARE * tagged_chars:
        return Check(False, "elements hold whole pages", coverage)
    pairs = backward = 0
    for units in pages:
        flow = [unit for unit in units if unit.kind not in DETACHED]
        for previous, unit in zip(flow, flow[1:], strict=False):
            a, b = previous.bbox, unit.bbox
            if a[0] >= b[2] or b[0] >= a[2]:  # side by side: another column
                continue
            pairs += 1
            size = max(1.0, (b[3] - b[1]) / max(1, len(unit.lines)))
            if b[1] < a[1] - max(size, line_gap):
                backward += 1
    if pairs and backward > config.TAGGED_MAX_BACKWARD_SHARE * pairs:
        return Check(False, "tag order runs against the page", coverage)
    return Check(True, "", coverage)


class Elements:
    """Structure elements found by their path, for attributes MuPDF does not report (the
    column and row spans of table cells)."""

    def __init__(self, pdf: pymupdf.Document) -> None:
        self.pdf = pdf
        self.cache: dict[Key, int | None] = {}

    def _kids(self, xref: int | None) -> list[str]:
        if xref is None:
            kind, value = _get(self.pdf, _catalog(self.pdf), "StructTreeRoot/K")
        else:
            kind, value = _get(self.pdf, xref, "K")
        if kind == "array":
            return _array_items(value)
        return [value] if kind in ("xref", "int", "dict") else []

    def xref(self, path: Path) -> int | None:
        key = _key(path)
        if key in self.cache:
            return self.cache[key]
        parent = self.xref(path[:-1]) if len(path) > 1 else None
        found: int | None = None
        if len(path) == 1 or parent is not None:
            kids = self._kids(parent)
            index = path[-1].index
            if 0 <= index < len(kids) and (match := _REF.match(kids[index])):
                found = int(match.group(1))
        self.cache[key] = found
        return found

    def spans(self, path: Path) -> tuple[int, int]:
        """(column span, row span) of a table cell, 1 when not stated."""
        xref = self.xref(path)
        if xref is None:
            return 1, 1
        kind, value = _get(self.pdf, xref, "A")
        if kind == "xref" and (match := _REF.match(value)):
            value = _object(self.pdf, int(match.group(1)))
        elif kind == "null":
            return 1, 1
        found = dict(_SPAN.findall(value))
        return int(found.get("ColSpan", 1)), int(found.get("RowSpan", 1))


def _array_items(text: str) -> list[str]:
    """Top-level items of a PDF array written as text: "[1 0 R <</MCID 3>> 4]"."""
    body = text.strip()[1:-1]
    items: list[str] = []
    depth = 0
    current = ""
    tokens = re.findall(r"<<|>>|\[|\]|\d+\s+\d+\s+R|\([^)]*\)|[^\s<>\[\]()]+", body)
    for token in tokens:
        if token in ("<<", "["):
            depth += 1
        elif token in (">>", "]"):
            depth -= 1
        current = f"{current} {token}".strip() if current else token
        if depth == 0:
            items.append(current)
            current = ""
    return items


def unit_block(
    unit: Unit, page: int, spans: Callable[[Path], tuple[int, int]] | None = None
) -> RawBlock:
    """The raw block of one unit: its kind gives the heading level, list item, table rows,
    footnote or role the rules would otherwise have to guess."""
    lines = [tagged.line for tagged in unit.lines]
    role = ROLES.get(unit.kind)
    separator = FIGURE_SEPARATOR if role == "figure" else "\n"
    chars = sum(line.chars for line in lines) or 1
    raw = RawBlock(
        text=separator.join(line.text for line in lines),
        original="\n".join(line.original or line.text for line in lines),
        page=page,
        bbox=unit.bbox,
        font_size=max((line.size for line in lines if line.size), default=None),
        bold=sum(line.bold * line.chars for line in lines) / chars,
        footnote_refs=[ref for line in lines for ref in line.refs],
        role=role,
        tagged=True,
        font=main_font(lines),
        italic=sum(line.italic * line.chars for line in lines) / chars,
    )
    if unit.kind in HEADING_LEVELS or unit.kind in ("H", "Title"):
        sections = sum(1 for node in unit.path[:-1] if node.kind in SECTIONS)
        raw.heading_level = HEADING_LEVELS.get(unit.kind, max(1, sections))
        raw.heading_source = "tags"
    elif unit.kind == "LI":
        raw.list_item = True
    elif unit.kind in ("Note", "FENote"):
        raw.footnote = True
    elif unit.kind == "Table":
        raw.rows = _rows(unit, spans)
    return raw


def _rows(unit: Unit, spans: Callable[[Path], tuple[int, int]] | None) -> list[list[str]]:
    """Table rows from the TR / TH / TD elements below the table, spanned cells filled with
    empty cells so the columns stay aligned."""
    depth = len(unit.path)
    rows: dict[Key, dict[Key, tuple[Path, list[str]]]] = {}
    for tagged in unit.lines:
        below = tagged.path[depth:]
        row_at = next((i for i, node in enumerate(below) if node.kind == ROW), None)
        cell_at = next((i for i, node in enumerate(below) if node.kind in CELLS), None)
        row_key = _key(below[: row_at + 1]) if row_at is not None else _key(below[:1])
        cell_path = tagged.path[: depth + cell_at + 1] if cell_at is not None else tagged.path
        cells = rows.setdefault(row_key, {})
        cells.setdefault(_key(cell_path), (cell_path, []))[1].append(tagged.line.text)

    grid: list[list[str]] = []
    pending: dict[int, int] = {}  # column -> rows a cell above still spans
    for cells in rows.values():
        row: list[str] = []
        for cell_path, texts in cells.values():
            while pending.get(len(row), 0) > 0:
                pending[len(row)] -= 1
                row.append("")
            columns, rows_down = spans(cell_path) if spans else (1, 1)
            for offset in range(max(1, columns)):
                if rows_down > 1:
                    pending[len(row)] = rows_down - 1
                row.append("\n".join(texts) if offset == 0 else "")
        while pending.get(len(row), 0) > 0:
            pending[len(row)] -= 1
            row.append("")
        grid.append(row)
    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def mark_spacing(blocks: Sequence[RawBlock], stats: LayoutStats) -> None:
    """A tagged block with clearly more space above it than a line gap is ``spaced``, the
    signal untagged layout gives."""
    previous: RawBlock | None = None
    for raw in blocks:
        tagged = raw.tagged and previous is not None and previous.page == raw.page
        if tagged and previous is not None and previous.bbox and raw.bbox:
            size = raw.font_size or stats.body_size
            gap = raw.bbox[1] - previous.bbox[3]
            if gap > stats.line_gap + config.HEADING_SPACE_ABOVE * size:
                raw.spaced = True
        previous = raw


def mark_bold_subheadings(blocks: Sequence[RawBlock]) -> None:
    """As for DOCX paragraphs: a short tagged paragraph set entirely in bold, without a final
    full stop and followed by plain text, is a subheading one level below the heading it
    follows."""
    for index, raw in enumerate(blocks):
        text = raw.text.strip()
        plain = raw.heading_level is None and not raw.list_item and raw.rows is None
        if not raw.tagged or not text or not plain or raw.role or raw.footnote:
            continue
        if numbering_info(text):
            continue
        following = next((b for b in blocks[index + 1 :] if b.text.strip() or b.rows), None)
        plain_after = following is not None and (
            following.rows is not None or following.list_item or following.bold < config.BOLD_SHARE
        )
        short = len(text.split()) <= config.DOCX_SUBHEADING_WORDS
        if raw.bold >= config.DOCX_BOLD_HEADING_SHARE and short and text[-1] != "." and plain_after:
            raw.heading_source = "subheading"


def join_pages(pages: Sequence[list[tuple[Key | None, RawBlock]]]) -> list[RawBlock]:
    """Blocks of all pages; an element that goes on at the top of the next page (a paragraph,
    a list item, a table, a note) becomes one block again."""
    out: list[RawBlock] = []
    last: tuple[Key, RawBlock, int] | None = None  # key, block, page of its last part
    for blocks in pages:
        first_tagged = next((i for i, (key, _) in enumerate(blocks) if key is not None), None)
        for position, (key, raw) in enumerate(blocks):
            if (
                position == first_tagged
                and last is not None
                and key == last[0]
                and last[2] == raw.page - 1
            ):
                _append(last[1], raw)
                last = (last[0], last[1], raw.page)
                continue
            out.append(raw)
            if key is not None:
                last = (key, raw, raw.page)
    return out


def _append(target: RawBlock, part: RawBlock) -> None:
    if target.rows is not None and part.rows is not None:
        target.rows.extend(part.rows)
    else:
        target.text = f"{target.text}\n{part.text}"
    target.original = f"{target.original}\n{part.original}"
    target.footnote_refs.extend(part.footnote_refs)
