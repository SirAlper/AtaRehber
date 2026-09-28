"""Digits for Turkish numbers written in words ("elli beş" -> "elli beş (55)").

Laws and regulations write most limits in words ("en az elli beş puan", "toplam on üç üyeden oluşur") while
transitional articles and tables use digits. Small models then prefer the number they can see as digits, even
when it belongs to an outdated provision; adding the digits next to the words puts both on an equal footing.
"""

import re

_UNITS = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
_TENS = {
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kırk": 40,
    "elli": 50,
    "altmış": 60,
    "yetmiş": 70,
    "seksen": 80,
    "doksan": 90,
}
_WORDS = {**_UNITS, **_TENS, "yüz": 100, "bin": 1000}
# Longest first, so "on" does not match the start of "onbir"-style joined numbers before longer words
_WORD = "|".join(sorted(_WORDS, key=len, reverse=True))
_LETTER = r"[\wçğıöşüÇĞİÖŞÜ]"
# Number words separated by a space or joined ("altmışbeş"). The lookaheads stop at the end of a whole word
# ("elli" in "elli beşinci" is not a number on its own) and skip words already followed by digits.
_NUMBER_RE = re.compile(
    rf"(?<!{_LETTER})(?:{_WORD})(?:[ ]?(?:{_WORD}))*(?!{_LETTER})(?![ ]?(?:{_WORD}))(?![ ]?\(\d)",
    re.IGNORECASE,
)
_FACE_IDIOMS = (" kızart", " yüz", " karası", " üstü", " çevir")
# Only numbers from ten upwards: "bir", "iki", "üç" are too common as words ("bir yarıyıl") to annotate
MIN_VALUE = 10


def parse_number(text: str):
    """Value of a Turkish number in words ('yüz yirmi beş' -> 125), or None if the words do not form one."""
    tokens = re.findall(_WORD, text.lower())
    if not tokens or "".join(tokens) != re.sub(r"\s", "", text.lower()):
        return None
    total, group = 0, 0
    seen = set()  # parts already used in the current group (below one thousand)
    for token in tokens:
        if token == "bin":
            if "bin" in seen:
                return None
            total, group, seen = (group or 1) * 1000, 0, {"bin"}
        elif token == "yüz":
            if seen - {"bin"} - {"unit"}:
                return None
            group, seen = (group or 1) * 100, seen - {"unit"} | {"yüz"}
        elif token in _TENS:
            if {"tens", "unit"} & seen:
                return None
            group, seen = group + _TENS[token], seen | {"tens"}
        else:
            if "unit" in seen:
                return None
            group, seen = group + _UNITS[token], seen | {"unit"}
    return total + group


def annotate_numbers(text: str) -> str:
    """Append the digits to Turkish numbers written in words: 'en az elli beş puan' -> 'en az elli beş (55) puan'."""

    def replace(match):
        words = match.group(0)
        value = parse_number(words)
        # Skip small numbers, words that are no number, and words that already spell out digits: "65 (altmışbeş)"
        if value is None or value < MIN_VALUE or text[match.start() - 1 : match.start()] == "(":
            return words
        # "yüz" is also "face": "yüz kızartıcı suç", "yüz yüze eğitim"
        if words.lower() == "yüz" and text[match.end() :].lower().startswith(_FACE_IDIOMS):
            return words
        return f"{words} ({value})"

    return _NUMBER_RE.sub(replace, text)
