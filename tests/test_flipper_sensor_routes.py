"""Manual Flipper reception uses no SDR reservation or rtl_433 process."""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def receiver(monkeypatch):
    from routes import sensor

    monkeypatch.setattr("app.sensor_process", None)
    fake = Mock()
    fake.snapshot.return_value = {
        "running": False,
        "source": "flipper",
        "state": "idle",
        "observations": [],
        "cursor": 0,
    }
    monkeypatch.setattr(sensor, "flipper_receiver", fake, raising=False)
    monkeypatch.setattr(sensor, "enabled_account", lambda name: {"role": "admin"}, raising=False)
    return fake


def test_flipper_start_never_claims_sdr_or_launches_rtl(client, receiver):
    with patch("app.claim_sdr_device") as claim, patch("routes.sensor.subprocess.Popen") as popen:
        response = client.post("/start_sensor", json={"source": "flipper", "frequency": "433.92", "duration_s": 10})
    assert response.status_code == 200
    assert response.get_json()["source"] == "flipper"
    receiver.start.assert_called_once_with("433.92", 10)
    claim.assert_not_called()
    popen.assert_not_called()


def test_flipper_start_requires_current_admin_role(client, receiver, monkeypatch):
    monkeypatch.setattr("routes.sensor.enabled_account", lambda name: {"role": "operator"})
    response = client.post("/start_sensor", json={"source": "flipper", "frequency": "433.92", "duration_s": 10})
    assert response.status_code == 403
    receiver.start.assert_not_called()


def test_flipper_status_includes_remote_session(client, receiver):
    receiver.snapshot.return_value = {"running": True, "source": "flipper", "state": "receiving"}
    assert client.get("/sensor/status").get_json()["source"] == "flipper"


def test_stop_does_not_claim_unconfirmed_remote_stop(client, receiver):
    receiver.snapshot.return_value = {"running": True, "state": "stopping"}
    receiver.stop.return_value = False
    response = client.post("/stop_sensor")
    assert response.status_code == 503


def test_status_does_not_bypass_admin_observation_guard(client, receiver, monkeypatch):
    monkeypatch.setattr("routes.sensor.enabled_account", lambda name: {"role": "operator"})
    receiver.snapshot.return_value = {
        "running": True,
        "source": "flipper",
        "state": "receiving",
        "observations": [{"seq": 1, "text": "private"}],
        "session_id": "private-session",
    }
    payload = client.get("/sensor/status").get_json()
    assert "observations" not in payload and "session_id" not in payload
    assert client.get("/sensor/flipper/observations").status_code == 403


def test_global_stop_refuses_false_success_when_remote_stop_unconfirmed(client, receiver):
    receiver.snapshot.return_value = {"running": True, "state": "receiving"}
    receiver.stop.return_value = False
    with patch("app.subprocess.run") as run:
        response = client.post("/killall")
    assert response.status_code == 503
    receiver.stop.assert_called_once()
    run.assert_not_called()


def test_flipper_payloads_stay_out_of_shared_sensor_stream(client, receiver):
    from routes import sensor

    with patch("app.sensor_queue") as shared:
        sensor._publish_flipper_status({"type": "raw", "source": "flipper", "text": "private observation"})
        shared.put_nowait.assert_not_called()
        sensor._publish_flipper_status({"type": "status", "source": "flipper", "text": "started"})
        shared.put_nowait.assert_called_once_with({"type": "status", "source": "flipper", "text": "started"})
