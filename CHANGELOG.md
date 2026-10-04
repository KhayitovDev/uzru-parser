# Changelog

## 0.2.0 (2026-10-04)

Measured with `tools/evaluate.py` on ten real Uzbek and Russian documents (legal acts,
textbooks, an FAQ): heading-path accuracy rose from 0.02–0.88 to 0.90–1.00 per document,
tables found in the sanitary-rules PDF from 6 to 11 of 12, table rows repeated by overlap
from 18 to 0, at the same speed and memory.

- PDF reading order: justified lines stored word by word are rebuilt before the XY-cut, and
  a column needs several rows, so a stretched line stays in its sentence.
- Centred multi-line titles and stamps are one block; "." spacer paragraphs are dropped.
- Tables: a table cut by a page break is joined (repeated header dropped, a cut cell's rest
  put back); a page number in a table frame is no row; values starting in lowercase are no
  longer taken for words cut between cells, so ruled tables keep all their columns.
- Chunking: tables are cut between rows with the header repeated and no overlap rows;
  chunk metadata (`content_type`, `tables` with header and rows, `is_appendix`,
  `source_title`, `language_source`); a chunk without its own language takes the
  document's.
- Headings: signatures, diagram labels and text that only looks like a heading are vetoed;
  unreliable PDF heading tags are ignored; appendix stamps give their label as a heading;
  titles nest under their label; sections typed as list items and sequences with a missing
  member are found; the document's opening title and a contents title leave the outline;
  recurring end-of-chapter headings sit beside the sections; a byte-order mark no longer
  hides a DOCX title; long numbered titles and "II." after an item-numbered paragraph are
  kept.
- Pictures inside the text are kept as `[image]` placeholders; documents report quality
  warnings (`no_text_layer`, `low_confidence_pages`, `pictures_not_read`, ...).
- The document title is taken from the content first; a file title is used only when the
  document says it too.
- `tools/evaluate.py`: quality evaluation of a folder of documents, with optional
  hand-made heading outlines (`--gold DIR`).

Then checked on 21 other files never used while developing (Uzbek legal acts, Russian
decrees converted from scans, technical specifications, an English book, slide decks),
which found these generic faults, now fixed:

- Language: English documents were labelled `uz` (a few Uzbek-looking lines decided), and
  their chunks then took `uz` too; a document mostly in no known language is `unknown`.
- DOCX: a cell merged down over rows was repeated in every row it covers (a header read
  three times); a placeholder title property ("Untitled") is ignored; a bold line that looks
  like an outline-level title is its sibling, not its child.
- Appendices: the stamp ("... qaroriga") now opens its appendix after the label instead of
  ending the previous chapter, also when its lines are separate blocks; the label heading no
  longer swallows it.
- Chunking: a short text under a heading stays with the first subsection instead of making
  a chunk of a few tokens.
- PDF: bullets glued to their text ("■Always ...", "✦ ...") start list items and keep their
  wrapped lines (Rust core); a book's running titles on every other page, and a short
  section's single one, are removed; a picture placeholder no longer turns the title above
  it into a caption.
- Headings: section numbers overrule contradicting Word outline levels; plain "I. / II. /
  III." chapter lines are chapters; "УТВЕРЖДЕНА" / "TASDIQLANGAN" stamps are no headings;
  a heading-style line right under another heading counts; bookmark levels are not
  overridden by a look-alike numbered style; the opening headings of a styled document are
  its title only when they are siblings or their level does not come back.
- Titles: a PDF's file title is also accepted when its words all appear on the cover; a
  logo letter is no title.

## 0.1.0 (2026-10-04)

First public alpha release.

**Features:** PDF and DOCX parsing for Russian and Uzbek (Latin and Cyrillic) into typed
blocks (headings with levels, paragraphs, lists, tables, footnotes) with per-block language;
structural chunking with heading paths, page ranges and overlap; a Rust core for
normalization, hyphenation repair, language detection, numbering and sentence splitting.

**Packaging:** PDF support is the optional `pdf` extra (`pip install "uzru-parser[pdf]"`)
because PyMuPDF is AGPL-3.0; `import uzru_parser` and DOCX parsing work without it. One abi3
wheel per platform covers CPython 3.10 and newer. Unreadable files raise `DocumentError`.

**PDF structure:** tagged PDFs are read from their structure tags (`pdf_route = "tagged"`);
other PDFs get a style profile of the whole document, headings that need a heading style and
a second signal (or a numbered heading word such as "1-ILOVA"), XY-cut reading order for
columns, ruled and unruled tables scored against each other, and a confidence score per page.
An optional layout model (PP-DocLayout-S through ONNX Runtime, the `layout` extra, off by
default) corrects low-confidence pages.

**Limitations:** no OCR (scanned pages get `needs_ocr`); titles broken across two columns or
pages may be split; DOCX page numbers are approximate; English is labelled `unknown`;
formulas and charts become `formula` / `figure` blocks; PDF parsing in threads is serialised.

### Changes in detail

- PDF: tagged route (headings, lists, tables with merged cells, notes from the structure tree;
  page headers caught inside a tagged paragraph are dropped); metadata `pdf_route`,
  `pdf_tags`, `styles`; page `extra` with `confidence` and `issues`.
- PDF headings: heading styles may be followed by another heading style; titles wrapped over
  several lines or blocks are one heading; numbered articles may wrap over six lines; inserted
  articles ("10¹-modda") and parts numbered in words ("BIRINCHI BOʻLIM", "ЧАСТЬ ПЕРВАЯ").
- PDF paragraphs: short lines ending with ";" close an enumeration item; a sentence left open
  at a page end goes on before a capital; ragged lines broken before a long word run on.
- PDF tables: only thin bars and stroked paths count as table rules (browser line
  backgrounds made fake tables), and ruled tables are only searched for when the page has
  rules both ways (faster pages without tables).
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
