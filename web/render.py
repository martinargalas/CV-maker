"""Driving headless Chrome, with the flags from render.sh and a few more.

The print flags are the CLI ones verbatim, including the `file://` absolute
path — a relative one silently renders a blank page at the default paper size.
The rest are there because this browser is being handed content from strangers:

  - it gets a throwaway profile inside a per-request temporary directory whose
    name comes from `mkdtemp`, never from anything a user typed;
  - name resolution is broken on purpose, so a URL that somehow reached the
    document cannot become a request;
  - it is killed by process group if it outlives the timeout, and the temporary
    directory goes away in a `finally`, on success, failure and timeout alike.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import tempfile
from pathlib import Path
from typing import List, Optional

RENDER_TIMEOUT = int(os.environ.get("RENDER_TIMEOUT", "20"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_RENDERS", "2"))

# Chrome's own sandbox needs privileges the container deliberately does not
# grant. Inside the image the container is the boundary instead, and the
# Dockerfile sets this; a local run keeps the sandbox on.
NO_SANDBOX = os.environ.get("CHROME_NO_SANDBOX") == "1"

_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)

# One browser process is expensive, and a request holds one for its whole
# render. Without this a handful of concurrent requests is enough to take the
# host down, which makes it a denial-of-service hole rather than a tuning knob.
_slots = asyncio.Semaphore(MAX_CONCURRENT)


class RenderError(RuntimeError):
    """Rendering failed. The message is safe to show to whoever asked."""


def find_chrome() -> str:
    override = os.environ.get("CHROME")
    if override:
        return override
    for candidate in _CANDIDATES:
        if "/" in candidate:
            if os.access(candidate, os.X_OK):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    raise RenderError("No Chrome/Chromium found. Set CHROME=/path/to/chrome.")


def _argv(chrome: str, workdir: Path, source: Path, output: Path) -> List[str]:
    args = [
        chrome,
        # --- identical to render.sh ---
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=4000",
        f"--print-to-pdf={output}",
        # --- because the content is untrusted ---
        # No --user-data-dir here on purpose: passing one makes Chrome treat the
        # run as a browser session and stay alive after printing, so every
        # render would sit until the timeout. The throwaway profile comes from
        # the redirected HOME in _env() instead.
        "--host-resolver-rules=MAP * ~NOTFOUND",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        # HOME points at the request's temporary directory, so Chrome finds no
        # keychain there and asks for one — a dialog nobody is sitting in front
        # of. These two tell it to keep passwords in memory and forget them,
        # which is what a browser that renders one page and exits should do.
        "--use-mock-keychain",
        "--password-store=basic",
    ]
    if NO_SANDBOX:
        args.append("--no-sandbox")
    args.append(f"file://{source}")
    return args


def _env(workdir: Path) -> dict:
    """Point Chrome's home at the request's temporary directory.

    Whatever profile, cache or crash data it decides to write lands inside the
    directory that gets removed when the request ends, rather than in the
    account's real browser profile.
    """
    env = dict(os.environ)
    home = workdir / "home"
    home.mkdir(exist_ok=True)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_CACHE_HOME=str(home / ".cache"),
    )
    return env


def page_count(pdf: bytes) -> Optional[int]:
    match = re.search(rb"/Count (\d+)", pdf)
    return int(match.group(1)) if match else None


async def render_pdf(document: str) -> bytes:
    """Render an HTML document to PDF bytes. Leaves nothing on disk."""
    async with _slots:
        return await _render(document)


async def _render(document: str) -> bytes:
    chrome = find_chrome()
    workdir = Path(tempfile.mkdtemp(prefix="cv-render-"))
    try:
        source = workdir / "cv.html"
        output = workdir / "cv.pdf"
        source.write_text(document, encoding="utf-8")

        process = await asyncio.create_subprocess_exec(
            *_argv(chrome, workdir, source, output),
            env=_env(workdir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            # Its own session, so a hung render can be killed as a group —
            # Chrome leaves children behind if only the parent is signalled.
            start_new_session=True,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=RENDER_TIMEOUT)
        except asyncio.TimeoutError:
            _kill_group(process.pid)
            await process.wait()
            raise RenderError(f"Rendering took longer than {RENDER_TIMEOUT} seconds.")

        if not output.exists() or output.stat().st_size == 0:
            raise RenderError("The browser produced no PDF.")
        return output.read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
