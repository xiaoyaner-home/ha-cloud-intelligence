# Technical references

These describe public formats and HA integration conventions, not official vendor
support for this community integration. External HTTP audits are optional through
`make external-links`; default checks validate local links offline.

- [Home Assistant config flows and reauthentication](https://developers.home-assistant.io/docs/core/integration/config_flow/):
  config-entry import, same-device credential replacement and reauthentication.
- [Home Assistant entity registry and unique IDs](https://developers.home-assistant.io/docs/entity_registry_index/):
  stable native entity/registry identities.
- [Home Assistant integration manifests](https://developers.home-assistant.io/docs/creating_integration_manifest/):
  local-polling/device metadata and runtime dependency declarations.
- [HACS integration publishing requirements](https://www.hacs.xyz/docs/publish/integration/):
  repository layout, manifest and root `brand/icon.png` requirements.
- [Home Assistant integration file structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/)
  and [brand images](https://developers.home-assistant.io/docs/core/integration/brand_images/):
  local `custom_components/<domain>/brand/` assets for custom integrations.
- [CoAP RFC 7252](https://www.rfc-editor.org/rfc/rfc7252):
  datagram framing, tokens, message IDs and options.
- [CoAP Observe RFC 7641](https://www.rfc-editor.org/rfc/rfc7641):
  observation convention; the supported fixed-zero firmware needs explicit local
  duplicate handling rather than sequence-based suppression.
- [cryptography symmetric encryption](https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/):
  maintained cryptographic primitives. The ALCS final-block framing remains a
  separate protocol format and is not standard authenticated encryption.
- [Apache License 2.0 standard text](https://www.apache.org/licenses/LICENSE-2.0.txt):
  canonical source of the unmodified [LICENSE](../LICENSE).

The Wilo property table in [requirements](requirements.md) is model metadata, not
a public account-login API specification or safe-operation certification. These
references do not supply user credentials or an Android export mechanism. No
proprietary client code, SDK source, vendor secret or vendor branding asset is distributed;
the repository's blue/cyan icon is original artwork under the repository Apache-2.0 license.
See [verification boundaries](verification.md) for actual offline evidence and
remaining live-device/release acceptance.
