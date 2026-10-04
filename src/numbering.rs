//! Detection of section numbering and list markers at the start of a line.

use std::sync::RwLock;

use crate::chars::is_apostrophe;

pub struct Numbering {
    pub kind: &'static str,
    pub depth: usize,
}

/// Chapter/section words and their rank (1 = largest unit). Set from Python's config
/// (`uzru_parser.config.HEADING_KEYWORDS`), the single place where the list lives.
static KEYWORDS: RwLock<Vec<(String, usize)>> = RwLock::new(Vec::new());

/// Replace the keyword list. Words are compared lowercased and without apostrophes.
pub fn set_keywords(keywords: Vec<(String, usize)>) {
    let normalized = keywords
        .into_iter()
        .map(|(word, rank)| (bare_lowercase(&word), rank))
        .collect();
    if let Ok(mut list) = KEYWORDS.write() {
        *list = normalized;
    }
}

fn bare_lowercase(word: &str) -> String {
    word.chars()
        .filter(|&c| !is_apostrophe(c))
        .flat_map(char::to_lowercase)
        .collect()
}

const BULLETS: &[char] = &[
    '•', '·', '▪', '●', '○', '■', '◦', '–', '—', '-', '*', '✓', '✔', '➢', '➤', '►', '▶', '◆', '❖',
    '□',
];
/// Opening quotes and brackets a title may start with when glued to its number: "5.“Umumiy".
const OPENING: &[char] = &['“', '«', '„', '"', '(', '‘', '\''];

/// Leading alphabetic word, lowercased and without apostrophes, plus the text after it.
fn leading_word(text: &str) -> (String, &str) {
    let end = text
        .find(|c: char| !(c.is_alphabetic() || is_apostrophe(c)))
        .unwrap_or(text.len());
    (bare_lowercase(&text[..end]), &text[end..])
}

const PARAGRAPH_SIGN: char = '§';
const PARAGRAPH_DEPTH: usize = 3;

fn depth_of(word: &str) -> Option<usize> {
    let list = KEYWORDS.read().ok()?;
    list.iter()
        .find(|(k, _)| k == word)
        .map(|&(_, depth)| depth)
}

/// Roman numeral letters, with the Cyrillic "І" (U+0406) and "Х" (U+0425) that OCR and
/// Cyrillic keyboards put in place of "I" and "X".
fn is_roman(c: char) -> bool {
    matches!(c, 'I' | 'V' | 'X' | 'L' | 'C' | '\u{0406}' | '\u{0425}')
}

/// Uzbek ordinal numbers end in "-inchi"/"-nchi": "birinchi", "ikkinchi", "uchinchi".
fn is_uzbek_ordinal(word: &str) -> bool {
    word.chars().count() >= 5 && ["nchi", "нчи"].iter().any(|end| word.ends_with(end))
}

/// Russian ordinal numbers: "первый", "вторая", "третий", ... "десятый".
fn is_russian_ordinal(word: &str) -> bool {
    const STEMS: &[&str] = &[
        "перв",
        "втор",
        "трет",
        "четв",
        "пят",
        "шест",
        "седьм",
        "восьм",
        "девят",
        "десят",
    ];
    STEMS.iter().any(|stem| word.starts_with(stem))
}

/// Keyword followed by a number: "Статья 5", "Приложение № 1", "РАЗДЕЛ II", "ЧАСТЬ ПЕРВАЯ".
fn keyword_first(text: &str) -> Option<usize> {
    if let Some(rest) = text.strip_prefix(PARAGRAPH_SIGN) {
        let next = rest.trim_start().chars().next()?;
        return (rest.starts_with(char::is_whitespace) && next.is_ascii_digit())
            .then_some(PARAGRAPH_DEPTH);
    }
    let (word, rest) = leading_word(text);
    let depth = depth_of(&word)?;
    if !rest.starts_with(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim_start();
    let next = rest
        .strip_prefix('№')
        .unwrap_or(rest)
        .trim_start()
        .chars()
        .next()?;
    let ordinal = is_russian_ordinal(&leading_word(rest).0);
    (next.is_ascii_digit() || is_roman(next) || ordinal).then_some(depth)
}

/// Superscript digits number inserted articles: "10¹-modda" comes between 10 and 11.
fn is_superscript_digit(c: char) -> bool {
    matches!(c, '¹' | '²' | '³' | '\u{2070}' | '\u{2074}'..='\u{2079}')
}

/// Number followed by a keyword, the Uzbek order: "1-modda", "12-bob", "10¹-modda",
/// "I BOʻLIM", "II-BOB", "BIRINCHI BOʻLIM".
fn number_first(text: &str) -> Option<usize> {
    let digits = text
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(text.len());
    let (first_word, after_word) = leading_word(text);
    let rest = if (1..=3).contains(&digits) {
        let after = text[digits..].trim_start_matches(is_superscript_digit);
        let rest = after.trim_start().strip_prefix('-')?.trim_start();
        if rest.starts_with(PARAGRAPH_SIGN) {
            return Some(PARAGRAPH_DEPTH);
        }
        rest
    } else if is_uzbek_ordinal(&first_word) {
        // "BIRINCHI BOʻLIM", "Ikkinchi qism"
        let after = after_word.trim_start();
        after.strip_prefix('-').unwrap_or(after).trim_start()
    } else {
        let numeral = text.find(|c: char| !is_roman(c)).unwrap_or(text.len());
        let after = &text[numeral..];
        if digits != 0 || !(1..=6).contains(&text[..numeral].chars().count()) {
            return None;
        }
        match after.trim_start().strip_prefix('-') {
            Some(rest) => rest.trim_start(),
            None if after.starts_with(char::is_whitespace) => after.trim_start(),
            None => return None,
        }
    };
    depth_of(&leading_word(rest).0)
}

fn keyword_depth(text: &str) -> Option<usize> {
    keyword_first(text).or_else(|| number_first(text))
}

fn decimal_depth(text: &str) -> Option<usize> {
    let b = text.as_bytes();
    let (mut i, mut groups, mut trailing_dot) = (0, 0, false);
    loop {
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == start || i - start > 3 {
            return None;
        }
        groups += 1;
        if i < b.len() && b[i] == b'.' {
            i += 1;
            if i < b.len() && b[i].is_ascii_digit() {
                continue;
            }
            trailing_dot = true;
        }
        break;
    }
    let mut rest = &text[i..];
    if !trailing_dot {
        // "5.3 . Title"
        if let Some(after_dot) = rest.trim_start().strip_prefix('.') {
            trailing_dot = true;
            rest = after_dot;
        }
    }
    // "5.3.Title", "5.“Title": a title glued to the final dot.
    let glued_title =
        trailing_dot && rest.starts_with(|c: char| c.is_alphabetic() || OPENING.contains(&c));
    let has_title =
        (rest.starts_with(char::is_whitespace) || glued_title) && !rest.trim().is_empty();
    // Without a final dot, "1.25 foiz" is a number in running text; "5.3 Title" a section.
    let titled = trailing_dot || rest.trim_start().starts_with(|c: char| !c.is_lowercase());
    (has_title && titled && (trailing_dot || groups > 1)).then_some(groups)
}

/// Roman numeral followed by a dot and a title: "I. Общие положения". A lone Cyrillic "Х."
/// is an initial ("Х. Хайдаров"), not ten.
fn roman_depth(text: &str) -> Option<usize> {
    let end = text.find(|c: char| !is_roman(c)).unwrap_or(text.len());
    let numeral = &text[..end];
    let rest = text[end..].strip_prefix('.')?;
    let letters = numeral.chars().count();
    let valid = (1..=6).contains(&letters)
        && numeral != "\u{0425}"
        && rest.starts_with(char::is_whitespace)
        && !rest.trim().is_empty();
    valid.then_some(1)
}

fn is_bullet(text: &str) -> bool {
    let mut chars = text.chars();
    chars.next().is_some_and(|c| BULLETS.contains(&c))
        && chars.next().is_some_and(char::is_whitespace)
}

fn is_ordered(text: &str) -> bool {
    let body = text.strip_prefix('(').unwrap_or(text);
    let label: String = body.chars().take_while(|c| c.is_alphanumeric()).collect();
    let valid = match label.chars().count() {
        1 => label.chars().all(char::is_alphanumeric),
        2 => label.chars().all(|c| c.is_ascii_digit()),
        _ => false,
    };
    valid
        && body[label.len()..].starts_with(')')
        && body[label.len() + 1..].starts_with(char::is_whitespace)
}

pub fn numbering_info(line: &str) -> Option<Numbering> {
    let text = line.trim_start();
    if let Some(depth) = keyword_depth(text) {
        return Some(Numbering {
            kind: "keyword",
            depth,
        });
    }
    if let Some(depth) = decimal_depth(text) {
        return Some(Numbering {
            kind: "decimal",
            depth,
        });
    }
    if let Some(depth) = roman_depth(text) {
        return Some(Numbering {
            kind: "decimal",
            depth,
        });
    }
    if is_bullet(text) {
        return Some(Numbering {
            kind: "bullet",
            depth: 1,
        });
    }
    if is_ordered(text) {
        return Some(Numbering {
            kind: "ordered",
            depth: 1,
        });
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Mirrors the default list in `uzru_parser.config` (tests only).
    fn install_keywords() {
        let words = [
            ("раздел", 1),
            ("тема", 1),
            ("приложение", 1),
            ("глава", 2),
            ("часть", 2),
            ("параграф", 3),
            ("статья", 4),
            ("mavzu", 1),
            ("boʻlim", 1),
            ("ilova", 1),
            ("bob", 2),
            ("qism", 2),
            ("modda", 4),
            ("мавзу", 1),
            ("бўлим", 1),
            ("илова", 1),
            ("боб", 2),
            ("қисм", 2),
            ("модда", 4),
        ];
        set_keywords(words.iter().map(|&(w, r)| (w.to_string(), r)).collect());
    }

    fn info(s: &str) -> Option<(&'static str, usize)> {
        install_keywords();
        numbering_info(s).map(|n| (n.kind, n.depth))
    }

    #[test]
    fn glued_markers_check_marks_and_running_decimals() {
        assert_eq!(info("5.“Umumiy qoidalar”"), Some(("decimal", 1)));
        assert_eq!(info("1.Qiymat"), Some(("decimal", 1)));
        assert_eq!(info("✓ Valyuta riski"), Some(("bullet", 1)));
        assert_eq!(info("1.25 foiz miqdorida"), None);
        assert_eq!(info("5.3 Banklarning turlari"), Some(("decimal", 2)));
    }

    #[test]
    fn decimal_sections() {
        assert_eq!(info("1. ОБЩИЕ ПОЛОЖЕНИЯ"), Some(("decimal", 1)));
        assert_eq!(info("1.1. Основные понятия"), Some(("decimal", 2)));
        assert_eq!(info("2.3.4 Asosiy qoidalar"), Some(("decimal", 3)));
        assert_eq!(info("2024. Год"), None);
        assert_eq!(info("5 штук"), None);
        assert_eq!(info("1."), None);
        assert_eq!(info("5.3.Banklarning turlari"), Some(("decimal", 2)));
        assert_eq!(info("5.3 . Banklarning turlari"), Some(("decimal", 2)));
        assert_eq!(info("12.05.2020 yil"), None);
        assert_eq!(info("1.5кг"), None);
    }

    #[test]
    fn roman_sections() {
        assert_eq!(info("I. Общие положения"), Some(("decimal", 1)));
        assert_eq!(info("IV. UMUMIY QOIDALAR"), Some(("decimal", 1)));
        assert_eq!(info("I."), None);
        assert_eq!(info("Index. text"), None);
        assert_eq!(info("И. И. Иванов"), None);
        assert_eq!(info("\u{0406}. Общие положения"), Some(("decimal", 1)));
        assert_eq!(
            info("\u{0406}\u{0406}\u{0406}. Состояние"),
            Some(("decimal", 1))
        );
        assert_eq!(info("\u{0425}\u{0406}. Заключение"), Some(("decimal", 1)));
        assert_eq!(info("Х. Хайдаров доктор наук"), None);
        assert_eq!(info("С. Иванов"), None);
    }

    #[test]
    fn keywords() {
        assert_eq!(info("Статья 5. Права сторон"), Some(("keyword", 4)));
        assert_eq!(info("РАЗДЕЛ II"), Some(("keyword", 1)));
        assert_eq!(info("Bo‘lim 3. Umumiy"), Some(("keyword", 1)));
        assert_eq!(info("Modda 12"), Some(("keyword", 4)));
        assert_eq!(info("МОДДА 7. Тартиб"), Some(("keyword", 4)));
        assert_eq!(info("Статья без номера"), None);
        assert_eq!(info("ПРИЛОЖЕНИЕ № 1"), Some(("keyword", 1)));
        assert_eq!(info("1-modda. Ushbu Kodeks"), Some(("keyword", 4)));
        assert_eq!(info("1-§. Yakka tartib"), Some(("keyword", 3)));
        assert_eq!(info("§ 2. Общие правила"), Some(("keyword", 3)));
        assert_eq!(info("§ без номера"), None);
        assert_eq!(info("12-bob. Asosiy qoidalar"), Some(("keyword", 2)));
        assert_eq!(info("10¹-modda. Yer uchastkasi"), Some(("keyword", 4)));
        assert_eq!(info("4²-модда. Тартиб"), Some(("keyword", 4)));
        assert_eq!(info("10¹ foiz"), None);
        assert_eq!(
            info("BIRINChI BOʻLIM. ASOSIY PRINSIPLAR"),
            Some(("keyword", 1))
        );
        assert_eq!(info("Ikkinchi qism"), Some(("keyword", 2)));
        assert_eq!(info("ИККИНЧИ БЎЛИМ. ИНСОН ҲУҚУҚЛАРИ"), Some(("keyword", 1)));
        assert_eq!(info("ЧАСТЬ ПЕРВАЯ"), Some(("keyword", 2)));
        assert_eq!(info("Раздел третий. Обязательства"), Some(("keyword", 1)));
        assert_eq!(info("Birinchi navbatda bob"), None);
        assert_eq!(info("Ikkinchi marta"), None);
        assert_eq!(info("Статья выше"), None);
        assert_eq!(info("3-MAVZU: BANK OPERATSIYALARI"), Some(("keyword", 1)));
        assert_eq!(info("10 - mavzu: Guruhlarda ishlash"), Some(("keyword", 1)));
        assert_eq!(info("4-МАВЗУ: Банк рисклари"), Some(("keyword", 1)));
        assert_eq!(info("Тема 5. Валютные операции"), Some(("keyword", 1)));
        assert_eq!(info("5 - modda. Erkinlik"), Some(("keyword", 4)));
        assert_eq!(info("1-MAVZUGA oid"), None);
        assert_eq!(info("I-BOB. PUL VA KREDIT"), Some(("keyword", 2)));
        assert_eq!(info("II - BOB"), Some(("keyword", 2)));
        assert_eq!(info("IV BOB"), Some(("keyword", 2)));
        assert_eq!(info("I-qism davomi"), Some(("keyword", 2)));
        assert_eq!(info("II-jahon urushi"), None);
        assert_eq!(info("I BOʻLIM. UMUMIY QOIDALAR"), Some(("keyword", 1)));
        assert_eq!(info("XIII BOB"), Some(("keyword", 2)));
        assert_eq!(info("3-қисм. Умумий"), Some(("keyword", 2)));
        assert_eq!(info("5-moddasi boʻyicha"), None);
        assert_eq!(info("1-bandda koʻrsatilgan"), None);
        assert_eq!(info("Ilova №2"), Some(("keyword", 1)));
    }

    #[test]
    fn list_markers() {
        assert_eq!(info("• пункт"), Some(("bullet", 1)));
        assert_eq!(info("- punkt"), Some(("bullet", 1)));
        assert_eq!(info("1) первый"), Some(("ordered", 1)));
        assert_eq!(info("а) первый"), Some(("ordered", 1)));
        assert_eq!(info("(2) ikkinchi"), Some(("ordered", 1)));
        assert_eq!(info("это) не список"), None);
        assert_eq!(info("-5 градусов"), None);
    }
}
