"""How long each job lasted, and the document title it is shown next to."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duration  # noqa: E402
from cvdoc import CV, build_document  # noqa: E402

TODAY = date(2026, 8, 12)


def built(**fields) -> str:
    base = {"name": "Someone", "jobs": [{"title": "Job", "when": "Jan 2024 - Present"}]}
    return build_document(CV.model_validate({**base, **fields}))


# ------------------------------------------------------------- the reading

@pytest.mark.parametrize("when,months", [
    ("Jan 2024 - Dec 2024", 12),
    ("Mar 2021 - May 2021", 3),          # inclusive: March, April, May
    ("Jan 2024 - Jan 2024", 1),
    ("Apr 2025 - Feb 2026", 11),
    ("March 2020 – June 2021", 16),      # en dash, full month names
    ("03/2021 - 12/2023", 34),
    ("2021-03 - 2023-12", 34),
    ("2019 - 2021", 25),                 # bare years count from January
    ("led 2024 - bre 2024", 3),          # Czech abbreviations
    ("leden 2024 - brezen 2024", 3),
    ("červenec 2023 - srpen 2023", 2),   # accents, and červenec not červen
])
def test_ranges_are_counted_inclusively(when, months):
    assert duration.months_between(when, TODAY) == months


@pytest.mark.parametrize("when", [
    "Jan 2024 - Present", "Jan 2024 - present", "Jan 2024 – Current",
    "led 2024 - dosud", "Jan 2024 - Současnost",
])
def test_a_job_still_running_counts_up_to_today(when):
    # January 2024 through August 2026 inclusive.
    assert duration.months_between(when, TODAY) == 32


@pytest.mark.parametrize("when", [
    "", "Present", "2024", "sometime last year", "Various", "Jan 2024",
    "Dec 2023 - Nov 2018",          # backwards
    "Jan 1200 - Jan 2026",          # longer than a working life
    "Jan 2024 - Feb 2024 - Mar 2024",
])
def test_anything_unreadable_is_reported_as_unknown(when):
    """Silence beats a guess: a wrong tenure on a CV is worse than none."""
    assert duration.months_between(when, TODAY) is None


# ------------------------------------------------------------- the wording

@pytest.mark.parametrize("months,text", [
    (1, "1 month"), (2, "2 months"), (11, "11 months"),
    (12, "1 year"), (13, "1 year 1 month"), (19, "1 year 7 months"),
    (24, "2 years"), (31, "2 years 7 months"), (60, "5 years"),
])
def test_english_wording(months, text):
    assert duration.describe(months, "en") == text


@pytest.mark.parametrize("months,text", [
    (1, "1 měsíc"), (3, "3 měsíce"), (7, "7 měsíců"),
    (12, "1 rok"), (19, "1 rok 7 měsíců"), (36, "3 roky"), (60, "5 let"),
    (25, "2 roky 1 měsíc"),
])
def test_czech_wording_uses_all_three_plural_forms(months, text):
    assert duration.describe(months, "cs") == text


# ------------------------------------------------------------ in the CV

def test_durations_are_off_unless_asked_for():
    assert "(" not in re.search(r'<p class="when">(.*?)</p>', built()).group(1)


def test_the_duration_follows_the_dates():
    doc = built(show_durations=True,
                jobs=[{"title": "Job", "when": "Jan 2024 - Dec 2024"}])
    assert '<p class="when">Jan 2024 - Dec 2024 (1 year)</p>' in doc


def test_the_duration_can_be_worded_in_czech():
    doc = built(show_durations=True, duration_language="cs",
                jobs=[{"title": "Job", "when": "Jan 2024 - Dec 2024"}])
    assert "(1 rok)" in doc


def test_a_date_line_that_cannot_be_read_is_left_exactly_as_typed():
    doc = built(show_durations=True,
                jobs=[{"title": "Job", "when": "on and off since school"}])
    assert '<p class="when">on and off since school</p>' in doc


def test_the_dates_are_still_escaped_with_durations_on():
    doc = built(show_durations=True,
                jobs=[{"title": "Job", "when": "<b>Jan 2024</b> - Dec 2024"}])
    assert "<b>Jan 2024</b>" not in doc
    assert "&lt;b&gt;Jan 2024&lt;/b&gt;" in doc


# ---------------------------------------------------------------- title

def test_the_document_title_is_the_name_and_nothing_else():
    """Inside <title> a comment is text, so the slot markers must not survive."""
    title = re.search(r"<title>(.*?)</title>", built(name="Jane Doe"), re.S).group(1)
    assert title.strip() == "Jane Doe"
    assert "slot:" not in title


def test_a_name_with_markup_in_it_is_still_escaped_in_the_title():
    title = re.search(r"<title>(.*?)</title>", built(name="<script>x</script>"), re.S).group(1)
    assert "<script>" not in title
    assert "&lt;script&gt;" in title


@pytest.mark.skipif(os.environ.get("CV_TEST_RENDER") != "1", reason="needs Chrome")
def test_the_pdf_metadata_carries_a_clean_title():
    """This is where it showed: a PDF reader displays /Title as the file's name."""
    from render import render_pdf
    pdf = asyncio.run(render_pdf(built(name="Jane Doe")))
    stored = re.search(rb"/Title \(([^)]*)\)", pdf)
    assert stored is not None
    assert b"slot:" not in stored.group(1)
    assert stored.group(1).strip() == b"Jane Doe"
