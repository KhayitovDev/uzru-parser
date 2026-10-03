//! Character classes shared by the text modules.

/// Apostrophe-like characters that Uzbek Latin text uses for `oʻ`, `gʻ` and `maʼlumot`.
pub fn is_apostrophe(c: char) -> bool {
    matches!(c, '\'' | '’' | '‘' | 'ʻ' | 'ʼ' | '`')
}
