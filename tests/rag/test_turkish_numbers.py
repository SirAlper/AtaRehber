import unittest

from src.rag.turkish_numbers import annotate_numbers, parse_number


class TestTurkishNumbers(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(parse_number("elli beş"), 55)
        self.assertEqual(parse_number("altmışbeş"), 65)
        self.assertEqual(parse_number("yüz yirmi beş"), 125)
        self.assertEqual(parse_number("bin dokuz yüz seksen bir"), 1981)
        self.assertEqual(parse_number("iki bin beş yüz"), 2500)
        self.assertIsNone(parse_number("on on"))
        self.assertIsNone(parse_number("iki üç"))

    def test_numbers_in_words_get_their_digits(self):
        self.assertEqual(annotate_numbers("en az elli beş puan"), "en az elli beş (55) puan")
        self.assertEqual(annotate_numbers("toplam on üç üyeden oluşur"), "toplam on üç (13) üyeden oluşur")
        self.assertEqual(annotate_numbers("otuz gün içinde"), "otuz (30) gün içinde")

    def test_words_that_are_no_numbers_or_already_have_digits_are_kept(self):
        for text in (
            "bir yarıyıl",  # below ten: too common as a word
            "yüz yüze eğitim",
            "yüz kızartıcı suç",
            "on birinci madde",  # ordinals
            "elli beşinci",
            "65 (altmışbeş) puan",
            "on (10) gün",
            "iki üç kişi",
        ):
            self.assertEqual(annotate_numbers(text), text)


if __name__ == "__main__":
    unittest.main()
