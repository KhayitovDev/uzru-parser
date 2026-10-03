"""Reading order of multi-column pages.

A page is cut into regions read one after another: columns are found at vertical gutters
between the lines, and full-width lines crossing a gutter (a title above the columns) separate
sections that are read top to bottom. Boxes with their own background next to the main text
(side boxes) are read after it. A page without columns or side boxes stays one region in its
original order.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import config
from .paragraphs import Line

BBox = tuple[float, float, float, float]


def reading_regions(lines: list[Line], boxes: Sequence[BBox], body_size: float) -> list[list[Line]]:
    """Lines grouped into regions in reading order."""
    if not lines:
        return []
    size = body_size or 10.0
    side: list[list[Line]] = []
    rest = lines
    for box in boxes:
        inside = [line for line in rest if _inside(line.bbox, box)]
        if len(inside) < config.SIDE_BOX_MIN_LINES or not _beside_text(box, rest, inside):
            continue
        side.append(inside)
        rest = [line for line in rest if not any(line is other for other in inside)]
    regions = _cut(rest, size) if rest else []
    if len(regions) <= 1 and not side:
        return [lines]
    return regions + side


def _inside(bbox: BBox, box: BBox) -> bool:
    return (
        bbox[0] >= box[0] - 1
        and bbox[1] >= box[1] - 1
        and bbox[2] <= box[2] + 1
        and (bbox[3] <= box[3] + 1)
    )


def _beside_text(box: BBox, lines: list[Line], inside: list[Line]) -> bool:
    """Main text lines sit left or right of the box at the same height."""
    return any(
        not any(line is other for other in inside)
        and line.bbox[1] < box[3]
        and line.bbox[3] > box[1]
        and (line.bbox[2] <= box[0] or line.bbox[0] >= box[2])
        for line in lines
    )


def _cut(lines: list[Line], size: float) -> list[list[Line]]:
    """Regions of ``lines`` in reading order, splitting at the widest usable gutter."""
    if len(lines) < 2 * config.MIN_COLUMN_LINES:
        return [lines]
    left_edge = min(line.bbox[0] for line in lines)
    width = max(line.bbox[2] for line in lines) - left_edge
    # Full-width lines (a title above the columns) would hide the gutter.
    narrow = [line for line in lines if line.bbox[2] - line.bbox[0] < config.SPANNING_SHARE * width]
    for gutter in _gutters(narrow, size):
        regions = _split_at(lines, gutter, size)
        if regions is not None:
            return regions
    return [lines]


def _gutters(lines: list[Line], size: float) -> list[tuple[float, float]]:
    """Vertical gaps between the lines' horizontal extents, widest first."""
    spans = sorted((line.bbox[0], line.bbox[2]) for line in lines)
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    gaps = [
        (merged[i][1], merged[i + 1][0])
        for i in range(len(merged) - 1)
        if merged[i + 1][0] - merged[i][1] >= config.COLUMN_GUTTER * size
    ]
    return sorted(gaps, key=lambda gap: gap[0] - gap[1])


def _split_at(
    lines: list[Line], gutter: tuple[float, float], size: float
) -> list[list[Line]] | None:
    """Read top to bottom: lines crossing the gutter separate sections; a section whose two
    sides are both text columns becomes those columns. ``None`` if no section has columns."""
    start, end = gutter
    middle = (start + end) / 2
    sections: list[tuple[bool, list[Line]]] = []
    for line in sorted(lines, key=lambda line: line.bbox[1]):
        crosses = line.bbox[0] < start and line.bbox[2] > end
        if sections and sections[-1][0] == crosses:
            sections[-1][1].append(line)
        else:
            sections.append((crosses, [line]))

    regions: list[list[Line]] = []
    pending: list[Line] = []
    found = False
    for crosses, section in sections:
        if not crosses:
            left = [line for line in section if (line.bbox[0] + line.bbox[2]) / 2 < middle]
            right = [line for line in section if (line.bbox[0] + line.bbox[2]) / 2 >= middle]
            if _is_column(left, size) and _is_column(right, size):
                if pending:
                    regions.append(_restore(pending, lines))
                    pending = []
                regions += _cut(_restore(left, lines), size) + _cut(_restore(right, lines), size)
                found = True
                continue
        pending.extend(section)
    if not found:
        return None
    if pending:
        regions.append(_restore(pending, lines))
    return regions


def _restore(subset: list[Line], order: list[Line]) -> list[Line]:
    """``subset`` in the original order of ``order``."""
    wanted = {id(line) for line in subset}
    return [line for line in order if id(line) in wanted]


def _is_column(lines: list[Line], size: float) -> bool:
    """Running text: enough lines, wide enough, and most of them filling the width."""
    if len(lines) < config.MIN_COLUMN_LINES:
        return False
    left = min(line.bbox[0] for line in lines)
    rights = sorted(line.bbox[2] for line in lines)
    edge = rights[int(0.9 * (len(rights) - 1))]
    width = edge - left
    if width < config.MIN_COLUMN_WIDTH * size:
        return False
    full = sum(1 for right in rights if right >= edge - config.COLUMN_RAGGED_SHARE * width)
    return full >= config.COLUMN_FULL_LINE_SHARE * len(lines)
