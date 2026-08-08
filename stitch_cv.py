#!/usr/bin/env python3
"""Stitch vertically-overlapping screenshots into a single tall image and export
it as a one-page PDF.

Usage:
    python3 stitch_cv.py out.pdf img_top.png img_middle.png img_bottom.png

Images must be given in top-to-bottom reading order. Screenshots of the same
scrolled page render identically, so the overlap between two consecutive images
is found by matching whole rows: distinctive rows from the top of the next image
are looked up in the previous one, and the alignment with the most votes wins.
"""

import sys
from collections import Counter, defaultdict

from PIL import Image

# Rows flatter than this (max minus min sample) are too plain to identify an
# alignment on their own - blank margins would match almost anywhere.
MIN_ROW_CONTRAST = 40
# How far into the next image we look for rows to vote with.
PROBE_DEPTH = 900
# An alignment needs this many agreeing rows to be trusted.
MIN_VOTES = 12
# Rows repeating more often than this are structural (separator lines, borders)
# and would vote for every alignment at once, so they are ignored.
MAX_ROW_REPEATS = 4


def load(path):
    """Open an image as RGB, flattening any alpha channel onto white."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def row_keys(img):
    """Return one hashable key per row, or None for rows without contrast."""
    grey = img.convert("L")
    width, height = grey.size
    data = grey.tobytes()

    keys = []
    for y in range(height):
        row = data[y * width : (y + 1) * width]
        keys.append(row if max(row) - min(row) >= MIN_ROW_CONTRAST else None)
    return keys


def find_overlap(keys_a, keys_b):
    """Return how many rows at the top of B repeat the bottom of A."""
    positions = defaultdict(list)
    for y, key in enumerate(keys_a):
        if key is not None:
            positions[key].append(y)

    repeats_b = Counter(k for k in keys_b if k is not None)
    votes = Counter()
    for y_b, key in enumerate(keys_b[:PROBE_DEPTH]):
        if key is None or repeats_b[key] > MAX_ROW_REPEATS:
            continue
        rows_a = positions.get(key, ())
        if len(rows_a) > MAX_ROW_REPEATS:
            continue
        for y_a in rows_a:
            delta = y_a - y_b  # where B's row 0 sits inside A
            if 0 < delta < len(keys_a):
                votes[delta] += 1

    if not votes:
        return 0

    delta, count = votes.most_common(1)[0]
    if count < MIN_VOTES:
        return 0
    return len(keys_a) - delta


def stitch(paths):
    images = [load(p) for p in paths]

    width = max(im.width for im in images)
    images = [
        im
        if im.width == width
        else im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        for im in images
    ]

    keys = [row_keys(im) for im in images]

    pieces = [(images[0], 0)]
    for i in range(1, len(images)):
        overlap = find_overlap(keys[i - 1], keys[i])
        if overlap == 0:
            print(f"  WARNING: no overlap found before {paths[i]}, appending as is")
        else:
            print(f"  {paths[i - 1]} -> {paths[i]}: overlap {overlap}px")
        pieces.append((images[i], overlap))

    total_height = sum(im.height - cut for im, cut in pieces)
    canvas = Image.new("RGB", (width, total_height), "white")

    y = 0
    for im, cut in pieces:
        canvas.paste(im.crop((0, cut, width, im.height)), (0, y))
        y += im.height - cut

    return canvas


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    out, paths = sys.argv[1], sys.argv[2:]
    print(f"Stitching {len(paths)} images:")
    canvas = stitch(paths)
    print(f"Result: {canvas.width}x{canvas.height}px")

    canvas.save(out.replace(".pdf", ".png"), "PNG")

    # Scale to A4 width (595pt at 72dpi) so the PDF is one tall page.
    page_width = 595
    scale = page_width / canvas.width
    page_height = round(canvas.height * scale)

    canvas.save(out, "PDF", resolution=72.0 / scale)
    print(f"Wrote {out} - single page {page_width}x{page_height}pt")


if __name__ == "__main__":
    main()
