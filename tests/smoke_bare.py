"""Smoke test for an install without the ``pdf`` extra (run by the release workflow).

Checks that the package imports, parses a generated DOCX, and explains how to get PDF
support. Not collected by pytest.
"""

import tempfile
from pathlib import Path

import docx
import uzru_parser

with tempfile.TemporaryDirectory() as folder:
    document = docx.Document()
    document.add_paragraph("Ilova foydalanuvchilarga bank tizimi haqida maʼlumot beradi.")
    path = Path(folder) / "plain.docx"
    document.save(str(path))
    parsed = uzru_parser.parse(path)
    assert parsed.blocks[0].text.startswith("Ilova"), parsed.blocks
    assert uzru_parser.chunk(parsed), "no chunks"

    pdf = Path(folder) / "file.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    try:
        uzru_parser.parse(pdf)
    except ImportError as error:
        assert "uzru-parser[pdf]" in str(error) and "AGPL" in str(error), error
    else:
        raise AssertionError("parsing a PDF without the extra should raise ImportError")

print("bare install OK:", uzru_parser.__version__)
