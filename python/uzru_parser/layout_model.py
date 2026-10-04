"""Optional layout model for the pages the rules are unsure about.

Install with ``pip install "uzru-parser[layout]"`` (ONNX Runtime) and enable it with
``Parser(layout_model=True)`` or a model path. The model is PP-DocLayout-S (PaddlePaddle,
Apache-2.0): a PicoDet detector of about 1.2 million parameters (4.7 MB as ONNX) that finds
page regions such as titles, text, tables, figures, formulas, headers, footers and footnotes.

It only runs on pages whose confidence is low (see :mod:`.confidence`) and only corrects the
rules: tables are looked for inside its table regions, its figure and formula regions group
labels and fragments, text in its header and footer regions is dropped, its title regions
count as a heading signal, and on pages where columns were read as one its text regions give
the reading order. The model is loaded once per process, on first use.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from . import config
from .paragraphs import Line

BBox = tuple[float, float, float, float]

#: Environment variable naming the ONNX file when ``layout_model=True``.
MODEL_ENV = "UZRU_LAYOUT_MODEL"
MODEL_FILE = "pp_doclayout_s.onnx"
INPUT_SIZE = 480
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
#: The model's classes, in its output order (PaddleX inference.yml of PP-DocLayout-S).
CLASSES = (
    "paragraph_title",
    "image",
    "text",
    "number",
    "abstract",
    "content",
    "figure_title",
    "formula",
    "table",
    "table_title",
    "reference",
    "doc_title",
    "footnote",
    "header",
    "algorithm",
    "footer",
    "seal",
    "chart_title",
    "chart",
    "formula_number",
    "header_image",
    "footer_image",
    "aside_text",
)
FIGURES = frozenset({"image", "chart", "seal", "header_image", "footer_image"})
FORMULAS = frozenset({"formula", "formula_number"})
FURNITURE = frozenset({"header", "footer", "number"})
TITLES = frozenset({"paragraph_title", "doc_title"})
#: Regions holding text that is read in order.
TEXT = frozenset(
    {
        "text",
        "abstract",
        "content",
        "reference",
        "aside_text",
        "footnote",
        "algorithm",
        "figure_title",
        "table_title",
        "chart_title",
        *TITLES,
    }
)

_LOCK = threading.Lock()
_SESSIONS: dict[str, Any] = {}


@dataclass(frozen=True)
class Region:
    kind: str
    score: float
    bbox: BBox


@dataclass
class Hints:
    """What the model says about one page, in the rules' terms."""

    figures: list[BBox] = field(default_factory=list)
    formulas: list[BBox] = field(default_factory=list)
    furniture: list[BBox] = field(default_factory=list)
    titles: list[BBox] = field(default_factory=list)
    footnotes: list[BBox] = field(default_factory=list)
    tables: list[BBox] = field(default_factory=list)
    order: list[BBox] | None = None  # text regions in reading order, when the order is fixed
    #: Tables found inside the table regions (filled in by the PDF reader).
    found_tables: list[Any] = field(default_factory=list)


def model_path(choice: bool | str | Path | None) -> Path | None:
    """The ONNX file to use: a given path, else ``UZRU_LAYOUT_MODEL``, else a file shipped
    next to this module; ``None`` when the model is off."""
    if choice is None or choice is False:
        return None
    if isinstance(choice, (str, Path)):
        return Path(choice)
    if env := os.environ.get(MODEL_ENV):
        return Path(env)
    return Path(__file__).parent / "models" / MODEL_FILE


def load(path: Path) -> tuple[Any, str]:
    """The ONNX Runtime session of ``path`` (cached per process) and a status: "ready", or
    why the model cannot run."""
    try:
        import numpy  # noqa: F401
        import onnxruntime
    except ImportError:
        return None, 'onnxruntime missing: pip install "uzru-parser[layout]"'
    if not path.is_file():
        return None, f"model file not found: {path.name}"
    key = str(path.resolve())
    with _LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            options = onnxruntime.SessionOptions()
            options.log_severity_level = 3  # the exported graph has harmless warnings
            options.enable_cpu_mem_arena = False  # a few MB less, no measurable cost
            session = onnxruntime.InferenceSession(
                key, sess_options=options, providers=["CPUExecutionProvider"]
            )
            _SESSIONS[key] = session
    return session, "ready"


def detect(session: Any, page: pymupdf.Page) -> list[Region]:
    """Regions of ``page`` in PDF points: the page is drawn at the model's input size and
    normalised like its training images."""
    import numpy as np

    width, height = page.rect.width, page.rect.height
    matrix = pymupdf.Matrix(INPUT_SIZE / width, INPUT_SIZE / height)  # type: ignore[no-untyped-call]
    pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), 255, dtype=np.uint8)
    rows, columns = min(INPUT_SIZE, image.shape[0]), min(INPUT_SIZE, image.shape[1])
    canvas[:rows, :columns] = image[:rows, :columns]
    pixels = (canvas.astype(np.float32) / 255.0 - np.array(MEAN, dtype=np.float32)) / np.array(
        STD, dtype=np.float32
    )
    scale = np.array([[INPUT_SIZE / height, INPUT_SIZE / width]], dtype=np.float32)
    detections, count = session.run(
        None, {"image": pixels.transpose(2, 0, 1)[None], "scale_factor": scale}
    )
    regions: list[Region] = []
    for row in detections[: int(np.ravel(count)[0])]:
        kind = int(row[0])
        if 0 <= kind < len(CLASSES) and float(row[1]) >= config.LAYOUT_MIN_SCORE:
            box = (float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            regions.append(Region(CLASSES[kind], float(row[1]), box))
    return regions


def hints(regions: Sequence[Region], page_box: BBox, issues: Sequence[str], size: float) -> Hints:
    """The corrections the regions allow on a page with the given confidence issues."""
    height = page_box[3] - page_box[1]
    band = config.LAYOUT_FURNITURE_BAND * height
    found = Hints()
    for region in regions:
        box = region.bbox
        if region.kind in FIGURES:
            found.figures.append(box)
        elif region.kind in FORMULAS:
            found.formulas.append(box)
        elif region.kind == "table":
            found.tables.append(box)
        elif region.kind in FURNITURE and (box[3] <= band or box[1] >= height - band):
            found.furniture.append(box)
        if region.kind in TITLES:
            found.titles.append(box)
        if region.kind == "footnote":
            found.footnotes.append(box)
    if "columns" in issues:
        text = [region.bbox for region in regions if region.kind in TEXT]
        found.order = xy_order(text, size) if len(text) > 1 else None
    return found


def xy_order(boxes: Sequence[BBox], size: float) -> list[BBox]:
    """Boxes in reading order by a recursive XY-cut: boxes spanning the region split it into
    bands first, then the widest vertical gap gives columns, then horizontal gaps sections."""
    if len(boxes) < 2:
        return list(boxes)
    left = min(box[0] for box in boxes)
    width = max(box[2] for box in boxes) - left
    wide = [box for box in boxes if box[2] - box[0] >= config.SPANNING_SHARE * width]
    if wide and len(wide) < len(boxes):
        ordered: list[BBox] = []
        band: list[BBox] = []
        for box in sorted(boxes, key=lambda b: b[1]):
            if box in wide:
                ordered += xy_order(band, size) + [box]
                band = []
            else:
                band.append(box)
        return ordered + xy_order(band, size)
    for axis in (0, 1):  # columns first, then sections
        cut = _widest_gap(boxes, axis, config.COLUMN_GUTTER * size)
        if cut is not None:
            first = [b for b in boxes if (b[axis] + b[axis + 2]) / 2 < cut]
            second = [b for b in boxes if (b[axis] + b[axis + 2]) / 2 >= cut]
            if first and second:
                return xy_order(first, size) + xy_order(second, size)
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def _widest_gap(boxes: Sequence[BBox], axis: int, minimum: float) -> float | None:
    """Middle of the widest empty stretch between the boxes along ``axis`` (0: x, 1: y)."""
    spans = sorted((box[axis], box[axis + 2]) for box in boxes)
    best: tuple[float, float] | None = None
    end = spans[0][1]
    for start, stop in spans[1:]:
        if start - end >= minimum and (best is None or start - end > best[1] - best[0]):
            best = (end, start)
        end = max(end, stop)
    return (best[0] + best[1]) / 2 if best else None


def order_lines(lines: Sequence[Line], boxes: Sequence[BBox]) -> list[list[Line]]:
    """Lines grouped by the region (in reading order) holding their centre. A line just
    outside every region joins the nearest one within LAYOUT_NEAREST_LINES of its own
    height; any other line goes to a last group in its original order."""
    groups: list[list[Line]] = [[] for _ in boxes]
    loose: list[Line] = []
    for line in lines:
        index = _region_of(line, boxes)
        if index is None:
            loose.append(line)
        else:
            groups[index].append(line)
    return [group for group in [*groups, loose] if group]


def _region_of(line: Line, boxes: Sequence[BBox]) -> int | None:
    cx, cy = (line.bbox[0] + line.bbox[2]) / 2, (line.bbox[1] + line.bbox[3]) / 2
    best: tuple[float, int] | None = None
    for index, (x0, y0, x1, y1) in enumerate(boxes):
        dx = max(x0 - cx, 0.0, cx - x1)
        dy = max(y0 - cy, 0.0, cy - y1)
        distance = (dx * dx + dy * dy) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, index)
    reach = config.LAYOUT_NEAREST_LINES * (line.bbox[3] - line.bbox[1])
    return best[1] if best is not None and best[0] <= reach else None


def inside(box: BBox | None, region: BBox) -> bool:
    """The centre of ``box`` lies in ``region``."""
    if box is None:
        return False
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]
