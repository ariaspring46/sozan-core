import re
import unittest

from app.services.fa_text import AFTER, BEFORE


def word(token: str) -> re.Pattern:
    return re.compile(BEFORE + token + AFTER)


class WordEdgeTests(unittest.TestCase):
    def test_arabic_punctuation_is_an_edge_not_part_of_the_word(self) -> None:
        # «کن،» «پسورد؟» «شبا؛» used to look like one word, because the whole Arabic block counted as letters
        for text in ("کن،", "کن؟", "کن؛", "کن.", "کن!", "کن", "(کن)", "«کن»", "ولی کن، بعد"):
            self.assertTrue(word("کن").search(text), text)

    def test_a_letter_next_to_the_word_still_blocks_it(self) -> None:
        self.assertIsNone(word("کن").search("بکن"))
        self.assertIsNone(word("کن").search("کنار"))
        self.assertIsNone(word("رمز").search("قرمز"))
        self.assertIsNone(word("رمز").search("رمزگذاری"))
        self.assertIsNone(word("شبا").search("شبانه"))

    def test_latin_letters_and_digits_stay_edges(self) -> None:
        # as before: only Persian/Arabic letters glue to a Persian word
        self.assertTrue(word("password").search("passwords"))
        self.assertTrue(word("کن").search("کن2"))


if __name__ == "__main__":
    unittest.main()
