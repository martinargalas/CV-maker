"""Reading the plain-text CV format.

The fixture is content-example.txt from the repository root — the same file the
CLI path hands people — so these tests cover the format as documented rather
than a copy of it that could drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import textimport  # noqa: E402
from app import app  # noqa: E402
from cvdoc import CV  # noqa: E402

client = TestClient(app)
EXAMPLE = (Path(__file__).resolve().parents[2] / "content-example.txt").read_text(encoding="utf-8")

# The same shapes as the English file, with Czech headings and the two things
# a hand-written CV does that the example does not: a job whose header has no
# employer or city, and a paragraph of prose ahead of unmarked bullets.
CZECH = """Jan Novák
Engineering Manager

Osobní údaje
============
jan.novak@example.com
+420 000 000 000
ČR, Moravskoslezský kraj

Profesionální shrnutí
=====================
Vedení vývojových týmů a delivery.

Vzdělání
========
Bakalář
Univerzita, Informační a komunikační technologie
Ostrava
Jan 2010

Dovednosti
==========
• Manažerské kompetence
• Vedení vývojových týmů

Jazyky
======
• Čeština
• Angličtina

Historie zaměstnání
===================
Engineering Manager
Firma
Brno
Apr 2025 - Feb 2026

Hlavním cílem byla stabilizace týmu.

Leadership & rozvoj lidí:
Škálování týmu z jednoho na dva
Mentorování vývojáře do role Tech Leada

Profesní rozvoj

Mar 2026 - Present

• Open-source projekt
"""


def parsed(text: str) -> dict:
    fields, _ = textimport.parse(text)
    CV.model_validate(fields)  # an import must always be loadable into the form
    return fields


# ------------------------------------------------------------ the example

def test_name_and_role_come_from_the_top():
    cv = parsed(EXAMPLE)
    assert cv["name"] == "Jane Doe"
    assert cv["role"] == "Engineering Manager"


def test_contact_lines_are_told_apart_by_shape_not_order():
    cv = parsed(EXAMPLE)
    assert cv["email"] == "jane@example.com"
    assert cv["phone"] == "+00 000 000 000"
    assert cv["location"] == "City, Country"


def test_sections_are_read():
    cv = parsed(EXAMPLE)
    assert cv["about"].startswith("Two or three sentences")
    assert cv["skills"][0] == "First skill"
    assert cv["languages"] == ["English", "Another language"]
    assert cv["interests"].startswith("A short line")
    assert cv["links"] == [
        {"label": "LinkedIn", "url": "https://www.linkedin.com/in/example/"},
        {"label": "GitHub", "url": "https://github.com/example"},
    ]


def test_education_and_courses_end_on_their_date():
    cv = parsed(EXAMPLE)
    assert cv["education"] == [{
        "title": "Degree",
        "subtitle": "University Name, Field of Study, City",
        "meta": "2010",
    }]
    assert [c["meta"] for c in cv["courses"]] == ["2023", "2021"]


def test_every_job_is_found_with_its_header_and_groups():
    cv = parsed(EXAMPLE)
    assert len(cv["jobs"]) == 3

    first = cv["jobs"][0]
    assert (first["title"], first["company"], first["city"]) == ("Job Title", "Company", "City")
    assert first["when"] == "Jan 2024 - Present"
    assert first["intro"].startswith("One or two sentences")
    assert [(g["label"], len(g["bullets"])) for g in first["groups"]] == [
        ("Group label", 3), ("Another group label", 2),
    ]


def test_unmarked_bullets_do_not_become_an_intro():
    """The second job is a flat list of sentences, not a paragraph."""
    second = parsed(EXAMPLE)["jobs"][1]
    assert second["intro"] == ""
    assert len(second["groups"][0]["bullets"]) == 2


def test_the_files_own_headings_become_the_cvs_headings():
    cv = parsed(EXAMPLE)
    assert cv["labels"]["work"] == "Employment history"
    assert cv["labels"]["about"] == "Professional Summary"


def test_the_instructions_at_the_bottom_are_not_read_as_content():
    cv = parsed(EXAMPLE)
    assert "HOW TO USE THIS FILE" not in str(cv)
    assert all("->" not in skill for skill in cv["skills"])


# -------------------------------------------------------------- in Czech

def test_czech_headings_are_understood_and_kept():
    cv = parsed(CZECH)
    assert cv["email"] == "jan.novak@example.com"
    assert cv["languages"] == ["Čeština", "Angličtina"]
    assert cv["labels"]["work"] == "Historie zaměstnání"
    assert cv["labels"]["education"] == "Vzdělání"


def test_a_job_with_only_a_title_and_a_date_is_still_a_job():
    jobs = parsed(CZECH)["jobs"]
    assert [j["title"] for j in jobs] == ["Engineering Manager", "Profesní rozvoj"]
    last = jobs[-1]
    assert (last["company"], last["city"]) == ("", "")
    assert last["when"] == "Mar 2026 - Present"
    assert last["groups"][0]["bullets"] == ["Open-source projekt"]


def test_prose_before_labelled_groups_is_the_intro():
    first = parsed(CZECH)["jobs"][0]
    assert first["intro"] == "Hlavním cílem byla stabilizace týmu."
    assert first["groups"][0]["label"] == "Leadership & rozvoj lidí"


# ------------------------------------------------------- limits and safety

def test_oversized_input_is_clamped_rather_than_refused():
    text = "A\nB\n\nSkills\n======\n" + "".join(f"• skill {i}\n" for i in range(200))
    fields, warnings = textimport.parse(text)
    CV.model_validate(fields)
    assert len(fields["skills"]) == 40
    assert any("40 of 200" in w for w in warnings)


def test_over_long_fields_are_shortened_rather_than_refused():
    text = "A\nB\n\nProfessional Summary\n====================\n" + ("word " * 1000)
    fields, warnings = textimport.parse(text)
    CV.model_validate(fields)
    assert len(fields["about"]) <= 1500
    assert any("shortened" in w for w in warnings)


def test_unknown_sections_are_reported_not_swallowed():
    _, warnings = textimport.parse("A\nB\n\nReferences\n==========\nSomeone\n")
    assert any("References" in w for w in warnings)


def test_markup_in_the_text_stays_text():
    cv = parsed("<script>alert(1)</script>\nRole\n")
    assert cv["name"] == "<script>alert(1)</script>"
    response = client.post("/api/preview", json=cv)
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.json()["html"]


def test_the_endpoint_refuses_input_that_is_not_text():
    response = client.post("/api/import-text", content=b"\xff\xfe\x00binary")
    assert response.status_code == 400


def test_the_endpoint_returns_something_the_form_can_load():
    response = client.post("/api/import-text", content=EXAMPLE.encode())
    assert response.status_code == 200
    body = response.json()
    assert body["cv"]["name"] == "Jane Doe"
    assert CV.model_validate(body["cv"])
