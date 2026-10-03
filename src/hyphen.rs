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
//! Otherwise the word list decides: a real joined word is joined; two real words that do not
//! form one are a compound and keep the hyphen ("pul-kredit"). Anything else is joined. The
//! next line must start with a lowercase letter, so "Москва-\nГород" and "пункт 1-\n2" are
//! never touched.
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

use std::collections::HashSet;

use crate::lexicon::is_known;

/// "audio- yoki video-": a hyphen before a conjunction stands for a shared word part and is
/// left as written.
const CONJUNCTIONS: &str = "va yoki hamda yohud ва ёки ҳамда ёхуд и или либо да";

fn before_conjunction(right: &str) -> bool {
    in_list(CONJUNCTIONS, &first_word(right).to_lowercase())
}

/// Each half of a compound found through the word list has at least this many letters.
const MIN_COMPOUND_PART: usize = 3;

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

/// A real compound: fixed lists, acronym suffixes ("BMT-ning"), or a hyphenated form that
/// the same document also uses unbroken ("pul-kredit" in `keep`).
fn keep_hyphen(left: &str, right: &str, keep: &HashSet<String>) -> bool {
    let left_word = last_word(left);
    let l = left_word.to_lowercase();
    let r = first_word(right).to_lowercase();
    is_acronym(left_word)
        || (l == "по" && PO_ENDINGS.iter().any(|e| r.ends_with(e)))
        || in_list(KEEP_LEFT, &l)
        || in_list(KEEP_RIGHT, &r)
        || KEEP_PAIRS.contains(&(l.as_str(), r.as_str()))
        || (!keep.is_empty() && keep.contains(&format!("{l}-{r}")))
}

/// Two known words that are not one known word together: a compound broken at its hyphen.
fn known_compound(left: &str, right: &str) -> bool {
    let (left, right) = (last_word(left), first_word(right));
    let long_enough = |w: &str| w.chars().count() >= MIN_COMPOUND_PART;
    long_enough(left)
        && long_enough(right)
        && !is_known(&format!("{left}{right}"))
        && is_known(left)
        && is_known(right)
}

/// "i.f.n.", "A.": a single letter followed by a dot right after the hyphen.
fn starts_with_initial(right: &str) -> bool {
    let word = first_word(right);
    word.chars().count() == 1 && right[word.len()..].starts_with('.')
}

#[derive(PartialEq)]
enum Wrap {
    /// Not a wrapped word: leave the text as it is.
    Leave,
    /// A word broken by the line end: drop the hyphen.
    Join,
    /// A real compound broken at its hyphen: keep the hyphen, drop the break.
    JoinKeepingHyphen,
}

/// How to treat `line` ending in `letter-` followed by `next`.
fn line_wrap(line: &str, next: &str, keep: &HashSet<String>) -> Wrap {
    let mut rev = line.chars().rev();
    if rev.next() != Some('-') || !rev.next().is_some_and(char::is_alphabetic) {
        return Wrap::Leave;
    }
    if !next.chars().next().is_some_and(char::is_lowercase)
        || starts_with_initial(next)
        || before_conjunction(next)
    {
        return Wrap::Leave;
    }
    let left = &line[..line.len() - 1];
    if keep_hyphen(left, next, keep) || known_compound(left, next) {
        Wrap::JoinKeepingHyphen
    } else {
        Wrap::Join
    }
}

/// Repair a wrap that kept its space inside one line ("boshqa- rish" -> "boshqarish",
/// "pul- kredit" -> "pul-kredit" when the document uses "pul-kredit").
fn join_inline_wraps(line: &str, keep: &HashSet<String>) -> String {
    let chars: Vec<(usize, char)> = line.char_indices().collect();
    let mut out = String::with_capacity(line.len());
    let mut copied = 0;
    for (k, &(i, c)) in chars.iter().enumerate() {
        if c != '-' || i < copied {
            continue;
        }
        let letter_before = k > 0 && chars[k - 1].1.is_alphabetic();
        let space_then_lower = chars.get(k + 1).is_some_and(|&(_, s)| s == ' ')
            && chars.get(k + 2).is_some_and(|&(_, l)| l.is_lowercase());
        if !letter_before || !space_then_lower {
            continue;
        }
        let right_start = chars[k + 2].0;
        if starts_with_initial(&line[right_start..]) || before_conjunction(&line[right_start..]) {
            continue;
        }
        let left = last_word(&line[..i]);
        let plain_word =
            left.chars().count() >= 2 && left.chars().all(|c| is_word_char(c) && !c.is_uppercase());
        let (before, after) = (&line[..i], &line[right_start..]);
        if keep_hyphen(before, after, keep) || known_compound(before, after) {
            out.push_str(&line[copied..=i]);
            copied = right_start;
        } else if plain_word {
            out.push_str(&line[copied..i]);
            copied = right_start;
        }
    }
    out.push_str(&line[copied..]);
    out
}

/// Repair `-\n` line wraps and inline "word- word" wraps. Other text is returned unchanged.
pub fn repair_hyphenation(text: &str) -> String {
    repair_with(text, &HashSet::new())
}

/// [`repair_hyphenation`] that also keeps hyphens of compounds listed in `keep`
/// (lowercase "left-right" pairs collected from the same document).
pub fn repair_with(text: &str, keep: &HashSet<String>) -> String {
    join_line_wraps(text, keep)
        .split('\n')
        .map(|line| join_inline_wraps(line, keep))
        .collect::<Vec<_>>()
        .join("\n")
}

fn join_line_wraps(text: &str, keep: &HashSet<String>) -> String {
    let mut out = String::with_capacity(text.len());
    let mut lines = text.split('\n').peekable();
    while let Some(first) = lines.next() {
        let mut current = first.to_string();
        // Keep gluing while the current line ends with a wrapped hyphen ("орга-\nниза-\nция").
        while let Some(&next) = lines.peek() {
            let trimmed = current.trim_end();
            let next_trimmed = next.trim_start();
            let cut = match line_wrap(trimmed, next_trimmed, keep) {
                Wrap::Leave => break,
                Wrap::Join => trimmed.len() - 1,
                Wrap::JoinKeepingHyphen => trimmed.len(),
            };
            let mut merged = trimmed[..cut].to_string();
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
        assert_eq!(repair_hyphenation("кто-\nто пришёл"), "кто-то пришёл");
        assert_eq!(repair_hyphenation("из-\nза стола"), "из-за стола");
        assert_eq!(repair_hyphenation("северо-\nзападный"), "северо-западный");
        assert_eq!(repair_hyphenation("во-\nпервых"), "во-первых");
        assert_eq!(repair_hyphenation("Москва-\nГород"), "Москва-\nГород");
    }

    #[test]
    fn keeps_po_adverbs_and_acronym_suffixes() {
        assert_eq!(repair_hyphenation("по-\nрусски"), "по-русски");
        assert_eq!(repair_hyphenation("по-\nмоему"), "по-моему");
        assert_eq!(repair_hyphenation("BMT-\nning qarori"), "BMT-ning qarori");
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
        ] {
            assert_eq!(repair_hyphenation(text), text, "{text}");
        }
    }

    #[test]
    fn kept_compounds_lose_only_the_break() {
        assert_eq!(repair_hyphenation("кто- то"), "кто-то");
        assert_eq!(repair_hyphenation("BMT- ning"), "BMT-ning");
    }

    #[test]
    fn document_compounds_keep_their_hyphen() {
        let keep: HashSet<String> = ["pul-kredit", "oltin-valyuta", "qoʻllab-quvvatlash"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        assert_eq!(
            repair_with("pul-\nkredit siyosati", &keep),
            "pul-kredit siyosati"
        );
        assert_eq!(
            repair_with("Pul- kredit va oltin- valyuta", &keep),
            "Pul-kredit va oltin-valyuta"
        );
        assert_eq!(
            repair_with("qoʻllab-\nquvvatlash", &keep),
            "qoʻllab-quvvatlash"
        );
        assert_eq!(repair_with("boshqa-\nrish", &keep), "boshqarish");
    }

    #[test]
    fn word_list_tells_compounds_from_wrapped_words() {
        for (text, expected) in [
            ("pul-\nkredit siyosati", "pul-kredit siyosati"),
            ("ilmiy- texnik taraqqiyot", "ilmiy-texnik taraqqiyot"),
            ("boshqa-\nrish", "boshqarish"),
            ("iqtisod- chilar", "iqtisodchilar"),
            ("Настоя-\nщим документом", "Настоящим документом"),
            ("деятель-\nности банка", "деятельности банка"),
            ("audio- yoki videoyozuvi", "audio- yoki videoyozuvi"),
            ("аудио- и видеозаписи", "аудио- и видеозаписи"),
            ("ички- ва ташқи", "ички- ва ташқи"),
        ] {
            assert_eq!(repair_hyphenation(text), expected, "{text}");
        }
    }

    #[test]
    fn initials_numbers_and_dashes_are_left_alone() {
        for text in [
            "Otamurodov-\ni.f.n., dotsent",
            "1978-\nyillarda",
            "pul –\nkredit",
            "A.Karimov —\nmuallif",
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
