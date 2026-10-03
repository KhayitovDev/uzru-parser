"""Measure uzru-parser speed on a generated Russian PDF and on the Rust core alone.

Usage: python benchmarks/benchmark_parser.py [pages]
Reports best-of-5 wall time, CPU time, pages/second and peak memory. Docling is not compared yet.
"""

from __future__ import annotations

import resource
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import pymupdf
from uzru_parser import chunk, parse
from uzru_parser.text import detect_language, normalize, repair_hyphenation

REPEATS = 5
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PARAGRAPH = (
    "Настоящий договор является основанием для оказания услуг. Стороны обязуются выполнять "
    "условия договора, а также нести ответственность за их нарушение. "
    "Ushbu qoidalar xizmat ko'rsatish tartibi va ma'lumot uchun belgilangan.\n"
)


def make_pdf(path: Path, pages: int) -> None:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_font(fontname="bench", fontfile=FONT)
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), PARAGRAPH * 8, fontname="bench")
    doc.save(path)


def timed(label: str, fn: Callable[[], object], units: float, unit_name: str) -> None:
    """Best of ``REPEATS`` runs, which hides scheduler noise."""
    best_wall = best_cpu = float("inf")
    for _ in range(REPEATS):
        wall, cpu = time.perf_counter(), time.process_time()
        fn()
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
        if wall < best_wall:
            best_wall, best_cpu = wall, cpu
    rate = units / best_wall
    print(f"{label:<28} wall {best_wall:7.3f}s  cpu {best_cpu:7.3f}s  {rate:12,.0f} {unit_name}/s")


def main() -> None:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "bench.pdf"
        make_pdf(pdf, pages)
        timed(f"parse PDF ({pages} pages)", lambda: parse(pdf), pages, "pages")
        document = parse(pdf)
        timed(f"chunk ({pages} pages)", lambda: chunk(document), pages, "pages")

    text = PARAGRAPH * 20_000
    mb = len(text.encode()) / 1e6
    timed("rust normalize", lambda: normalize(text), mb, "MB")
    timed("rust hyphenation", lambda: repair_hyphenation(text), mb, "MB")
    timed("rust detect_language", lambda: detect_language(text), mb, "MB")
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"peak memory (RSS)            {peak_mb:.0f} MB")


if __name__ == "__main__":
    main()
