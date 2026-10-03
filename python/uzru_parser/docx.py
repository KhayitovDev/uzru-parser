"""DOCX extraction with python-docx."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document as load_docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph

from . import config
from .assemble import assemble_document
from .models import Document, Page
from .structure import RawBlock, build_blocks
from .text import CleanStats, compound_pairs, numbering_info

BULLET = "• "
HEADING_STYLE_ID = re.compile(r"Heading(\d)")
HEADING_STYLE_NAME = re.compile(r"(?:heading|заголовок|sarlavha|сарлавҳа)\s*(\d)", re.IGNORECASE)
RENDERED_BREAK = "w:lastRenderedPageBreak"
EXPLICIT_BREAK = 'w:br[@w:type="page"]'


def parse_docx(path: str | Path) -> Document:
    path = Path(path)
    docx = load_docx(str(path))
    break_xpath = (
        RENDERED_BREAK if docx.element.body.xpath(f".//{RENDERED_BREAK}") else EXPLICIT_BREAK
    )

    raw_blocks: list[RawBlock] = []
    extras: dict[int, _Extra] = {}
    styles = _StyleCache()
    numbering = _Numbering(docx)
    page = 1
    for child in docx.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, docx)
            raw, extra = _paragraph_block(paragraph, page, styles, numbering)
            raw_blocks.append(raw)
            extras[id(raw)] = extra
            page += len(paragraph._p.xpath(f".//{break_xpath}"))
        elif child.tag == qn("w:tbl"):
            raw_blocks.append(_table_block(Table(child, docx), page))
    _mark_spacing(raw_blocks, extras)
    _mark_bold_subheadings(raw_blocks, extras)
    title = docx.core_properties.title or _leading_title(raw_blocks, extras)

    last_page = max(page, 1)
    pages = [Page(number=number) for number in range(1, last_page + 1)]
    properties = docx.core_properties
    stats = CleanStats()
    compounds = compound_pairs(raw.text for raw in raw_blocks)
    return assemble_document(
        path,
        "docx",
        pages,
        build_blocks(raw_blocks, compounds=compounds, stats=stats, page_layout=False),
        title=title or None,
        author=properties.author,
        extra={"pages_approximate": True, **stats.as_dict()},
    )


@dataclass(frozen=True)
class _StyleInfo:
    heading_level: int | None
    list_style: bool
    size: float | None
    bold: bool
    numbering: tuple[str, int] | None = None  # (numId, ilvl) set by the style
    keep_next: bool = False
    centred: bool = False


class _StyleCache:
    """Resolves each paragraph style once; documents reuse a handful of styles."""

    def __init__(self) -> None:
        self._cache: dict[str | None, _StyleInfo] = {}

    def info(self, paragraph: Paragraph) -> _StyleInfo:
        properties = paragraph._p.pPr
        style_id = properties.style if properties is not None else None
        if style_id not in self._cache:
            self._cache[style_id] = _resolve_style(paragraph)
        return self._cache[style_id]


def _style_chain(paragraph: Paragraph) -> list[BaseStyle]:
    chain: list[BaseStyle] = []
    style = paragraph.style
    while style is not None:
        chain.append(style)
        style = style.base_style
    return chain


def _resolve_style(paragraph: Paragraph) -> _StyleInfo:
    chain = _style_chain(paragraph)
    heading_level = None
    for style in chain:
        match = HEADING_STYLE_ID.fullmatch(style.style_id or "") or HEADING_STYLE_NAME.match(
            style.name or ""
        )
        outline = _outline_level(style.element.pPr)
        if style.style_id == "Title":
            heading_level = 1
        elif match:
            heading_level = int(match.group(1))
        elif outline is not None:
            heading_level = outline
        if heading_level is not None:
            break
    size = next((s.font.size.pt for s in chain if s.font.size is not None), None)  # type: ignore[attr-defined]
    bold = next((s.font.bold for s in chain if s.font.bold is not None), None)  # type: ignore[attr-defined]
    properties = [s.element.pPr for s in chain if s.element.pPr is not None]
    numbering = next((n for p in properties if (n := _num_pr(p)) is not None), None)
    keep_next = any(p.find(qn("w:keepNext")) is not None for p in properties)
    alignment = next(
        (s.paragraph_format.alignment for s in chain if s.paragraph_format.alignment is not None),  # type: ignore[attr-defined]
        None,
    )
    return _StyleInfo(
        heading_level=heading_level,
        list_style=any((s.style_id or "").startswith("List") for s in chain),
        size=size,
        bold=bool(bold),
        numbering=numbering,
        keep_next=keep_next,
        centred=alignment == WD_ALIGN_PARAGRAPH.CENTER,
    )


def _outline_level(properties: object) -> int | None:
    """Word's own outline level (``w:outlineLvl``, 0-based; 9 means body text)."""
    if properties is None:
        return None
    element = properties.find(qn("w:outlineLvl"))  # type: ignore[attr-defined]
    if element is None:
        return None
    value = int(element.get(qn("w:val"), "9"))
    return value + 1 if value < 9 else None


def _num_pr(properties: object) -> tuple[str, int] | None:
    """(numId, ilvl) of a ``w:numPr`` in paragraph properties; numId 0 switches numbering off."""
    if properties is None:
        return None
    num_pr = properties.find(qn("w:numPr"))  # type: ignore[attr-defined]
    if num_pr is None:
        return None
    num_id = num_pr.find(qn("w:numId"))
    level = num_pr.find(qn("w:ilvl"))
    if num_id is None:
        return None
    return num_id.get(qn("w:val"), "0"), int(
        level.get(qn("w:val"), "0")
    ) if level is not None else 0


ROMAN_VALUES = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


def _roman(number: int) -> str:
    out = ""
    for value, letters in ROMAN_VALUES:
        while number >= value:
            out += letters
            number -= value
    return out


def _letters(number: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa (Word repeats the letter)."""
    return chr(ord("a") + (number - 1) % 26) * ((number - 1) // 26 + 1)


def _format_number(number: int, kind: str) -> str:
    formats = {
        "decimal": str(number),
        "decimalZero": f"{number:02d}",
        "lowerLetter": _letters(number),
        "upperLetter": _letters(number).upper(),
        "lowerRoman": _roman(number),
        "upperRoman": _roman(number).upper(),
        "none": "",
    }
    return formats.get(kind, str(number))


class _Numbering:
    """Word list numbering: each (numId, level) has a format and a label template such as
    "%1." or "%1.%2)"; counters run per list and restart deeper levels, as Word does."""

    def __init__(self, docx: object) -> None:
        self.levels: dict[str, dict[int, tuple[str, str, int]]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        try:
            root = docx.part.numbering_part.element  # type: ignore[attr-defined]
        except (KeyError, NotImplementedError, AttributeError):
            return
        abstract: dict[str, dict[int, tuple[str, str, int]]] = {}
        for node in root.findall(qn("w:abstractNum")):
            levels: dict[int, tuple[str, str, int]] = {}
            for lvl in node.findall(qn("w:lvl")):
                fmt = lvl.find(qn("w:numFmt"))
                text = lvl.find(qn("w:lvlText"))
                start = lvl.find(qn("w:start"))
                levels[int(lvl.get(qn("w:ilvl"), "0"))] = (
                    fmt.get(qn("w:val"), "decimal") if fmt is not None else "decimal",
                    text.get(qn("w:val"), "") if text is not None else "",
                    int(start.get(qn("w:val"), "1")) if start is not None else 1,
                )
            abstract[node.get(qn("w:abstractNumId"), "")] = levels
        for node in root.findall(qn("w:num")):
            reference = node.find(qn("w:abstractNumId"))
            if reference is not None:
                levels = abstract.get(reference.get(qn("w:val"), ""), {})
                self.levels[node.get(qn("w:numId"), "")] = levels

    def label(self, num_id: str, level: int) -> str | None:
        """The marker Word shows for the next item of list ``num_id`` at ``level``."""
        levels = self.levels.get(num_id)
        if not levels or level not in levels:
            return None
        kind, template, start = levels[level]
        counters = self.counters.setdefault(num_id, {})
        counters[level] = counters.get(level, start - 1) + 1
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        if kind == "bullet":
            return "•"

        def value(match: re.Match[str]) -> str:
            at = int(match.group(1)) - 1
            fmt, _, first = levels.get(at, ("decimal", "", 1))
            return _format_number(counters.get(at, first), fmt)

        return re.sub(r"%(\d)", value, template).strip() or None


def _font_stats(paragraph: Paragraph, style: _StyleInfo) -> tuple[float | None, float]:
    sizes: list[float] = []
    chars = bold_chars = 0
    for run in paragraph.runs:
        length = len(run.text.strip())
        if not length:
            continue
        chars += length
        size = run.font.size.pt if run.font.size is not None else style.size
        if size is not None:
            sizes.append(float(size))
        if run.bold if run.bold is not None else style.bold:
            bold_chars += length
    return (max(sizes) if sizes else None), (bold_chars / chars if chars else 0.0)


def _paragraph_block(
    paragraph: Paragraph, page: int, styles: _StyleCache, numbering: _Numbering
) -> tuple[RawBlock, _Extra]:
    style = styles.info(paragraph)
    properties = paragraph._p.pPr
    level = _outline_level(properties) or style.heading_level
    own = _num_pr(properties)
    num = own if own is not None else style.numbering
    numbered = num is not None and num[0] != "0"
    list_item = level is None and (numbered or style.list_style)
    size, bold = _font_stats(paragraph, style)
    text = paragraph.text
    marker = numbering.label(*num) if numbered and num is not None and text.strip() else None
    if list_item and text.strip():
        text = f"{marker} {text}" if marker else f"{BULLET}{text}"
    keep_next = style.keep_next or (
        properties is not None and properties.find(qn("w:keepNext")) is not None
    )
    alignment = paragraph.paragraph_format.alignment
    centred = alignment == WD_ALIGN_PARAGRAPH.CENTER if alignment is not None else style.centred
    raw = RawBlock(
        text=text,
        page=page,
        font_size=size,
        bold=bold,
        heading_level=level,
        list_item=list_item,
    )
    return raw, _Extra(keep_next, centred, _space_before(paragraph))


@dataclass(frozen=True)
class _Extra:
    """Word-only facts about a paragraph, used while the reader decides headings."""

    keep_next: bool = False
    centred: bool = False
    space_before: float = 0.0


NO_EXTRA = _Extra()


def _space_before(paragraph: Paragraph) -> float:
    space = paragraph.paragraph_format.space_before
    if space is None:
        style = paragraph.style
        while style is not None and space is None:
            space = style.paragraph_format.space_before
            style = style.base_style
    return float(space.pt) if space is not None else 0.0


def _mark_spacing(blocks: list[RawBlock], extras: dict[int, _Extra]) -> None:
    """Paragraphs with clearly more space above them than body paragraphs are ``spaced``,
    the same signal PDF layout gives."""
    spaces = sorted(
        extras.get(id(raw), NO_EXTRA).space_before for raw in blocks if raw.text.strip()
    )
    if not spaces:
        return
    body = spaces[len(spaces) // 2]
    for raw in blocks:
        space = extras.get(id(raw), NO_EXTRA).space_before
        if space > max(body * config.DOCX_SPACED_RATIO, body + 1.0):
            raw.spaced = True


def _mark_bold_subheadings(blocks: list[RawBlock], extras: dict[int, _Extra]) -> None:
    """A short paragraph set entirely in bold (or kept with the next one by Word), without a
    final full stop and followed by plain text, is a subheading: one level below the
    numbered heading it follows. A bold term opening a plain paragraph is not one."""
    for index, raw in enumerate(blocks):
        text = raw.text.strip()
        if not text or raw.heading_level is not None or raw.list_item or raw.rows is not None:
            continue
        if numbering_info(text):  # numbered titles carry their own signal
            continue
        keep_next = extras.get(id(raw), NO_EXTRA).keep_next
        bold = raw.bold >= config.DOCX_BOLD_HEADING_SHARE
        short = len(text.split()) <= config.DOCX_SUBHEADING_WORDS
        following = next((b for b in blocks[index + 1 :] if b.text.strip() or b.rows), None)
        plain_after = following is not None and (
            following.rows is not None or following.list_item or following.bold < config.BOLD_SHARE
        )
        styled = bold or (keep_next and raw.bold >= config.BOLD_SHARE)
        if styled and short and text[-1] != "." and plain_after:
            raw.heading_source = "subheading"


def _leading_title(blocks: list[RawBlock], extras: dict[int, _Extra]) -> str:
    """The centred bold (or larger) lines opening the document before its first heading: the
    document's title when Word's title property is empty. They become ``title_page``."""
    sizes = sorted(raw.font_size for raw in blocks if raw.font_size and raw.text.strip())
    body = sizes[len(sizes) // 2] if sizes else 0.0
    lines: list[str] = []
    for raw in blocks:
        if not raw.text.strip():
            continue
        text = " ".join(raw.text.split())
        centred = extras.get(id(raw), NO_EXTRA).centred
        larger = body and raw.font_size and raw.font_size > body
        styled_heading = raw.heading_level is not None and raw.heading_source != "subheading"
        if styled_heading or numbering_info(text) or raw.list_item:
            break
        if not centred or not (raw.bold >= config.BOLD_SHARE or larger):
            break
        if lines and _capitals(text) != _capitals(lines[0]):  # "UMUMIY QISM" after the title
            break
        lines.append(text)
    if not lines:
        return ""
    for raw in [b for b in blocks if b.text.strip()][: len(lines)]:
        raw.role = "title_page"
        raw.heading_source = None
    return " ".join(lines)


def _capitals(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) >= 0.8 * len(letters)


def _table_block(table: Table, page: int) -> RawBlock:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        previous = None
        for cell in row.cells:
            if cell._tc is not previous:
                cells.append(cell.text)
            previous = cell._tc
        rows.append(cells)
    return RawBlock(text="", page=page, rows=rows)
