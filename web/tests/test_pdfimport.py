"""Reading a CV back out of a PDF.

The fixture is built the way a real one would be: the app renders a CV to PDF,
and the tests read that same PDF back. So this checks a genuine round trip
through Chrome's own output rather than a PDF written to suit the parser.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfimport  # noqa: E402
import textimport  # noqa: E402
from app import app  # noqa: E402
from cvdoc import CV, build_document  # noqa: E402

client = TestClient(app)

needs_chrome = pytest.mark.skipif(
    os.environ.get("CV_TEST_RENDER") != "1", reason="needs Chrome; set CV_TEST_RENDER=1"
)


@pytest.fixture(scope="module")
def rendered() -> bytes:
    """The example CV, as a PDF, rendered by the app itself."""
    from render import render_pdf
    data = json.loads((Path(__file__).resolve().parents[1] / "static" / "example.json").read_text())
    return asyncio.run(render_pdf(build_document(CV.model_validate(data))))


# ------------------------------------------------------- the pieces alone

def test_letter_spaced_headings_are_put_back_together():
    assert pdfimport._despace("C    O     N     T   A    C    T") == "CONTACT"
    assert pdfimport._despace(
        "W    O     R     K             E     X    P    E    R    I    E    N    C    E"
    ) == "WORK EXPERIENCE"


def test_ordinary_lines_are_left_alone():
    line = "Two or three sentences on what you do"
    assert pdfimport._despace(line) == line
    assert pdfimport._despace("2010") == "2010"


def test_a_two_column_page_is_read_a_column_at_a_time():
    # Proportioned like a real sheet: a sidebar that fills its own width, then
    # a clear channel, then the main column.
    page = "\n".join([
        "CONTACT                                 WORK EXPERIENCE",
        "someone.longname@example.com            Job Title, Company, City",
        "A City, And Then A Country              Jan 2024 - Present",
        "                                        Did a thing that went well.",
        "SKILLS                                  Did another thing entirely.",
        "First skill, spelled out at length      Earlier Job, Company, City",
        "Second skill, also spelled out          Mar 2021 - Dec 2023",
        "LANGUAGES                               Did an older thing as well.",
        "English, and one other language         And one more thing after that.",
    ])
    out = pdfimport._columns(page)
    # Everything from the left column arrives before anything from the right.
    assert out.index("First skill") < out.index("Job Title, Company")
    assert out.index("LANGUAGES") < out.index("Earlier Job, Company")


def test_a_single_column_page_is_left_in_its_own_order():
    page = "\n".join(["CONTACT", "me@example.com", "SKILLS", "First skill"] * 3)
    assert pdfimport._columns(page).count("CONTACT") == 3


# --------------------------------------------------------- what it refuses

def test_something_that_is_not_a_pdf_is_refused():
    with pytest.raises(pdfimport.PdfError, match="could not be read"):
        pdfimport.to_text(b"this is not a pdf at all")


def test_an_empty_file_is_refused():
    with pytest.raises(pdfimport.PdfError):
        pdfimport.to_text(b"")


def test_an_oversized_file_is_refused_before_it_is_parsed():
    with pytest.raises(pdfimport.PdfError, match="larger than"):
        pdfimport.to_text(b"%PDF-1.4" + b"\0" * (pdfimport.MAX_BYTES + 1))


def test_a_pdf_with_no_text_says_so_rather_than_returning_nothing():
    """A scan is a picture of a CV, and this app does not read pictures."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (600, 800), (240, 240, 240)).save(buffer, format="PDF")
    with pytest.raises(pdfimport.PdfError, match="scan or a picture"):
        pdfimport.to_text(buffer.getvalue())


def test_the_endpoint_reports_a_bad_file_without_crashing():
    response = client.post("/api/import-pdf", files={"file": ("x.pdf", b"nope", "application/pdf")})
    assert response.status_code == 400
    assert "error" in response.json()


# ------------------------------------------------------ the whole journey

@needs_chrome
def test_a_rendered_cv_reads_back_into_the_same_fields(rendered):
    text = pdfimport.to_text(rendered)
    fields, _ = textimport.parse(text)
    cv = CV.model_validate(fields)

    assert cv.name == "JANE DOE"
    assert cv.role == "ENGINEERING MANAGER"
    assert cv.email == "jane@example.com"
    assert cv.phone == "+00 000 000 000"
    assert cv.location == "City, Country"
    assert cv.about.startswith("Two or three sentences")
    assert cv.interests.startswith("A short line")


@needs_chrome
def test_the_columns_do_not_get_interleaved(rendered):
    """The sidebar must not end up shuffled into the work history."""
    cv = CV.model_validate(textimport.parse(pdfimport.to_text(rendered))[0])
    assert [job.title for job in cv.jobs] == [
        "Job Title, Company, City", "Earlier Job Title, Company, City",
    ]
    assert [job.when for job in cv.jobs] == ["Jan 2024 - Present", "Mar 2021 - Dec 2023"]
    assert cv.languages == ["English", "Another language"]


@needs_chrome
def test_wrapped_lines_and_dates_survive(rendered):
    cv = CV.model_validate(textimport.parse(pdfimport.to_text(rendered))[0])
    # A skill the column wrapped in two comes back as one skill.
    assert "Second skill, which can wrap onto more than one line" in cv.skills
    # The year sits in its own block in a PDF, away from the entry it belongs to.
    assert cv.education[0].meta == "2010"
    assert cv.courses[0].meta == "2023"


@needs_chrome
def test_a_url_broken_across_lines_is_made_whole(rendered):
    cv = CV.model_validate(textimport.parse(pdfimport.to_text(rendered))[0])
    assert {link.url for link in cv.links} == {
        "https://www.linkedin.com/in/example/", "https://github.com/example",
    }
    assert {link.label for link in cv.links} == {"LinkedIn", "GitHub"}


@needs_chrome
def test_the_endpoint_returns_the_text_and_a_loadable_cv(rendered):
    response = client.post(
        "/api/import-pdf", files={"file": ("cv.pdf", rendered, "application/pdf")}
    )
    assert response.status_code == 200
    body = response.json()
    assert "JANE DOE" in body["text"]
    assert CV.model_validate(body["cv"]).name == "JANE DOE"


@needs_chrome
def test_text_recovered_from_a_pdf_is_still_only_ever_text(rendered):
    """A PDF is parsed, never rendered, and what it carries stays data."""
    hostile = json.loads(
        (Path(__file__).resolve().parents[1] / "static" / "example.json").read_text()
    )
    hostile["name"] = "<script>alert(1)</script>"
    hostile["uppercase_name"] = False  # so the recovered text can be compared as typed
    from render import render_pdf
    pdf = asyncio.run(render_pdf(build_document(CV.model_validate(hostile))))

    body = client.post(
        "/api/import-pdf", files={"file": ("cv.pdf", pdf, "application/pdf")}
    ).json()
    assert "<script>" in body["text"]  # recovered faithfully, as text
    preview = client.post("/api/preview", json=body["cv"])
    assert "<script>alert(1)</script>" not in preview.json()["html"]
