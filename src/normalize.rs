//! Unicode normalization and text cleanup.
//!
//! Design rules:
//! * NFC only (never NFKC): it keeps `ё`, `й`, Uzbek letters and ligature-free text intact.
//! * `ё` is never turned into `е`.
//! * Uzbek apostrophes are only rewritten when they sit *between two Latin letters*,
//!   so quotes, Cyrillic text and standalone punctuation are left alone.
//! * Table-of-contents dot leaders ("........") collapse to a single ellipsis.

use unicode_normalization::{is_nfc, UnicodeNormalization};

use crate::chars::is_apostrophe;

/// Canonical Uzbek Latin modifier letters (Unicode recommendation).
const TURNED_COMMA: char = '\u{02BB}'; // ʻ  in oʻ, gʻ
const APOSTROPHE: char = '\u{02BC}'; // ʼ  tutuq belgisi, e.g. maʼlumot
const ELLIPSIS: char = '\u{2026}';
const MIN_LEADER_DOTS: usize = 4;

fn is_apostrophe_like(c: char) -> bool {
    is_apostrophe(c) || matches!(c, '´' | 'ʹ')
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
            | '\r'
    )
}

fn map_space(c: char) -> char {
    match c {
        '\u{00A0}' | '\u{2007}' | '\u{202F}' | '\u{2009}' | '\u{200A}' | '\u{2002}'
        | '\u{2003}' | '\t' | '\u{000B}' | '\u{000C}' => ' ',
        _ => c,
    }
}

/// `o`/`g` + apostrophe -> U+02BB (oʻ, gʻ); any other letter + apostrophe -> U+02BC (maʼlumot).
/// Only applies between two Latin letters; otherwise the character is returned unchanged.
fn uzbek_apostrophe(chars: &[char], i: usize) -> char {
    let c = chars[i];
    let between_latin_letters = is_apostrophe_like(c)
        && i > 0
        && chars.get(i + 1).is_some_and(char::is_ascii_alphabetic)
        && chars[i - 1].is_ascii_alphabetic();
    match (
        between_latin_letters,
        chars[i.saturating_sub(1)].to_ascii_lowercase(),
    ) {
        (false, _) => c,
        (true, 'o' | 'g') => TURNED_COMMA,
        (true, _) => APOSTROPHE,
    }
}

/// End index and dot count of a run of dots starting at `start`. Single spaces between
/// dots belong to the run; an ellipsis character counts as three dots.
fn dot_run(chars: &[char], start: usize) -> (usize, usize) {
    let is_dot = |c: char| c == '.' || c == ELLIPSIS;
    let (mut end, mut dots, mut j) = (start, 0, start);
    while j < chars.len() {
        if is_dot(chars[j]) {
            dots += if chars[j] == '.' { 1 } else { 3 };
            j += 1;
            end = j;
        } else if chars[j] == ' ' && chars.get(j + 1).copied().is_some_and(is_dot) {
            j += 1;
        } else {
            break;
        }
    }
    (end, dots)
}

/// Output buffer that collapses spaces and limits blank lines while text is appended.
struct Writer {
    out: String,
    pending_space: bool,
    newlines: u8,
}

impl Writer {
    fn new(capacity: usize) -> Self {
        Writer {
            out: String::with_capacity(capacity),
            pending_space: false,
            newlines: 0,
        }
    }

    fn space(&mut self) {
        self.pending_space = true;
    }

    fn newline(&mut self) {
        self.pending_space = false;
        self.newlines = self.newlines.saturating_add(1);
    }

    fn push(&mut self, c: char) {
        if !self.out.is_empty() {
            // At most one blank line between paragraphs; spaces never lead a line.
            for _ in 0..self.newlines.min(2) {
                self.out.push('\n');
            }
            if self.newlines == 0 && self.pending_space {
                self.out.push(' ');
            }
        }
        self.newlines = 0;
        self.pending_space = false;
        self.out.push(c);
    }
}

/// Normalize text: NFC, drop invisible chars, unify spaces, fix Uzbek apostrophes,
/// collapse dot leaders, runs of spaces and blank lines. Line structure (`\n`) is preserved.
pub fn normalize_text(text: &str) -> String {
    let chars: Vec<char> = if is_nfc(text) {
        text.chars()
            .filter(|&c| !is_invisible(c))
            .map(map_space)
            .collect()
    } else {
        text.nfc()
            .filter(|&c| !is_invisible(c))
            .map(map_space)
            .collect()
    };

    let mut writer = Writer::new(text.len());
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            ' ' => writer.space(),
            '\n' => writer.newline(),
            '.' | ELLIPSIS => {
                let (end, dots) = dot_run(&chars, i);
                if dots >= MIN_LEADER_DOTS {
                    writer.space();
                    writer.push(ELLIPSIS);
                    writer.space();
                } else {
                    for (offset, &c) in chars[i..end].iter().enumerate() {
                        match c {
                            ' ' => writer.space(),
                            _ => writer.push(uzbek_apostrophe(&chars, i + offset)),
                        }
                    }
                }
                i = end;
                continue;
            }
            _ => writer.push(uzbek_apostrophe(&chars, i)),
        }
        i += 1;
    }
    writer.out
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
        assert_eq!(normalize_text("  \n\n a\r\nb  "), "a\nb");
    }

    #[test]
    fn decomposed_input_is_composed() {
        assert_eq!(normalize_text("и\u{0306}"), "й");
    }
}
