//! Words that mix Cyrillic and Latin look-alike letters ("vаlyutа" with Cyrillic "а").
//!
//! The pairs are the letter-to-letter entries of the Unicode confusables list (UTS #39,
//! confusables.txt; Unicode License v3, see LICENSES/Unicode-3.0.txt) between the two scripts. Only true twins are listed: letters such as
//! и л д ж ш ч ў қ ғ ҳ have no Latin twin and are never converted. When both alphabets give a
//! possible spelling, the one that is a known word wins over the majority of letters.

use crate::lexicon::is_known;

/// Cyrillic letter -> Latin twin.
const CYRILLIC_TO_LATIN: &[(char, char)] = &[
    ('а', 'a'),
    ('е', 'e'),
    ('о', 'o'),
    ('р', 'p'),
    ('с', 'c'),
    ('у', 'y'),
    ('х', 'x'),
    ('і', 'i'),
    ('ј', 'j'),
    ('ѕ', 's'),
    ('һ', 'h'),
    ('ԁ', 'd'),
    ('ԛ', 'q'),
    ('ԝ', 'w'),
    ('ӏ', 'l'),
    ('А', 'A'),
    ('В', 'B'),
    ('Е', 'E'),
    ('К', 'K'),
    ('М', 'M'),
    ('Н', 'H'),
    ('О', 'O'),
    ('Р', 'P'),
    ('С', 'C'),
    ('Т', 'T'),
    ('Х', 'X'),
    ('У', 'Y'),
    ('І', 'I'),
    ('Ј', 'J'),
    ('Ѕ', 'S'),
    ('Ԛ', 'Q'),
    ('Ԝ', 'W'),
];

/// Latin letter -> Cyrillic twin, limited to letters of the Russian and Uzbek alphabets.
const LATIN_TO_CYRILLIC: &[(char, char)] = &[
    ('a', 'а'),
    ('c', 'с'),
    ('e', 'е'),
    ('o', 'о'),
    ('p', 'р'),
    ('x', 'х'),
    ('y', 'у'),
    ('A', 'А'),
    ('B', 'В'),
    ('C', 'С'),
    ('E', 'Е'),
    ('H', 'Н'),
    ('K', 'К'),
    ('M', 'М'),
    ('O', 'О'),
    ('P', 'Р'),
    ('T', 'Т'),
    ('X', 'Х'),
    ('Y', 'У'),
];

#[derive(Clone, Copy, PartialEq)]
enum Script {
    Latin,
    Cyrillic,
}

fn script(c: char) -> Option<Script> {
    if ('\u{0400}'..='\u{04FF}').contains(&c) && c.is_alphabetic() {
        Some(Script::Cyrillic)
    } else if c.is_ascii_alphabetic()
        || (('\u{00C0}'..='\u{024F}').contains(&c) && c.is_alphabetic())
    {
        Some(Script::Latin)
    } else {
        None
    }
}

fn twin(c: char, target: Script) -> Option<char> {
    let table = match target {
        Script::Latin => CYRILLIC_TO_LATIN,
        Script::Cyrillic => LATIN_TO_CYRILLIC,
    };
    table
        .iter()
        .find(|&&(from, _)| from == c)
        .map(|&(_, to)| to)
}

fn counts(chars: &[char]) -> (usize, usize) {
    chars
        .iter()
        .fold((0, 0), |(latin, cyrillic), &c| match script(c) {
            Some(Script::Latin) => (latin + 1, cyrillic),
            Some(Script::Cyrillic) => (latin, cyrillic + 1),
            None => (latin, cyrillic),
        })
}

/// The word converted entirely to `target`, if every minority letter has a twin.
fn converted(word: &[char], target: Script) -> Option<Vec<char>> {
    word.iter()
        .map(|&c| match script(c) {
            Some(s) if s != target => twin(c, target),
            _ => Some(c),
        })
        .collect()
}

/// Make one mixed word single-script: the alphabet whose version is a known word, else the
/// word's majority alphabet, else the text's. Returns false (and changes nothing) when no
/// version can be written or chosen.
fn fix_word(word: &mut [char], text_majority: Option<Script>) -> bool {
    let (latin, cyrillic) = counts(word);
    if latin == 0 || cyrillic == 0 {
        return false;
    }
    let majority = match latin.cmp(&cyrillic) {
        std::cmp::Ordering::Greater => Some(Script::Latin),
        std::cmp::Ordering::Less => Some(Script::Cyrillic),
        std::cmp::Ordering::Equal => text_majority,
    };
    let versions: Vec<(Script, Vec<char>)> = [Script::Latin, Script::Cyrillic]
        .into_iter()
        .filter_map(|target| converted(word, target).map(|chars| (target, chars)))
        .collect();
    let known: Vec<&(Script, Vec<char>)> = versions
        .iter()
        .filter(|(_, chars)| is_known(&chars.iter().collect::<String>()))
        .collect();
    let chosen = match known.as_slice() {
        [only] => Some(&only.1),
        _ => versions
            .iter()
            .find(|(target, _)| Some(*target) == majority)
            .map(|(_, chars)| chars),
    };
    let Some(chars) = chosen else {
        return false;
    };
    word.copy_from_slice(chars);
    true
}

/// Fix every mixed-script word in place; `is_word_char` decides word boundaries.
/// Returns the number of words changed.
pub fn fix_mixed_words(chars: &mut [char], is_word_char: impl Fn(char) -> bool) -> usize {
    let (latin, cyrillic) = counts(chars);
    let text_majority = match latin.cmp(&cyrillic) {
        std::cmp::Ordering::Greater => Some(Script::Latin),
        std::cmp::Ordering::Less => Some(Script::Cyrillic),
        std::cmp::Ordering::Equal => None,
    };
    let mut fixed = 0;
    let mut start = 0;
    while start < chars.len() {
        if !is_word_char(chars[start]) {
            start += 1;
            continue;
        }
        let end = (start..chars.len())
            .find(|&i| !is_word_char(chars[i]))
            .unwrap_or(chars.len());
        if fix_word(&mut chars[start..end], text_majority) {
            fixed += 1;
        }
        start = end;
    }
    fixed
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fix(text: &str) -> (String, usize) {
        let mut chars: Vec<char> = text.chars().collect();
        let n = fix_mixed_words(&mut chars, |c| c.is_alphabetic() || c == '’');
        (chars.into_iter().collect(), n)
    }

    #[test]
    fn latin_words_with_cyrillic_letters() {
        assert_eq!(fix("vаlyutа bozori"), ("valyuta bozori".into(), 1));
        assert_eq!(fix("MUNDАRIJА"), ("MUNDARIJA".into(), 1));
        assert_eq!(fix("II-BОB"), ("II-BOB".into(), 1));
        assert_eq!(fix("TА’LIM"), ("TA’LIM".into(), 1));
    }

    #[test]
    fn cyrillic_words_with_latin_letters() {
        assert_eq!(fix("Пoлитика бaнка"), ("Политика банка".into(), 2));
        assert_eq!(fix("ўқувчилaр"), ("ўқувчилар".into(), 1));
    }

    #[test]
    fn single_script_words_are_never_touched() {
        for text in [
            "Банковская система обеспечивает расчёты",
            "Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик",
            "Oʻzbekiston Respublikasi valyuta bozori",
            "XIX век, глава IV, MV=PY",
        ] {
            assert_eq!(fix(text), (text.to_string(), 0), "{text}");
        }
    }

    #[test]
    fn known_word_beats_the_letter_majority() {
        // Three Latin look-alikes against one Cyrillic "О": only "РОСТ" is a real word.
        assert_eq!(fix("PОCT"), ("РОСТ".into(), 1));
        assert_eq!(fix("bаnk"), ("bank".into(), 1));
    }

    #[test]
    fn words_without_twins_stay_mixed() {
        // "и" and "ш" have no Latin twin; the Latin majority cannot absorb them.
        assert_eq!(fix("bankиш"), ("bankиш".into(), 0));
    }
}
