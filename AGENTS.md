# Project guidance

Read [requirements](docs/requirements.md), [architecture](docs/architecture.md) and
[contributing](CONTRIBUTING.md) before changing behavior.

- This is a candidate HA local-authorization adapter, not account/cloud discovery.
- One standard config entry per device; multiple entries are supported. Preserve
  immutable productKey/deviceName identities across address/credential changes.
- First model: Wilo HiMulti-1 WiFi, exact public productKey `a15zaTr5sp1`.
  Reject unknown models before any active report request.
- Import only the user's own Android Cloud Intelligence device authorization.
  No embedded login, Google sign-in, token extraction or automatic renewal.
- Protect config entries and backups. Never log authorization, IDs, addresses,
  packets or exception bodies. Diagnostics use an explicit safe allowlist.
- Runtime must be self-contained under `custom_components/cloud_intelligence`.
  The dependency-free canonical core stays under `cloud_intelligence`;
  `tools/sync_core.py` checks the packaged copy byte-for-byte.
- Only sensors/binary sensors: all 12 states, no operating controls/services.
  TSL write flags/ranges are not permission or safety recommendations.
- The sole allowed property/set operation is the literal report request
  `params={"refresh":1}`. It requests telemetry, not an operating setting.
  One attempt per polling session, no retransmission or arbitrary setters.
- Poll at 120 seconds by default (minimum 60). Each session: one exact unicast
  identity check, auth, Observe registration, one report request, bounded receive.
  Return immediately on all 12 actual states; ACK/refresh echo is not success.
- All UDP receives must be nonblocking/cancellable; close sockets on every exit.
- Each client remembers its first successfully bound auth/Observe source port
  synchronously, including on failure/cancellation, and rebinds it on later reads.
  Identity probes stay independent but exact on every read. Reject same-client
  overlap immediately, release the guard on every exit, and retain the 10-second
  total budget. Bind conflicts fail clearly: no fallback, retries, reuse options,
  shared sockets, persistent listener or port in config/diagnostics/repr.
  New clients/restarts may choose new ports; local close is not remote teardown.
  Endpoint stability is a Beta live-comparison candidate, not a proven root-cause fix.
- Keep exact peer/token/URI/session/envelope checks, ctype 0 encrypted decoding,
  fixed-zero Observe support and session-scoped bounded MID/digest deduplication.
  Opt 1 has no packet MAC/replay protection: do not claim otherwise.
- Preserve power permission vs motor running and local reachability vs cloud
  status. Local receive times are never device source timestamps. Partial values
  stay unknown, never zero/off. Failed polls make entities unavailable.
- Start behavior changes with failing tests; run `make check` before committing.
  It includes real HA 2026.9.1 / Python 3.14 offline container tests and mutations.
  `make check-core` remains a pure Python 3.13 boundary.
- Use synthetic fixtures only, never real credentials/IDs/readings, private paths,
  proprietary client/SDK sources, vendor secrets or platform branding assets.
- Keep English/Chinese/Japanese docs and en/zh-Hans/zh-Hant/ja basic UI aligned.
- Candidate offline tests are not live-device, production or HACS-listing approval.
  No live networking, production access, push or release is part of default tests.
