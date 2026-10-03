//! Language/script detection for Russian and Uzbek (Latin + Cyrillic).
//!
//! Evidence per script combines a character n-gram model (`langid`) with marker words:
//! script-specific letters (strong), stop words and endings (weak). Sentences are also judged
//! one by one, so a text is "mixed" only when whole sentences are in another language, never
//! because of single loanwords.

use std::collections::HashSet;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::OnceLock;

use crate::chars::is_apostrophe;
use crate::langid::{Scores, OTHER_LATN, RU, UZ_CYRL, UZ_LATN};

pub struct Detection {
    pub language: &'static str,
    pub script: &'static str,
    pub confidence: f64,
}

#[derive(Clone, Copy, PartialEq)]
enum Vote {
    Ru,
    Uz,
    Neutral,
}

const RU_WORDS: &str = "и в не на что это как по для от из или при если который также может быть \
    настоящий договор стороны статья после все его они без под над между является должен должны \
    которые которых которая только уже так где когда чем был была были этот эти этого";

/// Uzbek stop words, Cyrillic and Latin (Latin forms are stored without apostrophes).
const UZ_WORDS: &str = "ва учун билан бу ёки ҳамда бўйича эса бўлган керак мумкин лозим тартиби \
    қоидалар ушбу каби ҳақида томонидан мазкур агар кейин шунингдек янги шу бир энг \
    va uchun bilan bu yoki hamda boyicha esa bolgan kerak mumkin lozim tartibi qoidalar ushbu \
    kabi haqida tomonidan umumiy xizmat respublikasi";

/// Word endings that mark Uzbek Latin text (checked on words of at least `MIN_SUFFIX_WORD`).
const UZ_SUFFIXES: &[&str] = &[
    "dagi", "ligi", "lik", "lari", "larni", "larga", "lardan", "larning",
];
/// The same for Uzbek Cyrillic.
const UZ_CYRILLIC_SUFFIXES: &[&str] = &[
    "даги",
    "лиги",
    "лари",
    "ларни",
    "ларга",
    "лардан",
    "ларда",
    "сида",
    "ланган",
    "лган",
    "нган",
];
/// Uzbek genitive, counted after a stem of `MIN_GENITIVE_STEM` letters: Russian words with
/// this ending have short stems (тренинг, скрининг, клининг).
const UZ_GENITIVE: &str = "нинг";
const MIN_GENITIVE_STEM: usize = 5;
/// Russian grammatical endings that Uzbek words, loanwords included, do not take.
const RU_SUFFIXES: &[&str] = &["ться", "тся", "ого", "ому", "ость", "ости", "ению", "ением"];
const MIN_SUFFIX_WORD: usize = 6;

/// The model's summed log-likelihood ratio is scaled down because the overlapping n-grams of
/// a word are not independent; marker words add fixed evidence.
const MODEL_WEIGHT: f64 = 0.1;
const STRONG_VOTE: f64 = 4.0;
const WEAK_VOTE: f64 = 1.5;
/// Sentences of at least this many words, with at least `SEGMENT_EVIDENCE`, are checked for
/// a second language; it makes the text "mixed" from `MIXED_SHARE` of those words.
const MIN_SEGMENT_WORDS: usize = 4;
const SEGMENT_EVIDENCE: f64 = 3.0;
const MIXED_SHARE: f64 = 0.2;
const MAX_ABBREVIATION: usize = 3;
/// The model reads at most this many words per script and sentence; its evidence is settled
/// long before, while marker words are counted throughout.
const MAX_MODEL_WORDS: usize = 40;
const SEGMENT_END: &[char] = &['.', '!', '?', '…', '\n'];

/// A Latin word that looks Uzbek: "q" not followed by "u" (qoida, huquq) or a typical ending.
fn has_uzbek_shape(word: &str) -> bool {
    let has_lone_q = word
        .match_indices('q')
        .any(|(i, _)| !word[i + 1..].starts_with('u'));
    has_lone_q || (word.len() >= MIN_SUFFIX_WORD && UZ_SUFFIXES.iter().any(|s| word.ends_with(s)))
}

/// Vote of a Cyrillic word without script-specific letters, from its ending.
fn cyrillic_ending_vote(word: &str) -> Vote {
    if word.chars().count() < MIN_SUFFIX_WORD {
        return Vote::Neutral;
    }
    let genitive = word
        .strip_suffix(UZ_GENITIVE)
        .is_some_and(|stem| stem.chars().count() >= MIN_GENITIVE_STEM);
    if genitive || UZ_CYRILLIC_SUFFIXES.iter().any(|s| word.ends_with(s)) {
        Vote::Uz
    } else if RU_SUFFIXES.iter().any(|s| word.ends_with(s)) {
        Vote::Ru
    } else {
        Vote::Neutral
    }
}

/// Longest stop word in bytes; longer words skip the lookup entirely.
const MAX_STOP_WORD_BYTES: usize = 24;

/// FNV-1a: much cheaper than SipHash for the short words looked up here.
#[derive(Default)]
struct Fnv(u64);

impl Hasher for Fnv {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, bytes: &[u8]) {
        let mut hash = if self.0 == 0 {
            0xcbf2_9ce4_8422_2325
        } else {
            self.0
        };
        for &b in bytes {
            hash = (hash ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3);
        }
        self.0 = hash;
    }
}

type WordSet = HashSet<&'static str, BuildHasherDefault<Fnv>>;

fn word_set(words: &'static str) -> WordSet {
    words.split_whitespace().collect()
}

fn ru_words() -> &'static WordSet {
    static SET: OnceLock<WordSet> = OnceLock::new();
    SET.get_or_init(|| word_set(RU_WORDS))
}

fn uz_words() -> &'static WordSet {
    static SET: OnceLock<WordSet> = OnceLock::new();
    SET.get_or_init(|| word_set(UZ_WORDS))
}

fn is_stop_word(set: &WordSet, word: &str) -> bool {
    word.len() <= MAX_STOP_WORD_BYTES && set.contains(word)
}

fn is_cyrillic(c: char) -> bool {
    ('\u{0400}'..='\u{04FF}').contains(&c)
}

/// `char::is_alphabetic` with a direct answer for ASCII and the Cyrillic block.
fn is_letter(c: char) -> bool {
    match c {
        'a'..='z' | 'A'..='Z' => true,
        '\u{0482}'..='\u{0489}' => false,
        '\u{0400}'..='\u{04FF}' => true,
        _ if c.is_ascii() => false,
        _ => c.is_alphabetic(),
    }
}

fn is_word_char(c: char) -> bool {
    is_letter(c) || is_apostrophe(c)
}

/// Lowercase of one char; arithmetic for the common Cyrillic ranges, `std` for the rest.
fn lowercase(c: char) -> char {
    let code = c as u32;
    let shift = match code {
        0x0410..=0x042F => 0x20,
        0x0400..=0x040F => 0x50,
        0x0460..=0x0481 | 0x048A..=0x04BF | 0x04D0..=0x04FF if code.is_multiple_of(2) => 1,
        _ => return c.to_lowercase().next().unwrap_or(c),
    };
    char::from_u32(code + shift).unwrap_or(c)
}

/// Classify one word; also reports whether the vote comes from a script-specific letter or
/// spelling. `bare` receives the lowercase word without apostrophes, `feature` the lowercase
/// word with apostrophes written as `'` (the language model's input).
fn classify(word: &str, bare: &mut String, feature: &mut String) -> (Vote, bool) {
    bare.clear();
    feature.clear();
    let (mut cyrillic, mut latin, mut uz_digraph) = (false, false, false);
    let (mut uz_letter, mut ru_letter, mut prev_og) = (false, false, false);
    for c in word.chars() {
        if is_apostrophe(c) {
            uz_digraph |= prev_og;
            prev_og = false;
            if !feature.is_empty() {
                feature.push('\'');
            }
            continue;
        }
        let lower = lowercase(c);
        bare.push(lower);
        feature.push(lower);
        match lower {
            'ў' | 'қ' | 'ғ' | 'ҳ' => uz_letter = true,
            // "ё" and "э" are common in Uzbek Cyrillic too (сиёсат, экзоген).
            'ы' | 'щ' => ru_letter = true,
            _ => {}
        }
        cyrillic |= is_cyrillic(lower);
        latin |= lower.is_ascii_alphabetic();
        prev_og = matches!(lower, 'o' | 'g');
    }
    if uz_letter {
        return (Vote::Uz, true);
    }
    if ru_letter {
        return (Vote::Ru, true);
    }
    if cyrillic {
        if is_stop_word(ru_words(), bare) {
            return (Vote::Ru, false);
        }
        if is_stop_word(uz_words(), bare) {
            return (Vote::Uz, false);
        }
        if !latin {
            return (cyrillic_ending_vote(bare), false);
        }
    } else if latin {
        if uz_digraph {
            return (Vote::Uz, true);
        }
        if is_stop_word(uz_words(), bare) || has_uzbek_shape(bare) {
            return (Vote::Uz, false);
        }
    }
    (Vote::Neutral, false)
}

/// Reusable per-call buffers.
#[derive(Default)]
struct Buffers {
    bare: String,
    feature: String,
    chars: Vec<char>,
}

/// Evidence for Uzbek (positive) against Russian (Cyrillic) or another language (Latin).
#[derive(Clone, Copy, Default)]
struct Evidence {
    cyrillic: Scores,
    latin: Scores,
    cyrillic_votes: f64,
    latin_votes: f64,
    cyrillic_words: usize,
    latin_words: usize,
}

impl Evidence {
    fn add_word(&mut self, word: &str, buffers: &mut Buffers) {
        let Buffers {
            bare,
            feature,
            chars,
        } = buffers;
        let (vote, strong) = classify(word, bare, feature);
        if !strong && !carries_language(word, bare) {
            return;
        }
        let weight = if strong { STRONG_VOTE } else { WEAK_VOTE };
        let vote = match vote {
            Vote::Uz => weight,
            Vote::Ru => -weight,
            Vote::Neutral => 0.0,
        };
        let has_cyrillic = feature.chars().any(is_cyrillic);
        let has_latin = feature.chars().any(|c| c.is_ascii_alphabetic());
        if has_cyrillic && !has_latin {
            if self.cyrillic_words < MAX_MODEL_WORDS {
                self.cyrillic.add_word(feature, [UZ_CYRL, RU], chars);
            }
            self.cyrillic_votes += vote;
            self.cyrillic_words += 1;
        } else if has_latin && !has_cyrillic {
            if self.latin_words < MAX_MODEL_WORDS {
                self.latin.add_word(feature, [UZ_LATN, OTHER_LATN], chars);
            }
            self.latin_votes += vote.max(0.0);
            self.latin_words += 1;
        }
    }

    fn add(&mut self, other: &Evidence) {
        self.cyrillic.add(&other.cyrillic);
        self.latin.add(&other.latin);
        self.cyrillic_votes += other.cyrillic_votes;
        self.latin_votes += other.latin_votes;
        self.cyrillic_words += other.cyrillic_words;
        self.latin_words += other.latin_words;
    }

    fn words(&self) -> usize {
        self.cyrillic_words + self.latin_words
    }

    fn cyrillic_score(&self) -> f64 {
        MODEL_WEIGHT * self.cyrillic.ratio(UZ_CYRL, RU) + self.cyrillic_votes
    }

    fn latin_score(&self) -> f64 {
        MODEL_WEIGHT * self.latin.ratio(UZ_LATN, OTHER_LATN) + self.latin_votes
    }

    /// Language of the Cyrillic words and its evidence, if there are any.
    fn cyrillic_language(&self) -> Option<(&'static str, f64)> {
        (self.cyrillic_words > 0).then(|| {
            let score = self.cyrillic_score();
            (if score > 0.0 { "uz" } else { "ru" }, score.abs())
        })
    }

    /// Uzbek if the Latin words are Uzbek; `None` for other Latin-script languages.
    fn latin_language(&self) -> Option<(&'static str, f64)> {
        let score = self.latin_score();
        (self.latin_words > 0 && score > 0.0).then_some(("uz", score))
    }

    /// Language of the script most of the words are written in.
    fn dominant_language(&self) -> Option<(&'static str, f64)> {
        if self.cyrillic_words >= self.latin_words {
            self.cyrillic_language()
        } else {
            self.latin_language()
        }
    }
}

/// Single letters and short capital abbreviations ("x", "KM", "ЯИМ") are variables, units
/// or acronyms, not words of a language.
fn carries_language(word: &str, bare: &str) -> bool {
    let letters = bare.chars().count();
    let abbreviation = letters <= MAX_ABBREVIATION && !word.chars().any(char::is_lowercase);
    letters >= 2 && !abbreviation
}

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}

fn script_of(text: &str) -> Option<&'static str> {
    let (mut cyrillic, mut latin) = (0usize, 0usize);
    for c in text.chars() {
        if is_cyrillic(c) {
            cyrillic += 1;
        } else if c.is_ascii_alphabetic() {
            latin += 1;
        }
    }
    let total = cyrillic + latin;
    if total == 0 {
        return None;
    }
    let share = cyrillic as f64 / total as f64;
    Some(if share >= 0.9 {
        "cyrillic"
    } else if share <= 0.1 {
        "latin"
    } else {
        "mixed"
    })
}

pub fn detect(text: &str) -> Detection {
    let Some(script) = script_of(text) else {
        return Detection {
            language: "unknown",
            script: "none",
            confidence: 0.0,
        };
    };

    let mut segments: Vec<Evidence> = Vec::new();
    let mut segment = Evidence::default();
    let mut buffers = Buffers::default();
    let mut start: Option<usize> = None;
    for (i, c) in text.char_indices().chain([(text.len(), ' ')]) {
        if i < text.len() && is_word_char(c) {
            start.get_or_insert(i);
            continue;
        }
        if let Some(begin) = start.take() {
            segment.add_word(&text[begin..i], &mut buffers);
        }
        if SEGMENT_END.contains(&c) && segment.words() > 0 {
            segments.push(std::mem::take(&mut segment));
        }
    }
    if segment.words() > 0 {
        segments.push(segment);
    }
    let mut total = Evidence::default();
    for part in &segments {
        total.add(part);
    }

    let found = match (total.cyrillic_language(), total.latin_language()) {
        (Some(cyrillic), None) => Some(cyrillic),
        (None, Some(latin)) => Some(latin),
        (Some(cyrillic), Some(latin)) if script == "mixed" && cyrillic.0 != latin.0 => {
            let words = total.words() as f64;
            let share = total.cyrillic_words as f64 / words;
            return Detection {
                language: "mixed",
                script,
                confidence: 1.0 - (2.0 * share - 1.0).abs(),
            };
        }
        (Some(cyrillic), Some(latin)) => Some(if cyrillic.1 >= latin.1 {
            cyrillic
        } else {
            latin
        }),
        (None, None) => None,
    };
    let Some((language, score)) = found else {
        return Detection {
            language: "unknown",
            script,
            confidence: 0.0,
        };
    };
    if let Some(confidence) = mixed_sentences(&segments) {
        return Detection {
            language: "mixed",
            script,
            confidence,
        };
    }
    Detection {
        language,
        script,
        confidence: sigmoid(score),
    }
}

/// Confidence of "mixed" when clear sentences in both languages each hold `MIXED_SHARE` of
/// the clearly classified words.
fn mixed_sentences(segments: &[Evidence]) -> Option<f64> {
    let (mut uz, mut ru) = (0usize, 0usize);
    for segment in segments {
        if segment.words() < MIN_SEGMENT_WORDS {
            continue;
        }
        match segment.dominant_language() {
            Some(("uz", score)) if score >= SEGMENT_EVIDENCE => uz += segment.words(),
            Some(("ru", score)) if score >= SEGMENT_EVIDENCE => ru += segment.words(),
            _ => {}
        }
    }
    let total = (uz + ru) as f64;
    let (uz_share, ru_share) = (uz as f64 / total, ru as f64 / total);
    (uz > 0 && ru > 0 && uz_share.min(ru_share) >= MIXED_SHARE)
        .then(|| 1.0 - (uz_share - ru_share).abs())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn labels(text: &str) -> (&'static str, &'static str) {
        let d = detect(text);
        (d.language, d.script)
    }

    #[test]
    fn russian() {
        assert_eq!(
            labels("Настоящий договор является основанием для оказания услуг."),
            ("ru", "cyrillic")
        );
    }

    #[test]
    fn uzbek_latin() {
        assert_eq!(
            labels("Ushbu qoidalar xizmat ko'rsatish tartibi va ma'lumot uchun."),
            ("uz", "latin")
        );
    }

    #[test]
    fn uzbek_cyrillic() {
        assert_eq!(
            labels("Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик ва маълумот."),
            ("uz", "cyrillic")
        );
    }

    #[test]
    fn mixed_and_unknown() {
        assert_eq!(
            labels(
                "Настоящий договор является основанием. Ushbu qoidalar xizmat tartibi va bilan."
            )
            .0,
            "mixed"
        );
        assert_eq!(labels("12345 ---"), ("unknown", "none"));
    }

    #[test]
    fn apostrophe_variants_mark_uzbek_latin() {
        for apostrophe in ["'", "’", "ʻ", "ʼ", "`"] {
            assert_eq!(
                labels(&format!("o{apostrophe}zbek g{apostrophe}or")).0,
                "uz"
            );
        }
    }

    #[test]
    fn fast_paths_match_std_over_the_cyrillic_block() {
        for code in 0x0400..=0x04FF {
            let c = char::from_u32(code).unwrap();
            assert_eq!(is_letter(c), c.is_alphabetic(), "is_letter U+{code:04X}");
            assert_eq!(
                lowercase(c),
                c.to_lowercase().next().unwrap(),
                "lowercase U+{code:04X}"
            );
        }
    }

    #[test]
    fn short_uzbek_latin_phrases_are_recognized() {
        for text in [
            "mehnat sohasidagi ijtimoiy sheriklik;",
            "Oldingi tahrirga qarang.",
            "huquqlar",
            "Elektron tijorat operatorlari jumlasiga quyidagilar kiradi:",
        ] {
            assert_eq!(labels(text), ("uz", "latin"), "{text}");
        }
        assert_eq!(labels("Quality quote request").0, "unknown");
    }

    #[test]
    fn english_text_is_not_labeled_uzbek() {
        let english = "Circular imports and meaning reasoning about modules. \
            Python uses reference counting for memory management, which is not thread-safe. \
            Threads share memory and are lightweight, but are limited by the interpreter lock.";
        assert_eq!(labels(english), ("unknown", "latin"));
    }

    #[test]
    fn uzbek_cyrillic_with_yo_and_e_is_not_mixed() {
        for text in [
            "Энди, чайқовчилик хужуми фақат натижасида олтин валюта резервлари экзоген шоклардагина содир бўлади.",
            "8-мавзу. Монетар сиёсатда қўлланиладиган математик моделлар",
            "Иқтисодиётнинг бошланғич мувозанат ҳолати",
            "Моделнинг назарий асослари:",
            "Олтин валюта резервлари динамикаси.",
            "Марказий банк олтин валюта резервларининг камайиш сабабларининг",
        ] {
            assert_eq!(labels(text), ("uz", "cyrillic"), "{text}");
        }
    }

    #[test]
    fn russian_with_yo_and_e_stays_russian() {
        for text in [
            "Это решение утверждено советом, и оно вступает в силу после опубликования.",
            "Ещё одна проверка: ученики пишут объяснения к этой задаче.",
            "Доктрина информационной безопасности Российской Федерации",
            "Проведение тренинга и скрининга для сотрудников компании",
            "Тренинг и скрининг для сотрудников",
        ] {
            assert_eq!(labels(text), ("ru", "cyrillic"), "{text}");
        }
    }

    #[test]
    fn plain_cyrillic_names_are_russian_with_less_confidence_than_sentences() {
        let names = detect("Москва Петербург");
        let sentence = detect("Настоящий договор является основанием для оказания услуг.");
        assert_eq!((names.language, sentence.language), ("ru", "ru"));
        assert!(names.confidence < sentence.confidence);
    }

    #[test]
    fn short_uzbek_cyrillic_without_uzbek_letters() {
        for text in [
            "Пул таклифи:",
            "Олтин валюта резервлари динамикаси.",
            "Хорижий валютани яшириш курси.",
            "кетмайди.",
        ] {
            assert_eq!(labels(text), ("uz", "cyrillic"), "{text}");
        }
    }

    #[test]
    fn russian_lines_stay_russian() {
        for text in [
            "Рецензенты:",
            "Статья 5. Права и обязанности сторон",
            "Москва, Кремль",
            "Правительство Российской Федерации приняло постановление.",
        ] {
            assert_eq!(labels(text), ("ru", "cyrillic"), "{text}");
        }
    }

    #[test]
    fn russian_loanwords_do_not_make_uzbek_mixed() {
        let text = "Компьютер технологиялари ва интернет тармоғи ривожланмоқда. Инфляция, \
            девальвация ва конституция каби атамалар иқтисодиёт дарсликларида учрайди.";
        assert_eq!(labels(text), ("uz", "cyrillic"));
    }

    #[test]
    fn whole_sentences_in_both_languages_are_mixed() {
        let text = "Вазирлар Маҳкамаси қарор қабул қилди. Правительство Российской Федерации \
            приняло постановление о налогах и сборах.";
        assert_eq!(labels(text).0, "mixed");
    }

    #[test]
    fn numbers_only_have_no_language() {
        for text in ["12345", "2021 — 2025", "(1.2.3)"] {
            assert_eq!(labels(text), ("unknown", "none"), "{text}");
        }
        for text in ["x", "KM", "(В.3)", "ЯИМ"] {
            assert_eq!(labels(text).0, "unknown", "{text}");
        }
    }
}
