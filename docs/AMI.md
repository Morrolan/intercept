# Intercept in AMI

This fork retains the native Flask application and receiver/decoder processes. Its AMI visual layer also applies when used standalone. `?ami=1` embeds it in AMI, with mode navigation and receiver controls still available. Spectrum, map and warning colours retain their meanings. The theme and bridge are local assets and work offline. Static asset URLs use an `-ami1` cache revision so browsers discard scripts cached from the upstream release without a release-version bump.

## Enable the module

Use an HTTPS hostname under the same parent domain as AMI (for example `intercept.example.test` and `ami.example.test`). The browser must be able to send Intercept's own sign-in cookie in AMI's frame. Authentication remains enabled; never use `INTERCEPT_DISABLE_AUTH` for this deployment. AMI's service-token integration does not sign a browser into Intercept.

1. Create a service token locally, outside shell history, using `python3 scripts/ami-token.py`. Store the printed token in your password manager and paste it into AMI's module registration. Store the separately printed digest in Intercept's private environment file. The script neither writes a credential file nor changes running configuration.
2. Configure Intercept, then restart it through its normal deployment:

   ```dotenv
   AMI_URL=https://ami.example.test
   INTERCEPT_AMI_TOKEN_SHA256=<64-character digest>
   ```

   `AMI_URL` must be an origin, with no path, credentials, query or fragment. Missing/invalid `AMI_URL` disables all module routes and preserves same-origin framing. The digest alone cannot authenticate; keep the bearer token secret. Rotate by generating a new pair, updating Intercept's digest and replacing AMI's saved token. Revocation also ends open event streams at their next heartbeat.
3. In **AMI → Modules**, add Intercept with its public HTTPS address. If it shares AMI's Docker network, use `http://intercept:5050` as the internal API address. Otherwise use an explicitly reachable private endpoint. Paste the bearer token. Only administrators may use the module by default; preserve that restriction because aircraft and vessel contacts are not per-user data.
4. Its Overview panel appears automatically. Open Intercept from AMI's app navigation and sign in to Intercept. The existing login, forced password change and standalone URL continue working. Framing is permitted only from self and the configured AMI origin; no token is exposed to the browser bridge.

## Read-only contract

- Public manifest: `/.well-known/ami-module.json`; sanitized liveness: `/api/module/health`.
- Bearer-protected stateless MCP: `/api/module/mcp` (`initialize`, `ping`, `tools/list`, `tools/call`). Browser sessions never authorize this endpoint, even if standalone auth is disabled.
- Tools: `get_status`, `list_receivers`, `get_contacts` (aircraft/vessels, maximum 50), `get_recent_events` (sequence cursor, maximum 50), and AMI-only `get_panel`.
- Reads never probe USB/network receivers or start/stop decoders. Receiver data comes from the application's existing discovery cache, and is stale after 60 seconds. An unprobed cache is unknown, not proof of missing hardware.
- Contacts include only allowlisted aviation/maritime fields, the original observation time, and stale flags. No pager messages, WiFi/Bluetooth identities, raw decoded payloads, receiver serials/addresses or observer GPS coordinates are exposed. No transmitted or capture-changing actions are available to the model.
- `get_status` samples the legacy process slots listed in `utils/ami.py`; standalone WiFi/Bluetooth managers and other specialist pipelines remain visible in Intercept itself. Idle is normal and is not reported as a fault. Health is adapter liveness, not a guarantee that all radio equipment is operational.

## Embedded speech

Inside AMI, Intercept's existing voice-alert queue sends speech to AMI's origin-checked bridge. AMI chooses the signed-in person's voice, effects, speed and fallback. Automatic alerts require both the chosen Intercept source switches and AMI's automatic read-aloud preference; manual previews use AMI too. Browser speech is used only in standalone Intercept. Embedded voice/rate/pitch controls are hidden in favour of AMI's settings; source switches and mute remain available.

## Health events

`GET /api/module/events` is bearer-protected SSE with `event: ami-event`, durable `id: intercept:<sequence>`, and `Last-Event-ID` replay. History is retained for 48 hours in `instance/ami-events.sqlite`; persist that directory. Unknown/invalid/future cursors are rejected. Reconnecting without a cursor replays the retained journal; AMI applies its own freshness and deduplication rules.

After the first authenticated AMI connection, one monitor samples the existing decoder process slots every 15 seconds. An exited process that remains attached for 60 seconds emits one critical `decoder-health` event; release/restart emits its matching recovery. Deliberately released idle decoders do not alert. State survives restarts, so a persistent fault is not re-announced on every reconnect. These events do not report intentional user actions or try to infer failures from silence. AMI handles delivery, subscriptions and quiet hours.

Keep Intercept's existing single WSGI worker: radio state is in process memory, and multiple workers would each see different decoders. This adapter uses no second web server and no node sidecar.

## Deployment and validation

The optional `ami-deploy/stacks/intercept/` configuration is deliberately separate from the existing AMI/VIGIL stacks. Choose the receiver host, devices, DNS and image revision before enabling it. No radio hardware or production stack is configured automatically. Image publication is gated on the fork's successful main-branch CI run.

```sh
python3 -m venv /tmp/intercept-test-env
/tmp/intercept-test-env/bin/pip install -r requirements-dev.txt
/tmp/intercept-test-env/bin/pytest tests/test_ami.py -q
/tmp/intercept-test-env/bin/pytest tests -q --timeout=120 --timeout-method=thread
/tmp/intercept-test-env/bin/ruff check .
```

The tests use temporary databases and mocked decoder state, never production receivers. Existing browser smoke tests exercise all dashboards and modes in dark/light themes and desktop/phone layouts. `tests/smoke/test_ami_embed.py` additionally checks a genuine cross-origin embedded login/navigation flow and bridge origin checks.
