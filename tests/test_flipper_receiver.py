"""Flipper bridge tests use fake HTTP/radio sessions only."""

import io
import threading
from unittest.mock import Mock

import pytest

from utils.flipper_receiver import FlipperClient, FlipperError, FlipperReceiver, receive_parameters


@pytest.mark.parametrize("frequency,duration", [("433.92", 10), ("315", 1), ("868", 30)])
def test_receive_parameters(frequency, duration):
    assert receive_parameters(frequency, duration) == (int(float(frequency) * 1000000), duration)


@pytest.mark.parametrize(
    "frequency,duration", [("350", 10), ("433.92", 31), ("nan", 5), ("433.9200001", 5), ("433.92", True)]
)
def test_invalid_parameters_rejected(frequency, duration):
    with pytest.raises(ValueError):
        receive_parameters(frequency, duration)


@pytest.mark.parametrize(
    "url", ["file:///tmp/x", "http://user:secret@host", "http://host/path", "http://host/?token=x"]
)
def test_private_endpoint_origin_only(url):
    with pytest.raises(FlipperError):
        FlipperClient(url, "token")


def test_http_is_bounded_and_does_not_follow_redirects():
    opener = Mock()
    response = io.BytesIO(b"x" * 262145)
    opener.open.return_value = response
    client = FlipperClient("http://flipper:3303", "token", opener=opener)
    with pytest.raises(FlipperError):
        client.status()
    assert opener.open.call_args.args[0].get_header("Authorization") == "Bearer token"


class FakeClient:
    def __init__(self):
        self.cancelled = False

    def start(self, frequency, duration):
        return {"session_id": "11111111-1111-4111-8111-111111111111", "state": "starting"}

    def poll(self, session, after):
        return {
            "session_id": session,
            "state": "cancelled" if self.cancelled else "completed",
            "frequency_hz": 433920000,
            "duration_s": 1,
            "preset": "OOK650",
            "observations": [] if self.cancelled else [{"seq": 1, "text": "Synthetic OOK observation"}],
            "cursor": 0 if self.cancelled else 1,
            "truncated": False,
            "error": None,
        }

    def cancel(self, session):
        self.cancelled = True


def test_completed_session_retains_observations_and_releases():
    events = []
    client = FakeClient()
    receiver = FlipperReceiver(events.append, lambda: client)
    receiver.start("433.92", 1)
    receiver._thread.join(2)
    status = receiver.snapshot()
    assert not status["running"] and status["state"] == "completed"
    assert status["observations"] == [{"seq": 1, "text": "Synthetic OOK observation"}]
    assert any(e["type"] == "raw" and "Flipper" in e["text"] for e in events)


def test_stop_during_start_cancels_the_eventual_remote_session():
    entered = threading.Event()
    release = threading.Event()
    client = FakeClient()
    original = client.start

    def start(*args):
        entered.set()
        release.wait(2)
        return original(*args)

    client.start = start
    receiver = FlipperReceiver(lambda e: None, lambda: client)
    receiver.start("433.92", 1)
    assert entered.wait(1)
    assert receiver.stop(timeout=0) is False
    release.set()
    receiver._thread.join(2)
    assert client.cancelled and not receiver.snapshot()["running"]


def test_unconfirmed_cancel_is_not_reported_as_stopped():
    client = FakeClient()
    client.poll = Mock(side_effect=FlipperError("unavailable"))
    client.cancel = Mock(side_effect=FlipperError("unavailable"))
    receiver = FlipperReceiver(lambda e: None, lambda: client)
    receiver.start("433.92", 1)
    receiver._thread.join(2)
    assert receiver.snapshot()["state"] == "error"
    assert receiver.snapshot()["running"] is True


def test_http_drip_response_has_total_deadline(monkeypatch):
    clock = [0.0]

    class Drip(io.BytesIO):
        def read1(self, size=-1):
            clock[0] += 0.8
            return super().read(1)

    response = Drip(b'{"ok":true}')
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr("utils.flipper_receiver.time.monotonic", lambda: clock[0])
    with pytest.raises(FlipperError):
        FlipperClient("http://flipper:3303", "token", opener).status()
    assert clock[0] < 5


def test_stop_retries_known_session_after_module_recovers():
    client = FakeClient()
    original_poll, original_cancel = client.poll, client.cancel
    client.poll = Mock(side_effect=FlipperError("offline"))
    client.cancel = Mock(side_effect=FlipperError("offline"))
    receiver = FlipperReceiver(lambda e: None, lambda: client)
    receiver.start("433.92", 1)
    receiver._thread.join(2)
    assert receiver.snapshot()["running"]
    client.poll, client.cancel = original_poll, original_cancel
    assert receiver.stop()
    assert client.cancelled
    assert receiver.snapshot()["state"] == "cancelled"


def test_expired_deadline_does_not_hide_a_live_worker():
    entered, release = threading.Event(), threading.Event()
    client = FakeClient()
    original = client.start

    def start(*args):
        entered.set()
        release.wait(2)
        return original(*args)

    client.start = start
    receiver = FlipperReceiver(lambda e: None, lambda: client)
    receiver.start("433.92", 1)
    try:
        assert entered.wait(1)
        receiver._deadline = 0
        assert receiver.snapshot()["running"]
        assert not receiver.stop(timeout=0)
    finally:
        release.set()
        receiver._thread.join(2)


@pytest.mark.parametrize(
    "change",
    [
        {"frequency_hz": 433920000.0},
        {"duration_s": True},
        {"truncated": "false"},
        {"cursor": 1, "observations": [{"seq": 1, "text": "x" * 513}]},
        {"cursor": 200, "observations": [{"seq": n, "text": "x" * 512} for n in range(1, 201)]},
    ],
)
def test_malicious_session_response_is_rejected_without_partial_history(change):
    client = FakeClient()
    session = client.start(433920000, 1)["session_id"]
    data = client.poll(session, 0)
    data.update(change)
    receiver = FlipperReceiver(lambda e: None)
    with pytest.raises(FlipperError):
        receiver._consume(data, session, 433920000, 1)
    assert receiver.snapshot()["observations"] == []


def test_raw_byte_budget_counts_sanitized_bytes_across_polls():
    client = FakeClient()
    session = client.start(433920000, 1)["session_id"]
    data = client.poll(session, 0)
    data.update(cursor=128, observations=[{"seq": n, "text": "\x01" * 512} for n in range(1, 129)])
    receiver = FlipperReceiver(lambda e: None)
    receiver._consume(data, session, 433920000, 1)
    data.update(cursor=129, observations=[{"seq": 129, "text": "extra"}])
    with pytest.raises(FlipperError):
        receiver._consume(data, session, 433920000, 1)
    assert receiver.snapshot()["cursor"] == 128


def test_terminal_worker_finishes_events_before_reporting_stopped():
    entered, release = threading.Event(), threading.Event()

    def emit(event):
        if event.get("text") == "stopped":
            entered.set()
            release.wait(2)

    receiver = FlipperReceiver(emit, FakeClient)
    receiver.start("433.92", 1)
    try:
        assert entered.wait(1)
        assert receiver.snapshot()["running"]
    finally:
        release.set()
        receiver._thread.join(2)
    assert not receiver.snapshot()["running"]


@pytest.mark.parametrize("drip_headers", [False, True])
def test_real_http_response_deadline_includes_dripping_headers(monkeypatch, drip_headers):
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                self.send_response(200)
                if drip_headers:
                    self.flush_headers()
                    self.wfile.write(b"X-Test: ")
                    self.wfile.flush()
                    for _ in range(30):
                        self.wfile.write(b"a")
                        self.wfile.flush()
                        time.sleep(0.05)
                    self.wfile.write(b"\r\n\r\n{}")
                    self.wfile.flush()
                else:
                    self.end_headers()
                    for byte in b'{"synthetic":true}':
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("Local loopback binding requires the test runner permission")
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr("utils.flipper_receiver.REQUEST_TIMEOUT", 0.2, raising=False)
    started = time.monotonic()
    try:
        with pytest.raises(FlipperError):
            FlipperClient(f"http://127.0.0.1:{server.server_port}", "synthetic").status()
        assert time.monotonic() - started < 0.8
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("origin", ["http://[invalid", "http://host:abc", "http://host:65536"])
def test_malformed_origin_is_a_configuration_error(origin):
    with pytest.raises(FlipperError):
        FlipperClient(origin, "synthetic")


@pytest.mark.parametrize(
    "change",
    [
        {"cursor": 2},
        {"cursor": 2, "observations": [{"seq": 2, "text": "missing first observation"}]},
    ],
)
def test_cursor_cannot_skip_unreceived_observations(change):
    client = FakeClient()
    session = client.start(433920000, 1)["session_id"]
    data = client.poll(session, 0)
    data.update(change)
    receiver = FlipperReceiver(lambda e: None)
    with pytest.raises(FlipperError):
        receiver._consume(data, session, 433920000, 1)
    assert receiver.snapshot()["cursor"] == 0
