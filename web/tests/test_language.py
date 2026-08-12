"""One language switch for the whole CV.

It decides three things at once: what the sections are called, how months are
named, and how a length is worded. What it must never do is overwrite a heading
somebody wrote themselves.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cvdoc import CV, build_document  # noqa: E402

FULL = {
    "name": "Someone",
    "email": "someone@example.com",
    "about": "A sentence.",
    "education": [{"title": "Degree", "meta": "2010"}],
    "skills": ["A skill"],
    "links": [{"label": "GitHub", "url": "https://github.com/example"}],
    "languages": ["English"],
    "interests": "Something.",
    "courses": [{"title": "A course", "meta": "2023"}],
    "jobs": [{"title": "Job", "start": "2024-01", "end": "2024-12"}],
}


def headings(**fields) -> list:
    doc = build_document(CV.model_validate({**FULL, **fields}))
    return re.findall(r"<h2>([^<]*)</h2>", doc)


def when(**fields) -> str:
    doc = build_document(CV.model_validate({**FULL, **fields}))
    return re.search(r'<p class="when">([^<]*)</p>', doc).group(1)


def test_english_is_the_default():
    assert headings() == [
        "Contact", "About Me", "Education", "Skills", "Links",
        "Languages", "Interests", "Courses", "Work Experience",
    ]


def test_czech_renames_every_section():
    assert headings(language="cs") == [
        "Kontakt", "O mně", "Vzdělání", "Dovednosti", "Odkazy",
        "Jazyky", "Zájmy", "Kurzy", "Pracovní zkušenosti",
    ]


def test_the_same_switch_names_the_months():
    assert when() == "Jan 2024 - Dec 2024"
    assert when(language="cs") == "leden 2024 - prosinec 2024"


def test_the_same_switch_words_the_length():
    assert when(show_durations=True) == "Jan 2024 - Dec 2024 (1 year)"
    assert when(language="cs", show_durations=True) == "leden 2024 - prosinec 2024 (1 rok)"


def test_a_heading_someone_wrote_is_left_alone():
    assert headings(language="cs", labels={"contact": "Spojení"})[0] == "Spojení"
    assert headings(language="en", labels={"work": "Where I have worked"})[-1] == \
        "Where I have worked"


def test_a_heading_left_at_the_english_default_follows_the_language():
    """Nobody chose "Contact"; it was simply never edited."""
    assert headings(language="cs", labels={"contact": "Contact"})[0] == "Kontakt"


def test_a_cv_saved_before_the_switch_still_opens():
    """The field was called duration_language and only worded the lengths."""
    cv = CV.model_validate({**FULL, "duration_language": "cs"})
    assert cv.language == "cs"
    assert "duration_language" not in cv.model_dump()


def test_an_explicit_language_wins_over_the_old_field():
    cv = CV.model_validate({**FULL, "language": "en", "duration_language": "cs"})
    assert cv.language == "en"


@pytest.mark.parametrize("value", ["de", "", "EN", "czech"])
def test_an_unknown_language_is_refused(value):
    with pytest.raises(Exception):
        CV.model_validate({**FULL, "language": value})


def test_headings_are_still_escaped():
    doc = build_document(CV.model_validate({**FULL, "labels": {"contact": "<b>x</b>"}}))
    assert "<h2><b>x</b></h2>" not in doc
    assert "&lt;b&gt;x&lt;/b&gt;" in doc
