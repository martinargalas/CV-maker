"""Working out how long someone held a job, from the dates they typed.

The date line is free text — people write "Jan 2024 - Present", "03/2021 –
12/2023" or just "2019" — so this reads what it recognises and says nothing at
all when it does not. A CV that quietly shows the wrong tenure is worse than
one that shows none, so every uncertain case returns None rather than a guess.

Counting is inclusive: March to May is three months, which is how people
describe their own time in a job.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional, Tuple

# "Present" and its neighbours, in both languages the app is used in.
_ONGOING = {
    "present", "current", "currently", "now", "today", "date", "ongoing",
    "soucasnost", "dosud", "nyni", "trva", "soucasne",
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # Czech, in the forms a date line actually uses.
    "leden": 1, "ledna": 1, "unor": 2, "unora": 2, "brezen": 3, "brezna": 3,
    "duben": 4, "dubna": 4, "kveten": 5, "kvetna": 5, "cerven": 6, "cervna": 6,
    "cervenec": 7, "cervence": 7, "srpen": 8, "srpna": 8, "zari": 9,
    "rijen": 10, "rijna": 10, "listopad": 11, "listopadu": 11,
    "prosinec": 12, "prosince": 12,
    "led": 1, "uno": 2, "bre": 3, "dub": 4, "kve": 5, "cvn": 6, "cvc": 7,
    "srp": 8, "zar": 9, "rij": 10, "lis": 11, "pro": 12,
}

# Longest first, so "cervenec" is not read as "cerven".
_MONTH_KEYS = sorted(_MONTHS, key=len, reverse=True)

# Tried in this order, and the first that yields exactly two halves wins. A
# bare hyphen comes last because "2021-03 - 2023-12" contains three of them and
# only the spaced one separates the two dates.
_SEPARATORS = (
    re.compile(r"\s*[–—]{1,2}\s*"),      # en and em dashes
    re.compile(r"\s+-{1,2}\s+"),         # a hyphen with space around it
    re.compile(r"\s+(?:to|az|do)\s+", re.I),
    re.compile(r"-{1,2}"),               # last resort: "03/2021-12/2023"
)


def _fold(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


def _month_from(word: str) -> Optional[int]:
    for key in _MONTH_KEYS:
        if word.startswith(key):
            return _MONTHS[key]
    return None


def _endpoint(text: str, today: date) -> Optional[Tuple[int, int]]:
    """One end of a range, as (year, month). Month defaults to January."""
    folded = _fold(text).strip().strip(".,;")
    if not folded:
        return None

    if any(word in _ONGOING for word in re.findall(r"[a-z]+", folded)):
        return (today.year, today.month)

    # 03/2021, 3.2021, 2021-03
    numeric = re.fullmatch(r"(\d{1,2})[./-](\d{4})", folded) or None
    if numeric:
        month, year = int(numeric.group(1)), int(numeric.group(2))
        return (year, month) if 1 <= month <= 12 else None

    iso = re.fullmatch(r"(\d{4})[./-](\d{1,2})", folded)
    if iso:
        year, month = int(iso.group(1)), int(iso.group(2))
        return (year, month) if 1 <= month <= 12 else None

    years = re.findall(r"\b(19|20)(\d{2})\b", folded)
    if len(years) != 1:
        return None
    year = int(years[0][0] + years[0][1])

    month = 1
    for word in re.findall(r"[a-z]+", folded):
        found = _month_from(word)
        if found:
            month = found
            break
    return (year, month)


def months_between(when: str, today: Optional[date] = None) -> Optional[int]:
    """How many months a date line covers, or None if it cannot be read."""
    today = today or date.today()

    parts = None
    for separator in _SEPARATORS:
        halves = [p for p in separator.split(_fold(when).strip()) if p.strip()]
        if len(halves) == 2:
            parts = halves
            break
    if parts is None:
        return None

    start = _endpoint(parts[0], today)
    end = _endpoint(parts[1], today)
    if start is None or end is None:
        return None

    total = (end[0] - start[0]) * 12 + (end[1] - start[1]) + 1
    # A range that runs backwards, or one longer than a working life, means the
    # line was misread rather than that the job really lasted that long.
    if total < 1 or total > 70 * 12:
        return None
    return total


def _plural(count: int, forms: Tuple[str, str, str]) -> str:
    """forms are (one, few, many) — Czech needs all three, English uses two."""
    if count == 1:
        return forms[0]
    if 2 <= count <= 4:
        return forms[1]
    return forms[2]


_WORDS = {
    "en": {"year": ("year", "years", "years"), "month": ("month", "months", "months")},
    "cs": {"year": ("rok", "roky", "let"), "month": ("měsíc", "měsíce", "měsíců")},
}


def describe(months: int, language: str = "en") -> str:
    words = _WORDS.get(language, _WORDS["en"])
    years, rest = divmod(months, 12)

    parts = []
    if years:
        parts.append(f"{years} {_plural(years, words['year'])}")
    if rest or not years:
        parts.append(f"{rest} {_plural(rest, words['month'])}")
    return " ".join(parts)


def for_line(when: str, language: str = "en", today: Optional[date] = None) -> Optional[str]:
    """The length of a job as text, or None when the dates were not readable."""
    months = months_between(when, today)
    return describe(months, language) if months is not None else None
