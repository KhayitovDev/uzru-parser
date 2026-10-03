"""The package works without the optional PyMuPDF dependency."""

import importlib
import sys
from pathlib import Path

import docx
import pytest


@pytest.fixture
def without_pymupdf(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setitem(sys.modules, "pymupdf", None)  # makes "import pymupdf" fail
    for name in [m for m in sys.modules if m == "uzru_parser" or m.startswith("uzru_parser.")]:
        if name != "uzru_parser._core":
            monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module("uzru_parser")
    yield module


def test_import_and_docx_work_without_pymupdf(without_pymupdf: object, tmp_path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Ilova foydalanuvchilarga bank tizimi haqida maʼlumot beradi.")
    path = tmp_path / "plain.docx"
    document.save(str(path))
    parsed = without_pymupdf.parse(path)  # type: ignore[attr-defined]
    assert parsed.blocks[0].text.startswith("Ilova")


def test_pdf_without_pymupdf_explains_the_extra(without_pymupdf: object, tmp_path: Path) -> None:
    path = tmp_path / "file.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ImportError, match=r"uzru-parser\[pdf\].*AGPL-3\.0"):
        without_pymupdf.parse(path)  # type: ignore[attr-defined]
