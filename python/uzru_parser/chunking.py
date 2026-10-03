"""Structural chunker: sections first, then blocks, then sentences, lines and words."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Block, BlockType, Document
from .text import detect_language, estimate_tokens, split_sentences

PARAGRAPH_JOINER = "\n\n"
DEFAULT_SKIP_ROLES = ("toc", "back_matter")
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


class Chunker:
    """Split a :class:`Document` into chunks of at most ``max_tokens`` tokens.

    A chunk never spans two sections: every heading starts a new chunk. Inside a section
    whole blocks are packed together; a block that is too large is split by sentences
    (lines for lists and tables, words as a last resort). ``overlap`` tokens from the end
    of the previous chunk are repeated at the start of the next one within the same section.

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
        for block in document.blocks:
            if not block.text.strip() or block.extra.get("role") in self.skip_roles:
                continue
            if block.type is BlockType.FOOTNOTE:
                run.footnotes.append(block.text)
            elif block.type is BlockType.HEADING:
                run.add_heading(block, self._count(block.text))
            else:
                for unit in self._units(block):
                    run.add_body(unit)
        run.flush()
        return run.chunks

    def _units(self, block: Block) -> list[_Unit]:
        tokens = self._count(block.text)
        page_end = block.extra.get("page_end", block.page)
        unit = _Unit(block.text, tokens, block.page, block.type, page_end=page_end)
        return [unit] if tokens <= self.max_tokens else self.split_unit(unit)

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
                units.append(_Unit(part, tokens, unit.page, unit.kind, joiner, unit.page_end))
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


class _Run:
    """Mutable state of a single :meth:`Chunker.chunk` call."""

    def __init__(self, chunker: Chunker, document: Document) -> None:
        self.chunker = chunker
        self.document = document
        self.chunks: list[Chunk] = []
        self.headings: list[tuple[int, str]] = []
        self.units: list[_Unit] = []
        self.carry: list[_Unit] = []
        self.footnotes: list[str] = []

    def add_heading(self, block: Block, tokens: int) -> None:
        level = block.level or 1
        deeper_than_pending = not self.headings or level > self.headings[-1][0]
        if self._has_body() or (self.units and not deeper_than_pending):
            self.flush()
        while self.headings and self.headings[-1][0] >= level:
            self.headings.pop()
        self.headings.append((level, block.text))
        self.carry = []
        unit = _Unit(block.text, tokens, block.page, BlockType.HEADING, page_end=block.page)
        self.units.append(unit)

    def add_body(self, unit: _Unit) -> None:
        max_tokens = self.chunker.max_tokens
        if self._has_body() and self._tokens() + unit.tokens > max_tokens:
            self.flush(carry_overlap=True)
        if self.carry and self._tokens() + unit.tokens > max_tokens:
            self.carry = []
        self.units.append(unit)

    def flush(self, carry_overlap: bool = False) -> None:
        if not self.units:
            return
        parts = [*self.carry, *self.units]
        text = parts[0].text + "".join(p.joiner + p.text for p in parts[1:])
        language = detect_language(text)
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
                heading_path=[title for _, title in self.headings],
                chunk_index=index,
                token_count=sum(u.tokens for u in parts),
                metadata={"footnotes": self.footnotes} if self.footnotes else {},
            )
        )
        self.footnotes = []
        self.carry = self._tail() if carry_overlap else []
        self.units = []

    def _has_body(self) -> bool:
        return any(u.kind is not BlockType.HEADING for u in self.units)

    def _tokens(self) -> int:
        return sum(u.tokens for u in self.carry) + sum(u.tokens for u in self.units)

    def _tail(self) -> list[_Unit]:
        """Trailing units of the current chunk that fit in the overlap budget."""
        budget = self.chunker.overlap
        tail: list[_Unit] = []
        for unit in reversed([u for u in self.units if u.kind is not BlockType.HEADING]):
            if unit.tokens <= budget:
                tail.insert(0, unit)
                budget -= unit.tokens
                continue
            if not tail:
                tail = self._fitting_tail(unit, budget)
            break
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
