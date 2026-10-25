"""Short-lived AMI browser entry passes; no bearer secret reaches the browser."""
import hashlib
import os
import secrets
import threading
import time
from collections import deque

from flask import request, session

from utils.database import get_db


def away_request():
    """Caddy must overwrite the access header and be the only public ingress. Fails closed: with the header
    present, only one exact "home" is home; anything else (away, duplicates joined as "away,home", other
    values) is away. No header at all is an internal call (AMI on the Docker network, the healthcheck)."""
    try:
        trusted = int(os.environ.get("INTERCEPT_TRUSTED_PROXIES", "0")) > 0
    except ValueError:
        trusted = False
    if not trusted or os.environ.get("INTERCEPT_AMI_ONLY_AWAY") != "1":
        return False
    value = request.headers.get("X-Intercept-Access")
    return value is not None and value != "home"


def mapped_account(username):
    if not isinstance(username, str) or not username:
        return None
    for entry in os.environ.get("INTERCEPT_AMI_USERS", "").split(","):
        source, separator, target = entry.strip().partition("=")
        if source.strip() == username:
            return (target.strip() if separator else source.strip()) or None
    return None


def enabled_account(username):
    with get_db() as conn:
        row = conn.execute(
            "SELECT username, role, must_change_password FROM users WHERE username = ? AND enabled = 1",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def start_session(account, *, via_ami=False):
    # Flask's signed-cookie sessions have no server-side id to regenerate.
    # Clear all old authentication state before issuing the replacement cookie.
    session.clear()
    session["logged_in"] = True
    session["username"] = account["username"]
    session["role"] = account["role"]
    if account["must_change_password"]:
        session["must_change_password"] = True
    if via_ami:
        session["via_ami"] = True


class EntryTickets:
    """Single-worker, atomic one-use store, bounded by a global issuance limit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tickets = {}
        self._attempts = deque()

    def rate_allowed(self):
        with self._lock:
            now = time.monotonic()
            while self._attempts and self._attempts[0] <= now - 60:
                self._attempts.popleft()
            if len(self._attempts) >= 30:
                return False
            self._attempts.append(now)
            return True

    def issue(self, username):
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._tickets = {key: value for key, value in self._tickets.items() if value[1] > now}
            self._tickets[hashlib.sha256(ticket.encode()).digest()] = (username, now + 60)
        return ticket

    def consume(self, ticket):
        if not isinstance(ticket, str) or not 32 <= len(ticket) <= 128:
            return None
        with self._lock:
            stored = self._tickets.pop(hashlib.sha256(ticket.encode()).digest(), None)
            if stored and stored[1] > time.monotonic():
                return stored[0]
        return None


entry_tickets = EntryTickets()
