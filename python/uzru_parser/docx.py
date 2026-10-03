"""DOCX extraction with python-docx."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document as load_docx
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph

from .assemble import assemble_document
from .models import Document, Page
from .structure import RawBlock, build_blocks
from .text import CleanStats, compound_pairs

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
    styles = _StyleCache()
    page = 1
    for child in docx.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, docx)
            raw_blocks.append(_paragraph_block(paragraph, page, styles))
            page += len(paragraph._p.xpath(f".//{break_xpath}"))
        elif child.tag == qn("w:tbl"):
            raw_blocks.append(_table_block(Table(child, docx), page))

    last_page = max(page, 1)
    pages = [Page(number=number) for number in range(1, last_page + 1)]
    properties = docx.core_properties
    stats = CleanStats()
    compounds = compound_pairs(raw.text for raw in raw_blocks)
    return assemble_document(
        path,
        "docx",
        pages,
        build_blocks(raw_blocks, compounds=compounds, stats=stats),
        title=properties.title,
        author=properties.author,
        extra={"pages_approximate": True, **stats.as_dict()},
    )


@dataclass(frozen=True)
class _StyleInfo:
    heading_level: int | None
    list_style: bool
    size: float | None
    bold: bool


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
        if style.style_id == "Title":
            heading_level = 1
        elif match:
            heading_level = int(match.group(1))
        if heading_level is not None:
            break
    size = next((s.font.size.pt for s in chain if s.font.size is not None), None)  # type: ignore[attr-defined]
    bold = next((s.font.bold for s in chain if s.font.bold is not None), None)  # type: ignore[attr-defined]
    return _StyleInfo(
        heading_level=heading_level,
        list_style=any((s.style_id or "").startswith("List") for s in chain),
        size=size,
        bold=bool(bold),
    )


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


def _paragraph_block(paragraph: Paragraph, page: int, styles: _StyleCache) -> RawBlock:
    style = styles.info(paragraph)
    level = style.heading_level
    properties = paragraph._p.pPr
    numbered = properties is not None and properties.numPr is not None
    list_item = level is None and (numbered or style.list_style)
    size, bold = _font_stats(paragraph, style)
    text = paragraph.text
    return RawBlock(
        text=f"{BULLET}{text}" if list_item and text.strip() else text,
        page=page,
        font_size=size,
        bold=bold,
        heading_level=level,
        list_item=list_item,
    )


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
