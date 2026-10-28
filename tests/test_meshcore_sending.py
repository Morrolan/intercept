"""Observe radio submission outcomes without transmitting any messages."""
import asyncio
import sys
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from utils.meshcore import MeshcoreClient, SerialConfig
from utils.meshcore_client import AsyncWorker


@pytest.fixture
def worker(monkeypatch):
    events = SimpleNamespace(OK='ok', MSG_SENT='sent', ERROR='error')
    monkeypatch.setitem(sys.modules, 'meshcore', SimpleNamespace(EventType=events))
    w = AsyncWorker(SerialConfig(), Mock())
    w._mc = Mock()
    w._mc.commands.send_chan_msg = AsyncMock(return_value=SimpleNamespace(type=events.OK))
    w._mc.commands.send_msg = AsyncMock(return_value=SimpleNamespace(type=events.MSG_SENT))

    def submit(coro):
        future = Future()
        try:
            future.set_result(asyncio.run(coro))
        except Exception as exc:
            future.set_exception(exc)
        return future

    monkeypatch.setattr(w, '_submit', submit)
    return w


def test_broadcast_uses_channel_zero(worker):
    future = worker.send_text('BROADCAST', 'synthetic')
    worker._mc.commands.send_chan_msg.assert_awaited_once_with(0, 'synthetic')
    worker._mc.commands.send_msg.assert_not_awaited()
    assert future.result() is None


def test_direct_message_uses_direct_command(worker):
    future = worker.send_text('aa' * 32, 'synthetic')
    worker._mc.commands.send_msg.assert_awaited_once_with('aa' * 32, 'synthetic')
    worker._mc.commands.send_chan_msg.assert_not_awaited()
    assert future.result() is None


@pytest.mark.parametrize('response,exception', [
    (SimpleNamespace(type='error'), RuntimeError),
    (None, TimeoutError),
    (SimpleNamespace(type='error', payload={'reason': 'no_event_received'}), TimeoutError),
    (SimpleNamespace(type='error', payload={'reason': 'timeout'}), TimeoutError),
    (SimpleNamespace(type='error', payload={'error': 'write failed'}), TimeoutError),
])
def test_radio_rejection_or_no_confirmation_is_observed(worker, response, exception):
    worker._mc.commands.send_chan_msg.return_value = response
    with pytest.raises(exception):
        worker.send_text('BROADCAST', 'synthetic').result()


def test_client_rejects_disconnected_send():
    client = MeshcoreClient()
    with pytest.raises(ConnectionError):
        client.send_text('BROADCAST', 'synthetic')


def test_client_observes_worker_failure():
    client = MeshcoreClient()
    client.on_connected('ble', 'synthetic')
    future = Future()
    future.set_exception(RuntimeError('Radio rejected message'))
    client._worker = Mock()
    client._worker.send_text.return_value = future
    with pytest.raises(RuntimeError, match='Radio rejected'):
        client.send_text('BROADCAST', 'synthetic')


def test_client_does_not_treat_submission_timeout_as_success():
    client = MeshcoreClient()
    client.on_connected('ble', 'synthetic')
    client._worker = Mock()
    client._worker.send_text.return_value.result.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        client.send_text('BROADCAST', 'synthetic')
