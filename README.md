# uzru-parser

CPU-first document parser and chunker for **Russian** and **Uzbek** (Latin and Cyrillic)
documents, built for retrieval-augmented generation (RAG). A Python API on top of a small
Rust core: no GPU, no machine-learning models to download, no network calls.

> **Alpha (0.1.0).** The API may change before 1.0.

## Installation

```bash
pip install uzru-parser            # DOCX support
pip install "uzru-parser[pdf]"     # DOCX and PDF support
```

PDF support uses [PyMuPDF](https://github.com/pymupdf/PyMuPDF), installed by the `pdf` extra.
PyMuPDF is licensed under **AGPL-3.0** (or a commercial licence from Artifex): check that this
fits your use before installing the extra. Without it, parsing a PDF raises an `ImportError`
that explains how to install it. On Alpine Linux, PyMuPDF also needs the C++ runtime:
`apk add libstdc++`.

Wheels are published for Linux (x86_64, aarch64, musl), macOS (Intel and Apple Silicon) and
Windows (x64), for CPython 3.10 and newer.

## Quick start

```python
from uzru_parser import Chunker, parse

document = parse("contract.docx")  # or "contract.pdf" with the pdf extra
print(document.metadata.title, document.language.language)

for block in document.blocks[:5]:
    print(block.type.value, block.page, block.text[:60])

chunks = Chunker(max_tokens=600, overlap=80).chunk(document)
for chunk in chunks[:3]:
    print(chunk.heading_path, chunk.page_start, chunk.text[:80])
```

`document.to_dict()` and `chunk.to_dict()` give plain JSON-ready dictionaries.

## Output

- **`Document`**: `metadata` (source, format, title, author, page count), `pages`
  (with a `needs_ocr` flag), `blocks`, and the document `language`.
- **Blocks**: `heading` (with `level`), `paragraph`, `list` (items in `extra["items"]`),
  `table`, `footnote`; each with its text, the raw extracted text, page, bounding box (PDF)
  and its own language. `extra["role"]` marks material set apart from the running text:
  `title_page`, `toc`, `back_matter`, `figure`, `formula`, `caption`.
- **Chunks**: text of at most `max_tokens` (estimated, or your own `token_counter`), the
  `heading_path` of headings above it, page range, language and script, and `metadata`
  (footnotes of the chunk). Headings start new chunks; title page, contents and back matter
  are left out of chunk text.
- **Language**: `ru`, `uz` (`latin` or `cyrillic` script), `mixed` or `unknown`, per block
  and per chunk.

## Supported formats

| Format | Reader | Notes |
|---|---|---|
| DOCX | python-docx | Word styles, outline levels, bold subheadings, Word list numbering, tables |
| PDF | PyMuPDF (`pdf` extra) | Text-based PDFs; headings, lists, ruled tables, footnotes, contents pages |

## Limitations

- No OCR: scanned or image-only pages produce no text and get `needs_ocr = True`.
- PDF layout: single-column pages are the main target; simple two- and three-column pages
  are reordered, complex layouts are not.
- DOCX page numbers are approximate (taken from page breaks).
- English text is labelled `unknown`.
- Formulas and charts are reduced to `formula` / `figure` blocks.
- PDF parsing from several threads is safe but serialised (PyMuPDF is not thread-safe); use
  processes for parallelism.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"
pytest && ruff check . && mypy
cargo test
```

See [ARCHITECTURE.md](https://github.com/KhayitovDev/uzru-parser/blob/main/ARCHITECTURE.md)
for the design and
[CHANGELOG.md](https://github.com/KhayitovDev/uzru-parser/blob/main/CHANGELOG.md) for changes.

## Licence

- Source code: [MIT](https://github.com/KhayitovDev/uzru-parser/blob/main/LICENSE).
- Bundled data files (language model and word list in `src/data/`): CC BY-SA 4.0, because
  they are adapted from CC BY-SA 4.0 corpora
  ([notice](https://github.com/KhayitovDev/uzru-parser/blob/main/src/data/LICENSE)).
- Optional PDF backend: PyMuPDF, AGPL-3.0 or commercial licence from Artifex.

Third-party sources, their licences and the required notices are listed in
[THIRD_PARTY.md](https://github.com/KhayitovDev/uzru-parser/blob/main/THIRD_PARTY.md).
