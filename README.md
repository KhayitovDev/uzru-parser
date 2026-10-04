# uzru-parser

CPU-first document parser and chunker for **Russian** and **Uzbek** (Latin and Cyrillic)
documents, built for retrieval-augmented generation (RAG). A Python API on top of a small
Rust core: no GPU, no machine-learning models to download, no network calls.

> **Alpha (0.2.0).** The API may change before 1.0.

## Installation

```bash
pip install uzru-parser            # DOCX support
pip install "uzru-parser[pdf]"     # DOCX and PDF support
pip install "uzru-parser[layout]"  # PDF support plus the optional layout model (ONNX Runtime)
```

PDF support uses [PyMuPDF](https://github.com/pymupdf/PyMuPDF), installed by the `pdf` extra.
PyMuPDF is licensed under **AGPL-3.0** (or a commercial licence from Artifex): check that this
fits your use before installing the extra. Without it, parsing a PDF raises an `ImportError`
that explains how to install it. On Alpine Linux, PyMuPDF also needs the C++ runtime:
`apk add libstdc++`.

Wheels are published for Linux (x86_64, aarch64, musl), macOS (Intel and Apple Silicon) and
Windows (x64), for CPython 3.10 and newer.

## Quick start

**Input**: `sample.docx`, a short Uzbek document with a title and two numbered sections:

```text
Ijara shartnomasi                                   (Heading 1)

1. Umumiy qoidalar                                  (Heading 2)
Ushbu shartnoma ijaraga beruvchi va ijarachi o‘rtasida turar joyni
vaqtincha foydalanishga berish shartlarini belgilaydi.

2. Tomonlarning majburiyatlari                      (Heading 2)
Ijarachi ijara haqini har oyning 10-sanasigacha to‘laydi va turar joyni
ozoda saqlaydi.
```

**Code**:

```python
import json
from uzru_parser import Chunker, parse

document = parse("sample.docx")  # or "sample.pdf" with the pdf extra
chunks = Chunker(max_tokens=600, overlap=80).chunk(document)

for chunk in chunks:
    print(json.dumps(chunk.to_dict(), ensure_ascii=False, indent=2))
```

**Output**: one JSON object per chunk, each section with the headings above it:

```json
{
  "chunk_id": "61725848e421179b-0000",
  "document_id": "61725848e421179b",
  "text": "Ijara shartnomasi\n\n1. Umumiy qoidalar\n\nUshbu shartnoma ijaraga beruvchi va ijarachi oʻrtasida turar joyni vaqtincha foydalanishga berish shartlarini belgilaydi.",
  "language": "uz",
  "script": "latin",
  "page_start": 1,
  "page_end": 1,
  "heading_path": [
    "Ijara shartnomasi",
    "1. Umumiy qoidalar"
  ],
  "chunk_index": 0,
  "token_count": 44,
  "metadata": {
    "content_type": "prose",
    "content_types": [
      "prose"
    ],
    "language_source": "chunk"
  }
}
{
  "chunk_id": "61725848e421179b-0001",
  "document_id": "61725848e421179b",
  "text": "2. Tomonlarning majburiyatlari\n\nIjarachi ijara haqini har oyning 10-sanasigacha toʻlaydi va turar joyni ozoda saqlaydi.",
  "language": "uz",
  "script": "latin",
  "page_start": 1,
  "page_end": 1,
  "heading_path": [
    "Ijara shartnomasi",
    "2. Tomonlarning majburiyatlari"
  ],
  "chunk_index": 1,
  "token_count": 33,
  "metadata": {
    "content_type": "prose",
    "content_types": [
      "prose"
    ],
    "language_source": "chunk"
  }
}
```

`ensure_ascii=False` keeps Cyrillic and Uzbek letters readable instead of `\u` escapes.
`document.to_dict()` gives the whole parsed document (pages, blocks, language) the same way.

## Output

- **`Document`**: `metadata` (source, format, title, author, page count), `pages`
  (with a `needs_ocr` flag), `blocks`, and the document `language`.
- **Blocks**: `heading` (with `level`), `paragraph`, `list` (items in `extra["items"]`),
  `table`, `footnote`; each with its text, the raw extracted text, page, bounding box (PDF)
  and its own language. `extra["role"]` marks material set apart from the running text:
  `title_page`, `toc`, `back_matter`, `figure`, `formula`, `caption`, `image`. A document
  whose first page opens with its title (an act's issuer and name) gets it as
  `metadata.title`, not as a heading.
- **Chunks**: text of at most `max_tokens` (estimated, or your own `token_counter`), the
  `heading_path` of headings above it, page range, language and script, and `metadata`.
  Headings start new chunks; title page, contents and back matter are left out of chunk
  text. Tables are cut only between rows; a chunk that goes on with a table starts with its
  header rows again, and overlap never repeats table rows.
- **Chunk metadata**: `content_type` (`prose`, `list`, `table`, `formula`, `figure`, `image`
  or `mixed`) and `content_types`; `tables` with the `header` and `rows` of each table part
  in the chunk and whether it is `continued` from the previous chunk; `is_appendix` for
  chunks under an appendix label ("1-ILOVA", "Приложение № 2"); `source_title`;
  `language_source` (`chunk`, or `document` when the chunk's text alone tells no language,
  as a table of chemical names); `footnotes`.
- **Quality warnings**: `metadata.extra["quality"]["warnings"]` lists what could not be read
  well: `no_text_layer` (scanned pages), `low_confidence_pages`, `pictures_not_read`
  (formulas or charts set as pictures: their place in the text is kept as `[image]`),
  `language_uncertain`, `little_or_no_text`.
- **Language**: `ru`, `uz` (`latin` or `cyrillic` script), `mixed` or `unknown`, per block
  and per chunk.
- **PDF details**: `metadata.extra["pdf_route"]` says how the PDF was read (`tagged`,
  `rules` or `rules+layout_model`, see below), `pdf_tags` what its structure tags were,
  `styles` the body and heading styles found; each page's `extra` holds its `confidence`
  (0 to 1) and the `issues` behind it; tables list merged cells in `extra["spans"]`.

## PDF routes

- **Tagged PDFs** (for example Word's "Save as PDF" with document structure tags): the
  author's headings, paragraphs, lists, tables and notes are read from the tags, after
  checking that they cover the text and follow the page. Needs PyMuPDF 1.26.6 or newer.
- **Other PDFs** are rebuilt from the layout: a style profile of the whole document (body
  and heading styles), headings that need a heading style and a second signal (numbering,
  bookmarks or contents, space around them), an XY-cut reading order for columns, ruled and
  unruled tables, and a confidence score per page.
- **Optional layout model** (off by default): with the `layout` extra,
  `Parser(layout_model=True)` lets [PP-DocLayout-S](https://huggingface.co/PaddlePaddle/PP-DocLayout-S)
  (Apache-2.0, 4.7 MB as ONNX, about 20 ms a page on a CPU) correct the pages with low
  confidence: tables, figures, formulas, headers and footers, titles, reading order. Point
  `UZRU_LAYOUT_MODEL` at the ONNX file (or pass its path as `layout_model`); without the
  file or ONNX Runtime the parser runs as usual and says why in
  `metadata.extra["layout_model"]`.

## Supported formats

| Format | Reader | Notes |
|---|---|---|
| DOCX | python-docx | Word styles, outline levels, bold subheadings, Word list numbering, tables |
| PDF | PyMuPDF (`pdf` extra) | Text-based PDFs; structure tags when present; headings, lists, ruled and unruled tables, footnotes, contents pages |

## Limitations

- No OCR: scanned or image-only pages produce no text and get `needs_ocr = True`.
- PDF layout: single-column pages are the main target; two- and three-column pages, also
  with different column layouts above and below, are reordered; complex layouts may need
  the optional layout model, which was trained on Chinese and English documents.
- DOCX page numbers are approximate (taken from page breaks).
- English text is labelled `unknown` (also the whole document when most of it is English).
- Formulas and charts are reduced to `formula` / `figure` blocks; pictures inside the text
  become `[image]` placeholders (their content needs OCR).
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
