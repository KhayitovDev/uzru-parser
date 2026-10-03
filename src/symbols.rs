//! Symbol-font characters.
//!
//! Symbol fonts (Symbol, Wingdings, ...) usually have no Unicode mapping, so PDF text comes
//! out as private-use characters at `0xF000 + font code` ("\u{F03D}" is code 0x3D "=").
//! The tables below translate those codes. An empty entry means the glyph has no text
//! meaning (bracket and arrow extension pieces) and is dropped.
//!
//! The Symbol table follows Adobe's Symbol encoding and glyph list (Adobe Glyph List,
//! Copyright 2002-2019 Adobe, BSD-3-Clause; notice in THIRD_PARTY.md).

/// Which code table a span uses, decided from its font name.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SymbolFont {
    /// Adobe Symbol encoding (math, Greek letters).
    Symbol,
    /// Wingdings-style dingbat fonts: bullets and arrows.
    Dingbats,
    /// No font information (DOCX, plain text): Symbol table, line-initial glyphs are bullets.
    Unknown,
}

pub fn font_family(font_name: &str) -> SymbolFont {
    let name = font_name.to_ascii_lowercase();
    if ["wingding", "webding", "dingbat"]
        .iter()
        .any(|n| name.contains(n))
    {
        SymbolFont::Dingbats
    } else if name.contains("symbol") {
        SymbolFont::Symbol
    } else {
        SymbolFont::Unknown
    }
}

const FIRST: u32 = 0xF020;
const LAST: u32 = 0xF0FF;

/// Adobe Symbol encoding for codes 0x20..=0xFF.
#[rustfmt::skip]
const SYMBOL: [&str; 224] = [
    // 0x20
    " ", "!", "∀", "#", "∃", "%", "&", "∋", "(", ")", "*", "+", ",", "-", ".", "/",
    // 0x30
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", ";", "<", "=", ">", "?",
    // 0x40
    "≅", "Α", "Β", "Χ", "Δ", "Ε", "Φ", "Γ", "Η", "Ι", "ϑ", "Κ", "Λ", "Μ", "Ν", "Ο",
    // 0x50
    "Π", "Θ", "Ρ", "Σ", "Τ", "Υ", "ς", "Ω", "Ξ", "Ψ", "Ζ", "[", "∴", "]", "⊥", "_",
    // 0x60
    "", "α", "β", "χ", "δ", "ε", "φ", "γ", "η", "ι", "ϕ", "κ", "λ", "μ", "ν", "ο",
    // 0x70
    "π", "θ", "ρ", "σ", "τ", "υ", "ϖ", "ω", "ξ", "ψ", "ζ", "{", "|", "}", "∼", "",
    // 0x80
    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
    // 0x90
    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
    // 0xA0
    "€", "ϒ", "′", "≤", "⁄", "∞", "ƒ", "♣", "♦", "♥", "♠", "↔", "←", "↑", "→", "↓",
    // 0xB0
    "°", "±", "″", "≥", "×", "∝", "∂", "•", "÷", "≠", "≡", "≈", "…", "", "", "↵",
    // 0xC0
    "ℵ", "ℑ", "ℜ", "℘", "⊗", "⊕", "∅", "∩", "∪", "⊃", "⊇", "⊄", "⊂", "⊆", "∈", "∉",
    // 0xD0
    "∠", "∇", "®", "©", "™", "∏", "√", "⋅", "¬", "∧", "∨", "⇔", "⇐", "⇑", "⇒", "⇓",
    // 0xE0
    "◊", "〈", "®", "©", "™", "∑", "", "", "", "", "", "", "", "", "", "",
    // 0xF0
    "", "〉", "∫", "", "", "", "", "", "", "", "", "", "", "", "", "",
];

/// Wingdings-style fonts: arrows (0xDF..=0xFA) become "→", every other glyph is used as
/// a bullet in running text and becomes "•".
fn dingbat(code: u32) -> &'static str {
    match code {
        0x20 => " ",
        0xDF..=0xFA => "→",
        _ => "•",
    }
}

/// Symbol glyphs that, at the start of a line, are used as list bullets.
const BULLET_LIKE: &[&str] = &[
    "/", "-", "*", "•", "⋅", "◊", "♦", "♣", "♥", "♠", "→", "⇒", "∼",
];

pub fn is_private_use(c: char) -> bool {
    ('\u{E000}'..='\u{F8FF}').contains(&c)
}

/// Plain text for a private-use character, or `None` when it has no meaning.
/// `line_start` marks a glyph that begins a line: with an unknown font it is a bullet.
pub fn map(c: char, font: SymbolFont, line_start: bool) -> Option<&'static str> {
    let code = c as u32;
    if !(FIRST..=LAST).contains(&code) {
        return None;
    }
    let code = code - 0xF000;
    let text = match font {
        SymbolFont::Dingbats => dingbat(code),
        SymbolFont::Unknown if line_start => "•",
        SymbolFont::Symbol | SymbolFont::Unknown => SYMBOL[(code - 0x20) as usize],
    };
    let text = if line_start && BULLET_LIKE.contains(&text) {
        "•"
    } else {
        text
    };
    (!text.is_empty()).then_some(text)
}

/// Replace private-use characters in text from one font. Returns the text and the number
/// of characters mapped and removed.
pub fn map_text(text: &str, font: SymbolFont) -> (String, usize, usize) {
    let mut out = String::with_capacity(text.len());
    let (mut mapped, mut removed) = (0, 0);
    let mut line_start = true;
    for c in text.chars() {
        if is_private_use(c) {
            match map(c, font, line_start) {
                Some(plain) => {
                    out.push_str(plain);
                    mapped += 1;
                }
                None => removed += 1,
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
    (out, mapped, removed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbol_font_math() {
        let (text, mapped, removed) = map_text(
            "a \u{F02B} b \u{F03D} c \u{F0B4} d \u{F0D7} e",
            SymbolFont::Symbol,
        );
        assert_eq!(text, "a + b = c × d ⋅ e");
        assert_eq!((mapped, removed), (4, 0));
        assert_eq!(
            map_text("\u{F061}\u{F0B3}\u{F062}", SymbolFont::Symbol).0,
            "α≥β"
        );
    }

    #[test]
    fn symbol_punctuation_starting_a_line_is_a_bullet() {
        assert_eq!(
            map_text("\u{F02F}dollar\n\u{F02D} kredit", SymbolFont::Symbol).0,
            "•dollar\n• kredit"
        );
        assert_eq!(
            map_text("\u{F061} koeffitsient", SymbolFont::Symbol).0,
            "α koeffitsient"
        );
        assert_eq!(
            map_text("\u{F028}a\u{F02B}b)", SymbolFont::Symbol).0,
            "(a+b)"
        );
        assert_eq!(map_text("a \u{F02F} b", SymbolFont::Symbol).0, "a / b");
    }

    #[test]
    fn dingbat_bullets_and_arrows() {
        assert_eq!(
            map_text("\u{F0FC}\u{F0A7}\u{F0D8}\u{F0E0}", SymbolFont::Dingbats).0,
            "•••→"
        );
    }

    #[test]
    fn unknown_font_line_start_is_a_bullet() {
        assert_eq!(
            map_text("\u{F02F}dollar\n \u{F02F}RUR", SymbolFont::Unknown).0,
            "•dollar\n •RUR"
        );
        assert_eq!(map_text("a\u{F02F}b", SymbolFont::Unknown).0, "a/b");
    }

    #[test]
    fn pieces_and_other_private_use_are_removed() {
        let (text, mapped, removed) = map_text("x\u{F0E6}y\u{E123}z", SymbolFont::Symbol);
        assert_eq!((text.as_str(), mapped, removed), ("xyz", 0, 2));
    }

    #[test]
    fn font_names() {
        assert_eq!(
            font_family("ABCDEE+Wingdings-Regular"),
            SymbolFont::Dingbats
        );
        assert_eq!(font_family("SymbolMT"), SymbolFont::Symbol);
        assert_eq!(font_family("TimesNewRomanPSMT"), SymbolFont::Unknown);
    }
}
