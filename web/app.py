"""The web app: a form in, a single-page PDF out.

Nothing is persisted. There is no database, no session, no upload directory and
no account. A request carries the whole CV, a PDF comes back, and the process
keeps nothing about it — including the logs, which never contain field values.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import photo as photo_lib
from cvdoc import CV, build_document
from render import RenderError, page_count, render_pdf

HERE = Path(__file__).resolve().parent

MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", 3 * 1024 * 1024))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"

app = FastAPI(title="CV maker", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


# ------------------------------------------------------------------ limits

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse oversized requests before reading them.

    Content-Length is a claim, not a fact, so the ASGI server's own limits and
    the field caps in the model are what actually bound memory use. This just
    turns the common case into a clean 413 instead of a slow parse.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# A per-process salt means the table holds no recoverable addresses: it is a
# counter keyed by an unrecoverable digest, and it empties itself as it goes.
_SALT = secrets.token_bytes(16)
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _bucket(request: Request) -> str:
    client = request.client.host if request.client else "?"
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client = forwarded.split(",")[0].strip()
    return hashlib.blake2b(_SALT + client.encode(), digest_size=16).hexdigest()


def rate_limit(request: Request) -> None:
    now = time.monotonic()
    hits = _hits[_bucket(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(429, "Too many requests. Wait a minute and try again.")
    hits.append(now)
    if len(_hits) > 10_000:  # keep the table from growing without bound
        for key in [k for k, v in _hits.items() if not v]:
            del _hits[key]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Report where a payload broke a limit, without echoing what was in it."""
    problems = []
    for error in exc.errors()[:10]:
        where = ".".join(str(p) for p in error["loc"] if p != "body")
        problems.append(f"{where or 'payload'}: {error['msg']}")
    return JSONResponse({"error": "; ".join(problems)}, status_code=422)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ routes

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(
        HERE / "templates" / "index.html",
        headers={
            # The page loads only its own script and stylesheet. script-src is
            # the directive that matters here and it stays at 'self'.
            #
            # style-src has to allow inline styles, and not for this page's
            # sake: a srcdoc iframe inherits its parent's policy, and the CV
            # document is inline-styled by design — that <style> block is the
            # template, shared with the CLI. Without this the preview renders
            # as unstyled text.
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; frame-src 'self' data:; "
                "base-uri 'none'; form-action 'none'"
            )
        },
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}


@app.post("/api/photo")
async def api_photo(request: Request, file: UploadFile = File(...)) -> dict:
    rate_limit(request)
    raw = await file.read(photo_lib.MAX_UPLOAD + 1)
    try:
        return {"photo": photo_lib.to_data_uri(raw)}
    except photo_lib.PhotoError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/preview")
async def api_preview(request: Request, cv: CV) -> dict:
    rate_limit(request)
    return {"html": _document(cv)}


@app.post("/api/render")
async def api_render(request: Request, cv: CV) -> Response:
    rate_limit(request)
    document = _document(cv)
    try:
        pdf = await render_pdf(document)
    except RenderError as exc:
        raise HTTPException(503, str(exc))

    headers = {
        # A fixed filename: the CV holder's name is their business, and a
        # response header is the one place it would leak into proxy logs.
        "Content-Disposition": 'attachment; filename="cv.pdf"',
        "Cache-Control": "no-store",
    }
    pages = page_count(pdf)
    if pages is not None and pages != 1:
        headers["X-CV-Pages"] = str(pages)
    return Response(pdf, media_type="application/pdf", headers=headers)


def _document(cv: CV) -> str:
    """Build the CV document, re-encoding the photo on the way through."""
    try:
        cv = cv.model_copy(update={"photo": photo_lib.resanitize(cv.photo)})
    except photo_lib.PhotoError as exc:
        raise HTTPException(400, str(exc))
    return build_document(cv)
