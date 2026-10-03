//! Uzbek Cyrillic to Latin, lowercase, with one apostrophe (`'`) for both ʻ and ʼ.
//!
//! Context rules follow the official alphabet: "е" is "ye" at a word start and after a vowel,
//! "ъ" or "ь"; "ц" is "ts" after a vowel and "s" elsewhere; "ь" is dropped.

fn is_vowel(c: char) -> bool {
    "аеёиоуўэюяы".contains(c)
}

/// Transliterate one lowercase-able Cyrillic word or text; other characters are kept.
pub fn cyrillic_to_latin(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + text.len() / 4);
    let mut previous: Option<char> = None;
    for c in text.chars() {
        let lower = c.to_lowercase().next().unwrap_or(c);
        let at_start = previous.is_none_or(|p| !p.is_alphabetic());
        let after_vowel = previous.is_some_and(|p| is_vowel(p) || p == 'ъ' || p == 'ь');
        let mapped: &str = match lower {
            'а' => "a",
            'б' => "b",
            'в' => "v",
            'г' => "g",
            'ғ' => "g'",
            'д' => "d",
            'е' if at_start || after_vowel => "ye",
            'е' | 'э' => "e",
            'ё' => "yo",
            'ж' => "j",
            'з' => "z",
            'и' | 'ы' => "i",
            'й' => "y",
            'к' => "k",
            'қ' => "q",
            'л' => "l",
            'м' => "m",
            'н' => "n",
            'о' => "o",
            'п' => "p",
            'р' => "r",
            'с' => "s",
            'т' => "t",
            'у' => "u",
            'ў' => "o'",
            'ф' => "f",
            'х' => "x",
            'ҳ' => "h",
            'ц' if !at_start && previous.is_some_and(is_vowel) => "ts",
            'ц' => "s",
            'ч' => "ch",
            'ш' | 'щ' => "sh",
            'ъ' => "'",
            'ь' => "",
            'ю' => "yu",
            'я' => "ya",
            _ => {
                out.extend(c.to_lowercase());
                previous = Some(lower);
                continue;
            }
        };
        out.push_str(mapped);
        previous = Some(lower);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn letters_and_context_rules() {
        for (cyrillic, latin) in [
            ("Ўзбекистон", "o'zbekiston"),
            ("ғалаба", "g'alaba"),
            ("қишлоқ хўжалиги", "qishloq xo'jaligi"),
            ("шаҳар", "shahar"),
            ("ер", "yer"),
            ("поезд", "poyezd"),
            ("кетди", "ketdi"),
            ("цирк", "sirk"),
            ("конституция", "konstitutsiya"),
            ("Франция", "fransiya"),
            ("съезд", "s'yezd"),
            ("компьютер", "kompyuter"),
            ("маълумот", "ma'lumot"),
            ("ёшлар", "yoshlar"),
            ("эълон", "e'lon"),
            ("2021 йил", "2021 yil"),
        ] {
            assert_eq!(cyrillic_to_latin(cyrillic), latin, "{cyrillic}");
        }
    }
}
