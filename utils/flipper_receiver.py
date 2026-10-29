"""Bounded receive-only bridge to the Flipper module; never opens serial ports."""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation

BANDS = ((300_000_000, 348_000_000), (387_000_000, 464_000_000), (779_000_000, 928_000_000))
TERMINAL = {"completed", "cancelled", "error"}
STATES = TERMINAL | {"idle", "starting", "receiving", "stopping"}
REQUEST_TIMEOUT = 3


class FlipperError(RuntimeError):
    pass


def receive_parameters(frequency, duration):
    try:
        hz = Decimal(str(frequency)) * 1_000_000
        if not hz.is_finite() or hz != hz.to_integral_value():
            raise ValueError()
        hz = int(hz)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError("Choose a Flipper frequency in 300–348, 387–464 or 779–928 MHz") from None
    if not any(low <= hz <= high for low, high in BANDS):
        raise ValueError("Choose a Flipper frequency in 300–348, 387–464 or 779–928 MHz")
    if type(duration) is not int or not 1 <= duration <= 30:
        raise ValueError("Flipper duration must be an integer from 1 to 30 seconds")
    return hz, duration


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _deadline_opener(deadline, guards):
    def connection_factory(connection_type):
        def create(*args, **kwargs):
            connection = connection_type(*args, **kwargs)
            connect = connection.connect

            def bounded_connect():
                connect()  # Configured host DNS is trusted; socket connect has an idle timeout.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    connection.close()
                    raise TimeoutError()
                # A duplicated TCP descriptor can interrupt a header/body read
                # without waiting on HTTPResponse's buffered-reader lock. This
                # also works when the original connection is wrapped in TLS.
                guard = socket.socket(fileno=os.dup(connection.sock.fileno()))

                def expire():
                    try:
                        guard.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

                timer = threading.Timer(remaining, expire)
                timer.daemon = True
                guards.append((timer, guard))
                timer.start()

            connection.connect = bounded_connect
            return connection

        return create

    class HTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, request):
            return self.do_open(connection_factory(http.client.HTTPConnection), request)

    class HTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(connection_factory(http.client.HTTPSConnection), request)

    # The token belongs only on the configured private connection, never an
    # ambient HTTP proxy selected by the process environment.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), HTTPHandler(), HTTPSHandler())


class FlipperClient:
    def __init__(self, origin, token, opener=None):
        try:
            parsed = urllib.parse.urlsplit(origin)
            _ = parsed.port  # Validate a supplied port even before making requests.
        except ValueError:
            raise FlipperError("Flipper receiver is not configured") from None
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not token
            or any(c.isspace() for c in token)
        ):
            raise FlipperError("Flipper receiver is not configured")
        self.origin, self.token = origin.rstrip("/"), token
        self.opener = opener

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("INTERCEPT_FLIPPER_URL", ""), os.environ.get("INTERCEPT_FLIPPER_TOKEN", ""))

    def request(self, method, path, body=None):
        req = urllib.request.Request(
            self.origin + "/api/receiver" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        guards = []
        try:
            deadline = time.monotonic() + REQUEST_TIMEOUT
            # read1 performs at most one underlying read. A read(size) can wait
            # forever when a peer keeps supplying bytes before its idle timeout.
            opener = self.opener or _deadline_opener(deadline, guards)
            with opener.open(req, timeout=0.5) as response:
                raw = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError()
                    chunk = response.read1(min(16384, 262145 - len(raw)))
                    if time.monotonic() >= deadline:
                        raise ValueError()
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        raise ValueError()
                    if not chunk:
                        break
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (urllib.error.URLError, ValueError, OSError, http.client.HTTPException):
            raise FlipperError("Flipper module unavailable or response invalid") from None
        finally:
            for timer, guard in guards:
                timer.cancel()
                guard.close()

    def status(self):
        return self.request("GET", "")

    def start(self, hz, duration):
        return self.request("POST", "", {"frequency_hz": hz, "duration_s": duration})

    def poll(self, session, after):
        return self.request("GET", "/" + str(uuid.UUID(session)) + "?after=" + str(after))

    def cancel(self, session):
        return self.request("DELETE", "/" + str(uuid.UUID(session)))


class FlipperReceiver:
    """Single session with bounded replay for short captures and truthful stop state."""

    def __init__(self, emit, client_factory=FlipperClient.from_environment):
        self.emit, self.client_factory = emit, client_factory
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._state = "idle"
        self._active = False
        self._deadline = 0
        self._observations = []
        self._cursor = 0
        self._error = None
        self._session = None
        self._frequency = None
        self._truncated = False
        self._client = None
        self._duration = None
        self._bytes = 0

    def _event(self, event):
        try:
            self.emit(event)
        except Exception:
            pass  # A full UI queue must not prevent remote cancellation.

    def snapshot(self, after=0):
        with self._lock:
            worker_alive = self._thread is not None and self._thread.is_alive()
            return {
                "running": worker_alive or (self._active and time.monotonic() < self._deadline),
                "source": "flipper",
                "state": self._state,
                "error": self._error,
                "session_id": self._session,
                "frequency_hz": self._frequency,
                "preset": "OOK650",
                "cursor": self._cursor,
                "truncated": self._truncated,
                "observations": [o.copy() for o in self._observations if o["seq"] > after],
            }

    def start(self, frequency, duration):
        hz, duration = receive_parameters(frequency, duration)
        client = self.client_factory()  # Validate configuration before claiming the view.
        with self._lock:
            if (self._thread and self._thread.is_alive()) or (self._active and time.monotonic() < self._deadline):
                raise FlipperError("Flipper receiver is already running or stopping")
            self._stop = threading.Event()
            self._state, self._active, self._error = "starting", True, None
            self._observations, self._cursor, self._session = [], 0, None
            self._bytes = 0
            self._frequency, self._truncated = hz, False
            self._client, self._duration = client, duration
            self._deadline = time.monotonic() + duration + 10
            self._thread = threading.Thread(
                target=self._run, args=(client, hz, duration), daemon=True, name="flipper-receiver"
            )
            self._thread.start()

    def stop(self, timeout=4):
        with self._lock:
            self._stop.set()
            thread = self._thread
            if (not thread or not thread.is_alive()) and self._active and self._session:
                # A previous transport failure must not make the Stop button
                # powerless after the module becomes reachable again.
                thread = threading.Thread(target=self._retry_stop, daemon=True, name="flipper-cancel")
                self._thread = thread
                thread.start()
        if thread and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.snapshot()["running"]

    def _retry_stop(self):
        confirmed = False
        try:
            self._client.cancel(self._session)
            while True:
                data = self._client.poll(self._session, self._cursor)
                state = self._consume(data, self._session, self._frequency, self._duration)
                if state in ("completed", "cancelled"):
                    confirmed = True
                    break
                if state == "error" or time.monotonic() >= self._deadline:
                    break
                time.sleep(0.1)
        except Exception:
            pass
        finally:
            with self._lock:
                self._active = not confirmed
                if confirmed:
                    self._error = None
            if confirmed:
                self._event({"type": "status", "source": "flipper", "text": "stopped"})

    def _consume(self, data, session, hz, duration):
        if (
            data.get("session_id") != session
            or data.get("state") not in STATES - {"idle"}
            or type(data.get("frequency_hz")) is not int
            or data["frequency_hz"] != hz
            or type(data.get("duration_s")) is not int
            or data["duration_s"] != duration
            or data.get("preset") != "OOK650"
            or type(data.get("truncated")) is not bool
        ):
            raise FlipperError("Invalid Flipper session response")
        observations, cursor = data.get("observations"), data.get("cursor")
        if (
            not isinstance(observations, list)
            or len(observations) > 200
            or type(cursor) is not int
            or not 0 <= cursor <= 200
        ):
            raise FlipperError("Invalid Flipper observations")
        fresh = []
        with self._lock:
            previous = self._cursor
            total_bytes = self._bytes
            for item in observations:
                if (
                    not isinstance(item, dict)
                    or type(item.get("seq")) is not int
                    or item["seq"] != previous + 1
                    or item["seq"] > cursor
                    or not isinstance(item.get("text"), str)
                    or len(item["text"].encode()) > 512
                ):
                    raise FlipperError("Invalid Flipper observation")
                text = re.sub(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", "", item["text"])
                fresh.append({"seq": item["seq"], "text": text})
                total_bytes += len(item["text"].encode())
                previous = item["seq"]
            if (
                cursor != previous
                or cursor < self._cursor
                or len(self._observations) + len(fresh) > 200
                or total_bytes > 65536
            ):
                raise FlipperError("Invalid Flipper cursor")
            self._observations.extend(fresh)
            self._bytes = total_bytes
            self._cursor, self._state = cursor, data["state"]
            self._truncated = bool(data.get("truncated"))
        for item in fresh:
            self._event(
                {"type": "raw", "source": "flipper", "text": f"Flipper {hz / 1e6:g} MHz OOK650: {item['text']}"}
            )
        return data["state"]

    def _run(self, client, hz, duration):
        session, confirmed = None, False
        try:
            result = client.start(hz, duration)
            session = str(uuid.UUID(result["session_id"]))
            if result.get("state") != "starting":
                raise FlipperError("Invalid Flipper start response")
            with self._lock:
                self._session = session
            self._event({"type": "status", "source": "flipper", "text": "started"})
            cancelled = False
            while time.monotonic() < self._deadline:
                if self._stop.is_set() and not cancelled:
                    client.cancel(session)
                    cancelled = True
                data = client.poll(session, self._cursor)
                state = self._consume(data, session, hz, duration)
                if state in TERMINAL:
                    confirmed = state != "error"
                    if state == "error":
                        raise FlipperError("Flipper receive failed; check module and CLI recovery status")
                    break
                self._stop.wait(0.25) if not cancelled else time.sleep(0.1)
            else:
                raise FlipperError("Flipper session deadline exceeded")
        except Exception:
            if session:
                try:
                    client.cancel(session)
                    data = client.poll(session, self._cursor)
                    if data.get("state") in ("completed", "cancelled"):
                        self._consume(data, session, hz, duration)
                        confirmed = True
                except Exception:
                    pass
            with self._lock:
                self._state = "error"
                self._error = (
                    "Receive failed; stop unconfirmed until the bounded session expires"
                    if not confirmed
                    else "Flipper receive failed"
                )
            self._event({"type": "error", "source": "flipper", "text": self._error})
        finally:
            with self._lock:
                self._active = not confirmed
            if confirmed:
                self._event({"type": "status", "source": "flipper", "text": "stopped"})
