/** Bounded Flipper OOK observations, kept separate from rtl_433 sensor decoding. */
window.FlipperSensor = (function () {
    let active = false, cursor = 0, request = 0, timer = null, starting = null;
    const element = id => document.getElementById(id);
    async function requestJSON(url, options = {}, timeoutMs = 5000) {
        const controller = new AbortController();
        const deadline = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, {...options, signal: controller.signal});
            return {response, data: await response.json()};
        } finally { clearTimeout(deadline); }
    }
    function selected() { return element('sensorSource')?.value === 'flipper'; }
    function controls(running) {
        const flipper = selected();
        document.body.dataset.sensorSource = flipper ? 'flipper' : 'rtl';
        if (element('flipperSensorView')) element('flipperSensorView').hidden = !flipper;
        for (const id of ['sensorGain', 'sensorPpm', 'sensorUnits', 'sensorLogging']) {
            if (element(id)) element(id).disabled = flipper;
        }
        for (const id of ['sensorRtlSettings', 'sensorRtlProtocols', 'sensorAntennaGuide']) {
            if (element(id)) element(id).hidden = flipper;
        }
        if (element('flipperSensorSettings')) element('flipperSensorSettings').hidden = !flipper;
        if (element('sensorSource')) element('sensorSource').disabled = running;
        if (element('sensorFrequency')) element('sensorFrequency').disabled = flipper && running;
        if (element('flipperSensorDuration')) element('flipperSensorDuration').disabled = running;
        document.querySelectorAll('#sensorMode .preset-btn').forEach(button => { button.disabled = flipper && running; });
        if (flipper && element('sensorScopePanel')) element('sensorScopePanel').style.display = 'none';
    }
    function selectSource() {
        if (!active) { request++; clearTimeout(timer); cursor = 0; controls(false); }
    }
    async function poll() {
        clearTimeout(timer);
        const current = ++request;
        try {
            const {response, data} = await requestJSON('/sensor/flipper/observations?after=' + cursor);
            if (current !== request) return;
            if (!response.ok) throw new Error(data.message || 'Flipper status unavailable');
            for (const observation of data.observations || []) {
                if (observation.seq > cursor) {
                    const line = document.createElement('div');
                    line.className = 'flipper-observation';
                    line.textContent = observation.text;
                    element('flipperSensorOutput').appendChild(line);
                    cursor = observation.seq;
                }
            }
            element('flipperSensorCount').textContent = 'Observations: ' + cursor;
            element('flipperSensorNotice').textContent = data.error || (data.truncated ? 'Observation limit reached' : data.state);
            active = !!data.running;
            setSensorRunning(active);
            controls(active);
            if (data.state === 'error') {
                element('statusText').textContent = 'Flipper receive needs attention';
                if (data.error) showInfo(data.error);
            }
            if (active) timer = setTimeout(poll, 500);
        } catch (error) {
            if (current !== request) return;
            showInfo(error.message);
            // Network failure is not confirmation that the bounded lease stopped.
            if (active) timer = setTimeout(poll, 1000);
        }
    }
    async function start() {
        const duration = element('flipperSensorDuration');
        if (!duration.reportValidity()) return;
        if (typeof currentAgent !== 'undefined' && currentAgent !== 'local') {
            showInfo('Flipper reception is configured on this Intercept server; select Local first.');
            return;
        }
        const frequency = element('sensorFrequency').value;
        cursor = 0;
        request++;
        clearTimeout(timer);
        element('flipperSensorCount').textContent = 'Observations: 0';
        element('flipperSensorOutput').replaceChildren();
        element('flipperSensorNotice').textContent = 'Starting receiver…';
        active = true;
        setSensorRunning(true);
        controls(true);
        const pending = requestJSON('/start_sensor', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({source: 'flipper', frequency, duration_s: Number(duration.value)})});
        starting = pending;
        try {
            const {response, data} = await pending;
            if (!response.ok || data.status !== 'started') {
                active = false;
                setSensorRunning(false);
                controls(false);
                element('flipperSensorNotice').textContent = data.message || 'Flipper receive could not start';
                showInfo(element('flipperSensorNotice').textContent);
                return;
            }
            await poll();
        } catch {
            element('flipperSensorNotice').textContent = 'Start confirmation unavailable; checking receiver…';
            await poll();
        } finally { if (starting === pending) starting = null; }
    }
    async function stop() {
        // Do not race a stop request ahead of its still-pending local start.
        if (starting) { try { await starting; } catch { /* Status remains authoritative. */ } }
        let data;
        try {
            const result = await requestJSON('/stop_sensor', {method: 'POST'}, 6000);
            const response = result.response;
            data = result.data;
            if (!response.ok) showInfo(data.message || 'Flipper stop is not confirmed');
        } catch { data = {status: 'error'}; showInfo('Flipper stop is not confirmed; checking its bounded session.'); }
        await poll();
        return data;
    }
    async function init() {
        const option = element('sensorFlipperOption');
        if (!option) return;
        try {
            const {data} = await requestJSON('/sensor/flipper');
            option.disabled = !data.configured || !data.can_receive;
            option.title = !data.can_receive ? 'Administrator access required' : !data.configured ? 'Flipper module not configured' : '';
            const {data: status} = await requestJSON('/sensor/status');
            if (status.source === 'flipper' && status.running && !option.disabled) {
                element('sensorSource').value = 'flipper';
                active = true;
                await poll();
            }
        } catch { option.disabled = true; option.title = 'Flipper module unavailable'; }
        controls(active);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
    return {selected, start, stop, selectSource, refresh: poll, isActive: () => active};
})();
