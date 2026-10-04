"""Public parsing entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from zipfile import BadZipFile

from docx.opc.exceptions import PackageNotFoundError

from .docx import parse_docx
from .models import Document


class DocumentError(ValueError):
    """The file cannot be read as a document: empty, damaged, password-protected or of an
    unsupported type."""


PDF_EXTRA_MESSAGE = (
    "PDF support needs the optional PyMuPDF dependency: "
    'pip install "uzru-parser[pdf]". Note that PyMuPDF is licensed under AGPL-3.0 '
    "(or a commercial licence from Artifex)."
)


class Parser:
    """Parse a file into a normalized :class:`Document`.

    Supports DOCX, and PDF with the optional ``pdf`` extra (PyMuPDF). ``detect_tables``
    toggles PDF table detection. ``layout_model`` (off by default; needs the ``layout``
    extra) lets a small layout model correct the PDF pages the rules are unsure about:
    ``True`` uses the file named by ``UZRU_LAYOUT_MODEL`` (or one shipped with the package),
    a path names the ONNX file.
    """

    def __init__(self, detect_tables: bool = True, layout_model: bool | str | Path = False) -> None:
        self.detect_tables = detect_tables
        self.layout_model = layout_model

    def parse(self, path: str | Path) -> Document:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in (".pdf", ".docx"):
            raise DocumentError(f"Unsupported file type: {suffix!r} (PDF and DOCX are supported)")
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {str(path)!r}")
        if path.stat().st_size == 0:
            raise DocumentError(f"{path.name} is empty")
        if suffix == ".pdf":
            return _pdf_reader()(
                path, detect_tables=self.detect_tables, layout_model=self.layout_model
            )
        try:
            return parse_docx(path)
        except (PackageNotFoundError, BadZipFile, KeyError) as error:
            raise DocumentError(f"{path.name} is not a valid DOCX file") from error


def _pdf_reader() -> Callable[..., Document]:
    """The PDF reader, imported on first use so the package works without PyMuPDF."""
    try:
        from .pdf import parse_pdf
    except ImportError as error:  # PyMuPDF missing or unusable
        raise ImportError(PDF_EXTRA_MESSAGE) from error
    return parse_pdf


def parse(path: str | Path) -> Document:
    """Shortcut for ``Parser().parse(path)``."""
    return Parser().parse(path)
