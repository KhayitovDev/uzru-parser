"""Scoring extracted tables."""

from __future__ import annotations


def table_score(rows: list[list[str]]) -> float:
    """How table-like an extracted grid is: rows with the usual number of filled cells
    (consistent columns), minus the share of empty cells and, twice, the share of words cut
    between two cells ("birlashgan" + ")")."""
    counts = [sum(1 for cell in row if cell.strip()) for row in rows]
    filled = [count for count in counts if count]
    cells = sum(len(row) for row in rows)
    if not filled or not cells:
        return -1.0
    usual = max(set(filled), key=filled.count)
    consistent = sum(1 for count in filled if count == usual) / len(filled)
    empty = 1 - sum(counts) / cells
    pairs = cuts = 0
    for row in rows:
        texts = [cell.strip() for cell in row if cell.strip()]
        for left, right in zip(texts, texts[1:], strict=False):
            pairs += 1
            cuts += left[-1].isalpha() and (right[0].islower() or right[0] in ").,;:")
    return consistent - empty - 2 * (cuts / pairs if pairs else 0.0)
