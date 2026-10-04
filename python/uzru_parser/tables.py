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
            cuts += _cut_between(left, right)
    return consistent - empty - 2 * (cuts / pairs if pairs else 0.0)


def _cut_between(left: str, right: str) -> bool:
    """A word or bracket cut by a wrong column boundary: the right cell opens with closing
    punctuation ("birlashgan" + ")"), or with a short lowercase fragment after a letter
    ("tashki" + "lot"). A cell that simply starts lowercase ("2,0 dan kam" + "oʻta xavfli")
    is a value of its own."""
    if not left[-1].isalpha():
        return False
    if right[0] in ").,;:":
        return True
    first = right.split()[0]
    return first[0].islower() and len(first) <= 3 and len(right.split()) == 1
