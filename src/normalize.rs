//! Unicode normalization and text cleanup.
//!
//! Design rules:
//! * NFC only (never NFKC): it keeps `ё`, `й`, Uzbek letters and ligature-free text intact.
//! * `ё` is never turned into `е`.
//! * Uzbek apostrophes are only rewritten when they sit *between two Latin letters*,
//!   so quotes, Cyrillic text and standalone punctuation are left alone.

use unicode_normalization::UnicodeNormalization;

/// Canonical Uzbek Latin modifier letters (Unicode recommendation).
const TURNED_COMMA: char = '\u{02BB}'; // ʻ  in oʻ, gʻ
const APOSTROPHE: char = '\u{02BC}'; // ʼ  tutuq belgisi, e.g. maʼlumot

fn is_apostrophe_like(c: char) -> bool {
    matches!(
        c,
        '\'' | '\u{2019}' | '\u{2018}' | '\u{02BB}' | '\u{02BC}' | '`' | '\u{00B4}' | '\u{02B9}'
    )
}

fn is_latin_letter(c: char) -> bool {
    c.is_ascii_alphabetic()
}

/// Characters that carry no visible content in extracted text.
fn is_invisible(c: char) -> bool {
    matches!(
        c,
        '\u{00AD}' // soft hyphen (PDF hyphenation is handled elsewhere)
            | '\u{200B}' // zero width space
            | '\u{200C}' // zero width non-joiner
            | '\u{200D}' // zero width joiner
            | '\u{2060}' // word joiner
            | '\u{FEFF}' // BOM / zero width no-break space
    )
}

fn map_space(c: char) -> char {
    match c {
        '\u{00A0}' | '\u{2007}' | '\u{202F}' | '\u{2009}' | '\u{200A}' | '\u{2002}'
        | '\u{2003}' | '\t' | '\u{000B}' | '\u{000C}' => ' ',
        _ => c,
    }
}

/// Rewrite apostrophe variants that sit between two Latin letters.
/// `o`/`g` + apostrophe -> U+02BB (oʻ, gʻ); any other letter + apostrophe -> U+02BC (maʼlumot).
fn fix_uzbek_apostrophes(chars: &[char]) -> Vec<char> {
    let mut out = Vec::with_capacity(chars.len());
    for (i, &c) in chars.iter().enumerate() {
        let between_letters = is_apostrophe_like(c)
            && i > 0
            && i + 1 < chars.len()
            && is_latin_letter(chars[i - 1])
            && is_latin_letter(chars[i + 1]);
        if between_letters {
            let prev = chars[i - 1].to_ascii_lowercase();
            out.push(if prev == 'o' || prev == 'g' {
                TURNED_COMMA
            } else {
                APOSTROPHE
            });
        } else {
            out.push(c);
        }
    }
    out
}

/// Replace table-of-contents dot leaders ("Статья 5 ........ 12") with a single ellipsis.
/// A leader is four or more dots, optionally separated by single spaces; an ellipsis
/// character counts as three dots, so ordinary "..." and "…" are left alone.
fn collapse_dot_leaders(chars: &[char]) -> Vec<char> {
    let is_dot = |c: char| c == '.' || c == '\u{2026}';
    let weight = |c: char| if c == '.' { 1 } else { 3 };
    let mut out = Vec::with_capacity(chars.len());
    let mut i = 0;
    while i < chars.len() {
        if !is_dot(chars[i]) {
            out.push(chars[i]);
            i += 1;
            continue;
        }
        let (mut end, mut dots, mut j) = (i, 0, i);
        while j < chars.len() {
            if is_dot(chars[j]) {
                dots += weight(chars[j]);
                j += 1;
                end = j;
            } else if chars[j] == ' ' && j + 1 < chars.len() && is_dot(chars[j + 1]) {
                j += 1;
            } else {
                break;
            }
        }
        if dots >= 4 {
            out.extend([' ', '\u{2026}', ' ']);
        } else {
            out.extend_from_slice(&chars[i..end]);
        }
        i = end;
    }
    out
}

/// Normalize text: NFC, drop invisible chars, unify spaces, fix Uzbek apostrophes,
/// collapse dot leaders, runs of spaces and blank lines. Line structure (`\n`) is preserved.
pub fn normalize_text(text: &str) -> String {
    let nfc: Vec<char> = text
        .nfc()
        .filter(|&c| !is_invisible(c))
        .map(map_space)
        .filter(|&c| c != '\r')
        .collect();
    let fixed = collapse_dot_leaders(&fix_uzbek_apostrophes(&nfc));

    let mut out = String::with_capacity(fixed.len());
    let mut prev_space = false;
    let mut newlines = 0u8;
    for c in fixed {
        match c {
            ' ' => {
                prev_space = true;
            }
            '\n' => {
                prev_space = false;
                newlines = newlines.saturating_add(1);
            }
            _ => {
                if newlines > 0 {
                    // At most one blank line between paragraphs; none before the first text.
                    if !out.is_empty() {
                        for _ in 0..newlines.min(2) {
                            out.push('\n');
                        }
                    }
                    newlines = 0;
                } else if prev_space && !out.is_empty() {
                    out.push(' ');
                }
                prev_space = false;
                out.push(c);
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_yo() {
        assert_eq!(normalize_text("Ёлка, всё"), "Ёлка, всё");
    }

    #[test]
    fn uzbek_latin_apostrophes() {
        assert_eq!(normalize_text("O'zbekiston"), "O\u{02BB}zbekiston");
        assert_eq!(normalize_text("o‘quvchilar"), "o\u{02BB}quvchilar");
        assert_eq!(normalize_text("g’amxo`rlik"), "g\u{02BB}amxo\u{02BB}rlik");
        assert_eq!(normalize_text("ma'lumot"), "ma\u{02BC}lumot");
        assert_eq!(normalize_text("ma’lumot"), "ma\u{02BC}lumot");
    }

    #[test]
    fn quotes_and_cyrillic_untouched() {
        assert_eq!(normalize_text("'hello' world"), "'hello' world");
        assert_eq!(normalize_text("маъно"), "маъно");
    }

    #[test]
    fn dot_leaders() {
        assert_eq!(
            normalize_text("Статья 5 ........ 12"),
            "Статья 5 \u{2026} 12"
        );
        assert_eq!(
            normalize_text("Раздел 1 . . . . . 3"),
            "Раздел 1 \u{2026} 3"
        );
        assert_eq!(normalize_text("Продолжение..."), "Продолжение...");
        assert_eq!(normalize_text("и т.д. и т.п."), "и т.д. и т.п.");
    }

    #[test]
    fn whitespace_and_invisibles() {
        assert_eq!(normalize_text("a\u{00A0}\u{00A0}b\u{200B}c  d"), "a bc d");
        assert_eq!(normalize_text("a \n\n\n\nb"), "a\n\nb");
    }
}
