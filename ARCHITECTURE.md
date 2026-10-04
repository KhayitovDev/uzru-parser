# Architecture

## Goal

A lightweight, CPU-only parser and chunker for Russian and Uzbek documents (RAG input).
It does not try to reproduce general document understanding (that is Docling's job);
difficult documents can later fall back to OCR/Docling.

## Layers

```
Python API  (parse / Parser, later chunk / Chunker, CLI)
   │
   ├── format readers (Python ecosystem)
   │     PDF → PyMuPDF      DOCX → python-docx      TXT/MD (planned)
   │
   ▼
Rust core  (uzru_parser._core, embedded native extension)
   normalize_text · repair_hyphenation · detect_language
   numbering_info · split_sentences · estimate_tokens
   │
   ▼
Document (blocks + metadata)  ──►  Chunker (separate step)  ──►  Chunks
```

Parsing and chunking are separate: the chunker only sees the `Document` model, so it can
be improved independently.

## PDF routes

```
PDF ─► structure tree that passes the checks? ── yes ─► tagged route (tagged.py)
            │ no (or too slow, or PyMuPDF < 1.26.6)
            ▼
       rules route: lines ─► XY-cut reading order ─► paragraphs, tables ─► style profile
            ─► per-page confidence ─► (optional) layout model on low-confidence pages,
               which re-runs those pages with its corrections
            ▼
   headings, levels, language ─► Document ─► chunks
```

`metadata.extra["pdf_route"]` records `tagged`, `rules` or `rules+layout_model`.

* **Tagged route** (`tagged.py`). Word processors write a structure tree into accessible
  PDFs; MuPDF links it to the page text (`TEXT_COLLECT_STRUCTURE`). Each block-level element
  becomes a raw block: `H1`–`H6` headings with fixed levels (`heading_source="tags"`), `P`,
  list items (`Lbl` + `LBody`), tables from `TR`/`TH`/`TD` with `ColSpan`/`RowSpan`, notes
  as footnotes, captions, figures, contents entries. The role map names custom tags. An
  element continuing on the next page is joined back. Text outside the tree (artifacts,
  untagged text) is rebuilt like an untagged page and placed by position; page furniture is
  removed as on the rules route. Paragraphs are then joined as for DOCX. The tags are used
  only when they cover at least 80% of the text, hold paragraphs rather than whole pages,
  run down the page in each column, and every element is among its parent's kids. Two MuPDF
  behaviours are handled: an element stays open until the next one starts (a footer drawn
  after the last paragraph is split off in the margin band), and a paragraph's tail on the
  next page may come back untagged (it is joined like a split paragraph). Pages with
  thousands of marked-content ids, or a parent tree that lists elements out of place, make
  MuPDF's lookups quadratic (PyMuPDF issue 5125): the tree is then dropped in memory and the
  rules route runs at normal speed.
* **Rules route**: the pipeline below.

## Pipeline order (PDF, rules route)

1. Character cleanup per span and line (`pdf._line`, `text.clean`): symbol-font characters
   (Adobe Symbol / Wingdings tables, by font name), look-alike letters from the other
   alphabet (UTS #39 confusables, per word), apostrophes, spaces. No private-use character
   survives.
2. Reading order (`columns.py`): columns are cut at gutters; when no gutter runs through
   the whole page, the page is first cut into bands at blank gaps and full-width lines and
   each band is cut on its own (XY-cut with the banding and pre-masking of XY-Cut++). A
   single-column page keeps its order. Tables: PyMuPDF's ruling-line strategy on pages
   with vector paths, and its text strategy where rows of aligned cells suggest an unruled
   table or a ruled table scores poorly; the better-scoring reading wins (`tables.py`:
   consistent columns, few empty cells, no words cut between cells). Merged cells keep
   their span (`extra["spans"]`) and a cell merged down repeats its text in each row.
3. Line → paragraph rebuilding (`paragraphs.py`) from the document's own statistics (body
   font size, typical line gap, right edge, whether the producer writes one block per line):
   justified lines stored word by word are rejoined, inline formula pieces stay in their
   sentence, lone list markers join their text. Figure labels are grouped
   (`role="figure"`); line shading and shaded text areas are not figures, and a paragraph's
   short last line is never a label.
4. Hyphen rejoining with the document's own compounds kept (`Hyphenator`).
5. Page furniture (`layout.py`): page numbers (also "- 7 -", "[7]", Roman ones) and margin
   text repeated on half of the pages, on most even or odd pages, or on three consecutive
   pages at the same height and size (running chapter titles); footnotes, title page,
   contents (by shape; several per book, with their title line) and back matter; then
   formula and chart fragments are grouped into `role="formula"` blocks.
6. Style profile (`profile.py`): one pass over the document groups blocks by look (font
   family, size, bold, italic, capitals). The body style holds the most text; heading
   styles are more prominent, rare, mostly short and followed by body text, ranked by
   size, weight and rarity. Page confidence (`confidence.py`): 1 minus the worst of five
   checks (columns read as one, poor tables, prominent blocks outside the heading styles,
   mostly very short lines, a broken text layer), with the failing checks as `issues` in
   `page.extra`.
7. Optional layout model (`layout_model.py`, off by default, `layout` extra): pages below
   `LOW_PAGE_CONFIDENCE` are drawn at 480×480 and PP-DocLayout-S finds regions. Its tables
   are looked for with `find_tables` inside them, its figure and formula regions group labels
   and fragments, header and footer regions near the edges drop their text, title regions
   count as a heading signal, and on pages flagged `columns` an XY-cut of its text regions
   gives the reading order. Those pages are rebuilt and rated again. The model loads once
   per process (about 50 MB with ONNX Runtime).
8. Headings and levels (`structure.py`): bookmarks, then the contents page, then numbering,
   then style. With a style profile a heading needs a heading style and a second signal
   (numbering, bookmarks or contents, space above and space or body text below, or a
   layout-model title); a short heading-style line may end with a full stop ("Валюта
   бозори."). Without heading styles (and for DOCX) two signals of numbering, bigger font,
   bold, capitals and space above are needed. Real words are required (an unnumbered heading
   a word of 4+ letters); a plain "N." item is a list item unless it belongs to a heading
   sequence.
   Vetoes: outline entries (a plan whose numbered titles return later as headings),
   formulas, captions above a table, figure or formula (`role="caption"`), text inside a
   table frame or a labelled drawing, run-in titles whose sentence runs on, ":" labels.
   Recurring heading text gets one decision. Levels are decided once per document:
   bookmarks, then numbering, then style rank. An unnumbered heading takes the level of the
   numbered headings it looks like; a style less prominent than a numbered heading style
   sits below it; else it sits inside the chapter; chapter words that never nest share a
   level; "1., 2." restarting inside "N.M" nest under it; a child never sits above its
   parent; levels are dense. Wrapped titles are joined.
9. Language per block, short blocks borrow their neighbours'; document language weighted by
   length.
10. Chunking.

Every tunable threshold and word list lives in `config.py`.

## Python / Rust boundary

* Python: file formats, orchestration, public API, data models.
* Rust: deterministic text processing. Each function takes a string and returns plain
  values, so crossing the boundary is cheap and there is no shared state.
* No separate process, service or HTTP layer.

## Structure detection (`structure.py`)

Format readers produce `RawBlock`s (text, page, bbox, font size and family, bold and italic
share, and what the reader already knows: heading level, list item, table rows and spans,
role). `build_blocks` turns them into typed blocks:

* **Heading**: see pipeline step 8; levels from bookmarks, numbering, then style.
* **List**: lines starting with a bullet or `1)` / `a)`; adjacent list blocks are merged.
* A long numbered clause (`1.1. Стороны обязуются ...`) stays a paragraph.

## Readers

* **PDF** (`pdf.py`): text blocks with font size, family, bold and italic share from
  PyMuPDF; the tagged route when the structure tags pass their checks. Ruled tables come
  from `find_tables()`, which only runs on pages with at least four vector paths because it
  is expensive (the text strategy only where aligned rows suggest a table); a table grows
  over the merged rows its own ruling closes. Text inside a
  table is not repeated as paragraphs. PyMuPDF is not thread-safe, so one document is read
  at a time under a lock (threads are safe but serialised; processes run in parallel). The
  title page gives the title when the file has none. `layout.py` removes page
  numbers and text repeated in the top/bottom 10% of at least half the pages. A page with
  images and almost no text gets `needs_ocr`, the hook for a future OCR/Docling fallback.
* **DOCX** (`docx.py`): heading level from the style (`Heading N`, localized names, `Title`,
  `w:outlineLvl`, inherited styles), lists from numbering/`List*` styles with Word's own
  markers ("1.", "a)", "•" from `numbering.xml`), tables from the table XML. A short paragraph
  set entirely in bold (or kept with the next) and followed by plain text is a subheading one
  level below the numbered heading before it; extra space above marks a paragraph as set
  apart. Leading centred bold lines are the title when Word's title property is empty.
  Unstyled paragraphs fall back to the same heuristics as PDF. Pages are approximate.

## Chunking (`chunking.py`)

Input is only the `Document`. Every heading starts a new chunk; inside a section whole
blocks are packed up to `max_tokens`. Oversized blocks are split by sentences (lines for
lists/tables, words as a last resort). Overlap repeats trailing sentences of the previous
chunk within the same section only, and never opens with list items cut off from their
lead-in. A lead-in line ending with ":" moves to the chunk with what it introduces. Blocks
with `role` `toc`, `back_matter` or `title_page` stay in `document.blocks` but never enter
chunk text; `figure` and `formula` blocks never form a chunk alone. Tokens are estimated (about 4 characters per token);
pass `token_counter` to use a real tokenizer. Each chunk carries `heading_path`, page range,
language/script and an extensible `metadata` dict.

## Data model (`python/uzru_parser/models.py`)

`Document` → `DocumentMetadata`, `Page[]`, `Block[]`, `LanguageInfo`.
`Block` has a `type` (heading, paragraph, list, table, code, quote), normalized `text`,
the original `raw_text`, page number, optional bbox, and per-block language.

## Text rules

* NFC only (never NFKC). `ё` is never turned into `е`. No stemming or stop-word removal.
* Uzbek apostrophes are rewritten only between two Latin letters: after `o`/`g` →
  `ʻ` (U+02BB), elsewhere → `ʼ` (U+02BC). Quotes and Cyrillic text are untouched.
* Hyphenation: join `letter-\nlowercase` unless the pieces form a known hyphenated word
  ("кто-то", "из-за", "северо-запад", ...). Heuristic, covered by tests, no dictionary.
* Language: per-word votes from script-specific letters and small stop-word lists;
  result is `ru | uz | mixed | unknown` plus script (`latin | cyrillic | mixed | none`).
  `LanguageInfo.locale` gives `uz-Latn` / `uz-Cyrl`.

## Confidence and fallback

Each PDF page carries `extra["confidence"]` and `extra["issues"]`; low-confidence pages are
what the optional layout model corrects. Pages without text (`needs_ocr`) get confidence 0
and the issue `no_text`: an OCR fallback for them is not implemented.

## Build and packaging

`maturin` builds `uzru_parser._core` from `src/` (PyO3, stable ABI `abi3-py310`, so one wheel
per platform serves CPython 3.10+); pure Python lives in `python/`. The optional `layout`
extra adds ONNX Runtime for the layout model; the model file itself is not shipped (point
`UZRU_LAYOUT_MODEL` at it). PyMuPDF (AGPL-3.0) is the optional `pdf` extra: `parser.py` imports the PDF reader only when a PDF is parsed and raises
an `ImportError` naming the extra when it is missing. Unreadable files (empty, damaged,
password-protected, unsupported) raise `DocumentError`. `.github/workflows/release.yml`
builds and tests the wheels and the sdist and publishes them with PyPI Trusted Publishing.
