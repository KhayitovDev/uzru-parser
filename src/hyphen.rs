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
//!
//! Extraction also leaves wraps inside one line ("boshqa- rish"). Those are joined when
//! the left word is entirely lowercase and the right word starts lowercase, so
//! "1978- yillarda" (digit), "Otamurodov- i.f.n." (capitalized, initials) and dashes
//! with spaces on both sides are kept.

/// Left pieces that form hyphenated words with almost anything that follows.
const KEEP_LEFT: &str = "кое кто что как где куда когда какой чей северо юго восточно западно \
    вице штаб унтер обер лейб";

/// Right pieces that are standalone particles.
const KEEP_RIGHT: &str = "то либо нибудь таки";

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

fn in_list(list: &str, word: &str) -> bool {
    list.split_whitespace().any(|w| w == word)
}

/// Endings of the "по-…" adverbs: по-русски, по-моему, по-другому.
const PO_ENDINGS: &[&str] = &["ски", "ому", "ему"];

fn is_acronym(word: &str) -> bool {
    word.chars().count() >= 2 && word.chars().all(char::is_uppercase)
}

fn keep_hyphen(left: &str, right: &str) -> bool {
    let left_word = last_word(left);
    let l = left_word.to_lowercase();
    let r = first_word(right).to_lowercase();
    is_acronym(left_word)
        || (l == "по" && PO_ENDINGS.iter().any(|e| r.ends_with(e)))
        || in_list(KEEP_LEFT, &l)
        || in_list(KEEP_RIGHT, &r)
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

/// Remove a space-separated wrap ("boshqa- rish" -> "boshqarish") in one line.
fn join_inline_wraps(line: &str) -> String {
    let chars: Vec<(usize, char)> = line.char_indices().collect();
    let mut out = String::with_capacity(line.len());
    let mut copied = 0;
    for (k, &(i, c)) in chars.iter().enumerate() {
        if c != '-' || i < copied {
            continue;
        }
        let space_then_lower = chars.get(k + 1).is_some_and(|&(_, s)| s == ' ')
            && chars.get(k + 2).is_some_and(|&(_, l)| l.is_lowercase());
        if !space_then_lower {
            continue;
        }
        let left = last_word(&line[..i]);
        let right_start = chars[k + 2].0;
        let right = first_word(&line[right_start..]);
        let initials =
            right.chars().count() == 1 && line[right_start + right.len()..].starts_with('.');
        let plain_word =
            left.chars().count() >= 2 && left.chars().all(|c| is_word_char(c) && !c.is_uppercase());
        if plain_word && !initials && !keep_hyphen(&line[..i], right) {
            out.push_str(&line[copied..i]);
            copied = right_start;
        }
    }
    out.push_str(&line[copied..]);
    out
}

/// Repair `-\n` line wraps and inline "word- word" wraps. Other text is returned unchanged.
pub fn repair_hyphenation(text: &str) -> String {
    join_line_wraps(text)
        .split('\n')
        .map(join_inline_wraps)
        .collect::<Vec<_>>()
        .join("\n")
}

fn join_line_wraps(text: &str) -> String {
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
    fn keeps_po_adverbs_and_acronym_suffixes() {
        assert_eq!(repair_hyphenation("по-\nрусски"), "по-\nрусски");
        assert_eq!(repair_hyphenation("по-\nмоему"), "по-\nмоему");
        assert_eq!(repair_hyphenation("BMT-\nning qarori"), "BMT-\nning qarori");
    }

    #[test]
    fn leaves_dashes_and_numbers() {
        assert_eq!(repair_hyphenation("a - b\nc"), "a - b\nc");
        assert_eq!(repair_hyphenation("пункт 1-\n2"), "пункт 1-\n2");
        assert_eq!(repair_hyphenation("конец-\n"), "конец-\n");
    }

    #[test]
    fn joins_inline_wraps() {
        assert_eq!(
            repair_hyphenation("boshqa- rish metodo- logiyasi"),
            "boshqarish metodologiyasi"
        );
        assert_eq!(
            repair_hyphenation("da- rajasini miq- dorini"),
            "darajasini miqdorini"
        );
        assert_eq!(repair_hyphenation("bogʻliq- liklarni"), "bogʻliqliklarni");
    }

    #[test]
    fn joins_inline_wraps_before_a_full_stop() {
        assert_eq!(
            repair_hyphenation("komission operatsi- yalar. Pul"),
            "komission operatsiyalar. Pul"
        );
        assert_eq!(
            repair_hyphenation("gʻarbona tiqish- tirish."),
            "gʻarbona tiqishtirish."
        );
        assert_eq!(
            repair_hyphenation("H.Otamurodov- i.f.n., dotsent"),
            "H.Otamurodov- i.f.n., dotsent"
        );
    }

    #[test]
    fn keeps_real_hyphens_and_dashes() {
        for text in [
            "1978- yillarda",
            "nashriyot-matbaa",
            "Otamurodov- i.f.n., dotsent",
            "Toshkent - 2021 yil",
            "pul – tovar",
            "кто- то",
            "BMT- ning",
        ] {
            assert_eq!(repair_hyphenation(text), text, "{text}");
        }
    }

    #[test]
    fn chained_wraps() {
        assert_eq!(
            repair_hyphenation("орга-\nниза-\nция труда"),
            "организация труда"
        );
    }
}
