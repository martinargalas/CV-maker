# CV maker

Make a good-looking CV as a **single-page PDF** — one continuous page, so no job
gets cut in half by a page break.

You don't need to know how to code. You need Chrome and about ten minutes.

<img src="preview.png" alt="A two-column CV: name and photo at the top, contact
details and skills down the left, work history on the right." width="420">

## What you get

- **One page, however long your CV is.** No awkward breaks, no half a job at the
  bottom of page 1.
- **Real text, not a picture.** Recruiters' systems can read it, and so can
  search. You can select and copy from it.
- **Sharp at any zoom, and tiny.** Usually around 130 KB.
- **Yours.** No account, no subscription, no watermark, no site that locks the
  download behind a paywall.

## Two ways to use this

**Edit a file, run a script.** The steps below. You need Chrome and about ten
minutes, and you end up editing a bit of HTML.

**Fill in a form in your browser.** If editing HTML is not for you, run the web
app instead: one command, a form, a *Download PDF* button. Same renderer, same
result — see [Running the web app](#running-the-web-app).

## Before you start

You need **Google Chrome** installed. That's it. (Chromium and Edge also work.)

On Windows, run the commands below in Git Bash or WSL.

## Making your CV

**1. Download this project.** Green *Code* button above → *Download ZIP* →
unzip it. Open a terminal in that folder.

**2. Write your content.** Open `content-example.txt` in any text editor. It's a
fill-in-the-blanks CV — name, contact, skills, jobs. Replace the placeholder
text with your own and save it.

**3. Turn it into a CV.** Two ways:

> **The easy way.** Open ChatGPT or Claude. Attach your filled-in text file and
> `template.html`, and ask:
>
> *"Build my CV from this text using this template. Keep the template's layout
> and styling, only replace the content. Give me back the complete HTML file."*
>
> Save what it gives you as `cv.html` in this folder.

> **By hand.** Copy `template.html` to `cv.html` and type your details over the
> placeholder text. It's ordinary HTML — if you can edit a web page, you can
> edit this. The example content shows you what goes where.

**4. Render it.**

```bash
./render.sh
```

Your PDF appears in the `out` folder. Done.

Changed something? Run `./render.sh` again. It takes a second.

## Your photo

Replace `photo.jpg` with your own, keeping the same filename. Square works best
— 400×400 pixels or larger. A smaller one will look soft when printed.

Don't want a photo? Delete this line from your `cv.html`:

```html
<img class="photo" src="photo.jpg" alt="">
```

## Several versions of your CV

Applying for different kinds of roles usually means different CVs. Just make
more files — `cv.html`, `cv-manager.html`, `cv-czech.html` — and run
`./render.sh` once. It renders all of them.

Your own files never end up in this project's history if you publish it
somewhere; they're excluded automatically.

## Two things to know before you send it

**It won't print nicely on A4.** The page is as tall as your CV, so a printer
either shrinks it or splits it across sheets. For sending by email or uploading,
that's fine. For handing someone a printed copy, see below.

**A few job portals check page size** and may complain about an unusual one.
Rare, but if a site rejects the file, that's the reason.

Need an ordinary multi-page A4 file instead? Open your `cv.html`, delete the
`<script>` block at the very bottom, and add this line just above `</style>`:

```css
@page { size: A4; margin: 15mm; }
```

Render again and you'll get a normal paginated PDF.

## If something goes wrong

| What you see | What to do |
|---|---|
| `No Chrome/Chromium found` | Install Google Chrome, or run `CHROME=/path/to/chrome ./render.sh` |
| `No cv*.html found` | You skipped step 3 — there's no `cv.html` in the folder yet |
| `WARNING: expected a single page` | Rare. Tell us in an issue and include your `cv.html` |
| `permission denied` running the script | Run `chmod +x render.sh` once |
| Photo looks blurry | Use a bigger image — 400×400 or more |
| Your text isn't showing up | You edited `template.html` instead of `cv.html` |

## Only have screenshots of an old CV?

If your CV is stuck in a tool you can't export from, `stitch_cv.py` joins
scrolling screenshots back into one PDF:

```bash
python3 stitch_cv.py out.pdf top.png middle.png bottom.png
```

Give it the screenshots top to bottom; overlap between them is fine and gets
removed automatically. Needs Pillow (`pip install pillow`).

This gives you a picture of a CV, not real text — recruiters' systems can't read
it. Use it to recover old content, then write it properly using the steps above.

## Running the web app

A small self-hosted site: you fill in a form, press a button, a PDF downloads.
Meant for a home network — you run it, you and the people you live with have
accounts on it, nobody else does.

Making a CV needs no account. An account is only for keeping CVs on the server
so you can come back to them later.

You need **Docker**. Nothing else — the container brings its own browser, so
you do not need Chrome for this route.

```bash
docker compose up --build
```

Then open **http://localhost:8000**. The first build takes a few minutes; after
that it starts in seconds. Stop it with Ctrl-C.

### What you can do there

- Fill in name, contact, summary, jobs, education, skills, links, languages,
  courses. Jobs hold groups of bullets; every list has *add* and *remove*.
- Upload a photo. It is resized and re-encoded as you upload it.
- Watch the layout update as you type.
- Rename the section headings, or translate them — the CV does not have to be
  in English.
- **Download PDF** gives you the same single-page file `./render.sh` produces.
- **Save** keeps the CV in your account, so it is waiting on the front page next
  time. Needs an account; everything else here does not.
- **Import text or PDF** fills in the form from a CV you already have. Paste the
  plain-text format from `content-example.txt`, pick a `.txt` file, or hand it
  the PDF of your current CV.
- **Reorder** jobs and groups of bullets with the ↑ and ↓ buttons on each block.
- **Show how long each job lasted** — a switch under *Work experience* adds
  `(1 year 7 months)` after the dates, worded in English or Czech. It is worked
  out from the dates when the CV is drawn, so a job still running keeps
  counting, and a date line it cannot read is left exactly as you typed it.
- **Export JSON** saves your answers to your own computer; **Import JSON** reads
  them back. Worth doing even with an account: it is a copy that does not depend
  on this server still being there.

To emphasise part of a bullet, wrap it in stars: `**like this**`. You never
have to type HTML.

Importing is a best guess, not a conversion. The text format does not mark
which paragraph is a job's intro and which lines are bullets, so check each job
afterwards; anything not recognised is listed rather than dropped silently.

**Importing a PDF is recovery, and it shows.** A PDF records where each letter
sits on the page, not what the words mean, so the app has to work out the
columns, put letter-spaced headings back together and rejoin addresses the page
broke in half. It gets the common shapes right and it will get some things
wrong, which is why the recovered text lands in a box for you to correct before
it becomes a CV rather than going straight into the fields.

Two limits worth knowing. A **scanned** PDF — a photograph or scan rather than
text — cannot be read at all, and the app says so instead of producing nonsense;
there is no OCR here. And a CV laid out in some way this has not met may come
back out of order, in which case fixing the text in the box is quicker than
fixing forty form fields afterwards.

### Accounts

The **first account created becomes the administrator.** Make yours as soon as
the app is up, before anyone else can. From *Admin* they can add people, reset a
forgotten password, remove an account, and turn off self-service signup once
everybody who needs an account has one.

An administrator manages accounts, not what is in them. There is no route that
hands anybody another person's CV, so setting the server up for your household
does not come with reading everyone's CV.

### What the server keeps

**Saved CVs and accounts, and nothing else.** They live in one SQLite file on
the `cv-data` volume:

- **CVs you saved**, in full, including the photo. Only ever readable by the
  account that saved them.
- **Accounts**: a username and a scrypt hash of the password. Passwords are not
  stored and cannot be recovered — a forgotten one is reset, not looked up.
- **Sessions**, as digests. The cookie holds a random token; the table holds its
  SHA-256, so reading the database does not let anyone sign in as you.

Everything else is still kept nowhere. A CV you do not save exists only for the
length of the request. Request logging is off by default, the PDF is sent under
the fixed filename `cv.pdf` rather than your name, and the rate limiter counts
against a salted digest rather than storing addresses.

**Back up the volume.** It is the only thing here that cannot be rebuilt, and
`docker compose down -v` deletes it along with the stack.

```bash
docker compose exec cv-maker sh -c 'cat /data/cv.db' > cv-backup.db
```

### Putting it on the internet

**It is published on every interface by default.** A stack deployed on a server
that nobody can open is a broken stack, so the port is exposed rather than
hidden behind a setting people have to find. What keeps it safe is the app and
whatever you put in front of it — so put a reverse proxy with HTTPS there, and
do not rely on the app being the only thing between the internet and your
server. To keep it to the machine it runs on instead, set `CV_BIND=127.0.0.1`.

Four things to know:

- **Set `SIGNUP_CODE`, or turn signup off.** On a home network anyone who can
  reach the app may create an account, which is the point. Reachable from
  anywhere else, that means anyone at all — so either set a code, or make your
  own account and switch signup off from the admin page.
- **Sign-in over plain http sends the password in the clear.** On your own
  network that is a judgement call; over the internet it is not — terminate
  HTTPS in front of it. The session cookie marks itself Secure as soon as the
  request arrives over https, including via a proxy that says so.
- **Anyone who can reach the port can render a CV on your server**, with or
  without an account. The render timeout, the concurrency limit and the rate
  limit are what stop that from being a way to exhaust the machine; lower them
  if it is somewhere busy, and do not raise them without a reason.
- **Set `TRUST_PROXY: "1"` only when a proxy in front actually sets
  `X-Forwarded-For`.** Turning it on without one lets anybody forge the header
  and walk past the rate limit.
- **Chromium runs without its own sandbox**, because that needs privileges the
  compose file deliberately refuses. The container is the boundary instead: no
  root, no capabilities, no new privileges, a read-only filesystem and a tmpfs
  for the one directory anything writes to. Keep those settings.

The renderer treats every field as hostile: text is escaped rather than
interpreted, the only script in the document is the one that measures the page
height, links that are not `http://` or `https://` are dropped, name resolution
is broken inside the browser so nothing can call out, and uploaded images are
decoded and re-encoded rather than passed through. `web/tests/test_security.py`
is the checklist, and it runs in a couple of seconds:

```bash
cd web && pip install -r requirements.txt pytest && python -m pytest
```

### Settings

Change these under `environment:` in `docker-compose.yml`, or set them as your
deployment tool's environment variables.

| Setting | Default | What it does |
|---|---|---|
| `RENDER_TIMEOUT` | `20` | Seconds before a stuck render is killed |
| `MAX_CONCURRENT_RENDERS` | `2` | Browsers allowed at once — each one is expensive |
| `RATE_LIMIT_PER_MINUTE` | `30` | Requests per visitor per minute |
| `MAX_BODY_BYTES` | `3145728` | Largest request accepted |
| `TRUST_PROXY` | `0` | Read the visitor's address from `X-Forwarded-For` |
| `CV_BIND` | `0.0.0.0` | Which host address to listen on |
| `CV_PORT` | `8000` | Which host port to listen on |
| `ALLOW_SIGNUP` | `1` | Whether people may create their own account at all |
| `SIGNUP_CODE` | empty | A shared secret needed to create one |
| `SESSION_DAYS` | `30` | How long staying signed in lasts |
| `MAX_CVS_PER_USER` | `50` | Saved CVs one account may keep |

### Running it from Portainer

*Stacks* → *Add stack* → *Repository*, then fill in the repository URL and
deploy. Everything else can stay as Portainer prefills it — the compose file is
at the root under its default name, so the *Compose path* field is already
right, and no environment variable is needed to reach the app.

The one field Portainer will not accept as typed is the stack **Name**: it has
to be lower case, so `cv-maker` rather than `CV-maker`.

If you want to change the port or keep it off the network, `CV_PORT` and
`CV_BIND` go in the stack's environment variables — no need to fork the
repository to edit a file.

The stack builds the image rather than pulling one, which needs a plain Docker
environment. Docker Swarm ignores `build`, along with the memory and process
limits; if that is where this is going, build and push the image separately
and replace the `build:` block with `image:`.

### It does not replace the script

`./render.sh` works exactly as before, with or without the web app, and needs
nothing from `web/`. Both doors use the same `template.html` and the same
Chrome flags, so they produce the same PDF — verified by rendering the same
content each way and comparing the drawing operators in the two files.

If you edit `template.html` to restyle your CV, both routes change together.
The `slot` comments in it mark the regions the web app fills in; leave them
where they are and the file behaves like ordinary HTML.

## Licence

MIT — use it, change it, share it.
