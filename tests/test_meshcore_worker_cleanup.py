"""Worker exit must drain deferred transport close callbacks."""
import asyncio
from unittest.mock import Mock

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
