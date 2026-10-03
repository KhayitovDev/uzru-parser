//! Tokenizer-free token estimate: about one token per four characters of each word.

pub fn estimate_tokens(text: &str) -> usize {
    text.split_whitespace()
        .map(|word| word.chars().count().div_ceil(4).max(1))
        .sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn estimates() {
        assert_eq!(estimate_tokens(""), 0);
        assert_eq!(estimate_tokens("a bb"), 2);
        assert_eq!(estimate_tokens("Настоящим документом"), 3 + 3);
    }
}
