//! Sentence splitting for Russian and Uzbek.
//!
//! Every delimiter is a candidate boundary; rules then rejoin the false ones (abbreviations,
//! initials, list numbers, quotes, brackets, dialogue dashes). The method, the rules and the
//! Russian abbreviation lists are ported from razdel (MIT, https://github.com/natasha/razdel);
//! the Uzbek lists (Latin and Cyrillic) are ours.

use std::collections::HashSet;
use std::sync::OnceLock;

const ENDINGS: &str = ".?!…";
const DASHES: &str = "‑–—−-";
const CLOSE_QUOTES: &str = "»”’";
const GENERIC_QUOTES: &str = "\"„'";
const CLOSE_BRACKETS: &str = ")]}";
const BULLET_CHARS: &str = "§абвгдеabcdef";
const BULLET_BOUNDS: &str = ".)";
/// A list marker ("8.1.", "IV.", "2)") is at most this long.
const BULLET_SIZE: usize = 20;
/// Characters of context the rules see on each side of a candidate.
const WINDOW: usize = 10;

/// Abbreviations followed by a number, a lowercase word or punctuation ("5 тыс. рублей").
const TAIL_SOKRS: &str = "дес тыс млн млрд дол долл коп руб р проц га барр куб кв км см час мин \
    сек в вв г гг с стр co corp inc изд ed др al \
    y yy й йй mln mlrd ming минг sh ш km кг kg t m м b б vil вил tum тум";
/// Abbreviations always followed by more of the sentence ("проф. Иванов").
const HEAD_SOKRS: &str = "букв ст трад лат венг исп кат укр нем англ фр итал греч евр араб яп слав \
    кит рус русск латв словацк хорв mr mrs ms dr vs св арх зав зам проф акад кн корр ред гр ср чл \
    им тов нач пол chap п пп ч чч гл абз пт no просп пр ул ш гор д к корп пер обл эт пом ауд оф ком \
    комн каб домовлад лит т рп пос х пл bd о оз а обр ум ок откр пс ps upd напр доп юр физ тел сб \
    внутр дифф гос отм \
    prof dots доц akad mas qar қар tahr таҳр j ж koʻch кўч";
const OTHER_SOKRS: &str = "сокр рис искл прим яз устар шутл";
/// Two-letter abbreviations "т. е."; the head ones are always followed by more text.
const TAIL_PAIR_SOKRS: &[(&str, &str)] = &[
    ("т", "п"),
    ("т", "д"),
    ("у", "е"),
    ("н", "э"),
    ("p", "m"),
    ("a", "m"),
    ("с", "г"),
    ("р", "х"),
    ("с", "ш"),
    ("з", "д"),
    ("л", "с"),
    ("ч", "т"),
    ("h", "k"),
    ("ҳ", "к"),
];
const HEAD_PAIR_SOKRS: &[(&str, &str)] = &[
    ("т", "е"),
    ("т", "к"),
    ("т", "н"),
    ("и", "о"),
    ("к", "н"),
    ("к", "п"),
    ("п", "н"),
    ("к", "т"),
    ("л", "д"),
    ("f", "d"),
    ("f", "n"),
    ("ф", "д"),
    ("ф", "н"),
];
const OTHER_PAIR_SOKRS: &[(&str, &str)] = &[
    ("ед", "ч"),
    ("мн", "ч"),
    ("повел", "накл"),
    ("жен", "р"),
    ("муж", "р"),
];
const INITIALS: &[&str] = &["дж", "ed", "вс", "sh", "ch", "oʻ", "gʻ", "ш", "ч"];

struct Sokrs {
    head: HashSet<&'static str>,
    any: HashSet<&'static str>,
}

fn sokrs() -> &'static Sokrs {
    static SOKRS: OnceLock<Sokrs> = OnceLock::new();
    SOKRS.get_or_init(|| {
        let head: HashSet<_> = HEAD_SOKRS.split_whitespace().collect();
        let mut any = head.clone();
        any.extend(TAIL_SOKRS.split_whitespace());
        any.extend(OTHER_SOKRS.split_whitespace());
        Sokrs { head, any }
    })
}

fn is_pair(pair: (&str, &str), list: &[(&str, &str)]) -> bool {
    list.iter().any(|&(a, b)| a == pair.0 && b == pair.1)
}

fn is_word_char(c: char) -> bool {
    c.is_alphabetic() && !c.is_numeric()
}

/// razdel's token: a run of letters, a run of digits, or one other non-space character.
fn first_token(text: &str) -> Option<&str> {
    let text = text.trim_start();
    let first = text.chars().next()?;
    let end = if is_word_char(first) {
        text.find(|c: char| !is_word_char(c))
    } else if first.is_ascii_digit() {
        text.find(|c: char| !c.is_ascii_digit())
    } else {
        Some(first.len_utf8())
    };
    Some(&text[..end.unwrap_or(text.len())])
}

fn last_token(text: &str) -> Option<&str> {
    let text = text.trim_end();
    let last = text.chars().next_back()?;
    let same: fn(char) -> bool = if is_word_char(last) {
        is_word_char
    } else if last.is_ascii_digit() {
        |c| c.is_ascii_digit()
    } else {
        return Some(&text[text.len() - last.len_utf8()..]);
    };
    let start = text
        .char_indices()
        .rev()
        .find(|&(_, c)| !same(c))
        .map_or(0, |(i, c)| i + c.len_utf8());
    Some(&text[start..])
}

fn tokens(text: &str) -> Vec<&str> {
    let mut found = Vec::new();
    let mut rest = text;
    while let Some(token) = first_token(rest) {
        let at = rest.find(token).unwrap_or(0);
        found.push(token);
        rest = &rest[at + token.len()..];
    }
    found
}

fn lower(text: &str) -> String {
    text.chars().flat_map(char::to_lowercase).collect()
}

fn is_lower_alpha(token: &str) -> bool {
    token.chars().all(char::is_alphabetic)
        && token.chars().any(char::is_lowercase)
        && !token.chars().any(char::is_uppercase)
}

/// "т. е" at the end of the left context: the two letters around the last dot.
fn left_pair(left: &str) -> Option<(String, String)> {
    let rest = left.trim_end();
    let second = rest.chars().next_back().filter(|c| c.is_alphanumeric())?;
    let rest = rest[..rest.len() - second.len_utf8()].trim_end();
    let rest = rest.strip_suffix('.')?.trim_end();
    let first = rest.chars().next_back().filter(|c| c.is_alphanumeric())?;
    Some((lower(&first.to_string()), lower(&second.to_string())))
}

struct Split<'a> {
    left: &'a str,
    delimiter: char,
    right: &'a str,
    buffer: &'a str,
}

fn is_sokr_right(token: &str) -> bool {
    token.chars().all(|c| c.is_ascii_digit())
        || !token.chars().all(char::is_alphabetic)
        || is_lower_alpha(token)
}

/// razdel's rules, in its order: `Some(true)` joins, `None` passes to the next rule; no rule
/// forces a split, which is the default.
type Rule = fn(&Split, &str, &str) -> Option<bool>;

const RULES: &[Rule] = &[
    trivial,
    delimiter_right,
    sokr_left,
    inside_pair_sokr,
    initials_left,
    list_item,
    close_quote,
    close_bracket,
    dash_right,
];

fn joins(split: &Split) -> bool {
    let (Some(left), Some(right)) = (last_token(split.left), first_token(split.right)) else {
        return true;
    };
    RULES
        .iter()
        .find_map(|rule| rule(split, left, right))
        .unwrap_or(false)
}

/// No space after the delimiter, or a lowercase word after it.
fn trivial(split: &Split, _: &str, right: &str) -> Option<bool> {
    (!split.right.starts_with(char::is_whitespace) || is_lower_alpha(right)).then_some(true)
}

fn delimiter_right(_: &Split, _: &str, right: &str) -> Option<bool> {
    let mut chars = right.chars();
    let first = chars.next()?;
    if chars.next().is_some() || GENERIC_QUOTES.contains(first) {
        return None;
    }
    (ENDINGS.contains(first)
        || first == ';'
        || CLOSE_QUOTES.contains(first)
        || CLOSE_BRACKETS.contains(first))
    .then_some(true)
}

fn sokr_left(split: &Split, left: &str, right: &str) -> Option<bool> {
    if split.delimiter != '.' {
        return None;
    }
    if let Some((a, b)) = left_pair(split.left) {
        if is_pair((&a, &b), HEAD_PAIR_SOKRS) {
            return Some(true);
        }
        if is_pair((&a, &b), TAIL_PAIR_SOKRS) || is_pair((&a, &b), OTHER_PAIR_SOKRS) {
            return is_sokr_right(right).then_some(true);
        }
    }
    let left = lower(left);
    let head = sokrs().head.contains(left.as_str());
    (head || (sokrs().any.contains(left.as_str()) && is_sokr_right(right))).then_some(true)
}

fn inside_pair_sokr(split: &Split, left: &str, right: &str) -> Option<bool> {
    if split.delimiter != '.' {
        return None;
    }
    let (left, right) = (lower(left), lower(right));
    [TAIL_PAIR_SOKRS, HEAD_PAIR_SOKRS, OTHER_PAIR_SOKRS]
        .iter()
        .any(|list| is_pair((&left, &right), list))
        .then_some(true)
}

fn initials_left(split: &Split, left: &str, _: &str) -> Option<bool> {
    if split.delimiter != '.' {
        return None;
    }
    let single_capital = left.chars().count() == 1 && left.chars().all(char::is_uppercase);
    (single_capital || INITIALS.contains(&lower(left).as_str())).then_some(true)
}

fn list_item(split: &Split, _: &str, _: &str) -> Option<bool> {
    let short = split.buffer.chars().count() <= BULLET_SIZE;
    (BULLET_BOUNDS.contains(split.delimiter)
        && short
        && tokens(split.buffer).iter().all(|t| is_bullet(t)))
    .then_some(true)
}

/// After a closing quote or bracket the sentence ends only if an ending precedes it.
fn close_bound(left: &str) -> Option<bool> {
    (!left.chars().all(|c| ENDINGS.contains(c))).then_some(true)
}

fn close_quote(split: &Split, left: &str, _: &str) -> Option<bool> {
    if CLOSE_QUOTES.contains(split.delimiter) {
        return close_bound(left);
    }
    if GENERIC_QUOTES.contains(split.delimiter) {
        if split.left.ends_with(char::is_whitespace) {
            return Some(true);
        }
        return close_bound(left);
    }
    None
}

fn close_bracket(split: &Split, left: &str, _: &str) -> Option<bool> {
    CLOSE_BRACKETS
        .contains(split.delimiter)
        .then(|| close_bound(left))
        .flatten()
}

fn dash_right(split: &Split, _: &str, right: &str) -> Option<bool> {
    if !right.chars().all(|c| DASHES.contains(c)) {
        return None;
    }
    let word = split
        .right
        .split(|c: char| !c.is_alphanumeric())
        .find(|w| !w.is_empty());
    word.is_some_and(is_lower_alpha).then_some(true)
}

fn is_bullet(token: &str) -> bool {
    token.chars().all(|c| c.is_ascii_digit())
        || (token.chars().count() == 1 && BULLET_BOUNDS.contains(token))
        || (token.chars().count() == 1 && BULLET_CHARS.contains(&*lower(token)))
        || token.chars().all(|c| "IVXMLІ".contains(c))
}

fn is_delimiter(c: char) -> bool {
    ENDINGS.contains(c)
        || c == ';'
        || GENERIC_QUOTES.contains(c)
        || CLOSE_QUOTES.contains(c)
        || CLOSE_BRACKETS.contains(c)
}

fn window_before(text: &str, end: usize) -> &str {
    let start = text[..end]
        .char_indices()
        .rev()
        .nth(WINDOW - 1)
        .map_or(0, |(i, _)| i);
    &text[start..end]
}

fn window_after(text: &str, start: usize) -> &str {
    let end = text[start..]
        .char_indices()
        .nth(WINDOW)
        .map_or(text.len(), |(i, _)| start + i);
    &text[start..end]
}

pub fn split_sentences(text: &str) -> Vec<String> {
    let mut sentences = Vec::new();
    let mut start = 0;
    for (i, c) in text.char_indices() {
        if !is_delimiter(c) {
            continue;
        }
        let stop = i + c.len_utf8();
        let split = Split {
            left: window_before(text, i),
            delimiter: c,
            right: window_after(text, stop),
            buffer: &text[start..i],
        };
        if !joins(&split) {
            push_trimmed(&mut sentences, &text[start..stop]);
            start = stop;
        }
    }
    push_trimmed(&mut sentences, &text[start..]);
    sentences
}

/// Does a sentence end between `left` and `right` (a line or block break)? A text that does
/// not end with a delimiter runs on.
pub fn is_sentence_break(left: &str, right: &str) -> bool {
    let left = left.trim_end();
    let Some(c) = left.chars().next_back().filter(|&c| is_delimiter(c)) else {
        return false;
    };
    let at = left.len() - c.len_utf8();
    let right = format!(" {}", right.trim_start());
    // The whole line is the buffer: only a line that is just a marker ("4.", "IV.") is one.
    !joins(&Split {
        left: window_before(left, at),
        delimiter: c,
        right: window_after(&right, 0),
        buffer: left[..at].trim_start(),
    })
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

    /// razdel's notation: sentences of `text` separated by "| |".
    fn check(text: &str) {
        let expected: Vec<&str> = text.split("| |").collect();
        assert_eq!(
            split_sentences(&text.replace("| |", " ")),
            expected,
            "{text}"
        );
    }

    #[test]
    fn razdel_cases() {
        // From razdel's unit tests (MIT).
        for case in [
            "фонетических правил языка; в случае, если",
            "(Прилепин — очень хороший писатель, лучше, чем Лимонов.| |Но враг)",
            "Петров - 176!| |Михайлов - 180!",
            "если бы… не тот широко",
            "Георгий Иванов.| |На грани музыки и сна",
            "исполняется 150 лет.| |31 мая 1859 года после неоднократных",
            "И т. д. и т. п.| |В общем, вся газета",
            "специалистом, к.п.н. И. П. Карташовым.",
            "основании п. 2, ст. 5 УПК",
            "Вблизи оз. Селяха",
            "уменьшить с 20 до 18 проц. (при сохранении",
            "6 июля 2007 г. \"в связи с совершением",
            "на 500 тыс. машин",
            "Влияние взглядов Л. В. Щербы",
            "директор фирмы Чарльз Дж. Филлипс",
            "Т.е. ОБЯЗАТЕЛЬНО письменно",
            "была утечка т.н. Таблицы боевых действий",
            "В 1996-1999гг. теффт",
            "России, т. е. 55 % опрошенных",
            "я ощущал в 1990-е.| |Славное было время",
            "словам, \"не будет точно\".| |\"Возможно, у нас",
            "Брось!..\"| |Связываться не хотелось",
            "Это чудовищные риски.| |\"Яндекс\" попал под удар",
            "кто они такие… »",
            "— Ты ей скажи, что я ей гостинца дам.| |— А мне дашь?",
            "4. Я присутствовал во время встречи",
            "IV. Гестационный сахарный диабет",
            "§2. Нахождение оптимального объекта.",
            "8.1. Зачем нужны эти классы?",
            "в данной квартире;| |2) отчуждать свою долю",
        ] {
            check(case);
        }
    }

    #[test]
    fn uzbek_abbreviations_and_initials() {
        for case in [
            "2021 y. dekabr oyida qabul qilindi.| |Qonun kuchga kirdi.",
            "Shartnoma 5 mln. soʻmga tuzildi.",
            "Taqrizchi: i.f.d. prof. O. Rashidov.",
            "Oʻzbekiston Respublikasi Prezidenti Sh. Mirziyoyev imzoladi.",
            "kitoblar, jurnallar va h.k. qoʻshildi.",
            "Тақризчи: и.ф.д. проф. О. Рашидов.",
            "Ўзбекистон қонун қабул қилди.| |Бу муҳим.",
            "Ushbu qoidalar kuchga kirdi.| |Oʻzbekiston Respublikasi «Qonun» qabul qildi.",
        ] {
            check(case);
        }
    }

    #[test]
    fn existing_behaviour_is_kept() {
        assert_eq!(
            split_sentences("Договор заключён. Стороны согласны! Это верно?"),
            ["Договор заключён.", "Стороны согласны!", "Это верно?"]
        );
        assert_eq!(
            split_sentences(
                "Директор А. С. Пушкин купил хлеб, т. е. еду, за 5 тыс. рублей. Затем ушёл."
            ),
            [
                "Директор А. С. Пушкин купил хлеб, т. е. еду, за 5 тыс. рублей.",
                "Затем ушёл."
            ]
        );
        assert_eq!(
            split_sentences("1. Общие положения. Текст 1.5 раза."),
            ["1. Общие положения.", "Текст 1.5 раза."]
        );
        assert_eq!(split_sentences("без точки"), ["без точки"]);
        assert!(split_sentences("   ").is_empty());
    }

    #[test]
    fn breaks_between_lines() {
        assert!(is_sentence_break("Договор заключён.", "Стороны согласны"));
        assert!(!is_sentence_break("в соответствии со ст.", "5 Закона"));
        assert!(!is_sentence_break("взгляды Л. В.", "Щербы"));
        assert!(!is_sentence_break("prof.", "Karimov"));
        assert!(!is_sentence_break("текст продолжается", "Дальше"));
        assert!(!is_sentence_break(
            "предложение.",
            "продолжение со строчной"
        ));
        assert!(is_sentence_break("сказал он.»", "Затем"));
        assert!(!is_sentence_break("4.", "Я присутствовал"));
        assert!(is_sentence_break(
            "Мониторинг качества банковских услуг. 2004.",
            "Banklar"
        ));
        assert!(is_sentence_break(
            "“Банковская система России”. 2009. 186 б.",
            "Bank"
        ));
    }
}
