"""DOCX extraction with python-docx."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document as load_docx
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph

from .assemble import assemble_document
from .models import Document, Page
from .structure import RawBlock, build_blocks

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
    page = 1
    for child in docx.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, docx)
            raw_blocks.append(_paragraph_block(paragraph, page))
            page += len(paragraph._p.xpath(f".//{break_xpath}"))
        elif child.tag == qn("w:tbl"):
            raw_blocks.append(_table_block(Table(child, docx), page))

    last_page = max(page, 1)
    pages = [Page(number=number) for number in range(1, last_page + 1)]
    properties = docx.core_properties
    return assemble_document(
        path,
        "docx",
        pages,
        build_blocks(raw_blocks),
        title=properties.title,
        author=properties.author,
        extra={"pages_approximate": True},
    )


def _style_chain(paragraph: Paragraph) -> list[BaseStyle]:
    chain: list[BaseStyle] = []
    style = paragraph.style
    while style is not None:
        chain.append(style)
        style = style.base_style
    return chain


def _heading_level(paragraph: Paragraph) -> int | None:
    for style in _style_chain(paragraph):
        if style.style_id == "Title":
            return 1
        match = HEADING_STYLE_ID.fullmatch(style.style_id or "") or HEADING_STYLE_NAME.match(
            style.name or ""
        )
        if match:
            return int(match.group(1))
    return None


def _is_list_item(paragraph: Paragraph) -> bool:
    properties = paragraph._p.pPr
    if properties is not None and properties.numPr is not None:
        return True
    return any((style.style_id or "").startswith("List") for style in _style_chain(paragraph))


def _style_value(paragraph: Paragraph, attribute: str) -> float | bool | None:
    for style in _style_chain(paragraph):
        value = getattr(style.font, attribute, None)  # type: ignore[attr-defined]
        if value is not None:
            return value.pt if attribute == "size" else value  # type: ignore[no-any-return]
    return None


def _font_stats(paragraph: Paragraph) -> tuple[float | None, float]:
    style_size = _style_value(paragraph, "size")
    style_bold = bool(_style_value(paragraph, "bold"))
    sizes: list[float] = []
    chars = bold_chars = 0
    for run in paragraph.runs:
        length = len(run.text.strip())
        if not length:
            continue
        chars += length
        size = run.font.size.pt if run.font.size is not None else style_size
        if size is not None:
            sizes.append(float(size))
        if run.bold if run.bold is not None else style_bold:
            bold_chars += length
    return (max(sizes) if sizes else None), (bold_chars / chars if chars else 0.0)


def _paragraph_block(paragraph: Paragraph, page: int) -> RawBlock:
    level = _heading_level(paragraph)
    list_item = level is None and _is_list_item(paragraph)
    size, bold = _font_stats(paragraph)
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
