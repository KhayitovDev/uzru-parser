//! Rust core of uzru-parser.
//!
//! Deterministic, CPU-only text processing exposed to Python as
//! `uzru_parser._core`. Every function here is pure: text in, text out.

use pyo3::prelude::*;

mod chars;
mod hyphen;
mod lang;
mod normalize;
mod numbering;
mod sentences;
mod tokens;

/// Normalize text for RAG use (NFC, invisible characters, Uzbek apostrophes, whitespace).
#[pyfunction]
fn normalize_text(text: &str) -> String {
    normalize::normalize_text(text)
}

/// Join words that a PDF broke across lines with a hyphen ("Настоя-\nщим" -> "Настоящим").
/// Legitimate hyphenated words ("кто-\nто", "из-\nза") keep their hyphen.
#[pyfunction]
fn repair_hyphenation(text: &str) -> String {
    hyphen::repair_hyphenation(text)
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

/// Split text into sentences, keeping abbreviations, initials and numbering intact.
#[pyfunction]
fn split_sentences(text: &str) -> Vec<String> {
    sentences::split_sentences(text)
}

/// Estimate the token count of `text` without a tokenizer.
#[pyfunction]
fn estimate_tokens(text: &str) -> usize {
    tokens::estimate_tokens(text)
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_text, m)?)?;
    m.add_function(wrap_pyfunction!(repair_hyphenation, m)?)?;
    m.add_function(wrap_pyfunction!(detect_language, m)?)?;
    m.add_function(wrap_pyfunction!(numbering_info, m)?)?;
    m.add_function(wrap_pyfunction!(split_sentences, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
