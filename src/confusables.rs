//! Words that mix Cyrillic and Latin look-alike letters ("vаlyutа" with Cyrillic "а").
//!
//! The pairs are the letter-to-letter entries of the Unicode confusables list (UTS #39,
//! confusables.txt) between the two scripts. Only true twins are listed: letters such as
//! и л д ж ш ч ў қ ғ ҳ have no Latin twin and are never converted.

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

/// Make one mixed word single-script. Returns false (and changes nothing) when a minority
/// letter has no twin or the majority cannot be decided.
fn fix_word(word: &mut [char], text_majority: Option<Script>) -> bool {
    let (latin, cyrillic) = counts(word);
    if latin == 0 || cyrillic == 0 {
        return false;
    }
    let target = match latin.cmp(&cyrillic) {
        std::cmp::Ordering::Greater => Script::Latin,
        std::cmp::Ordering::Less => Script::Cyrillic,
        std::cmp::Ordering::Equal => match text_majority {
            Some(target) => target,
            None => return false,
        },
    };
    let minority = |c: char| script(c).is_some_and(|s| s != target);
    if word
        .iter()
        .any(|&c| minority(c) && twin(c, target).is_none())
    {
        return false;
    }
    for c in word.iter_mut().filter(|c| minority(**c)) {
        *c = twin(*c, target).unwrap_or(*c);
    }
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
    fn words_without_twins_stay_mixed() {
        // "и" and "ш" have no Latin twin; the Latin majority cannot absorb them.
        assert_eq!(fix("bankиш"), ("bankиш".into(), 0));
    }
}
