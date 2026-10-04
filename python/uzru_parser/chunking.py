"""Structural chunker: sections first, then blocks, then sentences, lines and words."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import LEAD_IN_TOKENS, MIN_CHUNK_TOKENS
from .models import Block, BlockType, Document, LanguageInfo
from .text import detect_language, estimate_tokens, names_appendix, split_sentences

PARAGRAPH_JOINER = "\n\n"
DEFAULT_SKIP_ROLES = ("toc", "back_matter", "title_page")
LINE_TYPES = (BlockType.LIST, BlockType.TABLE, BlockType.CODE)


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    language: str
    script: str
    page_start: int
    page_end: int
    heading_path: list[str]
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Unit:
    text: str
    tokens: int
    page: int
    kind: BlockType
    joiner: str = PARAGRAPH_JOINER
    page_end: int = 0
    path: tuple[str, ...] = ()
    figure: bool = False  # figure label or formula text: never a chunk of its own
    table: int | None = None  # index of the table block the unit comes from
    rows: list[list[str]] = field(default_factory=list)  # the table rows the unit holds
    header: list[list[str]] = field(default_factory=list)  # its table's header rows
    is_header: bool = False  # the unit holds the table's header rows
    role: str | None = None  # the block's role ("formula", "image", ...)


class Chunker:
    """Split a :class:`Document` into chunks of at most ``max_tokens`` tokens.

    Level-1 and level-2 headings always start a new chunk; deeper headings do once the
    current chunk has some substance. A heading is never left alone, and a tiny chunk is
    merged into the previous one under the same heading. Inside a section whole blocks are
    packed together; a block that is too large is split by sentences (lines for lists and
    tables, words as a last resort). ``overlap`` tokens from the end of the previous chunk
    are repeated at the start of the next one within the same section.

    ``token_counter`` replaces the built-in estimate, e.g. with a real tokenizer.
    """

    def __init__(
        self,
        max_tokens: int = 600,
        overlap: int = 80,
        token_counter: Callable[[str], int] | None = None,
        skip_roles: tuple[str, ...] = DEFAULT_SKIP_ROLES,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if not 0 <= overlap < max_tokens:
            raise ValueError("overlap must be between 0 and max_tokens - 1")
        self.max_tokens = max_tokens
        self.overlap = overlap
        self._count = token_counter or estimate_tokens
        self.skip_roles = skip_roles

    def chunk(self, document: Document) -> list[Chunk]:
        run = _Run(self, document)
        for index, block in enumerate(document.blocks):
            if not block.text.strip() or block.extra.get("role") in self.skip_roles:
                continue
            if block.type is BlockType.FOOTNOTE:
                run.footnotes.append(block.text)
            elif block.type is BlockType.HEADING:
                run.add_heading(block, self._count(block.text))
            else:
                for unit in self._units(block, index):
                    run.add_body(unit)
        run.finish()
        return run.chunks

    def _units(self, block: Block, index: int = -1) -> list[_Unit]:
        if block.type is BlockType.TABLE and block.extra.get("rows"):
            return self._table_units(block, index)
        tokens = self._count(block.text)
        page_end = block.extra.get("page_end", block.page)
        figure = block.extra.get("role") in FIGURE_ROLES
        unit = _Unit(block.text, tokens, block.page, block.type, page_end=page_end, figure=figure)
        unit.role = block.extra.get("role")
        return [unit] if tokens <= self.max_tokens else self.split_unit(unit)

    def _table_units(self, block: Block, index: int) -> list[_Unit]:
        """A table that fits is one unit. A larger one is cut between rows only: its header
        rows form the first unit and every row its own, so no chunk ends inside a row and a
        chunk that goes on with the table can repeat the header."""
        rows = [row for row in block.extra["rows"] if any(cell.strip() for cell in row)]
        header = rows[: header_row_count(rows, block.extra.get("spans", []))]
        page_end = block.extra.get("page_end", block.page)
        text = "\n".join(row_text(row) for row in rows)
        tokens = self._count(text)
        if tokens <= self.max_tokens:
            return [
                _Unit(
                    text,
                    tokens,
                    block.page,
                    BlockType.TABLE,
                    page_end=page_end,
                    table=index,
                    rows=rows,
                    header=header,
                )
            ]
        units: list[_Unit] = []
        if header:
            head = "\n".join(row_text(row) for row in header)
            units.append(
                _Unit(
                    head,
                    self._count(head),
                    block.page,
                    BlockType.TABLE,
                    "\n",
                    page_end,
                    table=index,
                    rows=header,
                    header=header,
                    is_header=True,
                )
            )
        for row in rows[len(header) :]:
            line = row_text(row)
            parts = self._fit(line, " ")
            for number, part in enumerate(parts):
                units.append(
                    _Unit(
                        part,
                        self._count(part),
                        block.page,
                        BlockType.TABLE,
                        "\n",
                        page_end,
                        table=index,
                        rows=[row] if number == 0 else [],
                        header=header,
                    )
                )
        units[0].joiner = PARAGRAPH_JOINER
        return units

    def split_unit(self, unit: _Unit) -> list[_Unit]:
        """Break a unit into sentences (or lines), and oversized pieces into word groups."""
        if unit.kind in LINE_TYPES:
            pieces, joiner = [line for line in unit.text.split("\n") if line.strip()], "\n"
        else:
            pieces, joiner = split_sentences(unit.text), " "

        units: list[_Unit] = []
        for piece in pieces:
            for part in self._fit(piece, joiner):
                tokens = self._count(part)
                units.append(
                    _Unit(
                        part,
                        tokens,
                        unit.page,
                        unit.kind,
                        joiner,
                        unit.page_end,
                        figure=unit.figure,
                    )
                )
        units[0].joiner = unit.joiner
        return units

    def _fit(self, text: str, joiner: str) -> list[str]:
        if self._count(text) <= self.max_tokens:
            return [text]
        groups: list[list[str]] = [[]]
        used = 0
        for word in text.split():
            tokens = self._count(word)
            if groups[-1] and used + tokens > self.max_tokens:
                groups.append([])
                used = 0
            groups[-1].append(word)
            used += tokens
        return [" ".join(group) for group in groups]


FIGURE_ROLES = ("figure", "formula", "image")
#: A chunk with no language of its own inherits one of these from its document.
INHERITABLE_LANGUAGES = ("uz", "ru")


CONTENT_TYPES = {
    BlockType.PARAGRAPH: "prose",
    BlockType.QUOTE: "prose",
    BlockType.LIST: "list",
    BlockType.TABLE: "table",
    BlockType.CODE: "code",
}
#: A chunk's content type is the one holding at least this share of its tokens, else "mixed".
MAIN_CONTENT_SHARE = 0.7
#: A header cell has at most this many words; a longer cell is data.
HEADER_CELL_WORDS = 12


def row_text(row: list[str]) -> str:
    """A table row as one line: its non-empty cells joined by " | "."""
    return " | ".join(" ".join(cell.split()) for cell in row if cell.strip())


def header_row_count(rows: list[list[str]], spans: list[dict[str, int]]) -> int:
    """How many top rows head the table. A header row holds short labels, not sentences or
    a numbered item; a single caption cell above it ("(mlrd soʻm)") belongs to it, and so does
    a second row under cells merged across columns (a two-level header: a recorded span, a
    label repeated across, or a label merged down into the next row)."""
    start = 0
    width = max((len(row) for row in rows), default=0)
    first = _filled(rows[0]) if rows else []
    if len(first) == 1 and width >= 3:
        if not any(char.isalpha() for char in first[0]):
            return 0  # a stray mark, such as the quote opening an amended text
        if len(rows) > 1 and first[0] in (cell.strip() for cell in rows[1]):
            return 0  # a label merged down the first column: the rows are data
        start = 1
    if start + 1 >= len(rows) or not _header_like(_filled(rows[start])):
        return 0
    top, below = rows[start], rows[start + 1]
    spanned = any(span["row"] == start and span["cols"] > 1 for span in spans)
    repeated_across = any(a.strip() and a == b for a, b in zip(top, top[1:], strict=False))
    merged_down = any(a.strip() and a == b for a, b in zip(top, below, strict=False))
    two_level = (spanned or repeated_across) and merged_down or spanned
    if two_level and start + 2 < len(rows) and _header_like(_filled(below)):
        return start + 2
    return start + 1


def _filled(row: list[str]) -> list[str]:
    return [cell.strip() for cell in row if cell.strip()]


def _header_like(cells: list[str]) -> bool:
    """Column labels: not all numbers, not a numbered item, no cell a long sentence."""
    if not cells or all(_is_number(cell) for cell in cells):
        return False
    if _is_number(cells[0].rstrip(".)")) or not any(char.isalpha() for c in cells for char in c):
        return False
    return all(len(cell.split()) <= HEADER_CELL_WORDS and cell[-1] not in ".;" for cell in cells)


def _is_number(text: str) -> bool:
    return text.replace(",", "").replace(".", "").replace(" ", "").isdigit()


def _common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for path in paths[1:]:
        length = 0
        while length < min(len(prefix), len(path)) and prefix[length] == path[length]:
            length += 1
        prefix = prefix[:length]
    return prefix


class _Run:
    """Mutable state of a single :meth:`Chunker.chunk` call."""

    def __init__(self, chunker: Chunker, document: Document) -> None:
        self.chunker = chunker
        self.document = document
        self.chunks: list[Chunk] = []
        self.table_ids: list[set[int]] = []
        self.headings: list[tuple[int, str]] = []
        self.units: list[_Unit] = []
        self.carry: list[_Unit] = []
        self.footnotes: list[str] = []

    def add_heading(self, block: Block, tokens: int) -> None:
        level = block.level or 1
        body = self._body_tokens()
        # A short text under a heading ("1-ILOVA" / "... Farmoniga") introduces its first
        # subsection: it stays with it, under the subsection's path, instead of making a
        # chunk of its own.
        intro = bool(self.headings) and level > self.headings[-1][0] and body < MIN_CHUNK_TOKENS
        if body and (level <= 2 or body >= MIN_CHUNK_TOKENS) and not intro:
            self.flush()
        while self.headings and self.headings[-1][0] >= level:
            self.headings.pop()
        self.headings.append((level, block.text))
        self.carry = []
        unit = _Unit(block.text, tokens, block.page, BlockType.HEADING, page_end=block.page)
        unit.path = self._path()
        if intro:
            for pending in self.units:
                pending.path = unit.path
        self.units.append(unit)

    def add_body(self, unit: _Unit) -> None:
        max_tokens = self.chunker.max_tokens
        if self._body_tokens() and self._tokens() + unit.tokens > max_tokens:
            lead = self._lead_in()
            self.units = self.units[: len(self.units) - len(lead)]
            self.flush(carry_overlap=True)
            self.units = lead
            if unit.table is not None and unit.header and not unit.is_header:
                # The table goes on in this chunk: its header comes first, no old rows.
                self.carry = []
                self.units.append(self._repeated_header(unit))
        if self.carry and self._tokens() + unit.tokens > max_tokens:
            self.carry = []
        unit.path = self._path()
        self.units.append(unit)

    def _repeated_header(self, unit: _Unit) -> _Unit:
        text = "\n".join(row_text(row) for row in unit.header)
        unit.joiner = "\n"
        return _Unit(
            text,
            self.chunker._count(text),
            unit.page,
            BlockType.TABLE,
            PARAGRAPH_JOINER,
            unit.page,
            self._path(),
            table=unit.table,
            rows=unit.header,
            header=unit.header,
            is_header=True,
        )

    def _lead_in(self) -> list[_Unit]:
        """Trailing units that introduce what comes next (a short title line, "... the
        following:", or both), when the rest of the chunk still has body text."""
        units = self.units

        def short(unit: _Unit) -> bool:
            plain = unit.kind is BlockType.PARAGRAPH and not unit.figure
            return plain and unit.joiner == PARAGRAPH_JOINER and unit.tokens <= LEAD_IN_TOKENS

        def title(unit: _Unit) -> bool:
            return short(unit) and unit.text.rstrip()[-1:] not in ".!?:;…"

        start = len(units)
        if start and short(units[-1]) and units[-1].text.rstrip().endswith(":"):
            start -= 1
        if start and title(units[start - 1]):
            start -= 1
        rest = units[:start]
        if not any(u.kind is not BlockType.HEADING and not u.figure for u in rest):
            return []
        return units[start:]

    def flush(self, carry_overlap: bool = False) -> None:
        if not self.units:
            return
        own_tokens = sum(u.tokens for u in self.units)
        body = [u for u in self.units if u.kind is not BlockType.HEADING and not u.figure]
        path = _common_prefix([u.path for u in body]) if body else self._path()
        tiny = not carry_overlap and (not body or own_tokens < MIN_CHUNK_TOKENS)
        if tiny and self._merge_into_previous(path, own_tokens, headings_only=not body):
            self.units, self.carry = [], []
            return
        parts = [*self.carry, *self.units]
        text = parts[0].text + "".join(p.joiner + p.text for p in parts[1:])
        language, inherited = self._language(text)
        index = len(self.chunks)
        self.chunks.append(
            Chunk(
                chunk_id=f"{self.document.document_id}-{index:04d}",
                document_id=self.document.document_id,
                text=text,
                language=language.language,
                script=language.script,
                page_start=min(u.page for u in self.units),
                page_end=max(u.page_end or u.page for u in self.units),
                heading_path=list(path),
                chunk_index=index,
                token_count=sum(u.tokens for u in parts),
                metadata=self._metadata(parts, path, inherited),
            )
        )
        self.table_ids.append({u.table for u in parts if u.table is not None})
        self.footnotes = []
        self.carry = self._tail() if carry_overlap else []
        self.units = []

    def _language(self, text: str) -> tuple[LanguageInfo, bool]:
        """The chunk's own language; when its text alone tells none (a table of chemical
        names, numbers) but is written in the document's script, the document's language."""
        language = detect_language(text)
        document = self.document.language
        if (
            language.language == "unknown"
            and document.language in INHERITABLE_LANGUAGES
            and language.script in (document.script, "none")
        ):
            return LanguageInfo(document.language, document.script, document.confidence), True
        return language, False

    def _metadata(
        self, parts: list[_Unit], path: tuple[str, ...] = (), inherited: bool = False
    ) -> dict[str, Any]:
        """What the chunk holds, for filtering and citations: its content types, the table
        rows it carries (structured, with their header), whether it lies in an appendix, the
        document's title, where its language came from, its footnotes."""
        metadata: dict[str, Any] = {}
        body = [u for u in parts if u.kind is not BlockType.HEADING]
        tokens: dict[str, int] = {}
        for unit in body:
            if unit.role in FIGURE_ROLES:
                kind = str(unit.role)
            else:
                kind = CONTENT_TYPES.get(unit.kind, "prose")
            tokens[kind] = tokens.get(kind, 0) + unit.tokens
        if tokens:
            main = max(tokens, key=lambda kind: tokens[kind])
            share = tokens[main] / sum(tokens.values())
            metadata["content_type"] = main if share >= MAIN_CONTENT_SHARE else "mixed"
            metadata["content_types"] = sorted(tokens)
        tables: dict[int, dict[str, Any]] = {}
        for unit in body:
            if unit.table is None:
                continue
            entry = tables.setdefault(
                unit.table,
                {"header": unit.header, "rows": [], "page": unit.page, "continued": False},
            )
            if unit.is_header:
                # A header that is not the table's own first unit was repeated: the table
                # began in an earlier chunk.
                entry["continued"] = entry["continued"] or self._table_seen(unit.table)
            else:
                entry["rows"].extend(unit.rows)
        if tables:
            metadata["tables"] = list(tables.values())
        if any(names_appendix(title) for title in path):
            metadata["is_appendix"] = True
        if self.document.metadata.title:
            metadata["source_title"] = self.document.metadata.title
        metadata["language_source"] = "document" if inherited else "chunk"
        if self.footnotes:
            metadata["footnotes"] = self.footnotes
        return metadata

    def _table_seen(self, table: int | None) -> bool:
        return any(table in chunk_tables for chunk_tables in self.table_ids)

    def finish(self) -> None:
        """Flush what is left; a trailing heading without text joins the previous chunk."""
        if self.units and not self._body_tokens() and self.chunks:
            self._merge_into_previous(tuple(self.chunks[-1].heading_path), 0, headings_only=True)
            self.units = []
        self.flush()

    def _merge_into_previous(self, path: tuple[str, ...], tokens: int, headings_only: bool) -> bool:
        """Append the pending units to the previous chunk when it has the same heading (any
        heading for heading-only text) and the result still fits."""
        if not self.chunks:
            return False
        previous = self.chunks[-1]
        same_heading = headings_only or tuple(previous.heading_path) == path
        if not same_heading or previous.token_count + tokens > self.chunker.max_tokens:
            return False
        units = self.units
        previous.text += (
            units[0].joiner + units[0].text + "".join(u.joiner + u.text for u in units[1:])
        )
        previous.token_count += tokens
        previous.page_end = max(previous.page_end, *(u.page_end or u.page for u in units))
        if self.footnotes:
            previous.metadata.setdefault("footnotes", []).extend(self.footnotes)
            self.footnotes = []
        return True

    def _path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self.headings)

    def _body_tokens(self) -> int:
        return sum(u.tokens for u in self.units if u.kind is not BlockType.HEADING and not u.figure)

    def _tokens(self) -> int:
        return sum(u.tokens for u in self.carry) + sum(u.tokens for u in self.units)

    def _tail(self) -> list[_Unit]:
        """Trailing units of the current chunk that fit in the overlap budget."""
        budget = self.chunker.overlap
        tail: list[_Unit] = []
        body = [u for u in self.units if u.kind is not BlockType.HEADING and not u.figure]
        if body and body[-1].table is not None:
            return []  # table rows are never repeated; a continued table repeats its header
        start = len(body)
        for unit in reversed(body):
            if unit.tokens <= budget:
                tail.insert(0, unit)
                budget -= unit.tokens
                start -= 1
                continue
            if not tail:
                tail = self._fitting_tail(unit, budget)
            break
        while tail and tail[0].table is not None:
            tail.pop(0)
        return self._complete_list_start(tail, body, start, budget)

    @staticmethod
    def _complete_list_start(
        tail: list[_Unit], body: list[_Unit], start: int, budget: int
    ) -> list[_Unit]:
        """An overlap never opens with list items cut off from their lead-in ("... the
        following:"): it reaches back to the lead-in when that fits, else starts after the
        list."""
        if not tail or tail[0].kind is not BlockType.LIST:
            return tail
        whole_list = start > 0 and body[start - 1].kind is not BlockType.LIST and start < len(body)
        lead = body[start - 1] if start > 0 else None
        is_lead = (
            lead is not None
            and lead.kind is BlockType.PARAGRAPH
            and lead.text.rstrip().endswith(":")
        )
        if whole_list and is_lead and lead is not None and lead.tokens <= budget:
            return [lead, *tail]
        while tail and tail[0].kind is BlockType.LIST:
            tail.pop(0)
        return tail

    def _fitting_tail(self, unit: _Unit, budget: int) -> list[_Unit]:
        tail: list[_Unit] = []
        for piece in reversed(self.chunker.split_unit(unit)):
            if piece.tokens > budget:
                break
            tail.insert(0, piece)
            budget -= piece.tokens
        return tail


def chunk(
    document: Document,
    max_tokens: int = 600,
    overlap: int = 80,
    token_counter: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """Shortcut for ``Chunker(max_tokens, overlap).chunk(document)``."""
    return Chunker(max_tokens, overlap, token_counter).chunk(document)
