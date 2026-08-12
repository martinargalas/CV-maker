"""Reading the plain-text CV format that the CLI path uses.

`content-example.txt` is a fill-in-the-blanks CV: a name, a role, then sections
underlined with `=`. People arrive with one already filled in and should not
have to retype it into the form.

Parsing it is guesswork by nature — it is a text file people edit by hand, not
a format with a specification. So this module reads what it recognises, says
what it did not, and clamps anything oversized rather than refusing the whole
file. What comes out is a starting point for the form, not a final CV: the
result goes through the same model and the same escaping as anything typed in,
and the person can see and fix every field before rendering.

Headings are matched in English and Czech, and the ones it finds are carried
over as the CV's own section headings, so a Czech file produces a Czech CV.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import cvdoc

MAX_TEXT = 200_000

# The instructions at the bottom of content-example.txt, fenced off by a rule.
_CUT = re.compile(r"^-{10,}\s*$")
_UNDERLINE = re.compile(r"^=+\s*$")
_BULLET = re.compile(r"^[\s]*[••‣◦⁃*\-]\s+")

_MONTH = r"(?:[A-Za-zÀ-ž]{3,12}\.?\s+)?"
_UNTIL = r"(?:Present|Current|Now|Současnost|Dosud|Nyní)"
_DATE = re.compile(
    rf"^\s*{_MONTH}\d{{4}}\s*(?:[-–—]\s*(?:{_MONTH}\d{{4}}|{_UNTIL}))?\s*$",
    re.I,
)

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"^[\s+()\d./-]{7,}$")
_URL = re.compile(r"https?://\S+")

# Heading text -> which part of the CV it fills. Matched as substrings against
# a lower-cased, accent-stripped heading, so "Vzdělání" and "vzdelani" both hit.
_SECTIONS: List[Tuple[str, Tuple[str, ...]]] = [
    ("contact", ("personal information", "personal details", "contact", "osobni udaje",
                 "kontakt")),
    ("about", ("professional summary", "summary", "profile", "about me", "about",
               "profesionalni shrnuti", "shrnuti", "o mne", "profil")),
    ("education", ("education", "vzdelani")),
    ("skills", ("skills", "dovednosti", "znalosti")),
    ("links", ("websites", "social links", "links", "webove stranky", "odkazy")),
    ("languages", ("languages", "jazyky")),
    ("interests", ("hobbies", "interests", "konicky", "zajmy")),
    ("courses", ("courses", "certificat", "kurzy", "certifik")),
    ("work", ("employment", "work experience", "experience", "zamestnani", "praxe",
              "pracovni zkusenosti")),
]


def _fold(value: str) -> str:
    """Lower case, without accents, so Czech headings match without a table."""
    stripped = unicodedata.normalize("NFKD", value)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower().strip()


def _clean(line: str) -> str:
    return line.replace(" ", " ").strip()


def _debullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _paragraphs(lines: List[str]) -> List[List[str]]:
    """Split lines into blank-line-separated blocks."""
    blocks, current = [], []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


# ------------------------------------------------------------------ sections

def _split_sections(text: str) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Return the lines before the first heading, and (heading, lines) after."""
    lines = [_clean(line) for line in text.splitlines()]

    for index, line in enumerate(lines):
        if _CUT.match(line):
            lines = lines[:index]
            break

    # A file written to the documented format underlines its headings, and
    # those rules are then the only thing trusted — a job called "Education
    # Lead" must not become the education section. Only when a document has no
    # rules at all, which is what recovered text looks like, are headings
    # recognised by their wording.
    ruled = any(
        _UNDERLINE.match(later) and lines[index].strip()
        for index, later in enumerate(lines[1:])
    )

    preamble: List[str] = []
    sections: List[Tuple[str, List[str]]] = []
    heading: Optional[str] = None
    body: List[str] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        underlined = (
            line
            and index + 1 < len(lines)
            and _UNDERLINE.match(lines[index + 1])
        )
        is_heading = bool(underlined) or (not ruled and is_section_heading(line))
        if is_heading:
            if heading is None:
                preamble = body
            else:
                sections.append((heading, body))
            heading, body = line, []
            index += 2 if underlined else 1
            continue
        body.append(line)
        index += 1

    if heading is None:
        preamble = body
    else:
        sections.append((heading, body))
    return preamble, sections


def _section_key(heading: str) -> Optional[str]:
    folded = _fold(heading)
    for key, needles in _SECTIONS:
        if any(needle in folded for needle in needles):
            return key
    return None


# A heading with no rule under it has to be recognised by what it says, so it
# must be short, unpunctuated and one of the names we know.
MAX_BARE_HEADING = 45


def is_section_heading(line: str) -> bool:
    """Whether a line reads as a section heading on its own.

    Used for text that never had the `=` rules — a CV recovered from a PDF,
    say. It is deliberately strict: a long line, or one that ends a sentence,
    is prose no matter which words it contains.

    The name also has to account for most of the line. Without that, "A short
    line about what you do outside work" is an About heading, because it
    contains the word about, and it swallows the section it belongs to.
    """
    line = line.strip().rstrip(":").strip()
    if not line or len(line) > MAX_BARE_HEADING:
        return False
    if line.endswith((".", ",", ";", "!", "?")):
        return False

    folded = _fold(line)
    longest = max(
        (len(needle) for _, needles in _SECTIONS for needle in needles if needle in folded),
        default=0,
    )
    return bool(folded) and longest / len(folded) >= 0.5


# ------------------------------------------------------------- field readers

def _read_contact(lines: List[str], cv: Dict) -> None:
    for line in (_debullet(l) for l in lines if l.strip()):
        email = _EMAIL.search(line)
        if email and not cv["email"]:
            cv["email"] = email.group(0)
        elif _PHONE.match(line) and not cv["phone"]:
            cv["phone"] = line
        elif not cv["location"]:
            cv["location"] = line


def _read_links(lines: List[str]) -> List[Dict]:
    """Read "Label: https://..." rows, allowing for what a PDF does to them.

    A page break puts the label on one line and the address on the next, and a
    narrow column snaps a long address in half. Both are put back together
    here, since half a URL is a link that goes nowhere.
    """
    rows = [l.strip() for l in lines]
    links: List[Dict] = []

    def previous_label(at: int) -> str:
        for back in range(at - 1, -1, -1):
            if rows[back]:
                return rows[back][:-1].strip() if rows[back].endswith(":") else ""
        return ""

    index = 0
    while index < len(rows):
        line = rows[index]
        found = _URL.search(line) if line else None
        if not found:
            index += 1
            continue

        label = line[: found.start()].strip().rstrip(":").strip() or previous_label(index)

        url = found.group(0)
        # A continuation is the rest of an address the column was too narrow to
        # hold: one unbroken run of characters, on the very next line, that is
        # not the start of anything else. A blank line ends the address — past
        # that, the next word belongs to something other than this link.
        while index + 1 < len(rows):
            nxt = rows[index + 1]
            if not nxt or " " in nxt or _URL.search(nxt) or nxt.endswith(":"):
                break
            if _DATE.match(nxt) or len(nxt) > 60 or is_section_heading(nxt):
                break
            url += nxt
            index += 1

        links.append({"label": label, "url": url})
        index += 1
    return links


def _read_list(lines: List[str]) -> List[str]:
    """One item per line, except where a narrow column wrapped one in two.

    A continuation starts mid-sentence, so it opens with a lower-case letter
    and carries no marker of its own. Anything else starts a new item.
    """
    items: List[str] = []
    for line in (l for l in lines if l.strip()):
        continues = (
            items
            and not _BULLET.match(line)
            and line[:1].islower()
        )
        if continues:
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            items.append(_debullet(line))
    return items


def _read_entries(lines: List[str]) -> List[Dict]:
    """Education and courses: blocks of title / detail lines / a date."""
    entries: List[Dict] = []
    for block in _paragraphs(lines):
        block = [_debullet(l) for l in block]
        meta = ""
        if _DATE.match(block[-1]):
            meta = block.pop().strip()
        if not block:
            # A block that is only a date belongs to the entry above it. PDFs
            # put a gap there that the text format does not.
            if meta and entries and not entries[-1]["meta"]:
                entries[-1]["meta"] = meta
            continue
        entries.append({
            "title": block[0],
            "subtitle": ", ".join(block[1:]),
            "meta": meta,
        })
    return entries


# -------------------------------------------------------------------- jobs

def _looks_like_header_line(line: str) -> bool:
    """A title, employer or city line — short, and not a bullet or a label."""
    return bool(line) and len(line) <= 80 and not line.endswith(":") and not _BULLET.match(line)


def _read_jobs(lines: List[str]) -> List[Dict]:
    """Split the employment section on its date lines.

    A job's header is one to three short lines followed by a date range. The
    date is the reliable part — titles, employers and cities vary in how many
    lines they take, and the last entry in a real CV often has no city at all.
    """
    jobs: List[Dict] = []
    starts: List[Tuple[int, int]] = []  # (first header line, date line)

    for index, line in enumerate(lines):
        if not _DATE.match(line) or not line.strip():
            continue

        first, taken, blank_used = index, 0, False
        back = index - 1
        while back >= 0 and taken < 3:
            candidate = lines[back]
            if not candidate.strip():
                # A real CV sometimes leaves a gap between the title and the
                # date, with no employer or city in between. Step over one.
                if taken or blank_used:
                    break
                blank_used = True
                back -= 1
                continue
            if _DATE.match(candidate) or not _looks_like_header_line(candidate):
                break
            first, taken = back, taken + 1
            back -= 1

        if taken:
            starts.append((first, index))

    for order, (first, date_line) in enumerate(starts):
        end = starts[order + 1][0] if order + 1 < len(starts) else len(lines)
        header = [l for l in lines[first:date_line] if l.strip()]
        job = {
            "title": header[0] if header else "",
            "company": header[1] if len(header) > 1 else "",
            "city": ", ".join(header[2:]) if len(header) > 2 else "",
            "when": lines[date_line].strip(),
            "intro": "",
            "groups": [],
        }
        _read_job_body(lines[date_line + 1:end], job)
        jobs.append(job)
    return jobs


def _read_job_body(lines: List[str], job: Dict) -> None:
    blocks = _paragraphs(lines)
    if not blocks:
        return

    # Whether the first block is an intro or just unmarked bullets is the one
    # thing the format does not say, so it is guessed from shape:
    #
    #   one line, with more blocks after it        an intro
    #   a very long first line                     an intro, rest are bullets
    #   a first line in the width a text file      a wrapped sentence, so the
    #     wraps at, not ending a sentence            whole block is the intro
    #   anything else                              bullets
    #
    # It gets the common shapes right and the caller is told to check.
    first = blocks[0]
    opener = first[0]
    if not opener.endswith(":") and not _BULLET.match(opener):
        ends_sentence = opener.rstrip().endswith((".", "!", "?"))
        if len(first) == 1:
            if len(blocks) > 1 or len(opener) >= 120:
                job["intro"] = opener
                blocks = blocks[1:]
        elif len(opener) > 120:
            job["intro"] = opener
            blocks[0] = first[1:]
        elif 55 <= len(opener) <= 100 and not ends_sentence:
            job["intro"] = " ".join(first)
            blocks = blocks[1:]

    groups: List[Dict] = []
    for block in blocks:
        label = ""
        body = block
        if block[0].endswith(":"):
            label = _debullet(block[0])[:-1].strip()
            body = block[1:]
        bullets = [_debullet(l) for l in body if l.strip()]
        if label or bullets:
            groups.append({"label": label, "bullets": bullets})
    job["groups"] = groups


# ------------------------------------------------------------------- parse

def _clamp(items: List, limit: int, what: str, warnings: List[str]) -> List:
    if len(items) > limit:
        warnings.append(f"Kept the first {limit} of {len(items)} {what}.")
        return items[:limit]
    return items


# The model rejects anything longer than these, and a rejected import tells
# someone nothing about which line to shorten. Cut here instead and say so.
SHORT, LINE, PARA = 120, 300, 1500

_LIMITS = {
    "name": SHORT, "role": SHORT, "phone": SHORT, "email": SHORT, "location": SHORT,
    "meta": SHORT, "when": SHORT,
    "title": LINE, "subtitle": LINE, "company": LINE, "city": LINE, "label": LINE,
    "url": LINE,
    "about": PARA, "interests": PARA, "intro": PARA,
}


def _fit(cv: Dict, warnings: List[str]) -> None:
    cut = [0]

    def trim(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        cut[0] += 1
        return value[:limit].rstrip()

    def walk(node, limit_for_list: int):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    node[key] = trim(value, _LIMITS.get(key, LINE))
                else:
                    walk(value, PARA if key == "bullets" else LINE)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, str):
                    node[index] = trim(value, limit_for_list)
                else:
                    walk(value, limit_for_list)

    walk(cv, LINE)
    if cut[0]:
        warnings.append(f"{cut[0]} field(s) were longer than the form allows and were shortened.")


def parse(text: str) -> Tuple[Dict, List[str]]:
    """Turn the plain-text CV format into form data, plus notes on what it did."""
    warnings: List[str] = []
    if len(text) > MAX_TEXT:
        warnings.append("The file was very large; only the beginning was read.")
        text = text[:MAX_TEXT]

    cv: Dict = {
        "name": "", "role": "", "uppercase_name": True,
        "phone": "", "email": "", "location": "", "photo": "",
        "about": "", "education": [], "skills": [], "links": [],
        "languages": [], "interests": "", "courses": [], "jobs": [],
        "labels": {},
    }

    preamble, sections = _split_sections(text)
    headed = [l for l in preamble if l.strip()]
    if headed:
        cv["name"] = headed[0]
    if len(headed) > 1:
        cv["role"] = headed[1]

    for heading, lines in sections:
        key = _section_key(heading)
        if key is None:
            warnings.append(f"Section “{heading}” was not recognised and was skipped.")
            continue

        # Carry the file's own wording over as the CV's section heading, so a
        # Czech file does not come out with English headings.
        if key != "contact":
            cv["labels"][key] = heading[:120]
        else:
            cv["labels"]["contact"] = heading[:120]

        if key == "contact":
            _read_contact(lines, cv)
        elif key == "about":
            cv["about"] = " ".join(l for l in lines if l.strip())
        elif key == "interests":
            cv["interests"] = " ".join(l for l in lines if l.strip())
        elif key == "education":
            cv["education"] = _read_entries(lines)
        elif key == "courses":
            cv["courses"] = _read_entries(lines)
        elif key == "skills":
            cv["skills"] = _read_list(lines)
        elif key == "languages":
            cv["languages"] = _read_list(lines)
        elif key == "links":
            cv["links"] = _read_links(lines)
        elif key == "work":
            cv["jobs"] = _read_jobs(lines)

    cv["education"] = _clamp(cv["education"], cvdoc.MAX_ENTRIES, "education entries", warnings)
    cv["courses"] = _clamp(cv["courses"], cvdoc.MAX_ENTRIES, "courses", warnings)
    cv["skills"] = _clamp(cv["skills"], cvdoc.MAX_SKILLS, "skills", warnings)
    cv["languages"] = _clamp(cv["languages"], cvdoc.MAX_LANGUAGES, "languages", warnings)
    cv["links"] = _clamp(cv["links"], cvdoc.MAX_LINKS, "links", warnings)
    cv["jobs"] = _clamp(cv["jobs"], cvdoc.MAX_JOBS, "jobs", warnings)
    for job in cv["jobs"]:
        job["groups"] = _clamp(job["groups"], cvdoc.MAX_GROUPS, "groups in a job", warnings)
        for group in job["groups"]:
            group["bullets"] = _clamp(group["bullets"], cvdoc.MAX_BULLETS, "bullets", warnings)

    if not cv["jobs"]:
        warnings.append("No jobs were found — check that the employment section is present "
                        "and that each job ends its heading with a date line.")

    _fit(cv, warnings)
    return cv, warnings
