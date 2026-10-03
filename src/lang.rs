//! Lightweight language/script detection for Russian and Uzbek (Latin + Cyrillic).
//!
//! No model: each word is classified as Russian, Uzbek or neutral using
//! script-specific letters and small stop-word lists. The document label comes from
//! the share of classified words.

pub struct Detection {
    pub language: &'static str,
    pub script: &'static str,
    pub confidence: f64,
}

#[derive(PartialEq, Clone, Copy)]
enum Vote {
    Ru,
    Uz,
    Neutral,
}

const UZ_CYRL_LETTERS: &[char] = &['ў', 'қ', 'ғ', 'ҳ', 'Ў', 'Қ', 'Ғ', 'Ҳ'];
const RU_ONLY_LETTERS: &[char] = &['ы', 'э', 'щ', 'ё', 'Ы', 'Э', 'Щ', 'Ё'];

const RU_WORDS: &[&str] = &[
    "и",
    "в",
    "не",
    "на",
    "что",
    "это",
    "как",
    "по",
    "для",
    "от",
    "из",
    "или",
    "при",
    "если",
    "который",
    "также",
    "может",
    "быть",
    "настоящий",
    "договор",
    "стороны",
    "статья",
    "после",
    "все",
    "его",
    "они",
    "они",
    "без",
    "под",
    "над",
    "между",
    "является",
    "должен",
    "должны",
];

const UZ_CYRL_WORDS: &[&str] = &[
    "ва",
    "учун",
    "билан",
    "бу",
    "ёки",
    "ҳамда",
    "бўйича",
    "эса",
    "бўлган",
    "керак",
    "мумкин",
    "лозим",
    "тартиби",
    "қоидалар",
    "ушбу",
    "каби",
    "ҳақида",
    "томонидан",
];

const UZ_LATN_WORDS: &[&str] = &[
    "va",
    "uchun",
    "bilan",
    "bu",
    "yoki",
    "hamda",
    "boyicha",
    "esa",
    "bolgan",
    "kerak",
    "mumkin",
    "lozim",
    "tartibi",
    "qoidalar",
    "ushbu",
    "kabi",
    "haqida",
    "tomonidan",
    "umumiy",
    "xizmat",
    "respublikasi",
    "bo\u{02BB}yicha",
    "bo\u{02BB}lgan",
];

fn is_cyrillic(c: char) -> bool {
    ('\u{0400}'..='\u{04FF}').contains(&c)
}

fn is_latin(c: char) -> bool {
    c.is_ascii_alphabetic()
}

fn strip_apostrophes(word: &str) -> String {
    word.chars()
        .filter(|c| {
            !matches!(
                c,
                '\'' | '\u{2019}' | '\u{2018}' | '\u{02BB}' | '\u{02BC}' | '`'
            )
        })
        .collect()
}

fn has_uzbek_apostrophe_letters(word: &str) -> bool {
    // oʻ / gʻ style digraphs written with any apostrophe variant.
    let chars: Vec<char> = word.chars().collect();
    chars.windows(2).any(|w| {
        matches!(w[0].to_ascii_lowercase(), 'o' | 'g')
            && matches!(
                w[1],
                '\'' | '\u{2019}' | '\u{2018}' | '\u{02BB}' | '\u{02BC}' | '`'
            )
    })
}

fn classify(word: &str) -> Vote {
    let lower = word.to_lowercase();
    if lower.chars().any(|c| UZ_CYRL_LETTERS.contains(&c)) {
        return Vote::Uz;
    }
    if lower.chars().any(|c| RU_ONLY_LETTERS.contains(&c)) {
        return Vote::Ru;
    }
    if lower.chars().any(is_cyrillic) {
        if RU_WORDS.contains(&lower.as_str()) {
            return Vote::Ru;
        }
        if UZ_CYRL_WORDS.contains(&lower.as_str()) {
            return Vote::Uz;
        }
        return Vote::Neutral;
    }
    if lower.chars().any(is_latin) {
        if has_uzbek_apostrophe_letters(&lower) {
            return Vote::Uz;
        }
        let bare = strip_apostrophes(&lower);
        if UZ_LATN_WORDS.contains(&lower.as_str()) || UZ_LATN_WORDS.contains(&bare.as_str()) {
            return Vote::Uz;
        }
    }
    Vote::Neutral
}

pub fn detect(text: &str) -> Detection {
    let (mut cyr, mut lat) = (0usize, 0usize);
    for c in text.chars() {
        if is_cyrillic(c) {
            cyr += 1;
        } else if is_latin(c) {
            lat += 1;
        }
    }
    let total = cyr + lat;
    if total == 0 {
        return Detection {
            language: "unknown",
            script: "none",
            confidence: 0.0,
        };
    }
    let cyr_share = cyr as f64 / total as f64;
    let script = if cyr_share >= 0.9 {
        "cyrillic"
    } else if cyr_share <= 0.1 {
        "latin"
    } else {
        "mixed"
    };

    let (mut ru, mut uz, mut words) = (0usize, 0usize, 0usize);
    for w in text.split(|c: char| {
        !(c.is_alphabetic()
            || matches!(
                c,
                '\'' | '\u{2019}' | '\u{2018}' | '\u{02BB}' | '\u{02BC}' | '`'
            ))
    }) {
        if w.is_empty() {
            continue;
        }
        words += 1;
        match classify(w) {
            Vote::Ru => ru += 1,
            Vote::Uz => uz += 1,
            Vote::Neutral => {}
        }
    }
    let classified = ru + uz;

    let (language, confidence) = if classified == 0 {
        // No markers. Plain Cyrillic is most likely Russian, but with low confidence.
        if script == "cyrillic" {
            ("ru", 0.3)
        } else {
            ("unknown", 0.0)
        }
    } else {
        let (ru_f, uz_f) = (ru as f64 / classified as f64, uz as f64 / classified as f64);
        let coverage = (classified as f64 / words.max(1) as f64).min(1.0);
        if ru_f >= 0.2 && uz_f >= 0.2 {
            ("mixed", 1.0 - (ru_f - uz_f).abs())
        } else if uz_f > ru_f {
            ("uz", uz_f * (0.5 + 0.5 * coverage))
        } else {
            ("ru", ru_f * (0.5 + 0.5 * coverage))
        }
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

    #[test]
    fn russian() {
        let d = detect("Настоящий договор является основанием для оказания услуг.");
        assert_eq!((d.language, d.script), ("ru", "cyrillic"));
    }

    #[test]
    fn uzbek_latin() {
        let d = detect("Ushbu qoidalar xizmat ko'rsatish tartibi va ma'lumot uchun.");
        assert_eq!((d.language, d.script), ("uz", "latin"));
    }

    #[test]
    fn uzbek_cyrillic() {
        let d = detect("Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик ва маълумот.");
        assert_eq!((d.language, d.script), ("uz", "cyrillic"));
    }

    #[test]
    fn mixed_and_unknown() {
        let d = detect(
            "Настоящий договор является основанием. Ushbu qoidalar xizmat tartibi va bilan.",
        );
        assert_eq!(d.language, "mixed");
        let d = detect("12345 ---");
        assert_eq!((d.language, d.script), ("unknown", "none"));
    }
}
