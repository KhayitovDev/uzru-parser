//! Rule-based sentence splitting for Russian and Uzbek.

use crate::chars::is_apostrophe;

const TERMINATORS: &[char] = &['.', '!', '?', '…'];
const CLOSERS: &[char] = &['"', '»', '”', ')', '’', '\''];
const OPENERS: &[char] = &['«', '"', '“', '(', '„'];

const ABBREVIATIONS: &[&str] = &[
    "г", "гг", "ул", "руб", "коп", "тыс", "млн", "млрд", "им", "см", "напр", "ст", "пп", "др",
    "проф", "доц", "акад", "стр", "рис", "табл", "ред", "изд", "обл", "корп", "оф", "кв", "тел",
    "kv", "koch", "tel", "sh", "mln", "mlrd", "ming", "минг",
];

/// The alphanumeric word that ends right before `end`.
fn word_before(text: &str, end: usize) -> &str {
    let head = &text[..end];
    let start = head
        .char_indices()
        .rev()
        .find(|&(_, c)| !(c.is_alphanumeric() || is_apostrophe(c) || c == '.'))
        .map_or(0, |(i, c)| i + c.len_utf8());
    &head[start..]
}

fn is_abbreviation(word: &str) -> bool {
    let bare: String = word
        .chars()
        .filter(|&c| !is_apostrophe(c))
        .flat_map(char::to_lowercase)
        .collect();
    let single_letter = bare.chars().count() == 1 && bare.chars().all(char::is_alphabetic);
    single_letter || ABBREVIATIONS.contains(&bare.as_str())
}

fn is_numbering(word: &str) -> bool {
    !word.is_empty() && word.chars().all(|c| c.is_ascii_digit() || c == '.')
}

fn starts_sentence(c: char) -> bool {
    c.is_uppercase() || c.is_ascii_digit() || OPENERS.contains(&c)
}

pub fn split_sentences(text: &str) -> Vec<String> {
    let mut sentences = Vec::new();
    let mut start = 0;
    let mut iter = text.char_indices().peekable();

    while let Some((i, c)) = iter.next() {
        if !TERMINATORS.contains(&c) {
            continue;
        }
        let mut end = i + c.len_utf8();
        while let Some(&(j, n)) = iter.peek() {
            if TERMINATORS.contains(&n) || CLOSERS.contains(&n) {
                end = j + n.len_utf8();
                iter.next();
            } else {
                break;
            }
        }

        let rest = &text[end..];
        let boundary = match rest.chars().next() {
            None => true,
            Some(n) if n.is_whitespace() => {
                rest.trim_start().chars().next().is_none_or(starts_sentence)
            }
            Some(_) => false,
        };
        if !boundary {
            continue;
        }
        if c == '.' {
            let word = word_before(text, i);
            let at_sentence_start = text[start..i].trim_start() == word;
            if is_abbreviation(word) || (is_numbering(word) && at_sentence_start) {
                continue;
            }
        }
        push_trimmed(&mut sentences, &text[start..end]);
        start = end;
    }
    push_trimmed(&mut sentences, &text[start..]);
    sentences
}

fn push_trimmed(out: &mut Vec<String>, s: &str) {
    let s = s.trim();
    if !s.is_empty() {
        out.push(s.to_string());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_russian() {
        assert_eq!(
            split_sentences("Договор заключён. Стороны согласны! Это верно?"),
            ["Договор заключён.", "Стороны согласны!", "Это верно?"]
        );
    }

    #[test]
    fn keeps_abbreviations_and_initials() {
        assert_eq!(
            split_sentences(
                "Директор А. С. Пушкин купил хлеб, т. е. еду, за 5 тыс. рублей. Затем ушёл."
            ),
            [
                "Директор А. С. Пушкин купил хлеб, т. е. еду, за 5 тыс. рублей.",
                "Затем ушёл."
            ]
        );
    }

    #[test]
    fn keeps_numbering_and_decimals() {
        assert_eq!(
            split_sentences("1. Общие положения. Текст 1.5 раза."),
            ["1. Общие положения.", "Текст 1.5 раза."]
        );
    }

    #[test]
    fn splits_uzbek() {
        assert_eq!(
            split_sentences(
                "Ushbu qoidalar kuchga kirdi. O‘zbekiston Respublikasi «Qonun» qabul qildi."
            ),
            [
                "Ushbu qoidalar kuchga kirdi.",
                "O‘zbekiston Respublikasi «Qonun» qabul qildi."
            ]
        );
        assert_eq!(
            split_sentences("Ўзбекистон қонун қабул қилди. Бу муҳим."),
            ["Ўзбекистон қонун қабул қилди.", "Бу муҳим."]
        );
    }

    #[test]
    fn no_terminator_and_empty() {
        assert_eq!(split_sentences("без точки"), ["без точки"]);
        assert!(split_sentences("   ").is_empty());
    }
}
