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


def _halves(when: str) -> Optional[list]:
    for separator in _SEPARATORS:
        halves = [p for p in separator.split(_fold(when).strip()) if p.strip()]
        if len(halves) == 2:
            return halves
    return None


def months_between(when: str, today: Optional[date] = None) -> Optional[int]:
    """How many months a date line covers, or None if it cannot be read."""
    today = today or date.today()
    parts = _halves(when)
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


# ------------------------------------------------------ structured dates

_MONTH_NAMES = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "cs": ("leden", "únor", "březen", "duben", "květen", "červen",
           "červenec", "srpen", "září", "říjen", "listopad", "prosinec"),
}

_ONGOING_WORD = {"en": "Present", "cs": "současnost"}


def parse_month(value: str) -> Optional[Tuple[int, int]]:
    """"2024-03" or "2024" as (year, month). A bare year means January."""
    match = re.fullmatch(r"(\d{4})(?:-(\d{2}))?", (value or "").strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else 1
    return (year, month) if 1 <= month <= 12 else None


def format_month(value: str, language: str = "en") -> str:
    parsed = parse_month(value)
    if parsed is None:
        return ""
    year, month = parsed
    names = _MONTH_NAMES.get(language, _MONTH_NAMES["en"])
    # A bare year stays a bare year: someone who wrote 2019 did not mean
    # January 2019, they meant they do not remember the month.
    if not re.fullmatch(r"\d{4}-\d{2}", value.strip()):
        return str(year)
    return f"{names[month - 1]} {year}"


def format_range(start: str, end: str, ongoing: bool, language: str = "en") -> str:
    """The date line a pair of pickers stands for."""
    first = format_month(start, language)
    if not first:
        return ""
    if ongoing:
        return f"{first} - {_ONGOING_WORD.get(language, 'Present')}"
    last = format_month(end, language)
    return f"{first} - {last}" if last else first


def structure(when: str) -> Optional[Tuple[str, str, bool]]:
    """Turn a free-text range into what the date pickers hold, if it can.

    Used on import, so a CV that arrived as text or as a PDF gets the same
    pickers as one typed in. A half that named no month stays a bare year
    rather than being rounded to January, because that is what it said.
    """
    parts = _halves(when)
    if parts is None:
        return None

    def one(text: str) -> Optional[str]:
        folded = _fold(text).strip().strip(".,;")
        numeric = re.fullmatch(r"(\d{1,2})[./-](\d{4})", folded)
        if numeric:
            return f"{int(numeric.group(2)):04d}-{int(numeric.group(1)):02d}"
        iso = re.fullmatch(r"(\d{4})[./-](\d{1,2})", folded)
        if iso:
            return f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}"

        years = re.findall(r"\b(19|20)(\d{2})\b", folded)
        if len(years) != 1:
            return None
        year = int(years[0][0] + years[0][1])
        for word in re.findall(r"[a-z]+", folded):
            month = _month_from(word)
            if month:
                return f"{year:04d}-{month:02d}"
        # A year with no month cannot go in a month picker, and rounding it to
        # January would put a claim in the CV that the person did not make.
        # It stays free text instead.
        return None

    ongoing = any(
        word in _ONGOING for word in re.findall(r"[a-z]+", _fold(parts[1]))
    )
    start = one(parts[0])
    if start is None:
        return None
    if ongoing:
        return (start, "", True)

    end = one(parts[1])
    if end is None:
        return None
    return (start, end, False)


def months_for(start: str, end: str, ongoing: bool,
               today: Optional[date] = None) -> Optional[int]:
    """The length of a structured range, counted the same inclusive way."""
    today = today or date.today()
    begin = parse_month(start)
    if begin is None:
        return None
    finish = (today.year, today.month) if ongoing else parse_month(end)
    if finish is None:
        return None

    total = (finish[0] - begin[0]) * 12 + (finish[1] - begin[1]) + 1
    return total if 1 <= total <= 70 * 12 else None
