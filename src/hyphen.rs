//! PDF hyphenation repair.
//!
//! A line ending in `letter + "-"` followed by a line starting with a lowercase letter
//! is a wrapped word *unless* the hyphen belongs to the word itself. There is no
//! dictionary here, so the rules are deliberately conservative and explicit:
//!
//! * a few left pieces are real hyphenated prefixes ("кто-", "северо-", "вице-"),
//! * a few right pieces are real particles ("-то", "-либо", "-нибудь", "-таки"),
//! * a few exact pairs are fixed words ("из-за", "во-первых").
//!
//! Anything else is treated as a line wrap and joined. The next line must start with a
//! lowercase letter, so "Москва-\nГород" and "пункт 1-\n2" are never touched.

/// Left pieces that form hyphenated words with almost anything that follows.
const KEEP_LEFT: &[&str] = &[
    "кое",
    "кто",
    "что",
    "как",
    "где",
    "куда",
    "когда",
    "какой",
    "чей",
    "северо",
    "юго",
    "восточно",
    "западно",
    "вице",
    "штаб",
    "унтер",
    "обер",
    "лейб",
];

/// Right pieces that are standalone particles.
const KEEP_RIGHT: &[&str] = &["то", "либо", "нибудь", "таки"];

/// Exact (left, right) pairs of fixed hyphenated words.
const KEEP_PAIRS: &[(&str, &str)] = &[
    ("из", "за"),
    ("из", "под"),
    ("из", "подо"),
    ("во", "первых"),
    ("во", "вторых"),
    ("в", "третьих"),
    ("в", "четвёртых"),
    ("в", "четвертых"),
];

fn is_word_char(c: char) -> bool {
    c.is_alphabetic() || c == '\u{02BB}' || c == '\u{02BC}'
}

fn first_word(s: &str) -> &str {
    let end = s.find(|c: char| !is_word_char(c)).unwrap_or(s.len());
    &s[..end]
}

fn last_word(s: &str) -> &str {
    let start = s
        .char_indices()
        .rev()
        .find(|&(_, c)| !is_word_char(c))
        .map_or(0, |(i, c)| i + c.len_utf8());
    &s[start..]
}

fn keep_hyphen(left: &str, right: &str) -> bool {
    let l = last_word(left).to_lowercase();
    let r = first_word(right).to_lowercase();
    KEEP_LEFT.contains(&l.as_str())
        || KEEP_RIGHT.contains(&r.as_str())
        || KEEP_PAIRS.contains(&(l.as_str(), r.as_str()))
}

/// Does `line` end with `letter-` and should that hyphen be removed given the next line?
fn is_wrap(line: &str, next: &str) -> bool {
    let mut rev = line.chars().rev();
    if rev.next() != Some('-') || !rev.next().is_some_and(char::is_alphabetic) {
        return false;
    }
    next.chars().next().is_some_and(char::is_lowercase)
        && !keep_hyphen(&line[..line.len() - 1], next)
}

/// Repair `-\n` line wraps. Other text is returned unchanged.
pub fn repair_hyphenation(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut lines = text.split('\n').peekable();
    while let Some(first) = lines.next() {
        let mut current = first.to_string();
        // Keep gluing while the current line ends with a wrapped hyphen ("орга-\nниза-\nция").
        while let Some(&next) = lines.peek() {
            let trimmed = current.trim_end();
            let next_trimmed = next.trim_start();
            if !is_wrap(trimmed, next_trimmed) {
                break;
            }
            let mut merged = trimmed[..trimmed.len() - 1].to_string();
            merged.push_str(next_trimmed);
            current = merged;
            lines.next();
        }
        out.push_str(&current);
        if lines.peek().is_some() {
            out.push('\n');
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joins_wrapped_word() {
        assert_eq!(
            repair_hyphenation("Настоя-\nщим документом"),
            "Настоящим документом"
        );
        assert_eq!(
            repair_hyphenation("xizmat ko‘rsa-\ntish tartibi"),
            "xizmat ko‘rsatish tartibi"
        );
        assert_eq!(repair_hyphenation("по-\nлитика"), "политика");
    }

    #[test]
    fn keeps_legit_hyphens() {
        assert_eq!(repair_hyphenation("кто-\nто пришёл"), "кто-\nто пришёл");
        assert_eq!(repair_hyphenation("из-\nза стола"), "из-\nза стола");
        assert_eq!(repair_hyphenation("северо-\nзападный"), "северо-\nзападный");
        assert_eq!(repair_hyphenation("во-\nпервых"), "во-\nпервых");
        assert_eq!(repair_hyphenation("Москва-\nГород"), "Москва-\nГород");
    }

    #[test]
    fn leaves_dashes_and_numbers() {
        assert_eq!(repair_hyphenation("a - b\nc"), "a - b\nc");
        assert_eq!(repair_hyphenation("пункт 1-\n2"), "пункт 1-\n2");
        assert_eq!(repair_hyphenation("конец-\n"), "конец-\n");
    }

    #[test]
    fn chained_wraps() {
        assert_eq!(
            repair_hyphenation("орга-\nниза-\nция труда"),
            "организация труда"
        );
    }
}
