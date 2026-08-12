"""Getting the text back out of a CV that only exists as a PDF.

A PDF describes where glyphs sit on a page, not what the document means, so
this is recovery rather than conversion. Three things have to be undone before
the text reads like a CV again:

  - **Columns.** A two-column CV interleaves into nonsense if the page is read
    line by line, so the gutter is found and each column is read in turn.
  - **Letter spacing.** Headings set with wide tracking come out as
    "C  O  N  T  A  C  T". The gaps between letters are smaller than the gaps
    between words, which is enough to put them back together.
  - **Ligatures.** "ﬁ" and "ﬂ" are single glyphs in the file and single
    characters in the text; normalising turns them back into letters.

What comes out is shown to the person to correct before it becomes a CV. This
never produces a finished import on its own and is not meant to.
"""

from __future__ import annotations

import io
import re
import statistics
import unicodedata
from typing import List, Optional, Tuple

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from textimport import is_section_heading

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10
MAX_CHARS = 200_000

# Below this, there is no text worth parsing and the file is almost certainly
# a scan — a picture of a CV rather than a CV.
MIN_USEFUL_CHARS = 120

# The template draws list markers as a "-" in a pseudo-element, and other CVs
# use bullets of their own. They come through as text and are not content.
_MARKER = re.compile(r"^[\s]*[-–—••‣◦⁃*]\s+")


class PdfError(ValueError):
    """A file we cannot read. The message is safe to show."""


def _is_tracked(line: str) -> bool:
    """Whether a line is set with letters spaced apart, like a heading."""
    tokens = line.split()
    return len(tokens) >= 4 and sum(len(t) == 1 for t in tokens) / len(tokens) >= 0.7


def _despace(line: str) -> str:
    """Undo letter spacing, leaving ordinary lines alone.

    In a tracked-out heading the gaps between letters are all about the same
    size and the gaps between words are visibly larger, so the run lengths
    themselves say where the words are. This runs after the columns have been
    read apart, so a line here only ever holds one column's worth of text.
    """
    if not _is_tracked(line):
        return line

    body = line.strip()
    runs = [len(gap) for gap in re.findall(r" +", body)]
    if not runs:
        return line

    threshold = int(max(2 * statistics.median(runs), min(runs) + 1))
    words = [chunk.replace(" ", "") for chunk in re.split(rf" {{{threshold},}}", body)]
    return " ".join(word for word in words if word)


def _gutter(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Find the blank vertical channel between two columns, if there is one.

    A gutter is a range of character positions that is blank on every line that
    reaches across it. Text that happens to be short does not count as evidence,
    which is why only lines longer than the candidate position are consulted.
    """
    # Tracked-out headings are mostly spaces, so they would vote for a blank
    # channel almost anywhere. They are still split by whatever gutter the rest
    # of the page agrees on — they just do not get to choose it.
    body = [line for line in lines if line.strip() and not _is_tracked(line)]
    if len(body) < 8:
        return None

    width = max(len(line) for line in body)
    if width < 60:
        return None

    blank: List[bool] = []
    for column in range(width):
        reaching = [line for line in body if len(line) > column]
        if len(reaching) < 4:
            blank.append(False)
            continue
        blank.append(all(line[column] == " " for line in reaching))

    # The widest blank channel that starts somewhere in the middle of the page.
    best: Optional[Tuple[int, int]] = None
    start = None
    for column, is_blank in enumerate(blank + [False]):
        if is_blank and start is None:
            start = column
        elif not is_blank and start is not None:
            if column - start >= 5 and 0.25 * width < start < 0.8 * width:
                if best is None or (column - start) > (best[1] - best[0]):
                    best = (start, column)
            start = None
    return best


def _header_end(lines: List[str], left_end: int, right_start: int) -> int:
    """Where the columns start, and the full-width header above them ends.

    A name and a role run across the whole sheet, so cutting them at the gutter
    would leave "ENGINEE" in one column and "RING MANAGER" in the other. The
    columns are taken to begin at the first line that carries a section heading
    on its left-hand side.
    """
    for index, line in enumerate(lines):
        left = _despace(line[:left_end]).strip()
        if left and line[right_start:].strip() and is_section_heading(left):
            return index
    return 0


def _columns(text: str) -> str:
    """Read a two-column page one column at a time, or leave it as it is."""
    lines = text.splitlines()
    found = _gutter(lines)
    if found is None:
        return "\n".join(_despace(line) for line in lines)

    left_end, right_start = found
    split_at = _header_end(lines, left_end, right_start)

    header = lines[:split_at]
    body = lines[split_at:]

    # A tracked-out heading is wider than the words it spells, so one sitting
    # in the left column often reaches past the gutter's near edge — cutting
    # there costs it its last letter and stops it being a heading at all.
    # Cutting at the far edge keeps it whole and still separates two headings
    # that share a line.
    left = [line[: (right_start if _is_tracked(line) else left_end)] for line in body]
    right = [line[right_start:] for line in body]

    # A column that turned out to hold almost nothing means the guess was
    # wrong; the page is better read as it was.
    if sum(bool(l.strip()) for l in left) < 3 or sum(bool(r.strip()) for r in right) < 3:
        return "\n".join(_despace(line) for line in lines)

    parts = [header, left, right]
    return "\n\n".join(
        "\n".join(_despace(line).rstrip() for line in part) for part in parts if part
    )


def _unpick(text: str) -> str:
    """Fix the glyphs, and nothing that would move anything.

    Positions have to survive until the columns are worked out, so this only
    swaps characters for characters. NFKC turns the ﬁ and ﬂ ligatures back into
    the letters they stand for, and both are one character before and after.
    """
    return "\n".join(
        unicodedata.normalize("NFKC", line).rstrip() for line in text.splitlines()
    )


def _tidy(text: str) -> str:
    # Safe to squeeze runs of spaces now: the columns have already been read
    # apart, so what is left inside a line is padding rather than position.
    out = [re.sub(r"\s{2,}", " ", _MARKER.sub("", line)).strip() for line in text.splitlines()]

    # Collapse runs of blank lines, so the paragraph shapes the text parser
    # relies on survive.
    tidied: List[str] = []
    for line in out:
        if line or (tidied and tidied[-1]):
            tidied.append(line)
    return "\n".join(tidied).strip()


def to_text(raw: bytes) -> str:
    """Pull readable text out of a PDF, or say why that is not possible."""
    if len(raw) > MAX_BYTES:
        raise PdfError(f"That PDF is larger than {MAX_BYTES // 1024 // 1024} MB.")
    if not raw:
        raise PdfError("Empty file.")

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            # A blank password covers PDFs that are only protected against
            # editing, which is most of them.
            try:
                reader.decrypt("")
            except Exception:
                raise PdfError("That PDF is password-protected.")
        pages = reader.pages[:MAX_PAGES]
        chunks = [
            _columns(_unpick(page.extract_text(extraction_mode="layout") or ""))
            for page in pages
        ]
    except PdfError:
        raise
    except (PdfReadError, Exception):
        raise PdfError("That file could not be read as a PDF.")

    text = _tidy("\n\n".join(chunks))[:MAX_CHARS]

    if len(text) < MIN_USEFUL_CHARS:
        raise PdfError(
            "There is no text in that PDF — it looks like a scan or a picture of "
            "a CV. Reading text out of an image is not something this app does."
        )
    return text
