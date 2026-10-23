> Pre-commit snapshot. Live coordination and subsequent commit/PR results are in the primary AMI handoff directory named below. Create new task notes there when available; do not update this snapshot as a lock.

# Intercept reskin and embedded AMI module

Task: intercept-module
Agent: codex
Status: ready-for-review
Updated: 2026-10-23 Europe/London (BST)
Shared directory: /home/morrolan/Development/ami/docs/handoffs
Predecessor: plan in the owner's conversation

## Next step and blockers

- Next: commit/push the tested feature branches and open draft PRs. The clean Python 3.11 unit suite passed, satisfying the owner's conditional commit/push authorization. No live deployment.
- Blockers: deployment host and receiver hardware are not yet specified. Build and test with fixtures; do not operate live radios or deploy a hardware profile by guessing.

## Scope and ownership

- Owner approved the reviewed plan with "Build it" after confirming Intercept should embed in AMI like VIGIL.
- Fork: Morrolan/intercept, checkout /home/morrolan/Development/intercept. Native Flask architecture retained, initially admin-only service token and existing standalone sign-in.
- Review branches prepared: Intercept `codex/intercept-ami`; ami-deploy `codex/intercept-stack`. Primary AMI remains on its existing branch; unrelated alert-history changes remain there, untouched.
- Claimed: Intercept integration/theme/tests/deployment docs; ami-deploy opt-in Intercept stack and Caddy configuration; this handoff note.
- AMI/VIGIL alert-history changes are a separate incomplete task. Their dirty files must not be committed, reset or deployed as part of Intercept.

## Verified progress and decisions

- Fork inspected at 43c655d. Existing base templates and token CSS can carry the redesign across dashboards.
- AMI supports service modules with ui.embed without core changes; service modules retain their own UI login.
- No capture-start/stop or radio configuration tools will be exposed to the model in this release.
- Implemented in Intercept: opt-in manifest/health, bearer-only stateless MCP, five read tools including Overview panel, sanitized cached receiver/contact reads, durable debounced decoder-health SSE with 48-hour retention, embedded navigation/login redirects and configured-origin framing. Browser UI retains Intercept's own sign-in.
- New local AMI visual layer is included by each document head; square glass surfaces, teal accents, mono headings, outlined controls and newly authored outline branding. Semantic decoder graphics are preserved.
- Added token generator, setup documentation, regression tests and CI-gated fork image publication. Optional deployment files are under ami-deploy/stacks/intercept; the live Caddyfile/stacks are untouched.
- Read Claude's active Pi-hole note: its Caddy change is already present; no overlap with the opt-in Intercept snippet. No live DNS/radio/stack changes made.
- Browser review fixed the satellite phone status row's wrapping and higher-specificity upstream corner radii. Converted remaining coloured UI emoji to the existing Intercept SVG vocabulary or explicit text. Preserved the radiosonde parachute and TSCM scanner graphics after reviewing the branding replacements.
- `?ami=1` survives sign-in, local links and existing programmatic navigation using per-tab frame state; a standalone top-level tab ignores that state. The bridge verifies both configured origin and parent window. Static URL cache keys append `-ami1`; displayed VERSION stays 2.33.79.
- Updated AGENTS.md and imported it from CLAUDE.md; corrected their stale Docker description. Runtime remains native Flask and one gunicorn/gevent worker.
- Embedded VoiceAlerts now delegates through AMI's existing `ami-speak`/`ami-speech` bridge, preserving its queue/source/mute choices and requiring trusted AMI autoplay for automatic speech. Manual previews use AMI; native synthesis remains standalone only. Embedded duplicate voice/rate/pitch controls are hidden. Browser tests cover spoofed settings, ordered acknowledgements, manual previews, no native synthesis in AMI, and native synthesis in a standalone tab.

## Validation

- `ruff check .`: passed.
- Latest focused `pytest tests/test_ami.py tests/smoke/test_ami_embed.py -q --tb=short --timeout=90`: 10 passed, including final corner rules and origin/frame checks.
- Full `pytest tests -q --tb=short --timeout=120 --timeout-method=thread`: reached lifecycle tests at 45%, then one missing-dump1090 error-message failure and an unexpected SystemExit. No claim of a full pass.
- Isolated untouched `git archive HEAD` baseline at /tmp/intercept-ami-baseline reproduces the same `TestToolMissing::test_start_is_an_actionable_error[adsb]` failure (1 failed, 5 passed). Machine has /usr/local/bin/dump1090; its missing-tool harness expects different wording.
- CI-style shards: a-l = 782 passed, 13 deselected; m-z = 1302 passed, 3 failed. `--ignore` does not exclude a file explicitly supplied by the shell glob, so the latter included the full lifecycle file. Together: 2084 passed, 3 failed.
- Baseline also reproduces both `test_real_rtl_433_decodes_synthetic_capture` failures (2 MHz and 10 MHz) with the machine's rtl_433 25.02. No decoder production code or tests were altered to hide these failures.
- Actual AMI `validateManifest`, `checkTool`, `createMcpClient` and `checkPanel` exercised against a temporary live Intercept server: passed (`/tmp/validate_intercept_contract.py`). Temporary DB/token only; never live credentials.
- Initial full Chromium smoke run: 53 passed, 2 failed (satellite dashboard overflow at dark/light phone widths). After fixing it, focused module/embed/satellite checks: 18 passed, 44 deselected. A later full mode-switch regression rerun exceeded 300 seconds; direct per-mode trace subsequently finished every mode with no page errors (`/tmp/trace_intercept_modes.py`). Existing modes make server-side external requests and are slow on this host. Final affected-unit and all-dashboard checks are running after the cache revision.
- Optional stack `docker-compose ... config --quiet` with placeholder image/state/private-env settings: passed. No containers started.
- Final affected unit checks (AMI, static versioning, auth gate, Carto/Stadia settings): 27 passed. Final full dashboard/embed run (dark/light, desktop/phone): 49 passed, 4 mode-switch tests deselected.
- Initial clean-container run: 2083 passed, 2 skipped, 2 failed (a weather test made a live request despite claiming to test missing location; an orphan child remained a zombie without container init). Made only the weather test deterministic: mock absent location, assert the existing 400 response, assert no HTTP call. `tests/test_system.py`: 12 passed. Child-process tests with `--init`: 4 passed. Full clean-container rerun with both fixes is in progress; decoder tests are unchanged.
- Final clean-container command: `docker run --rm --init --network none --security-opt no-new-privileges localhost/intercept-ami-test` — **2085 passed, 2 skipped, 13 deselected** in 254.94s (Python 3.11.17). Missing radio-binary tests use their existing skips; no decoder tests were changed. The test image uses ordinary development dependencies plus Node, no real receiver tools/devices.
- Final voice-only additions: affected module/static/system/embedded tests **24 passed**; expanded standalone-vs-AMI voice browser check **1 passed**. Python runtime code did not change after the full clean unit run. Final lint/JS syntax/whitespace checks passed.
- `git diff --check`, Python lint and syntax checks of modified JS files: passed. The Docker command is Podman; it works with escalation. An isolated test image is building from /tmp/intercept-ami-container-test (Python 3.11 plus development deps and Node, no SDR tools). It is not the production radio image. Production image publication is prepared, not run.

## Ideas and review requests

- None.

## Handoff

- Before-commit state: implementation tested and ready; commits/PR links will be recorded below after publication. A snapshot of this note is included in Intercept for other checkouts; coordination continues in this primary AMI directory.
- Use image builds and Portainer for a later authorized rollout, not legacy deploy scripts. Receiver host, DNS and hardware remain to be selected. Unrelated alert-history work is still incomplete and uncommitted in AMI/VIGIL.
