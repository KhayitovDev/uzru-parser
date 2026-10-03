//! Known-word checks for Uzbek (Latin and Cyrillic) and Russian.
//!
//! `data/lexicon.txt` (built offline by `tools/build_lexicon.py`; data licensed CC BY-SA 4.0,
//! see src/data/LICENSE) holds word stems and the endings used to make them; a word is known
//! when its stem, made the same way, is listed.
//! Uzbek is stored in Latin, so Uzbek Cyrillic words are transliterated first.

use std::collections::HashSet;
use std::sync::OnceLock;

use crate::chars::is_apostrophe;
use crate::translit::cyrillic_to_latin;

static DATA: &str = include_str!("data/lexicon.txt");

struct Language {
    rounds: usize,
    endings: Vec<&'static str>,
    stems: HashSet<&'static str>,
}

struct Lexicon {
    min_stem: usize,
    uzbek: Language,
    russian: Language,
}

fn header(line: &str) -> (usize, Vec<&str>) {
    let mut parts = line.split_whitespace().skip(1);
    let rounds = parts.next().and_then(|r| r.parse().ok()).unwrap_or(1);
    let mut endings: Vec<&str> = parts.collect();
    endings.sort_by_key(|e| std::cmp::Reverse(e.chars().count()));
    (rounds, endings)
}

fn lexicon() -> &'static Lexicon {
    static LEXICON: OnceLock<Lexicon> = OnceLock::new();
    LEXICON.get_or_init(|| {
        let mut min_stem = 4;
        let mut uzbek = Language {
            rounds: 1,
            endings: Vec::new(),
            stems: HashSet::new(),
        };
        let mut russian = Language {
            rounds: 1,
            endings: Vec::new(),
            stems: HashSet::new(),
        };
        let mut section = None;
        for line in DATA.lines() {
            if let Some(value) = line.strip_prefix("#min-stem ") {
                min_stem = value.trim().parse().unwrap_or(min_stem);
            } else if line.starts_with("#uz-endings") {
                (uzbek.rounds, uzbek.endings) = header(line);
            } else if line.starts_with("#ru-endings") {
                (russian.rounds, russian.endings) = header(line);
            } else if line == "#uz" || line == "#ru" {
                section = Some(line);
            } else if !line.is_empty() {
                match section {
                    Some("#uz") => uzbek.stems.insert(line),
                    Some("#ru") => russian.stems.insert(line),
                    _ => false,
                };
            }
        }
        Lexicon {
            min_stem,
            uzbek,
            russian,
        }
    })
}

/// Strip the longest listed ending, up to `rounds` times; must match build_lexicon.py.
fn stem<'a>(word: &'a str, language: &Language, min_stem: usize) -> &'a str {
    let mut word = word;
    for _ in 0..language.rounds {
        let length = word.chars().count();
        let ending = language
            .endings
            .iter()
            .find(|e| word.ends_with(**e) && length - e.chars().count() >= min_stem);
        match ending {
            Some(e) => word = &word[..word.len() - e.len()],
            None => break,
        }
    }
    word
}

fn known_in(word: &str, language: &Language, min_stem: usize) -> bool {
    language.stems.contains(word) || language.stems.contains(stem(word, language, min_stem))
}

/// Lowercase with one apostrophe form, without apostrophes at either end.
fn normalize(word: &str) -> String {
    let mut out: String = word
        .chars()
        .map(|c| if is_apostrophe(c) { '\'' } else { c })
        .flat_map(char::to_lowercase)
        .collect();
    while out.ends_with('\'') {
        out.pop();
    }
    out.trim_start_matches('\'').to_string()
}

/// Is `word` a known Uzbek (either alphabet) or Russian word, inflected forms included?
pub fn is_known(word: &str) -> bool {
    let lexicon = lexicon();
    let word = normalize(word);
    if word.is_empty() {
        return false;
    }
    let cyrillic = word.chars().any(|c| ('\u{0400}'..='\u{04FF}').contains(&c));
    if !cyrillic {
        return known_in(&word, &lexicon.uzbek, lexicon.min_stem);
    }
    let russian = word.replace('ё', "е");
    known_in(&russian, &lexicon.russian, lexicon.min_stem)
        || known_in(&cyrillic_to_latin(&word), &lexicon.uzbek, lexicon.min_stem)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_words_in_all_three_alphabets() {
        for word in [
            "boshqarish",
            "qoidalari",
            "iqtisodchilar",
            "qoʻllab",
            "quvvatlash",
            "бошқариш",
            "иқтисодиёт",
            "настоящим",
            "деятельности",
        ] {
            assert!(is_known(word), "{word}");
        }
    }

    #[test]
    fn fragments_and_nonsense_are_unknown() {
        for word in ["тельнос", "xqzv", "кцуфж", ""] {
            assert!(!is_known(word), "{word}");
        }
    }
}
