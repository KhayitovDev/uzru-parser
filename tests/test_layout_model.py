"""The optional layout model: off by default, run only on unsure pages, and its regions only
correct the rules. A fake detector stands in for the model; one test runs the real model when
ONNX Runtime and the model file are installed."""

import importlib.util
import os
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from helpers import bold_font, cyrillic_font
from uzru_parser import BlockType, Parser, layout_model, parse
from uzru_parser import config as uzru_config
from uzru_parser.layout_model import Region, hints, order_lines, xy_order
from uzru_parser.paragraphs import Line

BODY = (
    "Bank tizimi davlat iqtisodiyotining muhim qismi boʻlib, pul muomalasini tartibga soladi "
    "va mijozlarga xizmat koʻrsatadi hamda boshqa vazifalarni ham bajaradi."
)


def sample_pdf(path: Path) -> Path:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="R", fontfile=cyrillic_font())
    page.insert_font(fontname="B", fontfile=bold_font())
    page.insert_text((72, 40), "Jurnal sarlavhasi 2026", fontname="R", fontsize=9)
    page.insert_text((72, 100), "Bank tizimi haqida", fontname="B", fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 120, 523, 200), BODY, fontname="R", fontsize=11)
    page.insert_text((200, 260), "x = y + 2", fontname="R", fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 300, 523, 380), BODY, fontname="R", fontsize=11)
    pdf.save(path)
    return path


REGIONS = [
    Region("header", 0.9, (70, 30, 200, 45)),
    Region("paragraph_title", 0.8, (70, 88, 200, 104)),
    Region("text", 0.9, (70, 115, 525, 200)),
    Region("formula", 0.8, (190, 248, 260, 264)),
    Region("text", 0.9, (70, 295, 525, 380)),
]


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Every page counts as unsure and the "model" returns REGIONS."""
    model = tmp_path / "model.onnx"
    model.write_bytes(b"fake")
    monkeypatch.setattr(uzru_config, "LOW_PAGE_CONFIDENCE", 1.01)
    monkeypatch.setattr(layout_model, "load", lambda path: (object(), "ready"))
    monkeypatch.setattr(layout_model, "detect", lambda session, page: list(REGIONS))
    return model


def test_off_by_default(tmp_path: Path) -> None:
    extra = parse(sample_pdf(tmp_path / "a.pdf")).metadata.extra
    assert extra["pdf_route"] == "rules" and "layout_model" not in extra


def test_regions_correct_unsure_pages(tmp_path: Path, fake_model: Path) -> None:
    document = Parser(layout_model=fake_model).parse(sample_pdf(tmp_path / "a.pdf"))
    extra = document.metadata.extra
    assert extra["pdf_route"] == "rules+layout_model"
    assert extra["layout_model"] == {"status": "used", "pages": [1]}
    assert document.pages[0].extra["layout_model"] is True
    texts = {b.text: b for b in document.blocks}
    assert "Jurnal sarlavhasi 2026" not in texts  # the header region is page furniture
    assert texts["Bank tizimi haqida"].type is BlockType.HEADING  # bold, in a title region
    assert texts["x = y + 2"].extra.get("role") == "formula"


def test_a_missing_model_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uzru_config, "LOW_PAGE_CONFIDENCE", 1.01)
    path = sample_pdf(tmp_path / "a.pdf")
    plain = parse(path)
    document = Parser(layout_model=tmp_path / "missing.onnx").parse(path)
    status = document.metadata.extra["layout_model"]["status"]
    if importlib.util.find_spec("onnxruntime") is None:
        assert status.startswith("onnxruntime missing")
    else:
        assert status == "model file not found: missing.onnx"
    assert [b.text for b in document.blocks] == [b.text for b in plain.blocks]


def test_confident_pages_never_run_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: Any) -> None:
        raise AssertionError("the model must not run")

    monkeypatch.setattr(layout_model, "load", fail)
    document = Parser(layout_model=tmp_path / "m.onnx").parse(sample_pdf(tmp_path / "a.pdf"))
    assert document.metadata.extra["layout_model"] == {"status": "not needed", "pages": []}


def test_xy_order_reads_columns_then_bands() -> None:
    title = (50.0, 50.0, 550.0, 70.0)
    left = [(50.0, 100.0 + 60 * i, 280.0, 150.0 + 60 * i) for i in range(3)]
    right = [(320.0, 100.0 + 60 * i, 550.0, 150.0 + 60 * i) for i in range(3)]
    footer_wide = (50.0, 400.0, 550.0, 420.0)
    shuffled = [right[1], left[2], footer_wide, right[0], title, left[0], right[2], left[1]]
    assert xy_order(shuffled, 10.0) == [title, *left, *right, footer_wide]


def test_hints_keep_furniture_to_the_margins_and_order_to_column_pages() -> None:
    regions = [
        Region("header", 0.9, (50, 20, 300, 40)),
        Region("footer", 0.9, (50, 400, 300, 420)),  # mid-page "footer": not furniture
        Region("text", 0.9, (50, 100, 280, 300)),
        Region("text", 0.9, (320, 100, 550, 300)),
        Region("image", 0.9, (60, 500, 300, 600)),
        Region("table", 0.9, (60, 620, 500, 700)),
    ]
    page = (0.0, 0.0, 595.0, 842.0)
    found = hints(regions, page, [], 10.0)
    assert found.furniture == [(50, 20, 300, 40)]
    assert found.figures == [(60, 500, 300, 600)] and found.tables == [(60, 620, 500, 700)]
    assert found.order is None
    assert hints(regions, page, ["columns"], 10.0).order == [
        (50, 100, 280, 300),
        (320, 100, 550, 300),
    ]


def line(text: str, x0: float, y: float, x1: float = 270.0) -> Line:
    return Line(text=text, bbox=(x0, y, x1, y + 12), size=10.0, chars=len(text))


def test_lines_follow_the_regions_and_strays_join_the_nearest() -> None:
    left = [line(f"chap {i}", 55, 110 + 14 * i) for i in range(3)]
    right = [line(f"oʻng {i}", 325, 110 + 14 * i, 540) for i in range(3)]
    stray = line("chap davomi", 55, 160)  # just below the left region
    far = line("sahifa izohi", 55, 700)
    mixed = [left[0], right[0], left[1], right[1], left[2], right[2], stray, far]
    boxes = [(50.0, 105.0, 280.0, 150.0), (320.0, 105.0, 550.0, 150.0)]
    groups = order_lines(mixed, boxes)
    assert groups == [[*left, stray], right, [far]]


MODEL = os.environ.get(layout_model.MODEL_ENV)


@pytest.mark.skipif(
    importlib.util.find_spec("onnxruntime") is None or not MODEL or not Path(MODEL).is_file(),
    reason="needs onnxruntime and UZRU_LAYOUT_MODEL",
)
def test_the_real_model_runs_on_an_unsure_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uzru_config, "LOW_PAGE_CONFIDENCE", 1.01)
    document = Parser(layout_model=True).parse(sample_pdf(tmp_path / "a.pdf"))
    assert document.metadata.extra["layout_model"]["status"] == "used"
    assert "Bank tizimi" in document.text
