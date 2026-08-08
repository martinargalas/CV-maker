"""Accounts, saved CVs and the admin page.

The thing worth being sure of is that one person's CV never reaches another
person, whether by guessing an id or by holding an administrator account.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def fresh_database(tmp_path):
    """Each test gets its own database file.

    The module is redirected rather than reimported: the app holds a reference
    to it, and swapping the module out from under a running app would leave the
    tests talking to a different one than the routes do.
    """
    import store
    was = (store.DATA_DIR, store.DB_PATH)
    store.DATA_DIR, store.DB_PATH = tmp_path, tmp_path / "cv.db"
    store.init()
    yield
    store.DATA_DIR, store.DB_PATH = was


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as app_module
    with TestClient(app_module.app) as test_client:
        yield test_client


HEAD = {"X-CV-Client": "1"}
CV = {"name": "Jane Doe", "role": "Engineer"}


def signup(client, username, password="hunter2hunter2"):
    return client.post("/api/signup", json={"username": username, "password": password, "code": ""},
                       headers=HEAD)


def login(client, username, password="hunter2hunter2"):
    return client.post("/api/login", json={"username": username, "password": password, "code": ""},
                       headers=HEAD)


# ----------------------------------------------------------------- signing in

def test_the_first_account_is_the_administrator(client):
    assert client.get("/api/me").json()["first_run"] is True
    body = signup(client, "alice").json()
    assert body["is_admin"] is True
    assert signup(client, "bob").json()["is_admin"] is False


def test_a_username_cannot_be_taken_twice(client):
    signup(client, "alice")
    client.post("/api/logout", json={}, headers=HEAD)
    assert signup(client, "ALICE").status_code == 409


def test_a_wrong_password_says_nothing_about_whether_the_account_exists(client):
    signup(client, "alice")
    client.post("/api/logout", json={}, headers=HEAD)
    known = login(client, "alice", "wrongwrongwrong")
    unknown = login(client, "nobody", "wrongwrongwrong")
    assert known.status_code == unknown.status_code == 401
    assert known.json()["error"] == unknown.json()["error"]


def test_short_passwords_are_refused(client):
    assert signup(client, "alice", "short").status_code == 400


def test_the_password_is_never_stored_or_returned(client):
    import store
    signup(client, "alice", "correcthorsebattery")
    assert "correcthorsebattery" not in client.get("/api/me").text
    with store.connect() as db:
        row = db.execute("SELECT * FROM users").fetchone()
    assert b"correcthorsebattery" not in bytes(row["password_hash"])
    assert "correcthorsebattery" not in str(tuple(row))


def test_the_session_cookie_is_not_readable_by_scripts(client):
    response = signup(client, "alice")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_the_stored_session_is_a_digest_not_the_token(client):
    import store
    signup(client, "alice")
    token = client.cookies.get("cv_session")
    with store.connect() as db:
        stored = db.execute("SELECT token_hash FROM sessions").fetchone()["token_hash"]
    assert token.encode() not in bytes(stored)
    assert store.session_user(token) is not None


def test_signing_out_ends_the_session(client):
    signup(client, "alice")
    token = client.cookies.get("cv_session")
    client.post("/api/logout", json={}, headers=HEAD)
    import store
    assert store.session_user(token) is None


def test_writes_without_the_app_header_are_refused(client):
    signup(client, "alice")
    assert client.post("/api/cvs", json={"title": "x", "cv": CV}).status_code == 403


def test_brute_force_is_throttled(client):
    signup(client, "alice")
    client.post("/api/logout", json={}, headers=HEAD)
    codes = [login(client, "alice", "nope-nope-nope").status_code for _ in range(12)]
    assert 429 in codes


# ------------------------------------------------------------- saved CVs

def test_a_saved_cv_comes_back(client):
    signup(client, "alice")
    cv_id = client.post("/api/cvs", json={"title": "Main", "cv": CV}, headers=HEAD).json()["id"]
    saved = client.get(f"/api/cvs/{cv_id}").json()
    assert saved["title"] == "Main"
    assert saved["cv"]["name"] == "Jane Doe"
    assert [t["title"] for t in client.get("/api/cvs").json()["cvs"]] == ["Main"]


def test_another_account_cannot_read_or_delete_it(client):
    signup(client, "alice")
    cv_id = client.post("/api/cvs", json={"title": "Main", "cv": CV}, headers=HEAD).json()["id"]
    client.post("/api/logout", json={}, headers=HEAD)

    signup(client, "bob")
    assert client.get(f"/api/cvs/{cv_id}").status_code == 404
    assert client.delete(f"/api/cvs/{cv_id}", headers=HEAD).status_code == 404
    assert client.get("/api/cvs").json()["cvs"] == []


def test_saved_cvs_need_an_account(client):
    assert client.get("/api/cvs").status_code == 401
    assert client.post("/api/cvs", json={"title": "x", "cv": CV}, headers=HEAD).status_code == 401


def test_making_a_cv_without_an_account_still_works(client):
    """The point of the app is the PDF; the account is only for keeping one."""
    assert client.post("/api/preview", json=CV).status_code == 200
    assert client.post("/api/import-text", content=b"Jane Doe\nEngineer\n").status_code == 200


def test_deleting_an_account_takes_its_cvs_with_it(client):
    import store
    signup(client, "alice")
    client.post("/api/cvs", json={"title": "Main", "cv": CV}, headers=HEAD)
    client.post("/api/logout", json={}, headers=HEAD)

    signup(client, "bob")
    bob_id = [u["id"] for u in store.list_users() if u["username"] == "bob"][0]
    client.post("/api/cvs", json={"title": "Bob's", "cv": CV}, headers=HEAD)
    client.post("/api/logout", json={}, headers=HEAD)

    login(client, "alice")
    assert client.delete(f"/api/admin/users/{bob_id}", headers=HEAD).status_code == 200
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM cvs WHERE owner_id = ?",
                          (bob_id,)).fetchone()["n"] == 0


# ---------------------------------------------------------------- admin

def test_admin_routes_need_an_admin(client):
    signup(client, "alice")
    client.post("/api/logout", json={}, headers=HEAD)
    signup(client, "bob")
    assert client.get("/api/admin/users").status_code == 403


def test_an_admin_sees_accounts_but_never_their_cv_contents(client):
    signup(client, "alice")
    client.post("/api/logout", json={}, headers=HEAD)

    signup(client, "bob")
    client.post("/api/cvs", json={"title": "Bob's CV", "cv": {
        "name": "Bob Secret", "email": "bob@example.com", "phone": "+420 000",
    }}, headers=HEAD)
    client.post("/api/logout", json={}, headers=HEAD)

    login(client, "alice")
    listing = client.get("/api/admin/users")
    assert listing.status_code == 200
    assert "bob" in listing.text
    # The count is there; the person's details are not.
    assert [u["cvs"] for u in listing.json()["users"] if u["username"] == "bob"] == [1]
    for leak in ("Bob Secret", "bob@example.com", "+420 000", "Bob's CV"):
        assert leak not in listing.text


def test_an_admin_cannot_delete_the_account_they_are_using(client):
    import store
    signup(client, "alice")
    alice_id = store.list_users()[0]["id"]
    assert client.delete(f"/api/admin/users/{alice_id}", headers=HEAD).status_code == 400


def test_turning_signups_off_stops_new_accounts(client):
    signup(client, "alice")
    client.post("/api/admin/signup-allowed", json={"allowed": False}, headers=HEAD)
    client.post("/api/logout", json={}, headers=HEAD)
    assert signup(client, "bob").status_code == 403


def test_changing_a_password_ends_other_sessions(client):
    import store
    signup(client, "alice", "hunter2hunter2")
    first = client.cookies.get("cv_session")
    login(client, "alice", "hunter2hunter2")          # a second browser
    second = client.cookies.get("cv_session")

    client.post("/api/password", json={"current": "hunter2hunter2",
                                       "replacement": "brandnewpassword"}, headers=HEAD)
    assert store.session_user(second) is not None      # the one that changed it
    assert store.session_user(first) is None           # every other one


def test_a_reset_password_signs_that_person_out_everywhere(client):
    import store
    signup(client, "alice")
    admin_cookie = dict(client.cookies)
    client.post("/api/logout", json={}, headers=HEAD)

    signup(client, "bob")
    bob_token = client.cookies.get("cv_session")
    bob_id = [u["id"] for u in store.list_users() if u["username"] == "bob"][0]
    client.post("/api/logout", json={}, headers=HEAD)

    client.cookies.update(admin_cookie)
    client.post(f"/api/admin/users/{bob_id}/password",
                json={"password": "resetresetreset"}, headers=HEAD)
    assert store.session_user(bob_token) is None
