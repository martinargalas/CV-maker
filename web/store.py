"""Accounts and saved CVs, in one SQLite file.

Saving CVs means the server now holds other people's names, addresses and
phone numbers, which it deliberately did not before. Two things follow, and
they shape this module:

  - **Passwords are never stored, and never recoverable.** What goes in the
    table is a scrypt hash with a per-user salt. A stolen database does not
    hand over anybody's password.
  - **Sessions are stored as digests too.** The cookie holds a random token;
    the table holds its SHA-256. Reading the table does not let you sign in as
    anyone.

Every query that touches a CV is filtered by its owner. Guessing an id is not
a way to read somebody else's CV, because the id alone never selects a row.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional

DATA_DIR = Path(os.environ.get("CV_DATA_DIR", Path(__file__).resolve().parent / "data"))
DB_PATH = DATA_DIR / "cv.db"

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
MAX_CVS_PER_USER = int(os.environ.get("MAX_CVS_PER_USER", "50"))

# scrypt at these parameters costs about 32 MB and a fraction of a second per
# attempt, which is the point: it makes guessing passwords expensive.
_SCRYPT = dict(n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash BLOB NOT NULL,
    salt          BLOB NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash BLOB PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cvs (
    id         TEXT PRIMARY KEY,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS cvs_by_owner ON cvs(owner_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
"""


class StoreError(Exception):
    """Something the caller can be told about verbatim."""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection per call. SQLite is quick enough, and this keeps the
    threadpool FastAPI runs sync endpoints in from sharing one."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    finally:
        connection.close()


def init() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass  # a mounted volume may not allow it; the container is single-user


# ------------------------------------------------------------------ users

def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def create_user(username: str, password: str, is_admin: bool = False) -> int:
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    with connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO users (username, password_hash, salt, is_admin, created_at) "
                "VALUES (?,?,?,?,?)",
                (username, digest, salt, int(is_admin), time.time()),
            )
        except sqlite3.IntegrityError:
            raise StoreError("That username is taken.")
        return int(cursor.lastrowid)


def set_password(user_id: int, password: str) -> bool:
    salt = secrets.token_bytes(16)
    with connect() as db:
        cursor = db.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (_hash_password(password, salt), salt, user_id),
        )
    return cursor.rowcount > 0


def is_admin(user_id: int) -> bool:
    with connect() as db:
        row = db.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_admin"])


def list_users() -> List[Dict]:
    """Accounts, with how many CVs each holds — never what is in them."""
    with connect() as db:
        rows = db.execute(
            "SELECT u.id, u.username, u.is_admin, u.created_at, "
            "       (SELECT COUNT(*) FROM cvs WHERE owner_id = u.id) AS cvs "
            "FROM users u ORDER BY u.created_at",
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user(user_id: int) -> bool:
    """Remove an account and everything it owns.

    Their CVs go with it — the foreign keys cascade — because leaving somebody's
    personal details behind after their account is gone is the wrong default.
    """
    with connect() as db:
        cursor = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cursor.rowcount > 0


# ------------------------------------------------------------- settings

def signup_allowed() -> bool:
    with connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key = 'signup_allowed'").fetchone()
    return True if row is None else row["value"] == "1"


def set_signup_allowed(allowed: bool) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES ('signup_allowed', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("1" if allowed else "0",),
        )


def verify_user(username: str, password: str) -> Optional[int]:
    """Return the user id, or None. Takes the same work either way.

    An unknown username still pays for a scrypt hash, so the response time does
    not say whether an account exists.
    """
    with connect() as db:
        row = db.execute(
            "SELECT id, password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None:
        _hash_password(password, b"decoy-salt-16byt")
        return None

    candidate = _hash_password(password, row["salt"])
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return None
    return int(row["id"])


def user_count() -> int:
    with connect() as db:
        return int(db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


def username_of(user_id: int) -> Optional[str]:
    with connect() as db:
        row = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["username"] if row else None


# --------------------------------------------------------------- sessions

def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def open_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        db.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
            (_digest(token), user_id, time.time() + SESSION_DAYS * 86400),
        )
    return token


def session_user(token: str) -> Optional[int]:
    if not token:
        return None
    with connect() as db:
        row = db.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (_digest(token),)
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        return None
    return int(row["user_id"])


def close_session(token: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))


def close_sessions_except(user_id: int, keep: str) -> None:
    """End every session for an account, optionally sparing the current one."""
    with connect() as db:
        if keep:
            db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (user_id, _digest(keep)),
            )
        else:
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------- saved CVs

def list_cvs(owner_id: int) -> List[Dict]:
    """Enough for the tiles, without loading every CV in full."""
    with connect() as db:
        rows = db.execute(
            "SELECT id, title, data, created_at, updated_at FROM cvs "
            "WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ).fetchall()

    tiles = []
    for row in rows:
        data = json.loads(row["data"])
        tiles.append({
            "id": row["id"],
            "title": row["title"],
            "name": data.get("name", ""),
            "role": data.get("role", ""),
            "photo": data.get("photo", ""),
            "jobs": len(data.get("jobs", [])),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return tiles


def get_cv(owner_id: int, cv_id: str) -> Optional[Dict]:
    with connect() as db:
        row = db.execute(
            "SELECT id, title, data FROM cvs WHERE id = ? AND owner_id = ?", (cv_id, owner_id)
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "title": row["title"], "cv": json.loads(row["data"])}


def create_cv(owner_id: int, title: str, data: Dict) -> str:
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) AS n FROM cvs WHERE owner_id = ?", (owner_id,)
        ).fetchone()["n"]
        if count >= MAX_CVS_PER_USER:
            raise StoreError(f"You already have {MAX_CVS_PER_USER} saved CVs. Delete one first.")

        cv_id = uuid.uuid4().hex
        now = time.time()
        db.execute(
            "INSERT INTO cvs (id, owner_id, title, data, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (cv_id, owner_id, title, json.dumps(data), now, now),
        )
    return cv_id


def update_cv(owner_id: int, cv_id: str, title: str, data: Dict) -> bool:
    with connect() as db:
        cursor = db.execute(
            "UPDATE cvs SET title = ?, data = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
            (title, json.dumps(data), time.time(), cv_id, owner_id),
        )
    return cursor.rowcount > 0


def rename_cv(owner_id: int, cv_id: str, title: str) -> bool:
    with connect() as db:
        cursor = db.execute(
            "UPDATE cvs SET title = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
            (title, time.time(), cv_id, owner_id),
        )
    return cursor.rowcount > 0


def delete_cv(owner_id: int, cv_id: str) -> bool:
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM cvs WHERE id = ? AND owner_id = ?", (cv_id, owner_id)
        )
    return cursor.rowcount > 0
