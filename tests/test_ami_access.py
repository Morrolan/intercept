"""AMI entry-pass contract and Caddy's opt-in away gate (no live services)."""
import hashlib
import sqlite3
from unittest.mock import Mock

import pytest

import app as runtime
from utils import ami_access, database

TOKEN = "test-only-service-secret-with-at-least-32-characters"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
AWAY = {"X-Intercept-Access": "away"}


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path, app):
    monkeypatch.setenv("AMI_URL", "https://ami.example.test")
    monkeypatch.setenv("INTERCEPT_AMI_TOKEN_SHA256", hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setenv("INTERCEPT_AMI_ONLY_AWAY", "1")
    monkeypatch.setenv("INTERCEPT_TRUSTED_PROXIES", "1")
    monkeypatch.setenv("INTERCEPT_AMI_USERS", "alice=operator, bob")
    monkeypatch.setattr(ami_access, "entry_tickets", ami_access.EntryTickets())
    database.close_db()
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "accounts.sqlite")
    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    database.init_db()
    with database.get_db() as conn:
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('operator', 'unused', 'admin')")
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('bob', 'unused', 'viewer')")
    if hasattr(runtime.limiter, "reset"):
        runtime.limiter.reset()
    yield
    database.close_db()


def issue(client, **changes):
    return client.post("/api/module/session", headers=AUTH,
                       json={"user": "alice", "role": "resident", "mfa": True, **changes})


def test_issue_enter_and_single_use(anon_client):
    with anon_client.session_transaction() as sess:
        sess.update(username="old", role="viewer", must_change_password=True, stale="remove")
    response = issue(anon_client)
    ticket = response.json["ticket"]
    assert len(ticket) >= 32 and response.json["expiresIn"] == 60
    assert ticket.encode() not in ami_access.entry_tickets._tickets
    response = anon_client.get("/ami/enter", query_string={"ticket": ticket}, headers=AWAY)
    assert response.status_code == 302 and response.location == "/?ami=1"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    with anon_client.session_transaction() as sess:
        assert dict(sess) == {"logged_in": True, "username": "operator", "role": "admin", "via_ami": True}
    response = anon_client.get("/ami/enter", query_string={"ticket": ticket}, headers=AWAY)
    assert response.status_code == 403 and b"Open Intercept again from AMI" in response.data
    assert "Location" not in response.headers


def test_expiry_and_invalid_tickets(anon_client, monkeypatch):
    clock = Mock(return_value=100)
    monkeypatch.setattr(ami_access.time, "monotonic", clock)
    ticket = issue(anon_client).json["ticket"]
    clock.return_value = 160
    for value in (ticket, "wrong-ticket", "x" * 129, ""):
        assert anon_client.get("/ami/enter", query_string={"ticket": value}).status_code == 403
    with anon_client.session_transaction() as sess:
        assert "logged_in" not in sess


@pytest.mark.parametrize("changes", [
    {"user": "outsider"}, {"user": "missing"}, {"user": []}, {"user": ""},
    {"mfa": False}, {"mfa": "true"}, {"mfa": 1}, {"role": "owner"},
])
def test_denied_has_no_check_details(anon_client, changes, monkeypatch):
    monkeypatch.setenv("INTERCEPT_AMI_USERS", "alice=operator, missing")
    response = issue(anon_client, **changes)
    assert response.status_code == 403 and response.json == {"error": "not allowed"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_service_token_required_even_with_browser_session(client, headers):
    assert client.post("/api/module/session", headers=headers,
                       json={"user": "alice", "role": "admin", "mfa": True}).status_code == 401


def test_unmapped_name_and_forced_password_change(anon_client):
    with database.get_db() as conn:
        conn.execute("UPDATE users SET must_change_password=1 WHERE username='bob'")
    ticket = issue(anon_client, user="bob", role="admin").json["ticket"]
    assert anon_client.get("/ami/enter", query_string={"ticket": ticket}).location == "/?ami=1"
    with anon_client.session_transaction() as sess:
        assert sess["username"] == "bob" and sess["role"] == "viewer"
        assert sess["must_change_password"] and sess["via_ami"]
    assert anon_client.get("/?ami=1", headers=AWAY).location == "/change-password?ami=1"
    assert anon_client.get("/change-password", headers=AWAY).status_code == 200


def test_disabled_account_at_issue_and_consume(anon_client):
    ticket = issue(anon_client).json["ticket"]
    with database.get_db() as conn:
        conn.execute("UPDATE users SET enabled=0 WHERE username='operator'")
    assert issue(anon_client).status_code == 403
    assert anon_client.get("/ami/enter", query_string={"ticket": ticket}).status_code == 403


def test_rate_limit(anon_client):
    for _ in range(30):
        assert issue(anon_client, mfa=False).status_code == 403
    response = issue(anon_client)
    assert response.status_code == 429 and response.is_json
    assert response.headers["Retry-After"] == "60"


def test_away_login_rejected_before_credentials_and_csrf(anon_client, monkeypatch, app):
    verify = Mock(side_effect=AssertionError("must not check passwords"))
    monkeypatch.setattr(runtime, "check_password_hash", verify)
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    for method in (anon_client.get, anon_client.post):
        response = method("/login", headers=AWAY)
        assert response.status_code == 403
        assert b"Intercept is opened through AMI when you're away from home" in response.data
        assert b'https://ami.example.test' in response.data and b'type="password"' not in response.data
    verify.assert_not_called()


@pytest.mark.parametrize("path,headers,status", [
    ("/", AWAY, 302), ("/change-password", AWAY, 302), ("/health", AWAY, 302),
    ("/api/preferences", AWAY, 401), ("/stream_pager", AWAY, 401),
    ("/status", {**AWAY, "X-Requested-With": "XMLHttpRequest"}, 401),
    ("/status", {**AWAY, "Accept": "text/event-stream"}, 401),
    ("/ws/waterfall", AWAY, 401),
])
def test_away_plain_session_is_not_signed_in(client, path, headers, status):
    response = client.get(path, headers=headers)
    assert response.status_code == status
    if status == 302:
        assert response.location == "/login"
    else:
        assert response.json == {"error": "Open Intercept through AMI"}


def test_away_via_ami_and_public_assets(client, anon_client):
    with client.session_transaction() as sess:
        sess["via_ami"] = True
    assert client.get("/change-password", headers=AWAY).status_code == 200
    for path in ("/favicon.svg", "/static/css/ami-theme.css"):
        assert anon_client.get(path, headers=AWAY).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Intercept-Access": "home"}])
def test_internal_and_home_password_login_unchanged(anon_client, monkeypatch, headers):
    monkeypatch.setattr(runtime, "check_password_hash", lambda *_: True)
    with anon_client.session_transaction() as sess:
        sess.update(logged_in=True, username="bob", role="viewer", via_ami=True)
    assert anon_client.get("/login", headers=headers).status_code == 200
    assert anon_client.get("/health", headers=headers).status_code == 200
    assert anon_client.post("/login", headers=headers,
                            data={"username": "operator", "password": "pw"}).status_code == 302
    with anon_client.session_transaction() as sess:
        assert sess["logged_in"] and "via_ami" not in sess


@pytest.mark.parametrize("setting,value", [
    ("INTERCEPT_TRUSTED_PROXIES", "0"), ("INTERCEPT_TRUSTED_PROXIES", "invalid"),
    ("INTERCEPT_TRUSTED_PROXIES", "-1"), ("INTERCEPT_AMI_ONLY_AWAY", None),
])
def test_header_ignored_without_opt_in_or_proxy(anon_client, monkeypatch, setting, value):
    if value is None:
        monkeypatch.delenv(setting)
    else:
        monkeypatch.setenv(setting, value)
    assert anon_client.get("/login", headers=AWAY).status_code == 200
    assert anon_client.get("/health", headers=AWAY).status_code == 200


def test_module_and_mcp_unaffected(anon_client, monkeypatch):
    from utils import ami
    monkeypatch.setattr(ami, "_journal", Mock())
    for headers in (AWAY, {}):
        manifest = anon_client.get("/.well-known/ami-module.json", headers=headers).json
        assert manifest["ui"]["session"] == "/api/module/session"
        assert manifest["ui"]["enter"] == "/ami/enter"
        assert anon_client.get("/api/module/health", headers=headers).status_code == 200
        response = anon_client.post("/api/module/mcp", headers={**headers, **AUTH},
                                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response.json["result"] == {}
        assert anon_client.post("/api/module/mcp", headers=headers, json={}).status_code == 401


def test_disable_auth_does_not_bypass_away_gate(anon_client, monkeypatch):
    monkeypatch.setenv("INTERCEPT_DISABLE_AUTH", "1")
    assert anon_client.get("/", headers=AWAY).location == "/login"


def test_enabled_migration_for_existing_accounts(tmp_path, monkeypatch):
    database.close_db()
    path = tmp_path / "old.sqlite"
    monkeypatch.setattr(database, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'old', 'unused', 'viewer')")
    database.init_db()
    assert ami_access.enabled_account("old")["role"] == "viewer"


@pytest.mark.parametrize("body", [None, [], {}, {"user": "alice", "role": "admin"}])
def test_incomplete_or_invalid_body_denied(anon_client, body):
    response = anon_client.post("/api/module/session", json=body, headers=AUTH)
    assert response.status_code == 403 and response.json == {"error": "not allowed"}


def test_disabled_password_login_denied(anon_client, monkeypatch):
    verify = Mock(side_effect=AssertionError("disabled account must not authenticate"))
    monkeypatch.setattr(runtime, "check_password_hash", verify)
    with database.get_db() as conn:
        conn.execute("UPDATE users SET enabled=0 WHERE username='operator'")
    response = anon_client.post("/login", data={"username": "operator", "password": "pw"})
    assert b"INVALID CREDENTIALS" in response.data
    verify.assert_not_called()


def test_ticket_consumption_is_atomic():
    from concurrent.futures import ThreadPoolExecutor

    tickets = ami_access.EntryTickets()
    ticket = tickets.issue("operator")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(tickets.consume, [ticket] * 8))
    assert results.count("operator") == 1
    assert results.count(None) == 7


@pytest.mark.parametrize("value", ["away", "away,home", "home,away", "Home", " home", "home ", "", "x"])
def test_anything_but_exact_home_is_away(anon_client, monkeypatch, value):
    """Fails closed: a smuggled duplicate or odd value never counts as home."""
    monkeypatch.setenv("INTERCEPT_TRUSTED_PROXIES", "1")
    monkeypatch.setenv("INTERCEPT_AMI_ONLY_AWAY", "1")
    response = anon_client.get("/login", headers={"X-Intercept-Access": value})
    assert response.status_code == 403
