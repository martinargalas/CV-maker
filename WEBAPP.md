# Web app — build spec

Turn the CLI renderer into a self-hosted web app, so people who won't open a
terminal can use it.

**Built.** It lives in `web/`; see *Running the web app* in README.md. This
file is kept as the brief it was written as, so the decisions below can be
checked against what was actually built.

Three things were then asked for that this brief rules out. README.md is the
accurate description; where the two disagree, believe the README.

- **Accounts and saved CVs exist.** The brief put them out of scope and said
  nothing is stored on the server. There is now a landing page of saved CVs,
  which needs somewhere to save them and somebody to own them.
- **The plain-text format can be imported.** The brief left it to the CLI.
- **The compose file is at the repository root**, not in `web/`, because that
  is where deployment tools look for it.

What did not change: the form never shows anybody HTML, the template is still
shared with the CLI rather than forked, and the security rules below still hold
line for line.

## What it does

One page. You fill in your CV, you press a button, a PDF downloads. No account,
no login, nothing saved on the server.

## The decision that shapes everything

**Form, not HTML editor.**

The CLI already serves people who can edit HTML. The web app exists for people
who can't — so it must never show them markup. Structured fields (name, role,
contact, then repeatable blocks for jobs, skills, education), and the server
builds the HTML from `template.html`.

Consequence: the template stops being a file people edit and becomes a rendering
target with named slots. Keep `template.html` working standalone for CLI users;
the app fills the same structure programmatically.

## Scope

In:

- Form with repeatable sections (add/remove a job, a skill, a bullet)
- Photo upload, resized server-side
- Live preview of the layout
- Render → PDF download
- Export/import the filled form as a JSON file, so people can keep their data and
  come back later without the server storing anything

Out, at least for v1:

- Accounts, saved CVs, any database
- Multiple visual themes
- LLM integration or anything needing an API key
- Editing the plain-text format from `content-example.txt` — that's the CLI path

## Stack

Single container: Python web server plus Chromium. One `Dockerfile`, one
`docker-compose.yml`, `docker compose up` and it runs.

FastAPI or Flask, whichever ends up smaller. The renderer is the existing Chrome
headless call — reuse the flags in `render.sh` verbatim, including the
`file://` absolute-path requirement.

## Security — read before writing the render endpoint

The server renders user-supplied content in a browser. Treat every field as
hostile.

- **Never render user HTML directly.** Build the document from the template and
  escape every field. If a raw-HTML mode is ever added, it needs a separate,
  sandboxed path.
- **Strip user scripts.** The page needs exactly one script — the one measuring
  its own height for `@page`. The server injects that. Nothing else runs.
- **Block local file reads and outbound requests.** Headless Chrome will happily
  fetch `file:///etc/passwd` into an `<img>` or call out to a URL someone puts in
  a field. Render with no network access, and don't hand it a file path derived
  from user input. Uploaded photos: re-encode server-side, never pass through.
- **Cap it.** Upload size, field lengths, number of repeated blocks, render
  timeout, and a concurrency limit — one Chromium per request, and a browser
  process is expensive.
- **Delete temp files after the response**, including on failure.

Expect people to run this exposed to the internet, not just on a homelab. Write
it so that's safe by default.

## Repo layout

```
web/                 the app — new
  app.py
  templates/
  static/
  Dockerfile
  docker-compose.yml
template.html        shared with CLI, gains named slots
render.sh            unchanged; CLI path stays working
```

The CLI must keep working with no web app installed. Two doors into the same
renderer.

## Done when

Someone who has never used a terminal can run one `docker compose up` command
from the README, open `localhost`, fill in a form, and download a CV that looks
identical to the CLI output.
