"""Local cross-repository contract smoke; fake device, real private HTTP."""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from utils.flipper_receiver import FlipperClient, FlipperError, FlipperReceiver

MODULE = Path(__file__).resolve().parents[2] / "ami-module-flipper"


@pytest.mark.skipif(
    not (MODULE / "server.mjs").exists() or not shutil.which("node"),
    reason="Local sibling Flipper module and Node required",
)
def test_real_flipper_http_capture_and_cancel():
    script = """
import {createService} from './server.mjs';
import {createHash} from 'node:crypto';
const transport={exchange:async()=> 'firmware_origin_fork : Momentum\\nfirmware_version : mntm-012',
 receive:async({durationS,signal,onReady,onLine})=>{
  onReady();onLine('Synthetic OOK observation');
  await new Promise(resolve=>{const timer=durationS===1?setTimeout(resolve,50):null;
   signal.addEventListener('abort',()=>{clearTimeout(timer);resolve();},{once:true});if(signal.aborted){clearTimeout(timer);resolve();}});
 }};
const service=createService({mode:'fake',directories:['/ext/nfc'],digest:createHash('sha256').update('synthetic-test-token').digest('hex'),
 acceptedVersion:'mntm-012',receiveEnabled:true}, {transport,events:{update(){}}});
service.server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:service.server.address().port})));
process.on('SIGTERM',async()=>{await service.stop();process.exit(0);});
"""
    process = subprocess.Popen(
        ["node", "--input-type=module", "-e", script],
        cwd=MODULE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    receiver = None
    try:
        port = json.loads(process.stdout.readline())["port"]
        origin = f"http://127.0.0.1:{port}"
        with pytest.raises(FlipperError):
            FlipperClient(origin, "wrong-token").status()
        events = []
        receiver = FlipperReceiver(events.append, lambda: FlipperClient(origin, "synthetic-test-token"))
        receiver.start("433.92", 1)
        receiver._thread.join(3)
        assert receiver.snapshot()["state"] == "completed"
        assert receiver.snapshot()["observations"] == [{"seq": 1, "text": "Synthetic OOK observation"}]
        assert any(e["type"] == "raw" for e in events)
        receiver.start("433.92", 30)
        deadline = time.monotonic() + 3
        while receiver.snapshot()["session_id"] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert receiver.stop(timeout=3)
        assert receiver.snapshot()["state"] == "cancelled"
    finally:
        if receiver:
            receiver.stop(timeout=1)
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
