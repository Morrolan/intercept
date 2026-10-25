# AMI entry passes and away-only browser access

Task: ami-only-away
Agent: codex
Status: ready-for-review
Updated: 2026-10-25 Europe/London (GMT)
Shared directory: /home/morrolan/Development/ami/docs/handoffs
Predecessor: owner's explicit implementation request; 2026-10-24-open-items-claude.md

## Next step and blockers

- Next: Claude reviews this uncommitted work, implements the matching AMI contract and validates it with Caddy before committing/deploying under the owner's authorization.
- No implementation blockers. The shared coordination directory is outside this session's writable roots; this handoff is stored in the Intercept worktree for review/copying.

## Scope and ownership

- Worktree: /home/morrolan/Development/intercept-ami-only, branch feat/ami-only-away, base 3365534. Initially clean.
- Owner explicitly forbids commits, pushes, deployment and network access. None performed.
- Changed app.py, routes/ami.py, utils/ami_access.py, utils/database.py, templates/ami_access.html, tests/test_ami_access.py, .env.example, docs/AMI.md and AGENTS.md.
- Read shared README and all three open task notes. No sibling checkout changes; unrelated alert-history work left alone.

## Verified progress and decisions

- Manifest advertises ui.session and ui.enter. Existing service-bearer authorization protects issuance. Strict MFA boolean, supported AMI role, exact allowlist mapping and enabled local account required; Intercept's role remains authoritative.
- Global 30 authenticated issuance attempts/minute, including eligibility failures. Hash-only random tickets, 60-second monotonic TTL, atomic single-use consumption. Account enabled state rechecked on entry.
- Existing users schema had no enabled state: added enabled=1 with migration for existing accounts; disabled accounts also cannot password-login.
- Shared session initialization clears signed-cookie state before setting normal fields and optional via_ami. No server-side session id exists to regenerate. Forced password change retained.
- Away enforcement runs before CSRF/legacy bypasses, only with both env opt-in and positive proxy trust. Module blueprint keeps its independent authorization; headerless health and home access retain normal behaviour.
- Entry responses have no-store/no-referrer. Global security headers now preserve an explicit stricter referrer policy. Docs require Caddy header overwrites, private container ingress, and redaction of ticket query strings in proxy access logs.
- No static assets changed, so no asset cache revision was needed. All changes remain local and uncommitted.

## Validation

- `ruff check .`: passed, using cached ruff 0.16.8 binary at /home/morrolan/.cache/uv/archive-v0/r5x3Lc5UtMnjq0SD0mY8o/ruff-0.16.8.data/scripts/ruff.
- `git diff --check`: passed.
- `PYTHONPATH=/tmp/intercept-away-test/deps:. python3 /tmp/intercept-away-test/run_pytest.py tests/test_ami_access.py tests/test_ami.py tests/test_auth_gate.py tests/test_password_change.py tests/test_proxy.py tests/test_database.py -q --timeout=120`: **105 passed**, 22.81 seconds.
- Temporary runner disables Scapy interface/socket configuration and IPv4/IPv6 route autoload before importing pytest. Sandbox blocks netlink enumeration. Production code unchanged by workaround.
- Missing Flask-Limiter, Flask-WTF and pytest-timeout dependencies loaded from already-cached wheels extracted under /tmp; no downloads. Actual CSRF-enabled away POST and actual limiter dependency exercised.
- First run caught global referrer-policy overwrite (98 passed, 1 failed); fixed and reran entire relevant set plus six added cases.
- No live Caddy, AMI or browser integration checks in this offline task. AMI's half is Claude's follow-up.

## Ideas and review requests

- Review exact shared session/enter contract against AMI's implementation and ensure Caddy never logs ticket values.

## Handoff

- Read docs/AMI.md and tests/test_ami_access.py first. The documented session endpoint supports admin/resident/viewer assertions but always logs the person into the mapped local account's existing role.
- No additional user decision needed for the implemented scope. Do not mistake this note for commit or deployment authorization.
