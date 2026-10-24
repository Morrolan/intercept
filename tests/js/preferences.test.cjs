/* Real client script, isolated browser primitives; no external dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/core/preferences.js', 'utf8');
function browser(prefs = {}, initial = {}, owner = '1') {
    class Storage {
        constructor(data = {}) { this.data = { ...data }; }
        getItem(k) { return Object.hasOwn(this.data, k) ? this.data[k] : null; }
        setItem(k, v) { this.data[k] = String(v); }
        removeItem(k) { delete this.data[k]; }
    }
    const store = new Storage(initial), session = new Storage(), calls = [], events = {};
    const config = { owner, prefs, syncedKeys: ['observerLat', 'observerLon', 'interceptTimezone'], perDeviceKeys: [], perDevicePrefixes: [] };
    let fail = false, server = { ...prefs };
    const context = vm.createContext({
        Storage, Blob, localStorage: store, sessionStorage: session,
        document: { getElementById: () => ({ textContent: JSON.stringify(config) }) },
        setTimeout: () => 1, clearTimeout: () => {},
        addEventListener: (name, fn) => { events[name] = fn; },
        fetch: async (url, options) => {
            calls.push({ url, options, data: JSON.parse(options.body) });
            if (fail) throw new Error('offline');
            for (const [k, v] of Object.entries(JSON.parse(options.body))) {
                if (!url.includes('import=1') || !Object.hasOwn(server, k)) server[k] = v;
            }
            return { ok: true, json: async () => ({ prefs: server }) };
        }
    });
    context.window = context;
    vm.runInContext(source, context);
    return { store, session, calls, events, prefs: context.InterceptPrefs,
        offline(value) { fail = value; }, server };
}
(async () => {
    const b = browser({ observerLat: 'server', observerLon: null }, {
        observerLat: 'old', observerLon: 'stale', interceptTimezone: 'local-zone', mainSidebarCollapsed: 'true'
    });
    assert.equal(b.store.getItem('observerLat'), 'server');
    assert.equal(b.store.getItem('observerLon'), null);
    assert.equal(b.store.getItem('mainSidebarCollapsed'), 'true');
    await b.prefs.flush();
    assert.deepEqual(b.calls[0].data, { interceptTimezone: 'local-zone' });
    assert.match(b.calls[0].url, /import=1/);
    b.store.setItem('observerLat', 'new');
    b.store.removeItem('observerLon');
    b.store.setItem('mainSidebarCollapsed', 'false');
    b.session.setItem('observerLat', 'session-only');
    await b.prefs.flush();
    assert.deepEqual(b.calls[1].data, { observerLat: 'new', observerLon: null });
    assert.equal(b.calls[1].options.headers['X-Intercept-Prefs-Owner'], '1');
    b.offline(true);
    b.store.setItem('observerLat', 'offline');
    await b.prefs.flush();
    assert.equal(b.store.getItem('observerLat'), 'offline');
    const reload = browser(b.server, b.store.data);
    assert.equal(reload.store.getItem('observerLat'), 'offline');
    await reload.prefs.flush();
    assert.equal(reload.server.observerLat, 'offline');
    assert.equal(reload.store.getItem('intercept.prefs.pending.1'), null);
    b.store.setItem('observerLat', 'newer');
    b.offline(false);
    await b.prefs.flush();
    assert.equal(b.server.observerLat, 'newer');
    const switched = browser({}, b.store.data, '2');
    assert.equal(switched.store.getItem('observerLat'), null);
    assert.equal(switched.store.getItem('mainSidebarCollapsed'), 'false');
    await switched.prefs.flush();
    assert.equal(switched.calls.length, 0);
    // Large valid values need ordinary fetch, beyond the keepalive body limit.
    const big = browser();
    big.store.setItem('observerLat', 'x'.repeat(65536));
    await big.prefs.flush();
    assert.equal(big.calls[0].options.keepalive, false);
    console.log('Preference client hydration/import/write/remove/offline/reload/isolation checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
