"""Parse optional variant count from a free-form prompt. Never confuse slides with variants."""
import re

MAX_VARIANTS = 48
WORDS = {
    "один": 1, "одна": 1, "одно": 1, "одну": 1,
    "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "одиннадцать": 11,
    "двенадцать": 12, "пятнадцать": 15, "двадцать": 20,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "ten": 10,
}
NUMBER = r"(?:\d{1,3}|" + "|".join(sorted(WORDS, key=len, reverse=True)) + r")"
UNIT = r"(?:вариант(?:ов|а|ы|е|ах)?|картин(?:ок|ки|ка|ку)?|изображени(?:й|я|е|яx)?|variations?|images?|pictures?)"
BEFORE = re.compile(r"(?<![\w])(" + NUMBER + r")\s+" + UNIT + r"(?![\w])", re.I)
AFTER = re.compile(r"(?<![\w])" + UNIT + r"\s*[:\-]?\s*(" + NUMBER + r")(?![\w])", re.I)


def extract_variant_count(prompt: str):
    """Only explicit 'five variants' / '7 images' phrases. No false match on '5 slides'."""
    for regex in (BEFORE, AFTER):
        match = regex.search(prompt)
        if match:
            token = match.group(1).lower()
            value = int(token) if token.isdigit() else WORDS.get(token)
            if value is not None:
                return value
    return None


def choose_variants(value, prompt: str):
    """Value 'auto'/blank uses instruction; default to 1. Limit large accidental batches."""
    if value is None or str(value).strip().lower() in ("", "auto", "авто"):
        count = extract_variant_count(prompt) or 1
    else:
        try:
            count = int(value)
        except (ValueError, TypeError):
            raise ValueError("Variants: use a number or 'авто'") from None
    if not 1 <= count <= MAX_VARIANTS:
        raise ValueError(f"Choose 1–{MAX_VARIANTS} variants per GPU job")
    return count
