//! Rust core of uzru-parser.
//!
//! Deterministic, CPU-only text processing exposed to Python as
//! `uzru_parser._core`. Every function here is pure: text in, text out.

use std::collections::HashSet;

use pyo3::prelude::*;

mod chars;
mod confusables;
mod hyphen;
mod lang;
mod langid;
mod lexicon;
mod normalize;
mod numbering;
mod sentences;
mod symbols;
mod tokens;
mod translit;

/// Normalize text for RAG use (NFC, invisible characters, Uzbek apostrophes, whitespace).
#[pyfunction]
fn normalize_text(text: &str) -> String {
    normalize::normalize_text(text)
}

/// [`normalize_text`] plus `(mixed_script_words_fixed, symbols_mapped, symbols_removed)`.
#[pyfunction]
fn normalize_text_stats(text: &str) -> (String, usize, usize, usize) {
    let (out, s) = normalize::normalize_with_stats(text);
    (out, s.mixed_words, s.symbols_mapped, s.symbols_removed)
}

/// Translate symbol-font characters using the font name of the text's span.
/// Returns `(text, mapped, removed)`.
#[pyfunction]
fn map_symbol_font(text: &str, font_name: &str) -> (String, usize, usize) {
    match symbols::font_family(font_name) {
        // Without a symbol font name the line-level normalizer decides (it knows line starts).
        symbols::SymbolFont::Unknown => (text.to_string(), 0, 0),
        family => symbols::map_text(text, family),
    }
}

/// Join words that a PDF broke across lines with a hyphen ("Настоя-\nщим" -> "Настоящим").
/// Legitimate hyphenated words ("кто-\nто", "из-\nза") keep their hyphen.
#[pyfunction]
fn repair_hyphenation(text: &str) -> String {
    hyphen::repair_hyphenation(text)
}

/// Hyphenation repair that also knows the compounds of one document.
#[pyclass]
struct Hyphenator {
    keep: HashSet<String>,
}

#[pymethods]
impl Hyphenator {
    /// `keep`: lowercase "left-right" pairs that the document writes with a hyphen.
    #[new]
    fn new(keep: Vec<String>) -> Self {
        Hyphenator {
            keep: keep.into_iter().map(|w| w.to_lowercase()).collect(),
        }
    }

    fn repair(&self, text: &str) -> String {
        hyphen::repair_with(text, &self.keep)
    }
}

/// Detect language and script. Returns `(language, script, confidence)` where
/// language is one of `ru | uz | mixed | unknown` and script is one of
/// `latin | cyrillic | mixed | none`.
#[pyfunction]
fn detect_language(text: &str) -> (&'static str, &'static str, f64) {
    let r = lang::detect(text);
    (r.language, r.script, r.confidence)
}

/// Section numbering / list marker at the start of a line: `(kind, depth)` where kind is
/// `decimal | keyword | bullet | ordered`, or `None`.
#[pyfunction]
fn numbering_info(line: &str) -> Option<(&'static str, usize)> {
    numbering::numbering_info(line).map(|n| (n.kind, n.depth))
}

/// Replace the chapter/section keyword list: `[(word, rank)]`, rank 1 = largest unit.
#[pyfunction]
fn set_heading_keywords(keywords: Vec<(String, usize)>) {
    numbering::set_keywords(keywords);
}

/// Split text into sentences, keeping abbreviations, initials and numbering intact.
#[pyfunction]
fn split_sentences(text: &str) -> Vec<String> {
    sentences::split_sentences(text)
}

/// Does a sentence end between `left` and `right` (abbreviation- and initial-aware)?
#[pyfunction]
fn is_sentence_break(left: &str, right: &str) -> bool {
    sentences::is_sentence_break(left, right)
}

/// Is `word` a known Uzbek (Latin or Cyrillic) or Russian word, inflected forms included?
#[pyfunction]
fn is_known_word(word: &str) -> bool {
    lexicon::is_known(word)
}

/// Estimate the token count of `text` without a tokenizer.
#[pyfunction]
fn estimate_tokens(text: &str) -> usize {
    tokens::estimate_tokens(text)
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_text, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_text_stats, m)?)?;
    m.add_function(wrap_pyfunction!(map_symbol_font, m)?)?;
    m.add_function(wrap_pyfunction!(repair_hyphenation, m)?)?;
    m.add_class::<Hyphenator>()?;
    m.add_function(wrap_pyfunction!(detect_language, m)?)?;
    m.add_function(wrap_pyfunction!(numbering_info, m)?)?;
    m.add_function(wrap_pyfunction!(set_heading_keywords, m)?)?;
    m.add_function(wrap_pyfunction!(split_sentences, m)?)?;
    m.add_function(wrap_pyfunction!(is_sentence_break, m)?)?;
    m.add_function(wrap_pyfunction!(is_known_word, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
