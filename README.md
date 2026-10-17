# Cloud Intelligence for Home Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

**Beta local integration.** An independent,
unofficial community integration for Cloud Intelligence (云智能), initially for
**Wilo HiMulti-1 WiFi**. Import your own single-device LAN authorization, then HA
polls that device directly. This is not account login or cloud device discovery.
No vendor affiliation or certification is implied.

## Features

- A native Wilo device and 12 read-only sensor/binary-sensor states: water pressure,
  water temperature, target pressure, mode, fault code, fault, power permission,
  motor running, starting pressure ratio, software version, target/actual speed.
- One standard HA config entry per device, multiple devices, stable registry IDs,
  persisted authorization, restart recovery, re-import and address reconfiguration.
- Direct local UDP polling, default 120 seconds (minimum 60), with a 10-second total
  budget. A complete actual report returns immediately; no long-running listener,
  phone connection, cloud fallback, private helper or external service is used.
- Tested with real HA **2026.9.1 / Python 3.14.6**: offline lifecycle tests use
  synthetic transport; separate live-device checks cover configuration, 12 native
  states, automatic polling and a full HA process restart. The saved entry and
  all device/entity IDs survived the restart, with fresh readings and no re-import.
- A scheduled read failed once during the short live observation; the following
  poll recovered automatically. Extended unattended operation, visual browser QA
  and other models remain outside the verified scope.

Polling sends one fixed `refresh=1` report request per session. The default remains
12 read-only entities. The only opt-in operating extension is experimental enable
permission (`switch`), not motor running (`run`); pressure, mode and speed writes,
arbitrary setters, refresh buttons and automatic command retries remain forbidden.

## Experimental enable control (not live-device validated)

In the entry's options, explicitly enable `enable_power_control` (default false).
Options reload the existing entry; the new HA standard switch has a separate
control-role unique ID and preserves all read/device/config identities. Use HA
`switch.turn_off` to remove enable permission, and `switch.turn_on` to restore it,
targeting the added switch entity. This is an interface for a separately designed
refill interlock, not an automatic refill controller or a safety-rated stop.

Each call accepts only a bool. A fresh full valid pre-read and a single fixed
`{"switch":0}` or `{"switch":1}` send share an authenticated Observe session.
Already at target is a no-op. Verification establishes a new authenticated
Observe token/key window AFTER send on the same endpoint, under one exclusive
10-second budget, obtains all 12 states, checks the target and unchanged
`presSet/mode/propor/tarSpeed`. Old-session packets and set/ACK200 cannot confirm.
Measurement/actual-speed changes are allowed. No device timestamp is assumed.

At the HA boundary, an enable command may wait for an already-running poll, but
never another control. It claims the control slot before waiting so no new poll can
cut in. Waiting plus the one fresh-pre-read/write/verification operation share a
10-second total service budget (within a 12-second caller I/O window). A failed
poll is not reused as control data. Cancellation/unload releases the claim; there
is no general queue, extra client or automatic retry. The core client still rejects
overlapping operations immediately.

A send attempt followed by timeout, cancellation, lost response or failed checks
is outcome unknown, never optimistic success and never automatically retried.
The HA entities become unavailable until a successful read. A recovery guard must
read and assess state before deciding anything; do not retry or resume blindly.
Disabled options refuse direct/stale entity calls; HA skips an unloaded switch
with its normal unavailable-target warning and performs no write.
ALCS opt 1 still has no packet MAC/replay protection: the new window rejects old
session packets, not all malicious replay or device-side cached state.

This candidate has only offline synthetic tests, no physical switch-write test,
no production approval and no root-cause-fix claim. Independent review and separately
authorized physical off/on, unchanged-setting, motor/enable, loss/cancellation,
refill recovery and long-running/firmware acceptance remain release gates.

## Endpoint-stability candidate (not yet live-validated)

One client now remembers its first OS-selected auth/Observe UDP source port and
rebinds it after success, failure, timeout or cancellation. Every read still checks
the exact device identity using an independent ephemeral probe, authenticates,
subscribes, requests one fixed report and closes its sockets. Same-client concurrent
reads fail immediately; accepted reads retain the 10-second total budget. No port
configuration, shared socket, reuse option, persistent listener or heartbeat is
added. A conflicting bind fails rather than switching ports; the port is not
reserved between reads, persisted, or exposed in diagnostics/repr. A new client or
process may select a different port.

This Beta change only reduces endpoint churn for a single-variable live comparison.
The earlier live observations above do not validate this candidate. Local close
is not remote session/observer teardown, and same-endpoint reauthentication is not
a guaranteed cleanup or recovery. No Observe=1/RST cleanup or hardware root-cause
fix is claimed. Independent review and restricted long-running device acceptance
remain required before release.

## Prepare your authorization

You must already have authorization for **your own device**, obtained using the
Android Cloud Intelligence app. This integration does not implement Android login,
Google login, credential extraction or an app export mechanism. Availability of
those fields depends on your authorized acquisition method; do not assume the app
has an export menu. Do not use another person's device/account authorization.

Add the following exact fields in HA:

| Field | Meaning |
| --- | --- |
| Name | Optional friendly label; defaults to Wilo HiMulti-1 WiFi |
| Host | Device's private LAN IPv4 address, reachable from HA; no DNS/public IP |
| `productKey` | Exact supported product key `a15zaTr5sp1` |
| `deviceName` | Device's immutable ALCS name, not its friendly label |
| `accessKey` | Your device's local access key (sensitive) |
| `accessToken` | Your device's local access token (sensitive) |

`iotId` and cloud account passwords are not used. HA must be able to send UDP to
the selected device's port 5683 and receive its replies. Only this exact peer is
contacted; there is no multicast scan. Other products and protection modes are
not supported. Keep HA and the device on a trusted LAN: supported ALCS opt 1 does
not provide packet MACs or replay protection. See [security](SECURITY.md).

**Authorization is stored in HA's standard config-entry storage. This integration
does not encrypt it.** Protect the configuration directory, backups and access to
HA. Masked UI inputs do not make backups safe to share. Never post authorization,
device identifiers, addresses or raw payloads in issues. Saving authorization does
not extend its validity; automatic renewal is not implemented.

## Install

For Home Assistant 2026.9.1 (the tested version), copy this repository's
`custom_components/cloud_intelligence` directory into your HA configuration's
`custom_components` directory. Copy the **whole directory**, including `_core` and
`translations`; no repository-root Python package or helper script is required.
Restart HA, then go to **Settings → Devices & services → Add integration →
Cloud Intelligence (Local)**. Enter the fields above. Addition requires an exact
local device identity, verified authorization and all 12 valid states; an ACK or
refresh echo alone cannot create an entry.

`make package` builds a deterministic manual-install ZIP under `dist/`. The archive already
has the HA layout `custom_components/cloud_intelligence/...`: extract it into the HA
configuration directory so that `custom_components/cloud_intelligence/manifest.json`
exists, then restart HA. This ZIP is a manual-install artifact, not a HACS release asset.
Do not copy the repository-root `cloud_intelligence` package.

### HACS

In HACS, open **Custom repositories**, add
`https://github.com/xiaoyaner0201/ha-cloud-intelligence` with category
**Integration**, download it, and restart HA. Then add **Cloud Intelligence (Local)**
under Settings → Devices & services. This is a custom-repository beta, not a listing
in the HACS default catalog. HACS installs from the repository; the ZIP attached to
[GitHub Releases](https://github.com/xiaoyaner0201/ha-cloud-intelligence/releases)
is for manual installation.

## Recovery and state meaning

- **Invalid authorization:** use HA's reauthentication prompt and re-import new
  authorization for the same `productKey` and `deviceName`. Re-import preserves
  device/entity IDs and refuses a different device. There is no silent renewal.
- **Changed IP/address or authorization:** use the entry's **Reconfigure** action;
  enter the new address and authorization. Friendly names can change without
  changing registry identity. Poll interval is in the entry's options.
- **Offline/timeout:** setup uses HA's standard retry behavior; failed polls make
  entities unavailable. Check LAN routing/firewall/address before re-importing.
- **Partial reports:** initial setup requires 12 states. Later missing/invalid
  fields are unknown, never filled from old values or converted to zero/off.
- `switch` means power permission; `run` means motor running. They are separate
  binary sensors. Local reachability is not cloud online status. The
  `locally_received_at` attribute records this HA host's actual receive time,
  **not** a device timestamp; absent values have no receive time.

Further testing is needed for firmware differences, credential expiry/revocation,
extended unattended operation and browser visual QA.
Complete account discovery, Google sign-in, automatic renewal and operating
controls other than the opt-in enable switch are outside this candidate. Basic UI
locales are en, zh-Hans, zh-Hant and
ja, with English fallback; this is not a claim of full language coverage.

## Development

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check
```

`make check` runs pure-core lint/contracts/link/mutation checks, then the real HA
suite in a disposable `linux/amd64` 2026.9.1 container (`--network none`, 2 GiB,
2 CPUs). Docker and the cached image are required; installation/image retrieval
is separate. All data is synthetic; device transports are blocked or stubbed, with
real UDP endpoint tests restricted to loopback. No
production HA directory is mounted. `make check-core` has no HA runtime dependency;
`make check-ha` runs the container suite explicitly. Runtime dependency:
`cryptography==48.0.1`, pinned by the component manifest.

- [Requirements and property table](docs/requirements.md)
- [Architecture](docs/architecture.md) · [Verification](docs/verification.md)
- [References](docs/references.md) · [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md) · [Apache-2.0 license](LICENSE)

No platform/vendor logos or proprietary client code are redistributed.
