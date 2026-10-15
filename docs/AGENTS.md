# Documentation guidance

- Keep `README.md`, `README.zh-CN.md` and `README.ja.md` aligned on installation,
  tested versions, supported scope and remaining acceptance gates.
- State only public product behavior and evidence that can be shared without
  credentials, device identifiers, addresses, readings, private paths or internal
  research history.
- Distinguish offline synthetic checks, single-device real-host acceptance, and
  remaining long-running and visual UI verification. A local HACS repository
  entry is not a default-store listing, release, certification or vendor claim.
- Describe the installable root as
  `custom_components/cloud_intelligence`; do not present the repository-root
  `cloud_intelligence` package or `tools/` as runtime requirements.
- Keep security wording explicit: authorization is user-provided, stored in HA's
  standard entry storage without integration-level encryption, intended for a
  trusted LAN, and not automatically renewed.
- Use synthetic examples and public references for reproducible setup and validation.
