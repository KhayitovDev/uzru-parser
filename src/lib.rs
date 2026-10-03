//! Rust core of uzru-parser.
//!
//! Deterministic, CPU-only text processing exposed to Python as
//! `uzru_parser._core`. Every function here is pure: text in, text out.

use pyo3::prelude::*;

mod hyphen;
mod lang;
mod normalize;

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

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_text, m)?)?;
    m.add_function(wrap_pyfunction!(repair_hyphenation, m)?)?;
    m.add_function(wrap_pyfunction!(detect_language, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
