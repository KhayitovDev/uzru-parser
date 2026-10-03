# Changelog

## 0.1.0 (unreleased)

- Rust core: Unicode normalization (Uzbek apostrophes), PDF hyphenation repair, language/script detection.
- Python: `Document` model, PyMuPDF-based PDF parser, `Parser` / `parse` API.
- Structure detection: headings (numbering, font size, bold, capitals) and lists.
- Structural chunker with heading paths, overlap and sentence/line/word fallbacks.
- Rust: numbering detection, sentence splitting, token estimate.
- DOCX parser (styles, lists, tables, approximate pages from page breaks).
- PDF: ruled-table detection, running header/footer and page-number removal, per-page `needs_ocr` flag.
- Rust: table-of-contents dot leaders collapse to a single ellipsis during normalization.
