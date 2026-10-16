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
- Preserve all 12 read-role sensor/binary-sensor entities and identities. The only
  operating extension is an experimental, non-optimistic enable-permission switch,
  gated by strict `enable_power_control=true` (default false), exact Wilo model.
  No pressure/mode/speed setter, arbitrary property API or custom control service.
- Allow fixed `refresh=1` once per report session and, only after a fresh complete
  valid pre-read in that authenticated Observe session, one fixed `switch=0/1`.
  Strict bool `LocalClient.set_power`; already satisfied is a no-op. Capture all
  five known writable settings before send; never retry after the send boundary.
- Confirm with a complete report in a new authenticated Observe token/key window
  established AFTER send, continuously bounded by the same exclusive 10-second
  operation/endpoint. Never reuse pre-write values or old-session notifications.
  Target switch must match and presSet/mode/propor/tarSpeed must be unchanged.
  Timeout/cancel/loss after attempted send is structured outcome unknown, not off
  or success; HA becomes unavailable. Opt 1 still has no anti-replay guarantee.
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
  Power control is an offline candidate, not yet physically write-tested; all
  physical off/on, loss/recovery and unchanged-setting gates remain outstanding.
  `make check-core` remains a pure Python 3.13 boundary.
- Use synthetic fixtures only, never real credentials/IDs/readings, private paths,
  proprietary client/SDK sources, vendor secrets or platform branding assets.
- Keep English/Chinese/Japanese docs and en/zh-Hans/zh-Hant/ja basic UI aligned.
- Candidate offline tests are not live-device, production or HACS-listing approval.
  No live networking, production access, push or release is part of default tests.
