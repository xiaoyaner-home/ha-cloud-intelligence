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
  at runtime. It runs all tests and combined branch coverage ≥90%, plus four
  additional HA/protocol mutations. No shared virtual environment is modified.
- `make package`: validates local manifest/HACS/locale shape, both HACS and Home Assistant
  brand icon copies (256x256 and 512x512), and builds a deterministic ZIP containing the
  component's Python/JSON files, permitted brand PNGs and Apache license. This is not an
  official HACS validator, default-store approval or published release.
- `make external-links`: optional bounded HTTP link audit, separate from default
  offline checks; not an install or release gate that runs silently.

## Experimental power candidate offline check

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
