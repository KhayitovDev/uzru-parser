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

## Pipeline order (PDF)

1. Character cleanup per span and line (`pdf._line`, `text.clean`): symbol-font characters
   (Adobe Symbol / Wingdings tables, by font name), look-alike letters from the other
   alphabet (UTS #39 confusables, per word), apostrophes, spaces. No private-use character
   survives.
2. Line → paragraph rebuilding (`paragraphs.py`) from the document's own statistics (body
   font size, typical line gap, right edge, whether the producer writes one block per line);
   figure labels are grouped (`role="figure"`).
3. Hyphen rejoining with the document's own compounds kept (`Hyphenator`).
4. Page furniture, footnotes, title page, contents (by shape) and back matter (`layout.py`).
5. Headings and levels (`structure.py`): bookmarks, then the contents page, then numbering,
   then font; a heading needs two signals and real words; a plain "N." item is a list item
   unless it belongs to a heading sequence; a child never sits above its parent.
6. Language per block, short blocks borrow their neighbours'; document language weighted by
   length.
7. Chunking.

Every tunable threshold and word list lives in `config.py`.

## Python / Rust boundary

* Python: file formats, orchestration, public API, data models.
* Rust: deterministic text processing. Each function takes a string and returns plain
  values, so crossing the boundary is cheap and there is no shared state.
* No separate process, service or HTTP layer.

## Structure detection (`structure.py`)

Format readers produce `RawBlock`s (text, page, bbox, font size, bold share).
`build_blocks` turns them into typed blocks:

* **Heading**: score from larger-than-body font (+2), bold (+1), uppercase (+2 if short),
  numbering (`1.`, `1.1.` +1; `Статья 5`, `Modda 3`, `Bo‘lim 2` +2). Score ≥ 2 and a short
  line without sentence punctuation. Level comes from numbering depth, else font-size rank.
* **List**: lines starting with a bullet or `1)` / `a)`; adjacent list blocks are merged.
* A long numbered clause (`1.1. Стороны обязуются ...`) stays a paragraph.

## Readers

* **PDF** (`pdf.py`): text blocks with font size and bold share from PyMuPDF. Ruled tables
  come from `find_tables()`, which only runs on pages with at least four vector paths because
  it is expensive. Text inside a table is not repeated as paragraphs. `layout.py` removes page
  numbers and text repeated in the top/bottom 10% of at least half the pages. A page with
  images and almost no text gets `needs_ocr`, the hook for a future OCR/Docling fallback.
* **DOCX** (`docx.py`): heading level from the style (`Heading N`, localized names, `Title`,
  inherited styles), lists from numbering/`List*` styles, tables from the table XML. Unstyled
  paragraphs fall back to the same heuristics as PDF. Pages are approximate (page breaks).

## Chunking (`chunking.py`)

Input is only the `Document`. Every heading starts a new chunk; inside a section whole
blocks are packed up to `max_tokens`. Oversized blocks are split by sentences (lines for
lists/tables, words as a last resort). Overlap repeats trailing sentences of the previous
chunk within the same section only. Tokens are estimated (about 4 characters per token);
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

## Fallback (future)

`Document` will carry a parse-confidence signal so low-confidence results can be handed
to an optional OCR/Docling fallback. Not implemented.

## Build

`maturin` builds `uzru_parser._core` from `src/` (PyO3); pure Python lives in `python/`.
