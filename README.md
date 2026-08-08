# cv-onepage

A CV as one HTML file, rendered to a **single-page PDF** — no pagination, no page
breaks cutting a job in half, text stays selectable and vector.

No LaTeX, no npm, no build step. You need Chrome and bash.

```bash
cp template.html cv.html   # then edit cv.html
./render.sh                # -> out/cv.pdf
```

## The trick

A CV is a continuous document, but PDF wants fixed pages. Most tools solve this
by paginating and hoping the breaks land somewhere sensible. This does the
opposite: it makes the page as tall as the content.

Chrome decides where to break using the `@page` size, and that size has to be
declared in CSS before printing. So the page measures itself first:

```js
const mm = document.documentElement.scrollHeight / 96 * 25.4 + 1;
const style = document.createElement("style");
style.textContent = "@page { size: 210mm " + mm.toFixed(2) + "mm; margin: 0; }";
document.head.appendChild(style);
```

`scrollHeight` is in CSS pixels, which are 1/96 inch, so dividing by 96 and
multiplying by 25.4 converts to millimetres. Chrome runs this on load, then
prints against the stylesheet it just received. Result: width stays A4, height
is whatever the CV needs, page count is always 1.

The `+ 1` millimetre absorbs sub-pixel rounding. Without it the last fraction of
a line spills onto a second page.

## Trade-offs

The output is A4-wide but as tall as it needs to be — around 700 mm for a dense
two-page CV. That is deliberate, and it costs you something:

- **It will not print on A4.** A printer scales it down or splits it.
- **Some job portals validate page dimensions** and may reject an unusual size.
  The text itself is real vector text, so ATS parsing is unaffected.

If you need a conventional multi-page A4 file, delete the `<script>` block at
the bottom of your `cv.html` and add `@page { size: A4; margin: 15mm; }`. Chrome
then paginates normally.

## Files

| File | What it does |
|---|---|
| `template.html` | The layout. Copy it to `cv.html` and write your own content. |
| `content-example.txt` | Plain-text skeleton of a CV. Fill it in, hand it plus the template to an LLM, get `cv.html` back. |
| `render.sh` | Renders every `cv*.html` in the folder to `out/`. |
| `stitch_cv.py` | Unrelated bonus — see below. |
| `photo.jpg` | Placeholder portrait. Replace with your own, ideally 400×400 or larger. |

Keeping several variants is the point: `cv.html`, `cv-backend.html`,
`cv-cz.html` all render in one go. `.gitignore` excludes `cv*.html` and `out/`
so your own CV never lands in a public repo by accident.

## Editing

The layout is a two-column flexbox with a hairline divider. Content classes:

- `.job` — one role. `h3` is the title, `.when` the dates, `.intro` an optional
  lead paragraph.
- `.group` — a labelled group of bullets inside a role. Optional.
- `.entry-title` / `.entry-meta` — sidebar entries with a date underneath.
- `<strong>` — inline emphasis for numbers and results.

The visual hierarchy relies on the gap above a job title (21px) being clearly
larger than the gap above a group label (12px). If you change one, change both,
or roles start to blur into the bullets above them.

Fonts are system-only (Avenir Next, then Helvetica Neue). Nothing is fetched at
render time, so output is byte-stable and works offline.

## stitch_cv.py

A separate tool for a separate problem: you have a CV rendered somewhere you
cannot export from, and only screenshots of it.

```bash
python3 stitch_cv.py out.pdf top.png middle.png bottom.png
```

It joins vertically overlapping screenshots into one tall image and writes it as
a single-page PDF. Overlap is detected by matching whole pixel rows — screenshots
of the same scrolled page render identically, so rows that repeat mark the seam.
Rows appearing more than four times are ignored, since borders and separator
lines repeat down the whole page and would otherwise vote for every alignment at
once.

Needs Pillow (`pip install pillow`). The output is a raster image in a PDF, so
prefer writing the HTML if you have the option.

## Licence

MIT
