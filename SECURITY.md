# Security policy

## Status and scope

Pre-release candidate, independent and unofficial. It imports a user's own local
device authorization and exposes 12 read-only HA entities for Wilo HiMulti-1 WiFi.
There is no cloud authentication or account discovery. The sole operating exception
is an opt-in experimental enable-permission switch, default false, exact model
only, with full pre-read, fixed one-shot switch=0/1 and new post-send authenticated
Observe window verification of target and unchanged other settings. Unknown
send outcomes (including cancellation) never trigger retry or optimistic state.
Polling includes one fixed `refresh=1` request per report session. No pressure,
mode, speed or arbitrary setter exists. Physical switch writes are not yet tested.
This interface is not an automatic refill controller or safety-rated stop. Do not
use this integration for pressure regulation, protection or any safety function.
See [requirements](docs/requirements.md).

## Credentials and local protocol

`accessKey` and `accessToken` are secrets. They are stored in standard HA config
entries; **the integration does not encrypt them**. Protect the HA configuration
directory, its backups, and administrator access. Password-style UI inputs only
mask display. Saving credentials does not extend their validity. There is no
implemented automatic renewal: re-import replacement authorization for the same
productKey/deviceName when expired or revoked. Never share authorization, raw
packets, device/account identifiers, addresses or signing material.

The supported ALCS opt 1 mode has no packet MAC or replay protection. Its server
nonce proof does not bind the client nonce, session ID or negotiation. AES-CBC
payload encryption and session/endpoint correlation do not make it an
authenticated-encryption protocol. Session-local bounded MID/digest filtering
suppresses retransmissions, **not adversarial replay**. Only use a trusted LAN;
do not expose UDP 5683 publicly. Sequence-window/checksum/unknown modes are
rejected rather than silently treated as supported.

The client permits only a private literal IPv4 address, pins destination/peer,
checks exact model/device identity, token, supplied URI, session option and
application envelopes. Discovery does not authorize writes or redirect traffic.
Unknown products cannot reach an active report request. There is no arbitrary
setter or model-metadata shortcut to device controls. No claims of unlimited
credential lifetime, official certification or production security validation.

## Data handling

Errors omit untrusted server/exception text. Diagnostics are an explicit safe
metadata allowlist and exclude credentials, identities, network addresses and
readings. Stable hashed IDs encode identity but are not anonymization. Local
receive times are not device timestamps or cloud online status. The pure core
stores no authorization and performs no network I/O.

## Reporting

Use the repository's **Security → Report a vulnerability** if private reporting is
enabled. If unavailable, open a content-free request for a private channel; do not
post exploit details or secrets while waiting. No guaranteed response SLA or
published security email is claimed.

Provide the affected commit/version, impact and a synthetic reproduction without
real account/device data. Do not test another person's account, touch production
or operate a live device without separate explicit authorization. Review of
future operating controls must be independent of TSL rw flags or declared ranges.
