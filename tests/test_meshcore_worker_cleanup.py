"""Worker exit must drain deferred transport close callbacks."""
import asyncio
from unittest.mock import Mock

import pytest

from utils.meshcore import SerialConfig
from utils.meshcore_client import AsyncWorker


def test_worker_drains_close_callbacks_and_cancels_tasks():
    worker = AsyncWorker(SerialConfig(port='/dev/test'), Mock())
    worker._loop = asyncio.new_event_loop()
    closed = []
    tasks = []

    async def pending_reader():
        try:
            await asyncio.Event().wait()
        finally:
            closed.append('reader')

    async def deferred_close():
        await asyncio.sleep(0.01)
        closed.append('transport')

    async def failed_connect():
        tasks.append(asyncio.create_task(pending_reader()))
        await asyncio.sleep(0)
        # SerialTransport.close schedules its actual descriptor close for later.
        asyncio.create_task(deferred_close())

    worker._connect_with_retry = failed_connect
    worker._run()
    assert closed == ['transport', 'reader']
    assert tasks[0].cancelled()
    assert worker._loop.is_closed()


def test_ble_connection_keeps_protocol_debug_logging_disabled():
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from utils.meshcore import BLEConfig

    mc = Mock()
    mc.contacts = {}
    mc.commands.get_contacts = AsyncMock()
    mc.disconnect = AsyncMock()
    mc.start_auto_message_fetching = AsyncMock()
    factory = Mock()
    factory.create_ble = AsyncMock(return_value=mc)
    library = SimpleNamespace(MeshCore=factory, EventType=Mock())
    client = Mock()
    worker = AsyncWorker(BLEConfig(), client)
    client.on_connected.side_effect = lambda **kwargs: worker._stop_event.set()
    with patch.dict(sys.modules, {'meshcore': library}):
        asyncio.run(worker._do_connect())
    factory.create_ble.assert_awaited_once_with(address=None, debug=False)

    mc.start_auto_message_fetching.assert_awaited_once()


@pytest.mark.parametrize('phase', ['contacts', 'receive'])
def test_disconnect_during_setup_is_not_overwritten_by_connected(phase):
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from utils.meshcore import BLEConfig

    client = Mock()
    worker = AsyncWorker(BLEConfig(), client)
    worker._asyncio_stop = asyncio.Event()
    mc = Mock()
    mc.is_connected = True
    mc.contacts = {}
    mc.commands.get_contacts = AsyncMock()
    mc.start_auto_message_fetching = AsyncMock()
    mc.disconnect = AsyncMock()

    async def disconnect_during_setup(*args, **kwargs):
        mc.is_connected = False
        worker._on_disconnected(None)

    if phase == 'contacts':
        mc.commands.get_contacts.side_effect = disconnect_during_setup
    else:
        mc.start_auto_message_fetching.side_effect = disconnect_during_setup
    factory = Mock()
    factory.create_ble = AsyncMock(return_value=mc)
    with patch.dict(sys.modules, {'meshcore': SimpleNamespace(MeshCore=factory, EventType=Mock())}):
        with pytest.raises(ConnectionError):
            asyncio.run(worker._do_connect())
    client.on_connected.assert_not_called()
    client.on_error.assert_called_once()
