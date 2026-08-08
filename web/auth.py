"""Signing in: cookies, the rules for a usable account, and brute-force limits.

The session cookie carries a random token and nothing else — no username, no
identifier, nothing that means anything if it is read. It is HttpOnly, so page
scripts cannot reach it, and SameSite=Strict, so another site cannot cause a
request that carries it. That last one is what makes cross-site request forgery
a non-issue here; the header check in the app is a second lock on the same door.
"""

from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, Response

import store

COOKIE = "cv_session"

ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "1") != "0"
# Optional shared secret for creating an account. Empty means anyone who can
# reach the app can make one, which is the right default for something running
# on a home network and the wrong one for anything reachable from outside.
SIGNUP_CODE = os.environ.get("SIGNUP_CODE", "")

USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 200

# Slow down guessing without locking anyone out for good.
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW = 300

_attempts: Dict[str, Deque[float]] = defaultdict(deque)


def check_username(username: str) -> str:
    username = username.strip()
    if not USERNAME.match(username):
        raise HTTPException(
            400,
            "A username is 3 to 32 characters, using letters, digits, dot, dash or underscore.",
        )
    return username


def check_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise HTTPException(400, "That password is too long.")
    return password


def check_signup_allowed(code: str) -> None:
    if not ALLOW_SIGNUP:
        raise HTTPException(403, "New accounts are turned off on this server.")
    if SIGNUP_CODE and not _same(code, SIGNUP_CODE):
        raise HTTPException(403, "That signup code is not right.")


def _same(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode(), right.encode())


def throttle_login(key: str) -> None:
    now = time.monotonic()
    tries = _attempts[key]
    while tries and now - tries[0] > LOGIN_WINDOW:
        tries.popleft()
    if len(tries) >= LOGIN_ATTEMPTS:
        raise HTTPException(429, "Too many sign-in attempts. Wait a few minutes.")
    tries.append(now)


def clear_attempts(key: str) -> None:
    _attempts.pop(key, None)


def set_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=store.SESSION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def is_secure(request: Request) -> bool:
    """Whether to mark the cookie Secure.

    Marking it Secure over plain http would stop the cookie being sent at all,
    which breaks sign-in on a home network. So it follows the actual scheme,
    including what a reverse proxy says it terminated.
    """
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def current_user(request: Request) -> Optional[int]:
    return store.session_user(request.cookies.get(COOKIE, ""))


def require_user(request: Request) -> int:
    user_id = current_user(request)
    if user_id is None:
        raise HTTPException(401, "Sign in to do that.")
    return user_id


def require_same_origin(request: Request) -> None:
    """A second lock behind SameSite=Strict.

    Every write from the app's own pages sends this header; a form submitted
    from somewhere else cannot add it without the browser asking this server
    for permission first, which it never gives.
    """
    if request.headers.get("x-cv-client") != "1":
        raise HTTPException(403, "That request did not come from the app.")
