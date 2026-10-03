//! Character n-gram language model: Uzbek Latin, Uzbek Cyrillic, Russian, other Latin.
//!
//! The table is trained offline by `tools/train_langid.py` and embedded at build time (data
//! licensed CC BY-SA 4.0, see src/data/LICENSE). Each entry maps the FNV-1a hash of an n-gram
//! (1 to 4 characters of a space-padded, lowercase word) to quantized log-probabilities per
//! class; unseen n-grams use a per-class floor.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::OnceLock;

pub const UZ_LATN: usize = 0;
pub const UZ_CYRL: usize = 1;
pub const RU: usize = 2;
pub const OTHER_LATN: usize = 3;
const CLASSES: usize = 4;
const MAX_ORDER: usize = 4;
const QUANT: f32 = 1000.0;
const MAGIC: &[u8] = b"UZLID1";

static DATA: &[u8] = include_bytes!("data/langid.bin");

/// The table keys are hashes already.
#[derive(Default)]
struct KeyHasher(u64);

impl Hasher for KeyHasher {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, _: &[u8]) {
        unreachable!("only u32 keys are hashed")
    }

    fn write_u32(&mut self, value: u32) {
        self.0 = u64::from(value);
    }
}

struct Model {
    floor: [[f32; MAX_ORDER]; CLASSES],
    table: HashMap<u32, [i16; CLASSES], BuildHasherDefault<KeyHasher>>,
}

fn read<const N: usize>(data: &[u8], at: &mut usize) -> [u8; N] {
    let bytes: [u8; N] = data[*at..*at + N]
        .try_into()
        .expect("model table is truncated");
    *at += N;
    bytes
}

fn model() -> &'static Model {
    static MODEL: OnceLock<Model> = OnceLock::new();
    MODEL.get_or_init(|| {
        assert!(DATA.starts_with(MAGIC), "unknown language model format");
        let mut at = MAGIC.len();
        let [classes, order] = read::<2>(DATA, &mut at);
        assert_eq!((classes as usize, order as usize), (CLASSES, MAX_ORDER));
        let entries = u32::from_le_bytes(read(DATA, &mut at)) as usize;
        let mut floor = [[0.0; MAX_ORDER]; CLASSES];
        for row in &mut floor {
            for value in row.iter_mut() {
                *value = f32::from_le_bytes(read(DATA, &mut at));
            }
        }
        let mut table = HashMap::with_capacity_and_hasher(entries, Default::default());
        for _ in 0..entries {
            let key = u32::from_le_bytes(read(DATA, &mut at));
            let mut row = [0i16; CLASSES];
            for value in &mut row {
                *value = i16::from_le_bytes(read(DATA, &mut at));
            }
            table.insert(key, row);
        }
        Model { floor, table }
    })
}

/// Summed log-probabilities of every n-gram seen so far, per class.
#[derive(Clone, Copy, Default)]
pub struct Scores {
    pub log_prob: [f64; CLASSES],
    pub grams: usize,
}

impl Scores {
    /// Log-likelihood ratio of class `a` over class `b`.
    pub fn ratio(&self, a: usize, b: usize) -> f64 {
        self.log_prob[a] - self.log_prob[b]
    }

    pub fn add(&mut self, other: &Scores) {
        for (sum, value) in self.log_prob.iter_mut().zip(other.log_prob) {
            *sum += value;
        }
        self.grams += other.grams;
    }

    /// Add the n-grams of `word` (lowercase letters, apostrophes written as `'`) to the scores
    /// of `classes`. `chars` is a reusable buffer.
    pub fn add_word(&mut self, word: &str, classes: [usize; 2], chars: &mut Vec<char>) {
        let model = model();
        chars.clear();
        chars.push(' ');
        chars.extend(word.chars());
        chars.push(' ');
        let last = chars.len() - 1;
        let mut utf8 = [0u8; 4];
        for start in 0..chars.len() {
            let mut hash: u32 = 0x811c_9dc5;
            for (offset, &c) in chars[start..].iter().take(MAX_ORDER).enumerate() {
                for &byte in c.encode_utf8(&mut utf8).as_bytes() {
                    hash = (hash ^ u32::from(byte)).wrapping_mul(0x0100_0193);
                }
                let order = offset + 1;
                if order == 1 && (start == 0 || start == last) {
                    continue; // the padding alone is not a unigram
                }
                let row = model.table.get(&hash);
                for class in classes {
                    self.log_prob[class] += match row {
                        Some(row) => f64::from(f32::from(row[class]) / QUANT),
                        None => f64::from(model.floor[class][order - 1]),
                    };
                }
                self.grams += 1;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scores(text: &str, classes: [usize; 2]) -> Scores {
        let mut scores = Scores::default();
        let mut chars = Vec::new();
        for word in text.split_whitespace() {
            scores.add_word(word, classes, &mut chars);
        }
        scores
    }

    #[test]
    fn table_loads_and_separates_the_classes() {
        let cyrillic = [UZ_CYRL, RU];
        let latin = [UZ_LATN, OTHER_LATN];
        assert!(scores("ўзбекистон республикаси ҳукумати", cyrillic).ratio(UZ_CYRL, RU) > 0.0);
        assert!(scores("российской федерации правительство", cyrillic).ratio(RU, UZ_CYRL) > 0.0);
        assert!(
            scores("o'zbekiston respublikasi hukumati", latin).ratio(UZ_LATN, OTHER_LATN) > 0.0
        );
        assert!(scores("the government of the republic", latin).ratio(OTHER_LATN, UZ_LATN) > 0.0);
    }

    #[test]
    fn unigrams_skip_the_padding() {
        let mut one = Scores::default();
        one.add_word("а", [UZ_CYRL, RU], &mut Vec::new());
        assert_eq!(one.grams, 1 + 2 + 1);
    }
}
