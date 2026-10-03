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
- Language detection: removed English-prone Uzbek endings and ignore marker words that cover under 5% of a text.
- Pipeline reordered: character cleanup first, then line-to-paragraph rebuilding, hyphens,
  page analysis, headings, language, chunks.
- Look-alike Cyrillic/Latin letters fixed per word (UTS #39 pairs); 9 apostrophe variants;
  symbol-font characters mapped by font (Symbol / Wingdings), none left in the output.
- Paragraphs rebuilt from lines using document statistics; figure labels grouped.
- Hyphens of compounds that the document writes whole are kept.
- Headings from bookmarks, contents page, numbering ("I-BOB", "5.3.Title"), font; real-word
  and two-signal rules; "N." items are list items unless used as headings; parent/child
  levels enforced.
- Contents detected by shape on all its pages; glued footnote numbers ("1И.") split.
- Tables: split header rows merged, repeated header cells dropped, running text rejected.
- Short blocks take their neighbours' language; tiny chunks merged; headings never alone.
- All thresholds and word lists in `config.py`; cleanup counts and heading sources in
  `document.metadata.extra`.
- Structure: outline entries (chapter plans) become lists; heading vetoes for formulas,
  captions (`role="caption"`), text inside tables or labelled drawings, run-in titles and
  ":" labels; levels from the look of numbered headings, rival chapter words share a level,
  restarting numbers nest, no level gaps; wrapped titles joined; recurring heading text gets
  one decision.
- PDF: line shading is not a figure; justified lines stored word by word, inline formula
  pieces and lone list markers are rejoined; formula and chart fragments become
  `role="formula"` blocks; tables grow over merged rows closed by their ruling; several
  contents sections per book with their titles; title from the title page; thread-safe
  (PyMuPDF work serialised under a lock).
- DOCX: bold standalone paragraphs, `w:outlineLvl` and `w:keepNext` give subheadings; Word
  list numbering kept ("1.", "a)", "•"); leading centred bold lines become the title.
- Chunking: lead-ins stay with their lists, overlap never opens with orphan list items;
  title page, contents and back matter stay out of chunk text.
