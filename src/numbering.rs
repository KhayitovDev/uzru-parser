//! Detection of section numbering and list markers at the start of a line.

use crate::chars::is_apostrophe;

pub struct Numbering {
    pub kind: &'static str,
    pub depth: usize,
}

const KEYWORDS: &[(&str, usize)] = &[
    ("раздел", 1),
    ("приложение", 1),
    ("глава", 2),
    ("часть", 2),
    ("статья", 3),
    ("параграф", 3),
    ("bolim", 1),
    ("ilova", 1),
    ("bob", 2),
    ("qism", 2),
    ("modda", 3),
    ("бўлим", 1),
    ("илова", 1),
    ("боб", 2),
    ("қисм", 2),
    ("модда", 3),
];

const BULLETS: &[char] = &['•', '·', '▪', '●', '○', '■', '◦', '–', '—', '-', '*'];

fn keyword_depth(text: &str) -> Option<usize> {
    let end = text
        .find(|c: char| !(c.is_alphabetic() || is_apostrophe(c)))
        .unwrap_or(text.len());
    let word: String = text[..end]
        .chars()
        .filter(|&c| !is_apostrophe(c))
        .flat_map(char::to_lowercase)
        .collect();
    let (_, depth) = KEYWORDS.iter().find(|(k, _)| *k == word)?;

    let rest = &text[end..];
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
    (next.is_ascii_digit() || matches!(next, 'I' | 'V' | 'X' | 'L' | 'C')).then_some(*depth)
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
    let rest = &text[i..];
    let has_title = rest.starts_with(char::is_whitespace) && !rest.trim().is_empty();
    (has_title && (trailing_dot || groups > 1)).then_some(groups)
}

/// Latin roman numeral followed by a dot and a title: "I. Общие положения".
fn roman_depth(text: &str) -> Option<usize> {
    let numeral: String = text
        .chars()
        .take_while(|c| matches!(c, 'I' | 'V' | 'X' | 'L' | 'C'))
        .collect();
    let rest = text[numeral.len()..].strip_prefix('.')?;
    let valid = (1..=6).contains(&numeral.len())
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

    fn info(s: &str) -> Option<(&'static str, usize)> {
        numbering_info(s).map(|n| (n.kind, n.depth))
    }

    #[test]
    fn decimal_sections() {
        assert_eq!(info("1. ОБЩИЕ ПОЛОЖЕНИЯ"), Some(("decimal", 1)));
        assert_eq!(info("1.1. Основные понятия"), Some(("decimal", 2)));
        assert_eq!(info("2.3.4 Asosiy qoidalar"), Some(("decimal", 3)));
        assert_eq!(info("2024. Год"), None);
        assert_eq!(info("5 штук"), None);
        assert_eq!(info("1."), None);
    }

    #[test]
    fn roman_sections() {
        assert_eq!(info("I. Общие положения"), Some(("decimal", 1)));
        assert_eq!(info("IV. UMUMIY QOIDALAR"), Some(("decimal", 1)));
        assert_eq!(info("I."), None);
        assert_eq!(info("Index. text"), None);
        assert_eq!(info("И. И. Иванов"), None);
    }

    #[test]
    fn keywords() {
        assert_eq!(info("Статья 5. Права сторон"), Some(("keyword", 3)));
        assert_eq!(info("РАЗДЕЛ II"), Some(("keyword", 1)));
        assert_eq!(info("Bo‘lim 3. Umumiy"), Some(("keyword", 1)));
        assert_eq!(info("Modda 12"), Some(("keyword", 3)));
        assert_eq!(info("МОДДА 7. Тартиб"), Some(("keyword", 3)));
        assert_eq!(info("Статья без номера"), None);
        assert_eq!(info("ПРИЛОЖЕНИЕ № 1"), Some(("keyword", 1)));
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
