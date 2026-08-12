"""The web app: a form in, a single-page PDF out.

Making a CV needs no account, and a CV that is not saved is not persisted: the
request carries it, a PDF comes back, and nothing about it is kept — including
in the logs, which never contain field values.

Saving is the exception, and it is opt-in. An account holds the CVs it saved
and nothing else can read them; see store.py for what that means on disk.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Deque, Dict

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import auth
import pdfimport
import photo as photo_lib
import store
import textimport
from cvdoc import CV, build_document
from render import RenderError, page_count, render_pdf

HERE = Path(__file__).resolve().parent

MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", 3 * 1024 * 1024))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"

@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    yield


app = FastAPI(title="CV maker", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
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

def _page(name: str) -> FileResponse:
    return FileResponse(
        HERE / "templates" / name,
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


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return _page("index.html")


@app.get("/edit", include_in_schema=False)
async def editor() -> FileResponse:
    return _page("editor.html")


@app.get("/admin", include_in_schema=False)
async def admin_page() -> FileResponse:
    return _page("admin.html")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}


# ------------------------------------------------------------ accounts

class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    password: str = Field(max_length=auth.MAX_PASSWORD)
    code: str = Field(default="", max_length=200)


@app.get("/api/me")
def api_me(request: Request) -> dict:
    user_id = auth.current_user(request)
    if user_id is None:
        return {"signed_in": False, "signup_allowed": store.signup_allowed(),
                "signup_needs_code": bool(auth.SIGNUP_CODE), "first_run": store.user_count() == 0}
    return {
        "signed_in": True,
        "username": store.username_of(user_id),
        "is_admin": store.is_admin(user_id),
    }


@app.post("/api/signup")
def api_signup(request: Request, body: Credentials) -> JSONResponse:
    rate_limit(request)
    auth.require_same_origin(request)
    username = auth.check_username(body.username)
    auth.check_password(body.password)

    # The person who sets the server up is the first to arrive, and becomes the
    # administrator. After that, whether anyone else may join is their call.
    first_run = store.user_count() == 0
    if not first_run:
        auth.check_signup_allowed(body.code)
        if not store.signup_allowed():
            raise HTTPException(403, "New accounts are turned off on this server.")

    try:
        user_id = store.create_user(username, body.password, is_admin=first_run)
    except store.StoreError as exc:
        raise HTTPException(409, str(exc))

    response = JSONResponse({"signed_in": True, "username": username, "is_admin": first_run})
    auth.set_cookie(response, store.open_session(user_id), auth.is_secure(request))
    return response


@app.post("/api/login")
def api_login(request: Request, body: Credentials) -> JSONResponse:
    auth.require_same_origin(request)
    auth.throttle_login(body.username.lower()[:64])

    user_id = store.verify_user(body.username.strip(), body.password)
    if user_id is None:
        # One message for both causes: saying which was wrong would confirm
        # whether an account exists.
        raise HTTPException(401, "That username and password do not match.")

    auth.clear_attempts(body.username.lower()[:64])
    response = JSONResponse({
        "signed_in": True,
        "username": store.username_of(user_id),
        "is_admin": store.is_admin(user_id),
    })
    auth.set_cookie(response, store.open_session(user_id), auth.is_secure(request))
    return response


@app.post("/api/logout")
def api_logout(request: Request) -> JSONResponse:
    auth.require_same_origin(request)
    store.close_session(request.cookies.get(auth.COOKIE, ""))
    response = JSONResponse({"signed_in": False})
    auth.clear_cookie(response)
    return response


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: str = Field(max_length=auth.MAX_PASSWORD)
    replacement: str = Field(max_length=auth.MAX_PASSWORD)


@app.post("/api/password")
def api_password(request: Request, body: PasswordChange) -> dict:
    auth.require_same_origin(request)
    user_id = auth.require_user(request)
    username = store.username_of(user_id)

    if store.verify_user(username, body.current) != user_id:
        raise HTTPException(403, "That is not your current password.")
    auth.check_password(body.replacement)
    store.set_password(user_id, body.replacement)
    # Every other session for this account stops working, which is the point of
    # changing a password you think somebody else knows.
    store.close_sessions_except(user_id, request.cookies.get(auth.COOKIE, ""))
    return {"ok": True}


# ----------------------------------------------------------- saved CVs

class SavedCV(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=120)
    cv: CV


@app.get("/api/cvs")
def api_list_cvs(request: Request) -> dict:
    return {"cvs": store.list_cvs(auth.require_user(request))}


@app.get("/api/cvs/{cv_id}")
def api_get_cv(request: Request, cv_id: str) -> dict:
    saved = store.get_cv(auth.require_user(request), cv_id)
    if saved is None:
        raise HTTPException(404, "That CV is not there.")
    return saved


@app.post("/api/cvs")
def api_create_cv(request: Request, body: SavedCV) -> dict:
    auth.require_same_origin(request)
    user_id = auth.require_user(request)
    title = body.title.strip() or body.cv.name.strip() or "Untitled CV"
    try:
        return {"id": store.create_cv(user_id, title, body.cv.model_dump())}
    except store.StoreError as exc:
        raise HTTPException(409, str(exc))


@app.put("/api/cvs/{cv_id}")
def api_update_cv(request: Request, cv_id: str, body: SavedCV) -> dict:
    auth.require_same_origin(request)
    user_id = auth.require_user(request)
    title = body.title.strip() or body.cv.name.strip() or "Untitled CV"
    if not store.update_cv(user_id, cv_id, title, body.cv.model_dump()):
        raise HTTPException(404, "That CV is not there.")
    return {"ok": True}


class Title(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=120)


@app.post("/api/cvs/{cv_id}/rename")
def api_rename_cv(request: Request, cv_id: str, body: Title) -> dict:
    auth.require_same_origin(request)
    user_id = auth.require_user(request)
    if not store.rename_cv(user_id, cv_id, body.title.strip() or "Untitled CV"):
        raise HTTPException(404, "That CV is not there.")
    return {"ok": True}


@app.post("/api/cvs/{cv_id}/duplicate")
def api_duplicate_cv(request: Request, cv_id: str) -> dict:
    auth.require_same_origin(request)
    user_id = auth.require_user(request)
    saved = store.get_cv(user_id, cv_id)
    if saved is None:
        raise HTTPException(404, "That CV is not there.")
    try:
        return {"id": store.create_cv(user_id, f"{saved['title']} (copy)", saved["cv"])}
    except store.StoreError as exc:
        raise HTTPException(409, str(exc))


@app.delete("/api/cvs/{cv_id}")
def api_delete_cv(request: Request, cv_id: str) -> dict:
    auth.require_same_origin(request)
    if not store.delete_cv(auth.require_user(request), cv_id):
        raise HTTPException(404, "That CV is not there.")
    return {"ok": True}


# --------------------------------------------------------------- admin

def _require_admin(request: Request) -> int:
    user_id = auth.require_user(request)
    if not store.is_admin(user_id):
        raise HTTPException(403, "That is for administrators.")
    return user_id


@app.get("/api/admin/users")
def api_admin_users(request: Request) -> dict:
    """Accounts and how much they hold — never what is in them.

    An administrator here runs the server; that is not the same as being
    allowed to read the CVs of the people who use it, so this returns counts
    and dates and no CV content at all.
    """
    _require_admin(request)
    return {"users": store.list_users(), "signup_allowed": store.signup_allowed()}


@app.post("/api/admin/signup-allowed")
def api_admin_signup(request: Request, body: dict) -> dict:
    auth.require_same_origin(request)
    _require_admin(request)
    store.set_signup_allowed(bool(body.get("allowed")))
    return {"signup_allowed": store.signup_allowed()}


@app.post("/api/admin/users")
def api_admin_create_user(request: Request, body: Credentials) -> dict:
    auth.require_same_origin(request)
    _require_admin(request)
    username = auth.check_username(body.username)
    auth.check_password(body.password)
    try:
        store.create_user(username, body.password, is_admin=False)
    except store.StoreError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def api_admin_delete_user(request: Request, user_id: int) -> dict:
    auth.require_same_origin(request)
    admin_id = _require_admin(request)
    if user_id == admin_id:
        raise HTTPException(400, "You cannot delete the account you are signed in with.")
    if not store.delete_user(user_id):
        raise HTTPException(404, "No such account.")
    return {"ok": True}


class NewPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(max_length=auth.MAX_PASSWORD)


@app.post("/api/admin/users/{user_id}/password")
def api_admin_reset_password(request: Request, user_id: int, body: NewPassword) -> dict:
    """Set a new password for someone who has forgotten theirs.

    Their sessions all end, so a reset cannot be used to quietly ride along
    beside someone who is still signed in.
    """
    auth.require_same_origin(request)
    _require_admin(request)
    auth.check_password(body.password)
    if not store.set_password(user_id, body.password):
        raise HTTPException(404, "No such account.")
    store.close_sessions_except(user_id, "")
    return {"ok": True}


@app.post("/api/photo")
async def api_photo(request: Request, file: UploadFile = File(...)) -> dict:
    rate_limit(request)
    raw = await file.read(photo_lib.MAX_UPLOAD + 1)
    try:
        return {"photo": photo_lib.to_data_uri(raw)}
    except photo_lib.PhotoError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/import-text")
async def api_import_text(request: Request) -> dict:
    """Read the plain-text CV format into form fields.

    The text is parsed, never executed and never rendered as it stands: what
    comes back is data for the form, which the person then sees and can correct
    before anything is drawn. It is validated against the same model as typed
    input, so an import cannot smuggle in a field the form would refuse.
    """
    rate_limit(request)
    raw = await request.body()
    if len(raw) > textimport.MAX_TEXT:
        raise HTTPException(413, "That file is too large to read.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "That file is not readable text. Save it as UTF-8 and retry.")

    fields, warnings = textimport.parse(text)
    try:
        cv = CV.model_validate(fields)
    except ValidationError:
        raise HTTPException(422, "That file could not be read as a CV.")
    return {"cv": cv.model_dump(), "warnings": warnings}


@app.post("/api/import-pdf")
async def api_import_pdf(request: Request, file: UploadFile = File(...)) -> dict:
    """Recover the text of a CV that only exists as a PDF.

    The file is read, never rendered: no page of it is ever drawn, opened in a
    browser or shown to anybody. What comes back is text for the person to
    check and correct, because a PDF says where glyphs sit and not what they
    mean, and no parser gets that right every time.
    """
    rate_limit(request)
    raw = await file.read(pdfimport.MAX_BYTES + 1)
    try:
        text = pdfimport.to_text(raw)
    except pdfimport.PdfError as exc:
        raise HTTPException(400, str(exc))

    fields, warnings = textimport.parse(text)
    try:
        cv = CV.model_validate(fields)
    except ValidationError:
        raise HTTPException(422, "That PDF could not be read as a CV.")
    return {"text": text, "cv": cv.model_dump(), "warnings": warnings}


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
