# Contributing

Read [project guidance](AGENTS.md), [requirements](docs/requirements.md) and
[architecture](docs/architecture.md). This is a candidate local-device adapter,
not account login or cloud discovery. No production release is claimed.

Use Python 3.13.12 with project-local tools from
[requirements-dev.txt](requirements-dev.txt). HA lifecycle tests run separately
inside actual HA 2026.9.1 / Python 3.14.6. `make check` includes both environments;
see [verification](docs/verification.md). Dependency installation and Docker image
retrieval are separate prerequisites; all checks themselves run offline.

Start behavior changes with a failing regression. Preserve the pure-core contracts
and package byte parity (`tools/sync_core.py`; use `--update` only after reviewing
canonical core changes). Keep commits focused and conventional. Maintain English,
Chinese and Japanese README status plus affected requirements/architecture/UI.

Only synthetic credentials, TEST-NET/private example addresses, device IDs and
readings belong in tests. Never commit live payloads, account data, signing inputs,
vendor secrets, private paths, proprietary SDK/client sources or branding assets.
Do not claim review/approval unless it occurred. Contributions use
[Apache-2.0](LICENSE); do not copy incompatible licensed implementations.

The runtime boundary permits one exact fixed `refresh=1` telemetry report request
per session. The sole experimental operating exception is strict-bool
`LocalClient.set_power`, enabled only by explicit `enable_power_control=true`.
Default false preserves all 12 read entities; the added switch uses a control-role
ID. Full valid pre-read, one fixed `switch=0/1` send, fresh post-send authenticated
Observe window and unchanged other writable settings are mandatory. No automatic
retry, optimistic state, pressure/mode/speed setting, arbitrary setter, extra
model, login or cloud request. Unknown outcomes must stay structured, including
cancellation. Unknown profiles fail before network/write. TSL is not safety advice.

Use real HA classes for flow/storage/registry/lifecycle tests. Replace network
transport only; never replace HA itself with fake dataclasses. Preserve encrypted
ctype 0, Observe 0, endpoint/session/envelope checks, bounded cancellation and
report-once tests. Never run live validation or mount production HA by default.
Any separately authorized live acceptance must target this exact adapter version,
not infer its success from another client or protocol implementation.

Authorization has a finite, externally controlled validity. No automatic renewal
is implemented. Recovery is same-device re-import through standard HA auth flow.
Protect config-entry data and backups; diagnostics must remain allowlisted.
[Security reporting](SECURITY.md) must not include credentials or raw traffic.

HACS packaging, a passing test suite and a built candidate ZIP are not a release,
listing or certification. Publishing requires a separately authorized review and
acceptance decision.
