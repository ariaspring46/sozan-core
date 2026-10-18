"""Word edges for Persian regexes.

`؀-ۿ` is the whole Arabic block, so it also holds « ، » « ؟ » « ؛ » and the Persian digits: «کن،» and «پسورد؟»
looked like one word and the pattern never matched. BEFORE and AFTER treat only letters as part of a word; Latin letters
and punctuation are edges, as they always were.
"""

FA_LETTER = r"ء-يٱ-ۓەۺ-ۿ"
BEFORE = rf"(?<![{FA_LETTER}])"
AFTER = rf"(?![{FA_LETTER}])"
