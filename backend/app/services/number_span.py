"""One number reader. Each caller picks a scope.

Money is what the inbox already checked: four digits and up, spoken amounts of 1000 and up, and percents.
Voice also sees a size, a count («سه» is 3), and a spoken price («۸۵۰ هزار» is 850000).
"""

from __future__ import annotations

import re

_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_GROUP_SEP = re.compile(r"(?<=\d)[,٬،'’٫.](?=\d{3}(?!\d))")
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[\u0600-\u06FF]+")
_NUM_WORDS = {
    "صفر": 0, "یک": 1, "یه": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "شیش": 6, "هفت": 7,
    "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12, "سیزده": 13, "چهارده": 14, "پانزده": 15,
    "پونزده": 15, "شانزده": 16, "هفده": 17, "هجده": 18, "هیجده": 18, "نوزده": 19, "بیست": 20, "سی": 30,
    "چهل": 40, "پنجاه": 50, "شصت": 60, "هفتاد": 70, "هشتاد": 80, "نود": 90, "صد": 100, "یکصد": 100,
    "دویست": 200, "سیصد": 300, "چهارصد": 400, "پانصد": 500, "پونصد": 500, "ششصد": 600, "هفتصد": 700,
    "هشتصد": 800, "نهصد": 900, "نیم": 0.5,
}
_SCALES = {"هزار": 1_000, "تومن": 0, "میلیون": 1_000_000, "ملیون": 1_000_000, "میلیارد": 1_000_000_000}
_COUNT = {"کالا", "عدد", "تا", "نفر", "قلم", "دانه"}


def _fold(text: str) -> str:
    return _GROUP_SEP.sub("", str(text or "").translate(_DIGIT_FOLD))


def spoken_money(folded: str) -> set[str]:
    """«یک و نیم میلیون»، «۲.۵ میلیون»، «دو میلیون و پانصد هزار» -> their integer value, when it is at least 1000."""
    found: set[str] = set()
    total = 0.0
    current = 0.0
    scaled = False
    run = False

    def close() -> None:
        nonlocal total, current, scaled, run
        value = int(round(total + current))
        if run and (scaled or value >= 1000) and value >= 1000:
            found.add(str(value))
        total = current = 0.0
        scaled = run = False

    for token in re.findall(r"\d+(?:\.\d+)?|[\u0600-\u06FF]+", folded):
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            current += float(token)
            run = True
        elif token in _NUM_WORDS:
            current += _NUM_WORDS[token]
            run = True
        elif token == "و" and run:
            continue
        elif token in _SCALES and _SCALES[token] and run:
            total += (current or 1) * _SCALES[token]
            current = 0.0
            scaled = True
        else:
            close()
    close()
    return found


def money_amounts(text: str) -> set[str]:
    """Inbox scope: a price, a spoken price, or a percent. A size such as ۵۴ is not an amount."""
    folded = _fold(text)
    found = set(re.findall(r"\d{4,}", folded))
    found.update(spoken_money(folded))
    found.update(re.findall(r"\d+(?:\.\d+)?\s*٪", folded))
    found.update(re.findall(r"\d+(?:\.\d+)?\s*%", folded))
    return found


def _spoken_voice(folded: str) -> tuple[set[str], list[tuple[int, int]]]:
    """Counts and spoken money. Spans cover a scaled run so «۸۵۰» inside «۸۵۰ هزار» is not a second number."""
    found: set[str] = set()
    spans: list[tuple[int, int]] = []
    total = 0.0
    current = 0.0
    scaled = False
    run = False
    run_start: int | None = None
    run_end: int | None = None

    def close(*, count: bool = False) -> None:
        nonlocal total, current, scaled, run, run_start, run_end
        value = int(round(total + current))
        if run and run_start is not None and run_end is not None:
            if scaled or value >= 1000:
                found.add(str(value))
                if scaled:
                    spans.append((run_start, run_end))
            elif count:
                found.add(str(value))
        total = current = 0.0
        scaled = run = False
        run_start = run_end = None

    for match in _TOKEN.finditer(folded):
        token = match.group()
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            if not run:
                run_start = match.start()
            current += float(token)
            run = True
            run_end = match.end()
        elif token in _NUM_WORDS:
            if not run:
                run_start = match.start()
            current += _NUM_WORDS[token]
            run = True
            run_end = match.end()
        elif token == "و" and run:
            run_end = match.end()
        elif token in _SCALES and _SCALES[token] and run:
            total += (current or 1) * _SCALES[token]
            current = 0.0
            scaled = True
            run_end = match.end()
        elif token in _COUNT and run:
            run_end = match.end()
            close(count=True)
        else:
            close()
    close()
    return found, spans


def voice_amounts(text: str) -> set[str]:
    """Voice scope: every digit, a spoken count («سه کالا» is 3), and a spoken price («۸۵۰ هزار» is 850000)."""
    folded = _fold(text)
    spoken, spans = _spoken_voice(folded)
    found = set(spoken)
    for match in re.finditer(r"\d+", folded):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            continue
        found.add(match.group())
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*[٪%]", folded):
        number = match.group(1)
        found.add(str(int(number)) if "." not in number else number)
    return found
