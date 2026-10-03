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
   │     PDF → PyMuPDF      DOCX → python-docx (planned)      TXT/MD (planned)
   │
   ▼
Rust core  (uzru_parser._core, embedded native extension)
   normalize_text · repair_hyphenation · detect_language
   (planned: line reconstruction, sentence splitting, chunking)
   │
   ▼
Document (blocks + metadata)  ──►  Chunker (separate step)  ──►  Chunks
```

Parsing and chunking are separate: the chunker only sees the `Document` model, so it can
be improved independently.

## Python / Rust boundary

* Python: file formats, orchestration, public API, data models.
* Rust: deterministic text processing. Each function takes a string and returns plain
  values, so crossing the boundary is cheap and there is no shared state.
* No separate process, service or HTTP layer.

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
