"""The CV data model, and the builder that turns it into an HTML document.

Everything a user types arrives here as data and leaves as escaped text. This
module is the only place that produces CV markup, so it is the only place that
has to be right about escaping.

Two rules hold throughout:

  - No value from the model is ever interpolated into markup without going
    through `_text` or `_rich`, both of which escape first.
  - The document references no external resource. The photo is a data: URI the
    server produced itself; links become href values only after passing a
    scheme allowlist, and are never fetched while printing.
"""

from __future__ import annotations

import html
import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import Annotated
from pydantic import StringConstraints

TEMPLATE = Path(__file__).resolve().parent.parent / "template.html"

# Caps. These bound both the render cost and how much a hostile payload can
# weigh; the form in the browser enforces the same numbers for feedback, but
# these are the ones that count.
MAX_JOBS = 20
MAX_GROUPS = 12
MAX_BULLETS = 20
MAX_SKILLS = 40
MAX_ENTRIES = 15
MAX_LINKS = 10
MAX_LANGUAGES = 15
MAX_PHOTO_CHARS = 700_000  # base64 of a re-encoded 400x400 JPEG, with headroom

Short = Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]
Line = Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]
Para = Annotated[str, StringConstraints(max_length=1500, strip_whitespace=True)]


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Short = ""
    # Longer than the other short fields: profile URLs carrying a tracking tail
    # are common, and truncating a URL leaves a link that goes nowhere.
    url: Line = ""


class Entry(BaseModel):
    """One education or course row: a title line, an optional second line, a date."""

    model_config = ConfigDict(extra="forbid")
    title: Line = ""
    subtitle: Line = ""
    meta: Short = ""


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Line = ""
    bullets: List[Para] = Field(default_factory=list, max_length=MAX_BULLETS)


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Line = ""
    company: Line = ""
    city: Line = ""
    when: Short = ""
    intro: Para = ""
    groups: List[Group] = Field(default_factory=list, max_length=MAX_GROUPS)


class Labels(BaseModel):
    """Section headings, so a CV can be written in a language other than English."""

    model_config = ConfigDict(extra="forbid")
    contact: Short = "Contact"
    about: Short = "About Me"
    education: Short = "Education"
    skills: Short = "Skills"
    links: Short = "Links"
    languages: Short = "Languages"
    interests: Short = "Interests"
    courses: Short = "Courses"
    work: Short = "Work Experience"


class CV(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Short = ""
    role: Short = ""
    uppercase_name: bool = True

    phone: Short = ""
    email: Short = ""
    location: Short = ""

    photo: str = Field(default="", max_length=MAX_PHOTO_CHARS)

    about: Para = ""
    education: List[Entry] = Field(default_factory=list, max_length=MAX_ENTRIES)
    skills: List[Line] = Field(default_factory=list, max_length=MAX_SKILLS)
    links: List[Link] = Field(default_factory=list, max_length=MAX_LINKS)
    languages: List[Line] = Field(default_factory=list, max_length=MAX_LANGUAGES)
    interests: Para = ""
    courses: List[Entry] = Field(default_factory=list, max_length=MAX_ENTRIES)

    jobs: List[Job] = Field(default_factory=list, max_length=MAX_JOBS)

    labels: Labels = Field(default_factory=Labels)

    @field_validator("photo")
    @classmethod
    def _photo_is_our_own_jpeg(cls, v: str) -> str:
        """Only accept the exact shape /api/photo emits.

        The bytes are decoded and re-encoded again before rendering; this check
        exists so a malformed or foreign URI is rejected early and loudly.
        """
        if not v:
            return v
        if not re.fullmatch(r"data:image/jpeg;base64,[A-Za-z0-9+/]+={0,2}", v):
            raise ValueError("photo must be a base64 image/jpeg data URI from /api/photo")
        return v


# ---------------------------------------------------------------- escaping

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def _text(value: str) -> str:
    """Plain escaped text. The only way a user string becomes markup."""
    return html.escape(value.strip(), quote=True)


def _rich(value: str) -> str:
    """Escaped text, then `**this**` turned into <strong>this</strong>.

    Escaping runs first, so by the time the emphasis pattern is applied there
    are no angle brackets left in the string and the only tags that can exist
    are the ones added on this line.
    """
    return _BOLD.sub(r"<strong>\1</strong>", _text(value))


def _url(value: str) -> str:
    """An http(s) URL, or empty. Anything else — javascript:, data:, file: — is dropped."""
    value = value.strip()
    if re.fullmatch(r"https?://[^\s<>\"']{1,300}", value, re.I):
        return html.escape(value, quote=True)
    return ""


def _join(*parts: str) -> str:
    return ", ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------- fragments

# Copied from the template so the web output uses the same glyphs as the CLI one.
_ICONS = {
    "phone": '<svg width="10" height="10" viewBox="0 0 24 24" fill="#6b6c70"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.2.2 2.4.6 3.6.1.3 0 .7-.2 1l-2.3 2.2z"/></svg>',
    "email": '<svg width="10" height="10" viewBox="0 0 24 24" fill="#6b6c70"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4-8 5-8-5V6l8 5 8-5v2z"/></svg>',
    "location": '<svg width="10" height="10" viewBox="0 0 24 24" fill="#6b6c70"><path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/></svg>',
}


def _section(heading: str, body: str) -> str:
    """A sidebar or main section, or nothing at all if it has no content."""
    if not body.strip():
        return ""
    return f"<section>\n<h2>{_text(heading)}</h2>\n{body}\n</section>"


def _header(cv: CV) -> str:
    name = cv.name.upper() if cv.uppercase_name else cv.name
    out = []

    # The template sets h1 to 35px with white-space: nowrap, which a long name
    # overflows. Shrink past the width the sample name occupies rather than let
    # it run off the sheet.
    style = ""
    if len(name) > 20:
        scale = max(0.55, 20 / len(name))
        style = f' style="font-size:{35 * scale:.1f}px;letter-spacing:{4.4 * scale:.2f}px"'
    if name:
        out.append(f"<h1{style}>{_text(name)}</h1>")
    if cv.role:
        out.append(f'<p class="role">{_text(cv.role)}</p>')
    if cv.photo:
        out.append(f'<img class="photo" src="{html.escape(cv.photo, quote=True)}" alt="">')
    return "\n".join(out)


def _contact(cv: CV) -> str:
    rows = []
    for kind, value in (("phone", cv.phone), ("email", cv.email), ("location", cv.location)):
        if value:
            rows.append(
                f'<div class="contact-row">\n{_text(value)}\n'
                f'<span class="icon">{_ICONS[kind]}</span>\n</div>'
            )
    return "\n".join(rows)


def _entries(items: List[Entry]) -> str:
    out = []
    for item in items:
        title = _join(item.title, item.subtitle)
        if not title and not item.meta:
            continue
        if title:
            out.append(f'<p class="entry-title">{_text(title)}</p>')
        if item.meta:
            out.append(f'<p class="entry-meta">{_text(item.meta)}</p>')
    return "\n".join(out)


def _bullet_list(items: List[str]) -> str:
    items = [i for i in items if i.strip()]
    if not items:
        return ""
    body = "\n".join(f"<li>{_rich(i)}</li>" for i in items)
    return f"<ul>\n{body}\n</ul>"


def _links(items: List[Link]) -> str:
    out = []
    for item in items:
        url = _url(item.url)
        if not url:
            continue
        label = _text(item.label) or url
        out.append(f'<p>{label}:<br><a href="{url}">{url}</a></p>')
    return "\n".join(out)


def _side(cv: CV) -> str:
    lab = cv.labels
    sections = [
        _section(lab.contact, _contact(cv)),
        _section(lab.about, f"<p>{_rich(cv.about)}</p>" if cv.about else ""),
        _section(lab.education, _entries(cv.education)),
        _section(lab.skills, _bullet_list(cv.skills)),
        _section(lab.links, _links(cv.links)),
        _section(lab.languages, _bullet_list(cv.languages)),
        _section(lab.interests, f"<p>{_rich(cv.interests)}</p>" if cv.interests else ""),
        _section(lab.courses, _entries(cv.courses)),
    ]
    return "\n\n".join(s for s in sections if s)


def _job(job: Job) -> str:
    out = []
    title = _join(job.title, job.company, job.city)
    if title:
        out.append(f"<h3>{_text(title)}</h3>")
    if job.when:
        out.append(f'<p class="when">{_text(job.when)}</p>')
    if job.intro:
        out.append(f'<p class="intro">{_rich(job.intro)}</p>')

    for group in job.groups:
        bullets = _bullet_list(group.bullets)
        if not bullets and not group.label:
            continue
        if group.label:
            out.append(f'<p class="group">{_text(group.label)}</p>')
        if bullets:
            out.append(bullets)

    if not out:
        return ""
    body = "\n".join(out)
    return f'<div class="job">\n{body}\n</div>'


def _main(cv: CV) -> str:
    jobs = "\n\n".join(j for j in (_job(job) for job in cv.jobs) if j)
    return _section(cv.labels.work, jobs)


# ---------------------------------------------------------------- assembly

_SLOT = "<!--slot:{name}-->"
_SLOT_END = "<!--/slot:{name}-->"


@lru_cache(maxsize=1)
def _template() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    for name in ("title", "header", "side", "main"):
        if _SLOT.format(name=name) not in text or _SLOT_END.format(name=name) not in text:
            raise RuntimeError(
                f"{TEMPLATE} is missing the '{name}' slot markers; the web app "
                f"cannot fill a template it does not recognise"
            )
    if text.count("<script") != 1:
        raise RuntimeError(f"{TEMPLATE} must contain exactly one <script>, the page-height one")
    return text


def _fill(doc: str, name: str, content: str) -> str:
    start, end = _SLOT.format(name=name), _SLOT_END.format(name=name)
    head, _, rest = doc.partition(start)
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n{content}\n{end}{tail}"


def build_document(cv: CV) -> str:
    """Render the model into a complete, self-contained HTML document.

    The result loads nothing from the network or the filesystem, and runs no
    script other than the template's own page-height measurement.
    """
    nonce = secrets.token_urlsafe(16)
    doc = _template()

    doc = _fill(doc, "title", _text(cv.name or "CV"))
    doc = _fill(doc, "header", _header(cv))
    doc = _fill(doc, "side", _side(cv))
    doc = _fill(doc, "main", _main(cv))

    # Belt and braces. Every field is escaped above, so no user script or user
    # URL should exist in this document at all; this policy means that if one
    # ever did, the browser still would not run it or fetch anything for it.
    csp = (
        "default-src 'none'; "
        "img-src data:; "
        "style-src 'unsafe-inline'; "
        f"script-src 'nonce-{nonce}'; "
        "base-uri 'none'; "
        "form-action 'none'"
    )
    doc = doc.replace(
        '<meta charset="utf-8">',
        f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{csp}">',
        1,
    )
    doc = doc.replace("<script>", f'<script nonce="{nonce}">', 1)
    return doc
