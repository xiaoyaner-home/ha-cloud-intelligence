# Verification

## Environments and commands

Host pure-core tooling is pinned in [requirements-dev.txt](../requirements-dev.txt):
Python 3.13.12, coverage 7.10.6 and ruff 0.12.12. The runtime core has no dependencies.
The installable HA component requires cryptography 48.0.1.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check
make package
```

Installation uses a package index/cache; a Docker daemon and cached
`ghcr.io/home-assistant/home-assistant:2026.9.1` image are separate prerequisites.
`make check` never fetches a package or image, authenticates to a cloud, scans a
LAN, contacts a device, mounts production HA or starts a persistent service.
A missing dependency/image is a failed prerequisite, not a skipped passing test.

- `make check-core`: pinned tools, exact packaged-core parity, lint/format, the
  original 29 stdlib tests with branch-enabled core coverage ≥90%, local doc links
  and two isolated core mutations. It needs no HA or cryptography installation.
- `make check-ha`: a disposable `--platform linux/amd64 --rm --network none`
  container, memory 2 GiB / CPU 2, with only this checkout bind-mounted at `/work`.
  Actual HA 2026.9.1 / Python 3.14.6, cryptography 48.0.1, coverage 7.16.0 are checked
  at runtime. It runs all tests and combined branch coverage ≥90%, plus six
  additional HA/protocol mutations. No shared virtual environment is modified.
- `make package`: validates local manifest/HACS/locale shape, both HACS and Home Assistant
  brand icon copies (256x256 and 512x512), and builds a deterministic ZIP containing the
  component's Python/JSON files, permitted brand PNGs and Apache license. This is not an
  official HACS validator, default-store approval or published release.
- `make external-links`: optional bounded HTTP link audit, separate from default
  offline checks; not an install or release gate that runs silently.

## Explicit control-switch refresh regression

A real HA request-refresh cooldown was primed while the synthetic physical pump
was on, followed by an external synthetic off without updating HA. The original
`homeassistant.update_entity` returned cached on, allowing the frozen native refill
policy to record restore debt even though control's own pre-read correctly no-oped.
After deadline advancement the original composition wrote on. This was reproduced
in software, not on a physical device.

The permanent `--original-off-debounce` mode of `tools/poll_policy_probe.py` now
checks both after-flush and after-deadline: physical off, HA off, pending false and
zero writes. It uses the same frozen policy revision and real HA/PowerSwitch/
Coordinator/LocalClient as below; only socket I/O is synthetic. No policy state,
fixtures, defaults or consumer logic is replaced. Six additional real HA tests
cover an active and actually expired cooldown, an earlier read plus an independent
fresh read, a busy control, failed/unknown reports, overlapping explicit services,
and cancellation during a read or while waiting for HA's refresh lock.

`make check` passes 29 core tests (99% core coverage) and 218 complete HA-container
tests (93% combined branch coverage, including the original 212). Both new isolated
mutations are killed by assertions: restoring request-refresh debounce and restoring
HA's staged-update cached return. The two core and all six HA/protocol mutation
baselines pass, and all eight mutants fail the intended assertions.

The predeadline composition fixture must release its earlier read after observing
that native `update_entity` is waiting, before waiting for restore to start. Its
former reverse wait order deadlocks once explicit refresh is genuinely fresh; that
is a fixture dependency error, not a runtime restore failure. The probe asserts
this waiting phase, then still inserts a second read in the pre-write scheduling
gap and requires the original single-client/bounded-control-wait assertions. Both
composition modes finish with exactly off/on writes, confirmed on and pending false.
The separate original-off regression requires zero writes throughout.

## Poll/control collision regression (earlier baseline)

The HA-only arbitration change retains the original core-client immediate overlap
rejection and its protocol/endpoint tests unchanged. That baseline passed
29 Python 3.13.12 core tests (99% coverage), 212 tests in HA 2026.9.1 / Python 3.14.6
(93% combined branch coverage), and all six assertion-killing mutations. The HA
coordinator retains 100% statement/branch coverage. The only superseded assertion
is the former HA control-vs-read immediate refusal; control-vs-control still refuses.

A real `PowerSwitch.turn_on` service against a blocked real-client read first failed
with `Local operation already in progress`, then passed with one fresh control
operation and at most one active synthetic physical socket. New cases cover poll
failure followed by independent complete/incomplete control pre-read, slot claiming,
second-control/new-poll refusal, bounded waiting, pre-send budget exhaustion,
cancellation without cancelling the poll, option/closed rechecks, actual unload,
structured shield failure, and post-send timeout/cancellation without retry.

`tools/poll_policy_probe.py --policy-source <read-only-policy-checkout> --predeadline
--output <evidence.json>` is a separate optional composition probe for the frozen
native HA refill policy at revision `4de1d1af056a7f4dea5cd13547972a1b9611f4bf`.
Run it in the same network-disabled HA image, mounting that checkout read-only.
It loads the public package and its `tests/e2e.py` Rig, uses actual PowerSwitch,
Coordinator and LocalClient, and replaces only physical socket I/O. The policy's
120-second duration and 12-second I/O defaults remain unchanged. A read is placed
in flight before advancing the persisted deadline; no pending edits, direct policy
step calls or manual retry occur. The old coordinator leaves pump off and pending
on after its unique restore attempt; the fixed coordinator records exactly off/on,
reads back on and clears pending. The original end+120 deadline is checked before
test-only deadline advancement; this is not a claim of waiting 120 wall-clock seconds.
The probe also permits injection in the post-refresh/pre-write scheduling gap by
omitting `--predeadline`. These remain synthetic offline checks, not production or
physical acceptance of this fix.

## Experimental power candidate offline check (earlier baseline)

`make check` passes with 29 Python 3.13.12 core tests (99% branch-enabled coverage)
and 205 tests in actual HA 2026.9.1 / Python 3.14.6 (93% combined branch-enabled
coverage). The HA count includes core cases, not 205 additional tests. All six
isolated mutation baselines pass and all six mutants fail the intended assertions.
New `power.py`, `switch.py` and the coordinator have 100% statement/branch coverage;
the client is 97%, transport 92%, including retained pre-existing paths.

RED was recorded before the new API/platform existed, then GREEN exercised strict
permission/bool/model/input boundaries, both fixed encodings, both-direction no-op,
full pre-read validity/proof/token/session/peer/URI gates, single send, ignored ACK
and set200, unchanged target/settings rejection, old-session packet exclusion,
new post-send verification, lost replies, short sends, timeout/cancellation,
shared read/write exclusion, independent clients, actual loopback source-port
reuse, real-client standard HA service calls, non-optimism, unload cancellation
and socket release, option reload and all original read/device/config identities.
Only the explicitly superseded no-switch packaging assertion changed to an
exact narrow-platform/default-off contract; all other existing assertions remain.
Synthetic inputs only; container networking is disabled, real UDP is loopback only.
No physical switch write, online device/HA access or credential-store access was
performed. This is a candidate, not a release, root-cause fix, formal independent
review or live-device validation. Physical gates are in [requirements](requirements.md).

## Recorded earlier read-only candidate check

The local core/HA/package checks completed successfully: 29 core tests on Python 3.13.12
with 99% core branch-enabled coverage, and 173 tests in the real HA container with 91%
combined branch-enabled coverage. The HA count includes the same core/protocol tests,
not 173 additional cases. All four mutation baselines passed and their mutants failed
the intended assertions. Local and external link checks validated 66 links; all 10 distinct
external references returned HTTP 200 and the canonical LICENSE matched. `make package`
also passed, with 24 exact ZIP members.
These are local checks only; the narrow live smoke result and transient scheduled-poll
failure/recovery are recorded below. The remote HACS workflow has not run from this checkout.

## Evidence and boundaries

The actual HA suite instantiates HomeAssistant with temporary config directories,
initializes its own registries/storage/loader, then runs real config flows and
native platforms. Only client/socket transport is replaced. No HA classes are
mocked. Restart loads the actual saved `core.config_entries` file into a new HA
instance and preserves device/entity IDs; tests do not merely serialize a local
dataclass. The extracted ZIP is also imported in an isolated Python process with
real HA and without the repository root core available.

Coverage includes all integration Python code and both the canonical and packaged
core. No runtime module is excluded to improve the score. Core parity prevents
copy drift. Protocol tests include an independent CoAP server codec and ECB/XOR
AES oracle for the final-block IV restart, not only self-roundtrip encryption.
All fixtures are synthetic and socket use is blocked or replaced; the container's
network is additionally disabled.

Two original core mutations corrupt running-vs-power separation and unknown-model
write permissions. Two adapter mutations conflate the actual HA power/run binary
states and reject valid encrypted content-format 0. Two additional power mutations
invert the fixed switch payload and bypass preservation of other writable settings.
Two explicit-refresh mutations restore request-refresh debounce and the overlapping
staged-update cached return, each killed through the real standard HA service.
Each runs in a distinct
throwaway repository copy, requires an unmodified passing baseline and an actual
assertion failure (not import/tool failure), and leaves working source unchanged.

Acceptance covers add/duplicate/multiple-device flows, same/mismatched reauth,
reconfigure/options, persisted restart, device/entity registries, all 12 correct
states, binary separation, unavailable/partial handling, setup retry/auth failure,
pending-read unload cancellation, diagnostic redaction, actual locale/fallback
loading, ctype 0, Observe 0, strict boundary rejection, fixed report once, total
timeout, socket cleanup and standalone packaging.

Offline tests do **not** prove this adapter's live-device operation, UI browser rendering,
indefinite authorization validity, automatic renewal, extended unattended operation,
other firmware/models, HACS store validation or production approval. A separate authorized
smoke check verified initial setup, 12 native states, local receive timestamps, a service
process/API health check and the absence of control services on one real HA host. Its first
roughly 120-second scheduled poll reported telemetry unavailable; the next automatic poll
recovered all 12 states with stable registry IDs. This short observation is not long-term
stability or production acceptance; a subsequent full HA process restart preserved the same entry, device and all 12
entity/registry IDs and produced fresh device readings without authorization re-import.
Browser visual QA and other-model support remain unverified. HACS action execution is a separate
remote CI gate and has not been run from this local checkout. Protocol-level compatibility
is not a substitute for acceptance of this exact HA implementation.
