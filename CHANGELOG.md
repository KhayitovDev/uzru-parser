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
- Faster language detection (about 2.5x) and a single-pass normalizer; shared character helpers.
- Hyphenation keeps "по-русски" style adverbs and acronym suffixes ("BMT-ning").
- Numbering recognizes "ПРИЛОЖЕНИЕ № 1" and roman sections ("I. Общие положения").
- DOCX: paragraph styles are resolved once per style (about 4x faster on a 6-page FAQ).
- Numbering: Uzbek order ("1-modda", "12-bob", "I BOʻLIM"), `§` sections, and legal hierarchy (part > chapter > paragraph > article); long article titles stay headings.
- Language detection recognizes short Uzbek Latin phrases ("q" without "u", typical endings).
