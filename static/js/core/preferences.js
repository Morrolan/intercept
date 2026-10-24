/* Account preferences. Registry/classification comes from utils/preferences.py.
 * Loaded synchronously before every localStorage reader, including in AMI.
 */
(() => {
    'use strict';
    const config = JSON.parse(document.getElementById('intercept-account-prefs').textContent);
    let store;
    try { store = window.localStorage; } catch (_) { return; }
    const keys = new Set(config.syncedKeys);
    const rawSet = Storage.prototype.setItem;
    const rawRemove = Storage.prototype.removeItem;
    const ownerKey = 'intercept.prefs.owner';
    const pendingKey = 'intercept.prefs.pending.' + config.owner;
    let activeBatch = Object.create(null);
    let pending = Object.create(null), imports = Object.create(null), timer, sending = false;
    const apply = prefs => {
        for (const [key, value] of Object.entries(prefs)) {
            if (!keys.has(key)) continue;
            try {
                if (value === null) rawRemove.call(store, key);
                else if (typeof value === 'string') rawSet.call(store, key, value);
            } catch (_) { /* Storage quota/privacy mode: sync must not stop startup. */ }
        }
    };
    try {
        const previous = store.getItem(ownerKey);
        // Never migrate another signed-in account's local values.
        if (previous !== null && previous !== config.owner) {
            for (const key of keys) rawRemove.call(store, key);
        }
        rawSet.call(store, ownerKey, config.owner);
        apply(config.prefs);
        for (const key of keys) {
            if (!Object.hasOwn(config.prefs, key)) {
                const value = store.getItem(key);
                if (value !== null) imports[key] = value;
            }
        }
    } catch (_) { /* Keep the page usable with unavailable storage. */ }
    // An offline write must survive navigation before the server recovers.
    try {
        const saved = JSON.parse(store.getItem(pendingKey) || '{}');
        pending = Object.fromEntries(Object.entries(saved).filter(([k, v]) =>
            keys.has(k) && (v === null || typeof v === 'string')));
        apply(pending);
    } catch (_) { /* Invalid/blocked outbox must not stop startup. */ }
    function remember() {
        try {
            const unsent = { ...activeBatch, ...pending };
            if (Object.keys(unsent).length) rawSet.call(store, pendingKey, JSON.stringify(unsent));
            else rawRemove.call(store, pendingKey);
        } catch (_) { /* Local preferences still work if the quota is full. */ }
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(flush, 700); };
    async function flush() {
        clearTimeout(timer);
        if (sending) return;
        const importing = Object.keys(imports).length > 0;
        const batch = importing ? imports : pending;
        if (!Object.keys(batch).length) return;
        if (importing) imports = Object.create(null);
        else pending = Object.create(null);
        sending = true;
        if (!importing) activeBatch = batch;
        try {
            const body = JSON.stringify(batch);
            const response = await fetch('/api/me/prefs' + (importing ? '?import=1' : ''), {
                method: 'PUT', credentials: 'same-origin', keepalive: new Blob([body]).size < 60000,
                headers: { 'Content-Type': 'application/json', 'X-Intercept-Prefs': '1', 'X-Intercept-Prefs-Owner': config.owner },
                body
            });
            if (!response.ok) throw new Error('Preferences unavailable');
            if (importing) {
                const { prefs } = await response.json();
                // A simultaneous import can only fill missing keys. Preserve
                // edits made here while that request was in flight.
                apply(Object.fromEntries(Object.entries(prefs).filter(([k]) => !Object.hasOwn(pending, k))));
            }
        } catch (_) {
            // Keep failed batches for online/pagehide or the next write. Newer
            // edits win, and failures never undo the working local preference.
            if (importing) imports = { ...batch, ...imports };
            else pending = { ...batch, ...pending };
            return;
        } finally {
            activeBatch = Object.create(null);
            sending = false;
            remember();
        }
        if (Object.keys(imports).length || Object.keys(pending).length) schedule();
    }
    function queue(key, value) { pending[key] = value; remember(); schedule(); }
    Storage.prototype.setItem = function (key, value) {
        key = String(key); value = String(value);
        rawSet.call(this, key, value);
        if (this === store && keys.has(key)) queue(key, value);
    };
    Storage.prototype.removeItem = function (key) {
        key = String(key);
        rawRemove.call(this, key);
        if (this === store && keys.has(key)) queue(key, null);
    };
    addEventListener('pagehide', flush);
    addEventListener('online', flush);
    window.InterceptPrefs = { apply, flush, syncedKeys: config.syncedKeys,
        perDeviceKeys: config.perDeviceKeys, perDevicePrefixes: config.perDevicePrefixes };
    if (Object.keys(imports).length || Object.keys(pending).length) schedule();
})();
