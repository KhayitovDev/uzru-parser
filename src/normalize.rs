//! Unicode normalization and text cleanup.
//!
//! Design rules:
//! * NFC only (never NFKC): it keeps `ё`, `й`, Uzbek letters and ligature-free text intact.
//! * `ё` is never turned into `е`.
//! * Uzbek apostrophes are only rewritten when they sit *between two Latin letters*,
//!   so quotes, Cyrillic text and standalone punctuation are left alone; English
//!   possessives and contractions ("user’s", "don’t") keep theirs.
//! * Table-of-contents dot leaders ("........") collapse to a single ellipsis.
//!
//! Order: symbol-font characters, then mixed-script words, then apostrophes, then spaces.
//! Each step needs the previous one: "TА’LIM" only gets its apostrophe once the Cyrillic
//! "А" is Latin.

use unicode_normalization::{is_nfc, UnicodeNormalization};

use crate::chars::is_apostrophe;
use crate::confusables::fix_mixed_words;
use crate::lexicon::is_known;
use crate::numbering::GLYPH_BULLETS;
use crate::symbols::{self, SymbolFont};

/// Canonical Uzbek Latin modifier letters (Unicode recommendation).
const TURNED_COMMA: char = '\u{02BB}'; // ʻ  in oʻ, gʻ
const APOSTROPHE: char = '\u{02BC}'; // ʼ  tutuq belgisi, e.g. maʼlumot
const ELLIPSIS: char = '\u{2026}';
const MIN_LEADER_DOTS: usize = 4;

/// What normalization changed, for document metadata.
#[derive(Default, Debug, PartialEq)]
pub struct Stats {
    pub mixed_words: usize,
    pub symbols_mapped: usize,
    pub symbols_removed: usize,
}

fn is_apostrophe_like(c: char) -> bool {
    is_apostrophe(c)
}

fn is_word_char(c: char) -> bool {
    c.is_alphabetic() || is_apostrophe(c)
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

/// Replace private-use characters (symbol fonts without a known font: Symbol table, a
/// line-initial glyph is a bullet) and drop the ones without meaning.
fn map_private_use(chars: Vec<char>, stats: &mut Stats) -> Vec<char> {
    if !chars.iter().any(|&c| symbols::is_private_use(c)) {
        return chars;
    }
    let mut out = Vec::with_capacity(chars.len());
    let mut line_start = true;
    for c in chars {
        if symbols::is_private_use(c) {
            match symbols::map(c, SymbolFont::Unknown, line_start) {
                Some(plain) => {
                    out.extend(plain.chars());
                    stats.symbols_mapped += 1;
                }
                None => stats.symbols_removed += 1,
            }
            line_start = false;
            continue;
        }
        out.push(c);
        if c == '\n' {
            line_start = true;
        } else if !c.is_whitespace() {
            line_start = false;
        }
    }
    out
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
    // A left quote or turned comma glued to "o"/"g" is the Uzbek letter, even before a
    // non-letter: "O‘.Haydarov".
    let after_o_or_g = i > 0
        && chars[i - 1].is_ascii_alphabetic()
        && matches!(chars[i - 1].to_ascii_lowercase(), 'o' | 'g');
    if matches!(c, '‘' | 'ʻ') && after_o_or_g {
        return TURNED_COMMA;
    }
    let between_latin_letters = is_apostrophe_like(c)
        && i > 0
        && chars.get(i + 1).is_some_and(char::is_ascii_alphabetic)
        && chars[i - 1].is_ascii_alphabetic();
    if between_latin_letters && english_apostrophe(chars, i) {
        return c;
    }
    match (
        between_latin_letters,
        chars[i.saturating_sub(1)].to_ascii_lowercase(),
    ) {
        (false, _) => c,
        (true, 'o' | 'g') => TURNED_COMMA,
        (true, _) => APOSTROPHE,
    }
}

/// English possessives and contractions ("user’s", "don’t", "we’re") keep their apostrophe:
/// the letters after it end the word and form an English ending, and the word is not Uzbek.
fn english_apostrophe(chars: &[char], i: usize) -> bool {
    let end = (i + 1..chars.len())
        .find(|&j| !chars[j].is_alphabetic())
        .unwrap_or(chars.len());
    let tail: String = chars[i + 1..end]
        .iter()
        .flat_map(|c| c.to_lowercase())
        .collect();
    if !matches!(tail.as_str(), "s" | "t" | "re" | "ve" | "ll" | "d" | "m") {
        return false;
    }
    let start = (0..i)
        .rev()
        .find(|&j| !is_word_char(chars[j]))
        .map_or(0, |j| j + 1);
    let word: String = chars[start..end].iter().collect();
    !is_known(&word)
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
    normalize_with_stats(text).0
}

/// [`normalize_text`] plus counts of what it fixed.
pub fn normalize_with_stats(text: &str) -> (String, Stats) {
    let mut stats = Stats::default();
    let base: Vec<char> = if is_nfc(text) {
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

    let mut chars = map_private_use(base, &mut stats);
    stats.mixed_words = fix_mixed_words(&mut chars, is_word_char);

    let mut writer = Writer::new(text.len());
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            ' ' => writer.space(),
            '\n' => writer.newline(),
            c if GLYPH_BULLETS.contains(&c) => {
                // "■Always" -> "■ Always": a bullet glued to its item's text.
                writer.push(c);
                if chars.get(i + 1).is_some_and(|c| c.is_alphanumeric()) {
                    writer.space();
                }
            }
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
    (writer.out, stats)
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
    fn symbol_font_bullets_become_plain_bullets() {
        assert_eq!(
            normalize_text("\u{F02F}dollar (11%) va dollar"),
            "• dollar (11%) va dollar"
        );
        assert_eq!(
            normalize_text("\u{F0B7} birinchi\n\u{F0FC}ikkinchi"),
            "• birinchi\n• ikkinchi"
        );
        assert_eq!(normalize_text("a \u{F03D} b \u{F03E} c"), "a = b > c");
        assert_eq!(normalize_text("\u{F02D} band"), "• band");
        assert_eq!(normalize_text("■Always put"), "■ Always put");
        assert_eq!(normalize_text("•Item and • item"), "• Item and • item");
    }

    #[test]
    fn no_private_use_character_survives() {
        let (text, stats) = normalize_with_stats("x \u{F0E6}y \u{E000}z \u{F8FF}");
        assert_eq!(text, "x y z");
        assert!(!text.chars().any(symbols::is_private_use));
        assert_eq!((stats.symbols_mapped, stats.symbols_removed), (0, 3));
    }

    #[test]
    fn mixed_script_words_are_fixed_before_apostrophes() {
        let (text, stats) = normalize_with_stats("TА’LIM vа vаlyutа");
        assert_eq!(text, "TAʼLIM va valyuta");
        assert_eq!(stats.mixed_words, 3);
        assert_eq!(normalize_text("II-BОB"), "II-BOB");
    }

    #[test]
    fn english_possessives_and_contractions_keep_their_apostrophe() {
        for text in [
            "the user’s funds",
            "it isn’t free",
            "we’re here",
            "don't share",
        ] {
            assert_eq!(normalize_text(text), text);
        }
        assert_eq!(normalize_text("ta’m va ba’d"), "ta\u{02BC}m va ba\u{02BC}d");
        assert_eq!(normalize_text("ma’lumot"), "ma\u{02BC}lumot");
    }

    #[test]
    fn single_script_text_is_unchanged() {
        for text in [
            "Банковская система обеспечивает расчёты.",
            "Ўзбекистон Республикаси ўқувчилар учун.",
            "Oʻzbekiston Respublikasi valyuta bozori.",
        ] {
            assert_eq!(
                normalize_with_stats(text),
                (text.to_string(), Stats::default())
            );
        }
    }

    #[test]
    fn all_nine_apostrophe_variants_are_unified() {
        for apostrophe in ['\'', '‘', '’', '`', '´', '′', '＇', 'ʻ', 'ʼ'] {
            let text = format!("o{apostrophe}zbek ma{apostrophe}lumot");
            assert_eq!(normalize_text(&text), "oʻzbek maʼlumot", "{apostrophe:?}");
        }
    }

    #[test]
    fn left_quote_after_o_or_g_is_the_uzbek_letter() {
        assert_eq!(
            normalize_text("O‘.Haydarov, G‘.Karimov"),
            "O\u{02BB}.Haydarov, G\u{02BB}.Karimov"
        );
        assert_eq!(normalize_text("he said ‘hello’"), "he said ‘hello’");
    }

    #[test]
    fn decomposed_input_is_composed() {
        assert_eq!(normalize_text("и\u{0306}"), "й");
    }
}
