# Requirements and acceptance boundaries

## Delivered candidate scope

An independent community HA custom integration with HACS repository layout. The
first slice imports **one device's local authorization**, not an account session
or cloud discovery. Complete Google sign-in, account discovery, automatic renewal,
other device adapters and operating controls are separate future work.

The installable directory is `custom_components/cloud_intelligence`. It contains
all its own protocol, model/identity core, HA config flow, coordinator, entities,
diagnostics and basic en/zh-Hans/zh-Hant/ja UI. No private paths, helper programs,
Android bridge, Keychain access, client SDK or continuously running app is needed
by runtime code. The pure-Python core remains independently testable; its packaged
copy must pass a byte-for-byte parity check.

Offline acceptance uses actual HA 2026.9.1 / Python 3.14.6. These tests are synthetic,
not live-device or production acceptance of this adapter. HACS metadata and a
manual-install ZIP builder are delivered; no release or default-store listing is
implied. See [installation and credential prerequisites](../README.md).

## Local authorization lifecycle

1. User supplies their own device's exact `productKey`, `deviceName`, `accessKey`,
   `accessToken`, private LAN IPv4 `host`, and optional friendly `name`. There is
   no `iotId` requirement. Only productKey `a15zaTr5sp1` selects Wilo HiMulti-1 WiFi;
   do not infer support from names, TSL rw flags or arbitrary product metadata.
2. Before create-entry: exact unicast identity check at configured IPv4/UDP 5683,
   ALCS server proof validation, encrypted Observe registration, one fixed report
   request, and all 12 actual valid states. The untrusted discovery reply cannot
   change the configured destination. Empty ACKs, registration, accepted refresh,
   or refresh echoes are never sufficient. No multicast or cloud fallback.
3. One standard config entry per device; multiple devices are supported. Store
   authorization only in entry data. HA restores it from standard storage after
   restart. The integration does not encrypt config entries or backups.
4. Reauthentication and reconfiguration accept replacement authorization only for
   the same immutable productKey/deviceName. Changing address, authorization or
   label preserves registry IDs. A changed address can be reconfigured explicitly.
5. Auth rejection maps to HA reauthentication; connection/initial-report failure
   maps to config-entry retry. Failed later polls mark entities unavailable.
   Saving credentials never promises unlimited validity. No renewal is claimed.

## Telemetry and operation boundary

Default polling is 120 seconds; options permit 60–3600 seconds. Each poll starts a
new session with a total budget of 10 seconds, covering identity check, auth,
subscription, report request and receive. Socket receives are nonblocking and
cancellable, with sockets closed in `finally`. Unload stops the coordinator and
cancels any pending read. There are no persistent UDP listeners or worker threads.

Within one `LocalClient`, the first successful authentication-socket bind lets the
OS choose a UDP source port; every later auth/Observe session rebinds that port,
including after rejection, error, timeout or cancellation. The port is remembered
synchronously at bind, not taken from a successful session result. Identity probes
remain independent ephemeral sockets and must validate the exact device before
every authentication. Overlapping reads on the same client fail immediately,
without opening sockets or queuing; each accepted read retains the same 10-second
total identity/auth/subscription/report/receive budget. Cancellation always releases
the read guard. Separate clients own separate in-memory endpoint state, not shared
sockets; no reuse socket options, configured/global fixed port or persistence are
introduced. Ports are not reserved while sockets are closed: a conflicting bind
fails clearly, with no alternate-port fallback or extra retries. A new client or
process may choose a new port. The port is absent from config, diagnostics and repr.

This Beta endpoint-stability candidate reduces endpoint churn for a separately
approved single-variable live comparison. Local close is not remote session or
observer teardown; same-endpoint reauthentication may permit reuse/cleanup but
neither guarantees it nor recovers an unresponsive device. No RFC Observe=1/RST
cleanup, heartbeat or firmware/client root-cause diagnosis is assumed. Independent
review and live long-running validation remain required; no root-cause fix or
release is claimed.

The **only** property/set operation is a fixed report request:

- CoAP GET `/sys/{productKey}/{deviceName}/thing/service/property/set`
- method `thing.service.property.set`, `params={"refresh":1}`
- only after the exact supported profile is authenticated and subscribed
- one send attempt, no retry, no arbitrary property/value/path input

It requests telemetry, not operating settings. This is not a passive or GET-only
protocol. All HA entities are read-only. No switch, number, select, button or custom
control service is registered. Device writes other than this bounded report request
are forbidden. Declared ranges are metadata, not safe-setting recommendations.

Observe GET uses `/sys/{productKey}/{deviceName}/thing/event/property/post`.
Notifications have exact method/version/envelope/property allowlists and session
option 71. Peer address/port and token must match; any returned URI must match.
Encrypted responses with content format 42, 50 or canonical empty content-format-0
are decrypted; format 0 is not accepted in the unencrypted auth branch. Auth proof
requires the server's 15-character ASCII nonce plus NUL; session derivation uses
printable nonces without NUL and raw HMAC-SHA1 output. AES is implemented with
`cryptography`, retaining the final padded block's IV restart format.

Only explicit opt 1 is supported. Sequence-window/checksum/unknown options are
rejected, not silently downgraded. Opt 1 has **no packet MAC/replay protection**.
A session-local bounded MID/plaintext-digest window filters retransmissions, keeps
new MIDs with equal payloads, rejects conflicting same-MID content and fails closed
on unexpired capacity pressure. Observe 0 does not suppress subsequent reports.
This is duplicate filtering, not a security anti-replay guarantee.

A poll returns immediately after all 12 actual property keys are received. Model
validation then determines which values are valid. Initial setup requires all 12
valid states; later partial reports expose valid peers and leave missing/invalid
values unknown, without merging old data or filling zero/off. No report is a
connection failure. Power permission, motor running and fault remain independent.

Local reports carry no device source timestamps. Per-property `locally_received_at`
is the actual local UTC receive time. It is not inserted into core `reported_at_ms`
and is not called a device timestamp. Local reachability never means cloud online.
Failed polling makes the entities unavailable rather than freshening old data.

## Pure core snapshot contract

The independent core still accepts a decoded `apiVer 1.0.4` property-shadow shape
`{"code":"200","data":{"property":{"time":1000,"value":1}}}`. Its per-property
reported timestamps are preserved when actually supplied, not replaced by fetch
or receive time. Local ALCS reports are adapted as value-only entries, with source
timestamps absent and local receive times stored separately by the HA adapter.

Error/malformed envelopes are rejected without echoing untrusted server text.
Bool values accept only bool or integer 0/1; integer types exclude bool; finite
numeric types are strict, without string conversion or step rounding. Text is
bounded, unknown integer enum codes retained by the core, and declared min/max
checked. Unknown scalar properties remain diagnostic read-only metadata, disabled
by default. Online status accepts integer 1 only; other statuses stay unknown.
Freshness is per-property with caller-supplied clock and threshold; missing/invalid
values or source times stay unknown, future times are classified separately.
The local adapter does not promote unknown models into active transport.

## Model and entity mapping

The internal semantic profile is `wilo_himulti_1`. The local adapter maps the exact
supported public product key to this profile. All 12 states are instantiated in HA,
including diagnostic fault-code and software-version sensors. Six dormant control
metadata descriptions in the pure core do not enable any HA controls.

| Property | Type / TSL access | Read surface | Future control (disabled) | Metadata / meaning |
| --- | --- | --- | --- | --- |
| `switch` | bool / rw | binary_sensor | switch | Powered/enabled, **not motor running** |
| `temperature` | int / r | sensor | — | 0–100, step 1, °C |
| `presSet` | float / rw | sensor | number | 1.0–8.0, step 0.1, bar; declaration only |
| `refresh` | enum / rw | **none** | button | Single action: 1 = refresh now; not a state/select |
| `mode` | enum / rw | sensor | select | 0 = automatic; 1 = manual |
| `error` | enum / r | diagnostic sensor | — | Raw code plus known label; unknown codes retained |
| `errorState` | bool / r | binary_sensor | — | Fault indicator |
| `run` | bool / r | binary_sensor | — | Motor running, independent of power |
| `propor` | int / rw | sensor | number | 10–90, step 1; TSL declares **no unit** |
| `version` | text / r | diagnostic sensor | — | Software version, maximum 64 characters |
| `pressure` | float / r | sensor | — | 0–8.0, step 0.1, bar |
| `tarSpeed` | int / rw | sensor | number | 1200–4800, step 60, r/min |
| `nowSpeed` | int / r | sensor | — | 0–4800, step 60, r/min |

Known `error` labels: 0 no fault; 1 undervoltage; 2 overvoltage; 3 pressure sensor
fault; 4 IPM module overtemperature; 5 water shortage; 8 motor phase loss / excess
current; 9 IPM overcurrent protection; 13 communication fault. No other code meaning
is invented. `entity_descriptions` provides 12 read-role surfaces, including
version diagnostics, and excludes the `refresh` command. The separate
`control_descriptions` provides six dormant control-role descriptors, not enabled
commands. The HA adapter also uses version in DeviceInfo.
Unknown models and additional unknown properties get disabled-by-default diagnostic
sensor/binary-sensor descriptions only. Declared TSL access and effective write
permission are separate fields; effective writes are always false in this version.

Core speed metadata retains the TSL `r/min`. The HA adapter normalizes it
to `rpm` with no multiplier; it must not apply a linear-speed device class. Read-only
setpoints must not be presented as live measurements. The HA adapter uses pressure/temperature device classes for actual measurements;
setpoints have no measurement state class.

## Stable identity

The core's versioned SHA-256 encoding is length-unambiguous and role-separated.
The local adapter uses namespace `alcs-local:{productKey}` and immutable deviceName,
then the property identifier and read role for each entity. Host, name, credentials,
state and ordering are excluded. It is a device-scoped identity, not a claimed
account namespace. Hashing is not anonymization of predictable identifiers.
A future cloud/shared-device adapter must explicitly review migration semantics.

## Acceptance and remaining gates

- [Core contracts](../tests/test_snapshot.py), [models](../tests/test_models.py),
  [identity](../tests/test_identity.py): the original pure-core behavior remains.
- [Protocol contracts](../tests/protocol/test_contracts.py): strict boundaries,
  encrypted content-format 0, Observe 0, session-local dedup and fixed report once.
- [Client/oracle tests](../tests/protocol/test_client.py): exact local identity,
  authorization, complete/partial handling, timeout/cancellation and independent
  AES ECB/XOR oracle.
- [Endpoint lifecycle](../tests/protocol/test_endpoint.py): real loopback UDP source
  ports across rounds/errors/cancellation, exclusive bind conflicts, immediate
  same-client overlap rejection, independent clients and per-round socket release.
  These tests establish lifecycle behavior, not a physical-device failure cause.
- [Real HA lifecycle](../tests/ha/test_lifecycle.py): add, duplicate, multi-device,
  same/mismatched re-import, persisted restart, registries, all 12 states, options,
  unload, auth/retry/unavailable, diagnostics and actual language fallback loading.
- [Packaging](../tests/ha/test_package.py): deterministic ZIP and standalone imports
  using only the installed component and real HA, without the repository core.
- [Verification](verification.md): pinned tools, branch coverage ≥90%, exact core
  parity and two core plus two HA/protocol assertion-killing mutations.

Default checks are offline and never contact production. Further release gates
include independent review, real-device acceptance of this actual adapter,
credential expiry/revocation/long-running behavior, firmware variants and a
separately approved release/HACS distribution check. No official affiliation,
full language coverage, general model support, unlimited authorization validity
or production approval is claimed.
