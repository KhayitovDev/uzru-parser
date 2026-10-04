"""PDF extraction with PyMuPDF.

Two routes lead to the same blocks. A tagged PDF whose structure tree passes the checks of
:mod:`.tagged` gives its paragraphs, headings, lists, tables and notes directly ("tagged");
any other PDF is rebuilt from its layout ("rules"). Order of work on the rules route:
characters are cleaned per span and line (symbol fonts, look-alike letters, apostrophes,
spaces), lines are rebuilt into paragraphs, hyphens are rejoined, page furniture / footnotes /
title page / contents are marked, then headings, language and blocks are built.
"""

from __future__ import annotations

import functools
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from . import config, tagged
from . import layout_model as layout_models
from .assemble import assemble_document
from .columns import reading_regions
from .confidence import page_confidence
from .layout import mark_footnotes, mark_title_page, mark_toc, strip_page_furniture
from .models import Document, Page
from .paragraphs import (
    BBox,
    LayoutStats,
    Line,
    build_paragraphs,
    figure_regions,
    group_formula_debris,
    layout_stats,
)
from .profile import StyleProfile, build_profile
from .structure import OutlineEntry, RawBlock, build_blocks
from .tables import table_score
from .text import CleanStats, Hyphenator, clean, compound_pairs, map_symbol_font

PYMUPDF_BOLD_FLAG = 16
PYMUPDF_ITALIC_FLAG = 2
PYMUPDF_SUPERSCRIPT_FLAG = 1
IMAGE_BLOCK = 1
SYMBOL_FONTS = ("symbol", "wingding", "webding", "dingbats")
MAX_MARK_CHARS = 3
MARK_SIZE_RATIO = 0.8
MARK_RAISE_RATIO = 0.15
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
_ONLY_PRIVATE_USE = re.compile(r"\s*[\ue000-\uf8ff]+\s*")
_SENTENCE_END = re.compile(r"[.!?:…;]\s*$")
_LONG_WORD = re.compile(r"[^\W\d_]{4,}")
#: A table cell holding a number: "12", "-3,5", "1 250", "45%", "(12.0)".
_NUMBER_CELL = re.compile(r"^\s*[-–+(]?\d[\d\s.,]*%?\)?\s*$")
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_FONT_STYLE_WORDS = re.compile(
    r"(bold|italic|oblique|regular|semibold|demibold|medium|light|black|heavy|roman$)"
)
_FONT_VENDOR_SUFFIX = re.compile(r"(psmt|mt|ps)$")
#: PyMuPDF is not thread-safe, and ``Page.find_tables`` flips a process-wide setting that
#: changes later text boxes; one document is read at a time, in any thread.
_PYMUPDF_LOCK = threading.Lock()


@dataclass
class _PageContent:
    number: int
    lines: list[Line]
    tables: list[RawBlock]
    drawings: list[BBox]  # vector drawings and images, grouped into figures later
    boxes: list[BBox]  # filled rectangles that may hold side boxes of text
    page_box: BBox
    needs_ocr: bool


@dataclass
class _TaggedRead:
    """The tagged route's result: the verdict on the tags and, when they pass, the blocks."""

    check: tagged.Check
    stats: CleanStats
    pages: list[Page]
    blocks: list[RawBlock]
    layout: LayoutStats
    compounds: set[str]
    #: Per page, the lines of each tagged element and the untagged lines (for confidence).
    parts: dict[int, list[list[Line]]] = field(default_factory=dict)


def parse_pdf(
    path: str | Path, detect_tables: bool = True, layout_model: bool | str | Path = False
) -> Document:
    """Parse a PDF. ``layout_model`` (off by default) lets the optional layout model correct
    the pages the rules are unsure about: ``True`` uses ``UZRU_LAYOUT_MODEL`` or the shipped
    model file, a path names the ONNX file."""
    path = Path(path)
    stats = CleanStats()
    pages: list[Page] = []
    contents: list[_PageContent] = []

    with _PYMUPDF_LOCK, _open(path) as pdf:
        meta = pdf.metadata or {}
        outline = [
            OutlineEntry(level=entry[0], title=clean(entry[1]), page=entry[2])
            for entry in pdf.get_toc(simple=True)
        ]
        tags = tagged.inspect(pdf)
        read = _read_tagged(pdf) if tags.usable else None
        if read is not None and read.check.ok:
            stats.add(read.stats)
            document = _tagged_document(path, meta, outline, read, tags, stats)
            if layout_models.model_path(layout_model) is not None:  # the tags are trusted
                document.metadata.extra["layout_model"] = {"status": "not needed", "pages": []}
            return document
        if tags.slow:
            tagged.detach(pdf)
        for number, page in enumerate(pdf, start=1):
            content = _read_page(page, number, detect_tables, stats)
            pages.append(
                Page(
                    number=number,
                    width=page.rect.width,
                    height=page.rect.height,
                    needs_ocr=content.needs_ocr,
                )
            )
            contents.append(content)

    layout = layout_stats([content.lines for content in contents])
    compounds = compound_pairs(line.text for content in contents for line in content.lines)
    hyphenator = Hyphenator(sorted(compounds))
    rules = _RulesPass(pages, contents, layout, hyphenator)
    raw_blocks, removed, profile = rules.run({})
    route = "rules"
    model_extra: dict[str, Any] = {}
    model = layout_models.model_path(layout_model)
    if model is not None:
        hints, model_extra = _model_hints(path, model, pages, contents, layout, detect_tables)
        if hints:
            raw_blocks, removed, profile = rules.run(hints)
            for number in hints:
                pages[number - 1].extra["layout_model"] = True
            route = "rules+layout_model"
    document_blocks = build_blocks(
        raw_blocks,
        outline=outline,
        compounds=compounds,
        stats=stats,
        text_is_clean=True,
        profile=profile,
    )
    return assemble_document(
        path,
        "pdf",
        pages,
        document_blocks,
        title=meta.get("title") or _title_page_title(raw_blocks),
        author=meta.get("author"),
        extra={
            "removed_page_furniture": removed,
            **stats.as_dict(),
            "pdf_route": route,
            **_tags_extra(tags, read),
            "styles": profile.summary(),
            **model_extra,
        },
    )


class _RulesPass:
    """Paragraphs, tables and page-level marks of an untagged PDF, with optional
    corrections (layout-model hints) for some pages; each run rates the pages again."""

    def __init__(
        self,
        pages: list[Page],
        contents: list[_PageContent],
        layout: LayoutStats,
        hyphenator: Hyphenator,
    ) -> None:
        self.pages = pages
        self.contents = contents
        self.layout = layout
        self.hyphenator = hyphenator

    def run(
        self, hints: dict[int, layout_models.Hints]
    ) -> tuple[list[RawBlock], int, StyleProfile]:
        raw_blocks: list[RawBlock] = []
        parts_by_page: dict[int, list[list[Line]]] = {}
        tables_by_page: dict[int, list[list[list[str]]]] = {}
        for content in self.contents:
            blocks, parts, tables = self._page(content, hints.get(content.number))
            parts_by_page[content.number] = parts
            tables_by_page[content.number] = [t.rows for t in tables if t.rows]
            raw_blocks.extend(blocks)
        heights = {page.number: page.height for page in self.pages}
        raw_blocks, removed = strip_page_furniture(raw_blocks, heights)
        mark_footnotes(raw_blocks, heights, self.layout.body_size)
        mark_title_page(raw_blocks, len(self.pages))
        mark_toc(raw_blocks, len(self.pages))
        raw_blocks = group_formula_debris(raw_blocks)
        profile = build_profile(raw_blocks, heights)
        _rate_pages(self.pages, parts_by_page, tables_by_page, raw_blocks, profile)
        return raw_blocks, removed, profile

    def _page(
        self, content: _PageContent, hints: layout_models.Hints | None
    ) -> tuple[list[RawBlock], list[list[Line]], list[RawBlock]]:
        layout = self.layout
        lines, drawings, tables = content.lines, content.drawings, content.tables
        if hints is not None:
            tables = tables + hints.found_tables
            lines = [
                line
                for line in lines
                if not any(layout_models.inside(line.bbox, box) for box in hints.furniture)
                and not any(_inside(line.bbox, table.bbox) for table in hints.found_tables)
            ]
            drawings = drawings + hints.figures
        regions = figure_regions(drawings, content.page_box, layout.body_size, lines)
        if hints is not None and hints.order:
            parts = layout_models.order_lines(lines, hints.order)
        else:
            parts = reading_regions(lines, content.boxes, layout.body_size)
        blocks = [
            block
            for part in parts
            for block in build_paragraphs(part, content.number, layout, regions)
        ]
        for block in blocks:
            block.text = self.hyphenator.repair(block.text)
        if hints is not None:
            _apply_marks(blocks, hints, content.page_box)
        return _merge_tables(blocks, tables), parts, tables


def _apply_marks(blocks: list[RawBlock], hints: layout_models.Hints, page_box: BBox) -> None:
    """Formula fragments, titles and footnotes the layout model points out."""
    height = page_box[3] - page_box[1]
    for raw in blocks:
        if raw.role is None and any(layout_models.inside(raw.bbox, b) for b in hints.formulas):
            if len(_LONG_WORD.findall(raw.text)) <= config.LAYOUT_FORMULA_WORDS:
                raw.role = "formula"
        if any(layout_models.inside(raw.bbox, box) for box in hints.titles):
            raw.layout_title = True
        bottom = raw.bbox is not None and raw.bbox[1] >= config.FOOTNOTE_ZONE * height
        if bottom and any(layout_models.inside(raw.bbox, box) for box in hints.footnotes):
            raw.footnote = True


def _model_hints(
    path: Path,
    model: Path,
    pages: list[Page],
    contents: list[_PageContent],
    layout: LayoutStats,
    detect_tables: bool,
) -> tuple[dict[int, layout_models.Hints], dict[str, Any]]:
    """Run the layout model on the low-confidence pages that have text; tables inside its
    table regions are looked for on the page itself."""
    low = [
        page
        for page in pages
        if not page.needs_ocr
        and page.extra.get("confidence", 1.0) < config.LOW_PAGE_CONFIDENCE
        and contents[page.number - 1].lines
    ]
    if not low:
        return {}, {"layout_model": {"status": "not needed", "pages": []}}
    session, status = layout_models.load(model)
    if session is None:
        return {}, {"layout_model": {"status": status, "pages": []}}
    hints: dict[int, layout_models.Hints] = {}
    with _PYMUPDF_LOCK, _open(path) as pdf:
        for page in low:
            content = contents[page.number - 1]
            pdf_page = pdf.load_page(page.number - 1)
            regions = layout_models.detect(session, pdf_page)
            found = layout_models.hints(
                regions, content.page_box, page.extra.get("issues", []), layout.body_size
            )
            if detect_tables:
                found.found_tables = _model_tables(pdf_page, page.number, found.tables, content)
            hints[page.number] = found
    return hints, {"layout_model": {"status": "used", "pages": [p.number for p in low]}}


def _model_tables(
    page: pymupdf.Page, number: int, boxes: list[BBox], content: _PageContent
) -> list[RawBlock]:
    """Tables inside the model's table regions that the rules missed: ruling lines first,
    then text alignment, the better-scoring reading kept."""
    found: list[RawBlock] = []
    for box in boxes:
        if any(_overlap(box, table.bbox) > 0.5 for table in content.tables):
            continue
        readings = [
            table
            for strategy in ("lines", "text")
            for table in _tables_from(
                page.find_tables(clip=box, strategy=strategy).tables,  # type: ignore[no-untyped-call]
                number,
            )
        ]
        best = max(readings, key=lambda t: table_score(t.rows or []), default=None)
        if best is not None and table_score(best.rows or []) >= config.TEXT_TABLE_MIN_SCORE:
            found.append(best)
    return found


def _rate_pages(
    pages: list[Page],
    parts: dict[int, list[list[Line]]],
    tables: dict[int, list[list[list[str]]]],
    blocks: list[RawBlock],
    profile: StyleProfile,
) -> None:
    """Each page's confidence and issues, in ``page.extra``; a page with images and no text
    (it needs OCR) gets none and the issue ``no_text``."""
    by_page: dict[int, list[RawBlock]] = {}
    for raw in blocks:
        by_page.setdefault(raw.page, []).append(raw)
    for page in pages:
        regions = parts.get(page.number, [])
        if page.needs_ocr:
            page.extra = {"confidence": 0.0, "issues": ["no_text"]}
            continue
        score, issues = page_confidence(
            regions, tables.get(page.number, []), by_page.get(page.number, []), profile
        )
        page.extra = {"confidence": score, "issues": issues}


def _tags_extra(tags: tagged.TagSummary, read: _TaggedRead | None) -> dict[str, Any]:
    """What the document's tags were and why they were (not) used."""
    if not tags.tree:
        return {}
    info: dict[str, Any] = {**tags.as_dict(), "used": bool(read and read.check.ok)}
    if tags.slow:
        info["reason"] = "too slow to follow"
    elif read is not None:
        info["coverage"] = round(read.check.coverage, 3)
        if read.check.reason:
            info["reason"] = read.check.reason
    return {"pdf_tags": info}


def _read_tagged(pdf: pymupdf.Document) -> _TaggedRead:
    """Read every page with its structure, check the tags, and build the blocks if they
    pass. Untagged text of a page is rebuilt from its lines and placed by its position."""
    stats = CleanStats()
    pages: list[Page] = []
    reads: list[tuple[_PageContent, list[tagged.TaggedLine]]] = []
    for number, page in enumerate(tagged.pages(pdf), start=1):
        content, lines = _read_tagged_page(page, number, stats)
        pages.append(
            Page(
                number=number,
                width=page.rect.width,
                height=page.rect.height,
                needs_ocr=content.needs_ocr,
            )
        )
        reads.append((content, lines))
    layout = layout_stats([content.lines for content, _ in reads])
    grouped = [
        tagged.page_units(lines, content.page_box[3] - content.page_box[1])
        for content, lines in reads
    ]
    total = sum(content_line.chars for content, _ in reads for content_line in content.lines)
    check = tagged.check([units for units, _ in grouped], total, layout.line_gap)
    if not check.ok:
        return _TaggedRead(check, stats, pages, [], layout, set())

    compounds = compound_pairs(line.text for content, _ in reads for line in content.lines)
    hyphenator = Hyphenator(sorted(compounds))
    elements = tagged.Elements(pdf)
    per_page: list[list[tuple[tagged.Key | None, RawBlock]]] = []
    parts: dict[int, list[list[Line]]] = {}
    for (content, _), (units, loose) in zip(reads, grouped, strict=True):
        parts[content.number] = [[t.line for t in unit.lines] for unit in units] + [loose]
        blocks: list[tuple[tagged.Key | None, RawBlock]] = [
            (unit.key, tagged.unit_block(unit, content.number, elements.spans)) for unit in units
        ]
        regions = figure_regions(content.drawings, content.page_box, layout.body_size, loose)
        loose_blocks = [
            block
            for part in reading_regions(loose, content.boxes, layout.body_size)
            for block in build_paragraphs(part, content.number, layout, regions)
        ]
        per_page.append(_place_by_position(blocks, loose_blocks))
    raw_blocks = tagged.join_pages(per_page)
    for raw in raw_blocks:
        if raw.rows is None:
            raw.text = hyphenator.repair(raw.text)
    return _TaggedRead(check, stats, pages, raw_blocks, layout, compounds, parts)


def _tagged_document(
    path: Path,
    meta: dict[str, Any],
    outline: list[OutlineEntry],
    read: _TaggedRead,
    tags: tagged.TagSummary,
    stats: CleanStats,
) -> Document:
    """Blocks of a tagged PDF: the tags already say what each block is; page furniture,
    footnotes in untagged text, contents and formula fragments are found as on the rules
    route, and paragraphs are joined as for DOCX (the author's paragraphs, not page lines)."""
    heights = {page.number: page.height for page in read.pages}
    raw_blocks, removed = strip_page_furniture(read.blocks, heights)
    mark_footnotes(raw_blocks, heights, read.layout.body_size)
    mark_toc(raw_blocks, len(read.pages))
    raw_blocks = group_formula_debris(raw_blocks)
    tagged.mark_spacing(raw_blocks, read.layout)
    tagged.mark_bold_subheadings(raw_blocks)
    profile = build_profile(raw_blocks, heights)
    tables: dict[int, list[list[list[str]]]] = {}
    for raw in raw_blocks:
        if raw.rows:
            tables.setdefault(raw.page, []).append(raw.rows)
    _rate_pages(read.pages, read.parts, tables, raw_blocks, profile)
    document_blocks = build_blocks(
        raw_blocks,
        outline=outline,
        compounds=read.compounds,
        stats=stats,
        text_is_clean=True,
        page_layout=False,
        profile=profile,
    )
    return assemble_document(
        path,
        "pdf",
        read.pages,
        document_blocks,
        title=meta.get("title") or None,
        author=meta.get("author"),
        extra={
            "removed_page_furniture": removed,
            **stats.as_dict(),
            "pdf_route": "tagged",
            **_tags_extra(tags, read),
            "styles": profile.summary(),
        },
    )


def _place_by_position(
    blocks: list[tuple[tagged.Key | None, RawBlock]], loose: list[RawBlock]
) -> list[tuple[tagged.Key | None, RawBlock]]:
    """Untagged blocks go before the first tagged block that starts below them."""
    slots: dict[int, list[tuple[tagged.Key | None, RawBlock]]] = {}
    for raw in loose:
        top = raw.bbox[1] if raw.bbox else 0.0
        slot = next(
            (i for i, (_, block) in enumerate(blocks) if block.bbox and block.bbox[1] >= top),
            len(blocks),
        )
        slots.setdefault(slot, []).append((None, raw))
    placed: list[tuple[tagged.Key | None, RawBlock]] = []
    for index, item in enumerate(blocks):
        placed.extend(slots.get(index, []))
        placed.append(item)
    placed.extend(slots.get(len(blocks), []))
    return placed


def _read_tagged_page(
    page: pymupdf.Page, number: int, stats: CleanStats
) -> tuple[_PageContent, list[tagged.TaggedLine]]:
    """A page's lines in structure order with their structure paths (no table search: a
    tagged table is in the tags)."""
    drawings = page.get_cdrawings()  # type: ignore[no-untyped-call]
    flags = pymupdf.TEXTFLAGS_DICT | tagged.STRUCTURE_FLAG
    page_dict = page.get_text("dict", flags=flags)  # type: ignore[no-untyped-call]
    lines: list[tagged.TaggedLine] = []
    images: list[BBox] = []
    chars = 0
    for block_number, (path, block) in enumerate(tagged.text_blocks(page_dict)):
        if block["type"] == IMAGE_BLOCK:
            images.append(tuple(block["bbox"]))
            continue
        block_lines = [_line(raw, block_number, stats, clean_text=False) for raw in block["lines"]]
        block_lines = [line for line in block_lines if line.text.strip()]
        _clean_lines(block_lines, stats)
        for line in block_lines:
            if line.text.strip():
                chars += line.chars
                lines.append(tagged.TaggedLine(line, path))
    content = _PageContent(
        number=number,
        lines=[item.line for item in lines],
        tables=[],
        drawings=[tuple(d["rect"]) for d in drawings] + images,
        boxes=[tuple(d["rect"]) for d in drawings if d.get("fill") is not None],
        page_box=tuple(page.rect),
        needs_ocr=_is_scanned(images, tuple(page.rect), chars),
    )
    return content, lines


def _open(path: Path) -> pymupdf.Document:
    """Open a PDF, turning PyMuPDF's errors into clear ones."""
    from .parser import DocumentError

    try:
        pdf = pymupdf.open(path)  # type: ignore[no-untyped-call]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError) as error:
        raise DocumentError(f"{path.name} is not a valid PDF file") from error
    if pdf.needs_pass:
        pdf.close()  # type: ignore[no-untyped-call]
        raise DocumentError(f"{path.name} is password-protected")
    return pdf


def _title_page_title(blocks: list[RawBlock]) -> str | None:
    """The title page's largest lines, in reading order, when the file names no title."""
    page = [b for b in blocks if b.role == "title_page" and b.font_size and b.text.strip()]
    if not page:
        return None
    largest = max(b.font_size or 0.0 for b in page)
    title = [
        " ".join(b.text.split())
        for b in page
        if (b.font_size or 0.0) >= largest / config.LARGER_FONT_RATIO
    ]
    return " ".join(title) or None


def _read_page(
    page: pymupdf.Page, number: int, detect_tables: bool, stats: CleanStats
) -> _PageContent:
    drawings = page.get_cdrawings()  # type: ignore[no-untyped-call]
    tables = _find_tables(page, number, len(drawings)) if detect_tables else []
    page_dict = page.get_text("dict", sort=True)  # type: ignore[no-untyped-call]
    lines: list[Line] = []
    images: list[BBox] = []
    chars = 0

    for block_number, block in enumerate(page_dict["blocks"]):
        if block["type"] == IMAGE_BLOCK:
            images.append(tuple(block["bbox"]))
            continue
        block_lines = [_line(raw, block_number, stats, clean_text=False) for raw in block["lines"]]
        block_lines = [line for line in block_lines if line.text.strip()]
        _clean_lines(block_lines, stats)
        for line in block_lines:
            if not line.text.strip():
                continue
            chars += line.chars
            lines.append(line)
    if detect_tables:
        tables = _add_text_tables(page, number, tables, lines)
    lines = [line for line in lines if not any(_inside(line.bbox, t.bbox) for t in tables)]

    rects: list[BBox] = [tuple(d["rect"]) for d in drawings]
    for table in tables:
        lines = _extend_table(table, rects, lines)

    return _PageContent(
        number=number,
        lines=lines,
        tables=tables,
        drawings=[tuple(d["rect"]) for d in drawings] + images,
        boxes=[tuple(d["rect"]) for d in drawings if d.get("fill") is not None],
        page_box=tuple(page.rect),
        needs_ocr=_is_scanned(images, tuple(page.rect), chars),
    )


def _is_scanned(images: list[BBox], page_box: BBox, chars: int) -> bool:
    """A page whose text is in pictures: images and almost no text, or images covering most
    of the page with only a stamp or a page number as text."""
    if not images:
        return False
    if chars < config.MIN_TEXT_CHARS:
        return True
    x0, y0, x1, y1 = page_box
    area = (x1 - x0) * (y1 - y0)
    covered = sum(
        max(0.0, min(b[2], x1) - max(b[0], x0)) * max(0.0, min(b[3], y1) - max(b[1], y0))
        for b in images
    )
    mostly_images = area > 0 and covered >= config.SCAN_IMAGE_COVER * area
    return mostly_images and chars < config.SCAN_MAX_TEXT_CHARS


def _clean_lines(lines: list[Line], stats: CleanStats) -> None:
    """Clean the text of one block's lines with a single call; per line only when a line
    vanishes in cleaning and the lines no longer line up."""
    if not lines:
        return
    batch = CleanStats()
    parts = clean("\n".join(line.text for line in lines), batch).split("\n")
    if len(parts) == len(lines):
        stats.add(batch)
        for line, part in zip(lines, parts, strict=True):
            line.text = part
        return
    for line in lines:
        line.text = clean(line.text, stats)


@functools.lru_cache(maxsize=256)
def _symbol_font(font: str) -> bool:
    name = font.lower()
    return any(symbol in name for symbol in SYMBOL_FONTS)


@functools.lru_cache(maxsize=256)
def _bold_font(font: str) -> bool:
    return "bold" in font.lower()


@functools.lru_cache(maxsize=256)
def _italic_font(font: str) -> bool:
    name = font.lower()
    return "italic" in name or "oblique" in name


@functools.lru_cache(maxsize=256)
def _font_family(font: str) -> str:
    """The family of a PDF font name: "ABCDEF+TimesNewRomanPS-BoldItalicMT" -> "timesnewroman"."""
    name = _SUBSET_PREFIX.sub("", font)
    name = re.split(r"[-,]", name, maxsplit=1)[0]
    name = _FONT_STYLE_WORDS.sub("", name.lower())
    return _FONT_VENDOR_SUFFIX.sub("", name.replace(" ", "")) or font.lower()


def _is_symbol_span(span: dict[str, Any]) -> bool:
    return _symbol_font(span["font"]) or bool(_ONLY_PRIVATE_USE.fullmatch(span["text"]))


def _is_reference_mark(
    span: dict[str, Any], kept: list[str], line_size: float | None, baseline: float
) -> bool:
    """A small raised number glued to the end of a word: a footnote reference mark."""
    text = span["text"].strip()
    if not text.isdigit() or len(text) > MAX_MARK_CHARS or not "".join(kept).strip():
        return False
    if span["flags"] & PYMUPDF_SUPERSCRIPT_FLAG:
        return True
    if not line_size:
        return False
    small = span["size"] <= MARK_SIZE_RATIO * line_size
    raised = span["origin"][1] <= baseline - MARK_RAISE_RATIO * line_size
    return bool(small and raised)


def _line(
    raw_line: dict[str, Any], block_number: int, stats: CleanStats, clean_text: bool = True
) -> Line:
    """One printed line with cleaned text, its style and its footnote reference marks."""
    spans = raw_line["spans"]
    symbol = [_is_symbol_span(s) for s in spans]
    line_size = max(
        (s["size"] for s, sym in zip(spans, symbol, strict=True) if not sym and s["text"].strip()),
        default=None,
    )
    baseline = max((s["origin"][1] for s in spans), default=0.0)

    kept: list[str] = []
    original: list[str] = []
    refs: list[str] = []
    sizes: list[float] = []
    fonts: dict[str, int] = {}
    chars = bold_chars = italic_chars = 0
    for span, is_symbol in zip(spans, symbol, strict=True):
        original.append(span["text"])
        if _is_reference_mark(span, kept, line_size, baseline):
            refs.append(span["text"].strip())
            continue
        text = span["text"]
        if _PRIVATE_USE.search(text):
            text = map_symbol_font(text, span["font"], stats)
        kept.append(text)
        if is_symbol:
            continue
        length = len(span["text"].strip())
        chars += length
        if length:
            sizes.append(span["size"])
        if span["flags"] & PYMUPDF_BOLD_FLAG or _bold_font(span["font"]):
            bold_chars += length
        if span["flags"] & PYMUPDF_ITALIC_FLAG or _italic_font(span["font"]):
            italic_chars += length
        if length:
            family = _font_family(span["font"])
            fonts[family] = fonts.get(family, 0) + length
    text = "".join(kept)
    return Line(
        text=clean(text, stats) if clean_text else text,
        bbox=tuple(raw_line["bbox"]),
        size=max(sizes, default=None),
        bold=bold_chars / chars if chars else 0.0,
        chars=chars,
        original="".join(original),
        refs=refs,
        block=block_number,
        font=max(fonts, key=fonts.__getitem__) if fonts else "",
        italic=italic_chars / chars if chars else 0.0,
    )


def _is_table(rows: list[list[str]]) -> bool:
    """Reject layouts that merely look like tables: one filled column, prose lines, or
    rows that continue each other's sentences."""
    filled = [[bool(cell.strip()) for cell in row] for row in rows]
    columns = max(len(row) for row in filled)
    used = [i for i in range(columns) if any(i < len(row) and row[i] for row in filled)]
    multi_cell = sum(1 for row in filled if sum(row) >= 2)
    if len(used) < config.MIN_TABLE_COLUMNS or multi_cell / len(rows) < config.MIN_MULTI_CELL_ROWS:
        return False
    main = max(used, key=lambda i: sum(1 for row in filled if i < len(row) and row[i]))
    cells = [row[main].strip() if main < len(row) else "" for row in rows]
    pairs = [(a, b) for a, b in zip(cells, cells[1:], strict=False) if a and b]
    running = sum(1 for a, b in pairs if not _SENTENCE_END.search(a) and b[:1].islower())
    return not pairs or running < config.RUNNING_TEXT_ROWS * len(pairs)


def _find_tables(page: pymupdf.Page, number: int, drawings: int) -> list[RawBlock]:
    """Ruled tables (PyMuPDF's "lines" strategy), on pages with enough vector paths."""
    if drawings < config.MIN_RULING_PATHS:
        return []
    return _tables_from(page.find_tables().tables, number)  # type: ignore[no-untyped-call]


def _tables_from(found: list[Any], number: int) -> list[RawBlock]:
    """Raw table blocks of PyMuPDF tables: merged cells come with their span, a cell merged
    down over several rows repeats its text in each (every row reads on its own)."""
    tables: list[RawBlock] = []
    for table in found:
        grid = table.extract()
        spans = _cell_spans(table)
        for row, column, height, _ in spans:
            for below in range(row + 1, min(row + height, len(grid))):
                if column < len(grid[below]) and grid[below][column] is None:
                    grid[below][column] = grid[row][column]
        rows = [[cell or "" for cell in row] for row in grid]
        if len(rows) >= config.MIN_TABLE_ROWS and _is_table(rows):
            raw = RawBlock(text="", page=number, bbox=tuple(table.bbox), rows=rows)
            raw.spans = spans or None
            tables.append(raw)
    return tables


def _cell_spans(table: Any) -> list[tuple[int, int, int, int]]:
    """(row, column, rows, columns) of each cell whose box covers more than one grid cell."""
    boxes = [cell for row in table.rows for cell in row.cells if cell is not None]
    lefts = sorted({round(box[0], 1) for box in boxes})
    tops = sorted({round(box[1], 1) for box in boxes})
    spans: list[tuple[int, int, int, int]] = []
    for r, row in enumerate(table.rows):
        for c, box in enumerate(row.cells):
            if box is None:
                continue
            width = 1 + sum(1 for x in lefts if box[0] + 1 < x < box[2] - 1)
            height = 1 + sum(1 for y in tops if box[1] + 1 < y < box[3] - 1)
            if width > 1 or height > 1:
                spans.append((r, c, height, width))
    return spans


def _add_text_tables(
    page: pymupdf.Page, number: int, ruled: list[RawBlock], lines: list[Line]
) -> list[RawBlock]:
    """Tables without ruling lines, and a second opinion on weak ruled ones: PyMuPDF's "text"
    strategy runs only on regions where rows of aligned cells suggest a table, and on ruled
    tables that score poorly; the better-scoring reading of a region wins."""
    free = [line for line in lines if not any(_inside(line.bbox, t.bbox) for t in ruled)]
    regions = _aligned_regions(free)
    regions += [
        t.bbox for t in ruled if t.bbox and table_score(t.rows or []) < config.TABLE_WEAK_SCORE
    ]
    if not regions:
        return ruled
    tables = list(ruled)
    for region in regions:
        found = page.find_tables(clip=region, strategy="text").tables  # type: ignore[no-untyped-call]
        for table in _tables_from(found, number):
            score = table_score(table.rows or [])
            rival = next((t for t in tables if _overlap(t.bbox, table.bbox) > 0.5), None)
            if rival is None:
                if score >= config.TEXT_TABLE_MIN_SCORE:
                    tables.append(table)
            elif score > table_score(rival.rows or []) + config.TABLE_SCORE_MARGIN:
                tables[tables.index(rival)] = table
    return tables


def _overlap(a: BBox | None, b: BBox | None) -> float:
    """Intersection over the smaller box."""
    if a is None or b is None:
        return 0.0
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return width * height / smaller


def _aligned_regions(lines: list[Line]) -> list[BBox]:
    """Regions where at least TEXT_TABLE_MIN_ROWS consecutive rows split into cells at the
    same places: three or more cells, or two whose later cells are numbers. Two text columns
    (long lines, no numbers) do not qualify."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0])):
        row = rows[-1] if rows else None
        if row is not None and _same_band(row[0], line):
            row.append(line)
        else:
            rows.append([line])
    regions: list[BBox] = []
    run: list[list[Line]] = []
    for row in [*rows, []]:
        if row and _cell_row(row) and (not run or _aligned(run[-1], row)):
            run.append(row)
            continue
        if len(run) >= config.TEXT_TABLE_MIN_ROWS:
            members = [line for cells in run for line in cells]
            regions.append(
                (
                    min(line.bbox[0] for line in members) - 2,
                    min(line.bbox[1] for line in members) - 2,
                    max(line.bbox[2] for line in members) + 2,
                    max(line.bbox[3] for line in members) + 2,
                )
            )
        run = [row] if row and _cell_row(row) else []
    return regions


def _same_band(a: Line, b: Line) -> bool:
    top, bottom = max(a.bbox[1], b.bbox[1]), min(a.bbox[3], b.bbox[3])
    smaller = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]) or 1.0
    return bottom - top >= 0.5 * smaller


def _cells(row: list[Line]) -> list[Line]:
    return sorted(row, key=lambda line: line.bbox[0])


def _cell_row(row: list[Line]) -> bool:
    cells = _cells(row)
    if len(cells) < 2:
        return False
    size = max(line.size or 10.0 for line in cells)
    gaps = all(
        b.bbox[0] - a.bbox[2] >= config.TABLE_CELL_GAP * size
        for a, b in zip(cells, cells[1:], strict=False)
    )
    numbers = sum(1 for line in cells[1:] if _NUMBER_CELL.match(line.text))
    return gaps and (len(cells) >= 3 or numbers == len(cells) - 1)


def _aligned(upper: list[Line], lower: list[Line]) -> bool:
    """At least two cells of ``lower`` start, end or are centred where cells of ``upper`` do."""
    size = max(line.size or 10.0 for line in upper + lower)
    tolerance = config.PARAGRAPH_ALIGN_TOLERANCE * size

    def anchors(line: Line) -> tuple[float, float, float]:
        return (line.bbox[0], line.bbox[2], (line.bbox[0] + line.bbox[2]) / 2)

    matched = sum(
        1
        for line in lower
        if any(
            abs(a - b) <= tolerance
            for other in upper
            for a, b in zip(anchors(line), anchors(other), strict=True)
        )
    )
    return matched >= 2


def _extend_table(table: RawBlock, rects: list[BBox], lines: list[Line]) -> list[Line]:
    """Grow a table over the rows its own ruling closes below the detected box (a merged last
    row): vertical rules or a full-width cell starting inside the table and reaching further
    down. Text in the added part becomes the table's last row; the remaining lines return."""
    if table.bbox is None or table.rows is None:
        return lines
    x0, y0, x1, y1 = table.bbox
    slack = config.TABLE_RULE_SLACK * (y1 - y0)
    continuing = [
        r
        for r in rects
        if r[0] >= x0 - slack
        and r[2] <= x1 + slack
        and y0 - slack <= r[1] <= y1 + slack
        and r[3] > y1 + slack
        and (r[2] - r[0] <= slack or r[2] - r[0] >= 0.5 * (x1 - x0))
    ]
    if len(continuing) < 2 and not any(r[2] - r[0] >= 0.5 * (x1 - x0) for r in continuing):
        return lines
    bottom = max(r[3] for r in continuing)
    extended = (x0, y0, x1, bottom)
    added = [line for line in lines if _inside(line.bbox, extended)]
    if added:
        columns = max(len(row) for row in table.rows)
        text = " ".join(line.text for line in added)
        table.rows.append([text] + [""] * (columns - 1))
    table.bbox = extended
    return [line for line in lines if not any(line is other for other in added)]


def _inside(box: BBox | None, container: BBox | None) -> bool:
    """True when the centre of ``box`` lies within ``container``."""
    if box is None or container is None:
        return False
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return container[0] <= cx <= container[2] and container[1] <= cy <= container[3]


def _merge_tables(blocks: list[RawBlock], tables: list[RawBlock]) -> list[RawBlock]:
    """Insert each table before the first text block that starts below it."""
    merged = list(blocks)
    for table in sorted(tables, key=lambda t: t.bbox[1] if t.bbox else 0.0):
        top = table.bbox[1] if table.bbox else 0.0
        position = next(
            (i for i, b in enumerate(merged) if b.bbox and b.bbox[1] >= top), len(merged)
        )
        merged.insert(position, table)
    return merged
