# Architecture

## Modules and ownership

| Path | Responsibility |
| --- | --- |
| `cloud_intelligence/` | Dependency-free immutable model/snapshot/identity core |
| `custom_components/cloud_intelligence/_core/` | Exact packaged copy; no root-package runtime dependency |
| `alcs.py` in the component | CoAP framing, HMAC proof and cryptography AES block format |
| `telemetry.py` | Cancellable nonblocking UDP session, exact validation, bounded dedup, one fixed report request |
| `client.py` | Private-IPv4 input gate, exact unicast device identity, total time budget, model validation |
| `config_flow.py` | Single-device import, same-device reauth/reconfigure and polling options |
| `coordinator.py` | Low-frequency local polling, HA auth/retry/availability, pending-read cancellation |
| `entity.py`, `sensor.py`, `binary_sensor.py` | Stable registry identity and 12 native read-only states |
| `power.py`, `switch.py` | Safe power outcomes and opt-in non-optimistic standard enable switch |
| `diagnostics.py` | Explicit safe metadata allowlist; no credentials, identities, addresses or state values |
| `translations/`, `strings.json` | Four basic UI locales with English fallback |
| `tests/ha/`, `tests/protocol/` | Actual HA lifecycle, isolated install, independent synthetic protocol server/oracle |
| `tools/` | Core parity, pinned tools, container suite, link/mutation checks and ZIP builder |

## One-device import

The flow accepts the user's existing local device authorization and validates it
before creating a standard config entry. `LocalClient` first contacts the supplied
private IPv4 address at UDP 5683 for one exact identity check; it does not accept
redirects or unauthenticated advertised ports. It then authenticates the supported
Wilo identity, registers encrypted Observe and requests one fixed report. Only
verified authorization plus all 12 valid actual states permits initial setup.

Identity is `device_unique_id("alcs-local:" + productKey, deviceName)`; entity IDs
add exact property ID and the `read` role. Friendly labels, current addresses and
credentials are mutable and excluded. Re-import refuses a different identity
before networking or changing the existing entry. The config entry owns private
credential storage and HA restores it on restart. There is no separate token file,
account discovery, renewal implementation or external credential helper.

## Polling and lifecycle

A `LocalCoordinator` owns each entry's client and polls every 120 seconds by default
(minimum 60). `LocalClient.read` bounds identity/auth/subscription/report/receive to
10 seconds total. Auth/registration stages are also individually bounded. Sockets
are nonblocking and async receive waits are cancellable. Every socket closes in
`finally`; no worker thread or long-lived Observe listener exists. A complete
report returns immediately instead of waiting out the total receive budget.

Each client privately owns a `telemetry._Endpoint` (port memory only, no socket).
Its first successful auth-socket bind uses port 0 and synchronously stores the
OS-selected port before any send or await. Subsequent sessions rebind it even after
failure/cancellation; each socket still closes in `finally`. Identity probes keep
independent ephemeral sockets and exact validation before every auth. No endpoint
state enters entry storage, diagnostics or repr, and there is no shared socket or
reuse option. Closed sockets do not reserve ports: conflicts fail explicitly with
no port-changing fallback or increased retries. New clients/processes can select
new ports; stability is not promised across restart or source-IP changes.

`read` rejects same-client overlap immediately, before validation/network work;
a `finally` releases its guard on every exit. There is no lock queue or added wait
outside the existing 10-second accepted-read budget. Other clients remain independent.
Coordinator unload still cancels and awaits the active read, releasing its socket.
This minimal Beta candidate changes endpoint allocation, not polling/Observe
architecture. Local close does not tear down remote sessions/observers, and repeated
auth on the same endpoint is not a proven remote-cleanup mechanism. No heartbeat,
Observe cancellation or hardware root-cause fix is claimed. Independent review
and a restricted live long-stability comparison remain gates.

Polls allow only the literal `refresh=1` report request, once after subscription.
The experimental `LocalClient.set_power(bool)` extension is strict opt-in (default
false), and shares that client's immediate-fail read/write gate, stable endpoint
and 10-second total budget. It validates a fresh full pre-read in the same
session, records five writable settings, no-ops at target, otherwise sends exactly
one fixed switch=0/1. It closes that socket and establishes a new authenticated
Observe token/key window AFTER send, continuously under the gate/deadline. All
12 valid states must arrive anew: target switch and unchanged other four settings
are mandatory; actual measurements/speed may change. Neither same-session queued
old target reports nor ACK/set200 prove success. No pre-write snapshot is merged.
Opt 1 still cannot prove device source time or provide MAC/anti-replay protection.

`power.py` defines safe results and sent/uncertain unknown/cancellation outcomes.
The send-attempt flag is set synchronously before sendto; no retry follows any
unknown outcome. `PowerCancelled` remains asyncio cancellation; the coordinator
wraps unknown service errors with the same flags, marks states unavailable and
tracks/cancels/awaits controls on unload. At the HA coordinator boundary, a control
claims its slot synchronously and may wait for the existing read (never another
control), shielding it from cancellation of the service waiter. New polls and
controls cannot enter that gap. One absolute 10-second deadline includes waiting,
fresh pre-read, send and verification. Its internal `time.monotonic()` boundary
can only tighten the client's own budget, which starts before synchronous input
validation. Both report sessions retain that absolute boundary; the final send
check runs after encoding and before marking the send attempt. Asyncio receives
remaining durations, never a timestamp assumed to share its clock epoch. The
client timeout setting is not mutated. Closed/options are rechecked
before client I/O. Poll errors do not supply control data or bypass its own fresh
complete pre-read. Exhaustion before send refuses without a write; after attempted
send, timeout/cancel remains structured unknown and unavailable, never retried.
`async_close` cancels both the shielded read and the control waiter before awaiting
shutdown, without a cyclic wait. No long-lived listener, general queue or new client.
`switch.py` adds only an opt-in standard switch with a control-role ID on the same
device; all 12 read IDs and config identity remain unchanged. Options use existing
reload listeners and permission is checked on every call, including stale entities.
No arbitrary setter, pressure/mode/speed write or custom write service exists.
No live switch-write, root-cause-fix or production approval is claimed.

Initial failures use HA's standard ConfigEntryNotReady or ConfigEntryAuthFailed
paths. Later connection failures make coordinator entities unavailable; auth
failures start reauthentication. Unload removes platform listeners, shuts down
scheduling and cancels/awaits a pending read. Failed platform unload retains its
coordinator. Tests exercise both outcomes and a persisted restart with real HA
storage and registries, not mocked HA classes.

## Data and time

Model values are validated by the pure core. Each report merges only within its
current bounded session; polls never carry missing values forward from a previous
poll. Missing/invalid properties are unknown. The first setup requires a complete
report; later valid partial reports may update only their valid properties.

Source timestamps are absent in local reports. Core `reported_at_ms` remains
`None`; local UTC receive times live in a separate mapping and appear as
`locally_received_at`. This is not a device-origin clock or cloud online status.
Power permission (`switch`), motor running (`run`) and fault (`errorState`) are
independent binary sensors. Setpoints are read-only observations with no
measurement state class. `r/min` is normalized to `rpm` without scaling.

## Protocol limits

Pin exact peer, token, any returned URI, option-71 session and response-envelope
identity. Encrypted ctype 0 must still decrypt; ctype 0 is not accepted for auth.
Observe values fixed at 0 do not order reports. Bounded session-local MID/digest
dedup keeps distinct MIDs, rejects conflicting content, and never evicts unexpired
entries on capacity pressure. It is not security replay protection.

Explicit opt 1 only: no packet MAC/replay protection, sequence-window/checksum
support or automatic downgrade. Server proof uses a 15-character ASCII nonce plus
NUL; raw session key derivation excludes NUL. AES primitives come from
`cryptography`, with the final padded block restarting the IV independently of
earlier CBC blocks. Tests use an independent ECB/XOR oracle, not just self-roundtrip.
See [security](../SECURITY.md) and [requirements](requirements.md).

## Packaging and verification boundary

The canonical core stays HA-independent. `tools/sync_core.py --update` copies it
into the component; default checks require exact file-set and byte parity. HACS
installs only this self-contained directory. The repository root `brand/` holds the
HACS-required copy of the original icon, while `custom_components/cloud_intelligence/brand/`
holds the Home Assistant local copy. The ZIP builder includes Python/JSON runtime files,
permitted brand PNGs and the Apache license, with deterministic metadata. An isolated
Python process imports the extracted component with the installed HA runtime and without
the repository root core on its import path.

`make check-core` uses pinned Python 3.13 development tools. `make check-ha` uses
actual HA 2026.9.1 / Python 3.14.6 in a disposable, resource-capped, network-disabled
container with this checkout as its only bind mount. Synthetic socket/transport
stubs block device networking; endpoint lifecycle tests additionally bind/send real
UDP only on loopback, using synthetic protocol replies. Offline correctness is not live acceptance of the
adapter, a HACS listing, official certification or production validation.
