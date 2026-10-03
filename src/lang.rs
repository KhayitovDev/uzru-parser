//! Lightweight language/script detection for Russian and Uzbek (Latin + Cyrillic).
//!
//! No model: each word votes Russian, Uzbek or neutral using script-specific letters and
//! small stop-word lists. The label comes from the share of voting words.

use std::collections::HashSet;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::OnceLock;

use crate::chars::is_apostrophe;

pub struct Detection {
    pub language: &'static str,
    pub script: &'static str,
    pub confidence: f64,
}

#[derive(Clone, Copy, PartialEq)]
enum Vote {
    Ru,
    Uz,
    Neutral,
}

const RU_WORDS: &str = "и в не на что это как по для от из или при если который также может быть \
    настоящий договор стороны статья после все его они без под над между является должен должны";

/// Uzbek stop words, Cyrillic and Latin (Latin forms are stored without apostrophes).
const UZ_WORDS: &str = "ва учун билан бу ёки ҳамда бўйича эса бўлган керак мумкин лозим тартиби \
    қоидалар ушбу каби ҳақида томонидан \
    va uchun bilan bu yoki hamda boyicha esa bolgan kerak mumkin lozim tartibi qoidalar ushbu \
    kabi haqida tomonidan umumiy xizmat respublikasi";

/// Longest stop word in bytes; longer words skip the lookup entirely.
const MAX_STOP_WORD_BYTES: usize = 24;

/// FNV-1a: much cheaper than SipHash for the short words looked up here.
#[derive(Default)]
struct Fnv(u64);

impl Hasher for Fnv {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, bytes: &[u8]) {
        let mut hash = if self.0 == 0 {
            0xcbf2_9ce4_8422_2325
        } else {
            self.0
        };
        for &b in bytes {
            hash = (hash ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3);
        }
        self.0 = hash;
    }
}

type WordSet = HashSet<&'static str, BuildHasherDefault<Fnv>>;

fn word_set(words: &'static str) -> WordSet {
    words.split_whitespace().collect()
}

fn ru_words() -> &'static WordSet {
    static SET: OnceLock<WordSet> = OnceLock::new();
    SET.get_or_init(|| word_set(RU_WORDS))
}

fn uz_words() -> &'static WordSet {
    static SET: OnceLock<WordSet> = OnceLock::new();
    SET.get_or_init(|| word_set(UZ_WORDS))
}

fn is_stop_word(set: &WordSet, word: &str) -> bool {
    word.len() <= MAX_STOP_WORD_BYTES && set.contains(word)
}

fn is_cyrillic(c: char) -> bool {
    ('\u{0400}'..='\u{04FF}').contains(&c)
}

/// `char::is_alphabetic` with a direct answer for ASCII and the Cyrillic block.
fn is_letter(c: char) -> bool {
    match c {
        'a'..='z' | 'A'..='Z' => true,
        '\u{0482}'..='\u{0489}' => false,
        '\u{0400}'..='\u{04FF}' => true,
        _ if c.is_ascii() => false,
        _ => c.is_alphabetic(),
    }
}

fn is_word_char(c: char) -> bool {
    is_letter(c) || is_apostrophe(c)
}

/// Lowercase of one char; arithmetic for the common Cyrillic ranges, `std` for the rest.
fn lowercase(c: char) -> char {
    let code = c as u32;
    let shift = match code {
        0x0410..=0x042F => 0x20,
        0x0400..=0x040F => 0x50,
        0x0460..=0x0481 | 0x048A..=0x04BF | 0x04D0..=0x04FF if code.is_multiple_of(2) => 1,
        _ => return c.to_lowercase().next().unwrap_or(c),
    };
    char::from_u32(code + shift).unwrap_or(c)
}

/// Classify one word. `bare` is a reusable buffer for its lowercase form without apostrophes.
fn classify(word: &str, bare: &mut String) -> Vote {
    bare.clear();
    let (mut cyrillic, mut latin, mut uz_digraph) = (false, false, false);
    let mut prev_og = false;
    for c in word.chars() {
        if is_apostrophe(c) {
            uz_digraph |= prev_og;
            prev_og = false;
            continue;
        }
        let lower = lowercase(c);
        bare.push(lower);
        match lower {
            'ў' | 'қ' | 'ғ' | 'ҳ' => return Vote::Uz,
            'ы' | 'э' | 'щ' | 'ё' => return Vote::Ru,
            _ => {}
        }
        cyrillic |= is_cyrillic(lower);
        latin |= lower.is_ascii_alphabetic();
        prev_og = matches!(lower, 'o' | 'g');
    }
    if cyrillic {
        if is_stop_word(ru_words(), bare) {
            return Vote::Ru;
        }
        if is_stop_word(uz_words(), bare) {
            return Vote::Uz;
        }
    } else if latin && (uz_digraph || is_stop_word(uz_words(), bare)) {
        return Vote::Uz;
    }
    Vote::Neutral
}

fn script_of(text: &str) -> Option<&'static str> {
    let (mut cyrillic, mut latin) = (0usize, 0usize);
    for c in text.chars() {
        if is_cyrillic(c) {
            cyrillic += 1;
        } else if c.is_ascii_alphabetic() {
            latin += 1;
        }
    }
    let total = cyrillic + latin;
    if total == 0 {
        return None;
    }
    let share = cyrillic as f64 / total as f64;
    Some(if share >= 0.9 {
        "cyrillic"
    } else if share <= 0.1 {
        "latin"
    } else {
        "mixed"
    })
}

pub fn detect(text: &str) -> Detection {
    let Some(script) = script_of(text) else {
        return Detection {
            language: "unknown",
            script: "none",
            confidence: 0.0,
        };
    };

    let (mut ru, mut uz, mut words) = (0usize, 0usize, 0usize);
    let mut bare = String::new();
    for word in text
        .split(|c: char| !is_word_char(c))
        .filter(|w| !w.is_empty())
    {
        words += 1;
        match classify(word, &mut bare) {
            Vote::Ru => ru += 1,
            Vote::Uz => uz += 1,
            Vote::Neutral => {}
        }
    }

    let voters = ru + uz;
    if voters == 0 {
        // No markers: plain Cyrillic is most likely Russian, but with low confidence.
        return if script == "cyrillic" {
            Detection {
                language: "ru",
                script,
                confidence: 0.3,
            }
        } else {
            Detection {
                language: "unknown",
                script,
                confidence: 0.0,
            }
        };
    }

    let (ru_share, uz_share) = (ru as f64 / voters as f64, uz as f64 / voters as f64);
    let coverage = voters as f64 / words.max(1) as f64;
    let weight = 0.5 + 0.5 * coverage;
    let (language, confidence) = if ru_share >= 0.2 && uz_share >= 0.2 {
        ("mixed", 1.0 - (ru_share - uz_share).abs())
    } else if uz_share > ru_share {
        ("uz", uz_share * weight)
    } else {
        ("ru", ru_share * weight)
    };
    Detection {
        language,
        script,
        confidence,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn labels(text: &str) -> (&'static str, &'static str) {
        let d = detect(text);
        (d.language, d.script)
    }

    #[test]
    fn russian() {
        assert_eq!(
            labels("Настоящий договор является основанием для оказания услуг."),
            ("ru", "cyrillic")
        );
    }

    #[test]
    fn uzbek_latin() {
        assert_eq!(
            labels("Ushbu qoidalar xizmat ko'rsatish tartibi va ma'lumot uchun."),
            ("uz", "latin")
        );
    }

    #[test]
    fn uzbek_cyrillic() {
        assert_eq!(
            labels("Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик ва маълумот."),
            ("uz", "cyrillic")
        );
    }

    #[test]
    fn mixed_and_unknown() {
        assert_eq!(
            labels(
                "Настоящий договор является основанием. Ushbu qoidalar xizmat tartibi va bilan."
            )
            .0,
            "mixed"
        );
        assert_eq!(labels("12345 ---"), ("unknown", "none"));
    }

    #[test]
    fn apostrophe_variants_mark_uzbek_latin() {
        for apostrophe in ["'", "’", "ʻ", "ʼ", "`"] {
            assert_eq!(
                labels(&format!("o{apostrophe}zbek g{apostrophe}or")).0,
                "uz"
            );
        }
    }

    #[test]
    fn fast_paths_match_std_over_the_cyrillic_block() {
        for code in 0x0400..=0x04FF {
            let c = char::from_u32(code).unwrap();
            assert_eq!(is_letter(c), c.is_alphabetic(), "is_letter U+{code:04X}");
            assert_eq!(
                lowercase(c),
                c.to_lowercase().next().unwrap(),
                "lowercase U+{code:04X}"
            );
        }
    }

    #[test]
    fn plain_cyrillic_defaults_to_russian_with_low_confidence() {
        let d = detect("Москва Петербург");
        assert_eq!(d.language, "ru");
        assert!(d.confidence < 0.5);
    }
}
