"""Real HA lifecycle, synthetic transport, no external network.

These tests instantiate HomeAssistant itself, config flows and both registries.
No Home Assistant classes are replaced with local stand-ins.
"""

import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.cloud_intelligence._core import WILO_MODEL_KEY, parse_snapshot
from custom_components.cloud_intelligence.client import CannotConnect, InvalidAuth, LocalSnapshot
from custom_components.cloud_intelligence.diagnostics import async_get_config_entry_diagnostics
from custom_components.cloud_intelligence.entity import identity
from tests.protocol.test_client import DATA as PROTOCOL_DATA
from tests.protocol.test_endpoint import BoundLanSocket

DATA = dict(
    name="Synthetic pump",
    host="192.168.254.20",
    productKey="a15zaTr5sp1",
    deviceName="SYNTHETIC_DEVICE",
    accessKey="synthetic-key",
    accessToken="synthetic-token",
)
VALUES = dict(
    switch=1,
    temperature=23,
    presSet=4.0,
    mode=0,
    error=0,
    errorState=0,
    run=0,
    propor=30,
    version="SYNTHETIC-v1",
    pressure=1.3,
    tarSpeed=1800,
    nowSpeed=0,
)


def reading(values=None):
    values = VALUES if values is None else values
    snapshot = parse_snapshot(
        {"code": "200", "data": {k: {"value": v} for k, v in values.items()}},
        model_key=WILO_MODEL_KEY,
    )
    return LocalSnapshot(
        snapshot, {k: "2020-01-01T00:00:00+00:00" for k in values}, len(values) == 12
    )


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "custom_components").symlink_to(
            Path.cwd() / "custom_components", target_is_directory=True
        )
        self.guard = patch(
            "custom_components.cloud_intelligence.telemetry.Socket",
            side_effect=AssertionError("REAL NETWORK FORBIDDEN"),
        )
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.stub = AsyncMock(return_value=reading())
        self.patcher = patch(
            "custom_components.cloud_intelligence.client.LocalClient.read", self.stub
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.hass = await self.new_hass()

    async def new_hass(self):
        hass = HomeAssistant(str(self.root))
        hass.config.skip_pip = True
        loader.async_setup(hass)
        hass.config_entries = ConfigEntries(hass, {})
        from homeassistant.bootstrap import async_load_base_functionality

        self.assertTrue(await async_load_base_functionality(hass))
        self.assertTrue(await async_setup_component(hass, "homeassistant", {}))
        return hass

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        await self.hass.async_block_till_done()

    async def add(self, data=None):
        result = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence", context={"source": "user"}, data=data or DATA
        )
        self.assertEqual(result["type"], "create_entry", result)
        await self.hass.async_block_till_done()
        entry = result["result"]
        self.assertEqual(entry.state, ConfigEntryState.LOADED)
        return entry

    async def test_add_twelve_native_entities_device_and_binary_separation(self):
        entry = await self.add()
        self.assertEqual(entry.unique_id, identity(DATA))
        self.assertEqual(dict(entry.data), DATA)
        registry = er.async_get(self.hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        self.assertEqual(len(entities), 12)
        self.assertEqual({e.domain for e in entities}, {"sensor", "binary_sensor"})
        states = {e.original_name: self.hass.states.get(e.entity_id) for e in entities}
        self.assertEqual(states["Power permission"].state, "on")
        self.assertEqual(states["Motor running"].state, "off")
        self.assertEqual(states["Water pressure"].state, "1.3")
        self.assertEqual(states["Actual speed"].attributes["unit_of_measurement"], "rpm")
        self.assertNotIn("state_class", states["Target pressure"].attributes)
        self.assertEqual(
            states["Water pressure"].attributes["locally_received_at"],
            "2020-01-01T00:00:00+00:00",
        )
        self.assertIsNone(entry.runtime_data.data.snapshot.sample("pressure").reported_at_ms)
        devices = dr.async_entries_for_config_entry(dr.async_get(self.hass), entry.entry_id)
        self.assertEqual(len(devices), 1)
        self.assertEqual(
            (devices[0].manufacturer, devices[0].model, devices[0].sw_version),
            ("Wilo", "HiMulti-1 WiFi", "SYNTHETIC-v1"),
        )
        self.assertEqual(entry.runtime_data.update_interval.total_seconds(), 120)
        self.assertFalse(
            any(
                self.hass.services.has_service("cloud_intelligence", key)
                for key in ("set", "refresh")
            )
        )

    async def test_duplicate_id_no_second_validation(self):
        await self.add()
        calls = self.stub.call_count
        result = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence",
            context={"source": "user"},
            data={**DATA, "host": "192.168.254.21", "accessToken": "replacement"},
        )
        self.assertEqual(result["reason"], "already_configured")
        self.assertEqual(self.stub.call_count, calls)

    async def test_two_devices(self):
        a = await self.add()
        b = await self.add({**DATA, "deviceName": "SYNTHETIC_SECOND"})
        self.assertNotEqual(a.unique_id, b.unique_id)
        self.assertEqual(len(er.async_get(self.hass).entities), 24)

    async def test_reauth_same_identity_and_mismatch(self):
        entry = await self.add()
        before = set(er.async_get(self.hass).entities)
        flow = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence",
            context={"source": "reauth", "entry_id": entry.entry_id},
            data=dict(entry.data),
        )
        self.assertEqual(flow["step_id"], "reauth_confirm")
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {**DATA, "accessToken": "replacement"}
        )
        self.assertEqual(result["reason"], "reauth_successful")
        await self.hass.async_block_till_done()
        self.assertEqual(entry.data["accessToken"], "replacement")
        self.assertEqual(set(er.async_get(self.hass).entities), before)
        flow = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence",
            context={"source": "reauth", "entry_id": entry.entry_id},
            data=dict(entry.data),
        )
        calls = self.stub.call_count
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {**DATA, "deviceName": "ANOTHER"}
        )
        self.assertEqual(result["reason"], "wrong_device")
        self.assertEqual(self.stub.call_count, calls)
        self.assertEqual(entry.data["deviceName"], DATA["deviceName"])

    async def test_reconfigure_address_and_options(self):
        entry = await self.add()
        flow = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence", context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {**DATA, "host": "192.168.254.21"}
        )
        self.assertEqual(result["reason"], "reconfigure_successful")
        await self.hass.async_block_till_done()
        self.assertEqual(entry.data["host"], "192.168.254.21")
        result = await self.hass.config_entries.options.async_init(entry.entry_id)
        self.assertEqual(result["type"], "form")
        result = await self.hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 60}
        )
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        self.assertEqual(entry.runtime_data.update_interval.total_seconds(), 60)

    async def test_storage_restart_registry_identity_and_unload(self):
        entry = await self.add()
        entry_id, ids = entry.entry_id, set(er.async_get(self.hass).entities)
        await self.hass.async_stop(force=True)
        await self.hass.async_block_till_done()
        stored = json.loads((self.root / ".storage/core.config_entries").read_text())
        self.assertEqual(stored["data"]["entries"][0]["data"]["accessToken"], DATA["accessToken"])
        self.hass = await self.new_hass()
        restored = self.hass.config_entries.async_get_entry(entry_id)
        self.assertIsNotNone(restored)
        self.assertEqual(dict(restored.data), DATA)
        self.assertTrue(await self.hass.config_entries.async_setup(entry_id))
        await self.hass.async_block_till_done()
        self.assertEqual(set(er.async_get(self.hass).entities), ids)
        coordinator = restored.runtime_data
        self.assertTrue(await self.hass.config_entries.async_unload(entry_id))
        await self.hass.async_block_till_done()
        self.assertTrue(coordinator._shutdown_requested)
        self.assertIsNone(coordinator.pending)
        states = self.hass.states.async_all("sensor") + self.hass.states.async_all("binary_sensor")
        # HA keeps unavailable registry placeholders after unloading an entry.
        self.assertTrue(all(state.state == "unavailable" for state in states))
        self.assertFalse(coordinator._listeners)

    async def test_unload_cancels_pending_read(self):
        entry = await self.add()
        started, closed = asyncio.Event(), asyncio.Event()

        async def blocked(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        self.stub.side_effect = blocked
        task = asyncio.create_task(entry.runtime_data.async_refresh())
        await asyncio.wait_for(started.wait(), 1)
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(closed.is_set())

    async def test_unload_cancels_real_client_and_releases_loopback_endpoint(self):
        entry = await self.add()
        coordinator = entry.runtime_data
        # Restore the actual client; only its transport remains synthetic.
        self.patcher.stop()
        coordinator.client.data = dict(PROTOCOL_DATA)
        sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sink.bind(("127.0.0.1", 0))
        self.addCleanup(sink.close)
        discovery, state = BoundLanSocket(sink), BoundLanSocket(sink)
        self.addCleanup(discovery.close)
        self.addCleanup(state.close)
        state.block = True
        with patch(
            "custom_components.cloud_intelligence.telemetry.Socket",
            side_effect=[discovery, state],
        ):
            task = asyncio.create_task(coordinator.async_refresh())
            await asyncio.wait_for(state.entered.wait(), 1)
            diagnostics = await async_get_config_entry_diagnostics(self.hass, entry)
            self.assertNotIn(str(state.actual[1]), json.dumps(diagnostics))
            self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(discovery.closed and state.closed)
        self.assertFalse(coordinator.client._reading)
        self.assertIsNone(coordinator.pending)
        self.assertTrue(coordinator._shutdown_requested)
        self.assertFalse(coordinator._listeners)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(state.actual)
        finally:
            probe.close()
        self.assertNotIn("port", entry.data)
        self.assertNotIn(str(state.actual[1]), repr(coordinator.client))

    async def test_offline_first_setup_and_invalid_auth(self):
        self.stub.side_effect = CannotConnect
        result = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence", context={"source": "user"}, data=DATA
        )
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.stub.side_effect = InvalidAuth
        result = await self.hass.config_entries.flow.async_configure(result["flow_id"], DATA)
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertNotIn(DATA["accessToken"], str(result))

    async def test_poll_failure_unavailable_partial_no_zero_diagnostics(self):
        entry = await self.add()
        self.stub.side_effect = CannotConnect
        await entry.runtime_data.async_refresh()
        self.assertFalse(entry.runtime_data.last_update_success)
        self.assertTrue(
            all(
                s.state == "unavailable"
                for s in self.hass.states.async_all()
                if s.entity_id.startswith(("sensor.", "binary_sensor."))
            )
        )
        self.stub.side_effect = None
        self.stub.return_value = reading({"pressure": 2.4})
        await entry.runtime_data.async_refresh()
        entities = er.async_entries_for_config_entry(er.async_get(self.hass), entry.entry_id)
        states = {e.original_name: self.hass.states.get(e.entity_id) for e in entities}
        self.assertEqual(states["Water temperature"].state, "unknown")
        self.assertEqual(states["Motor running"].state, "unknown")
        self.assertEqual(states["Water pressure"].state, "2.4")
        diagnostics = await async_get_config_entry_diagnostics(self.hass, entry)
        text = json.dumps(diagnostics)
        for value in DATA.values():
            self.assertNotIn(value, text)
        self.assertEqual(diagnostics["valid_property_count"], 1)
        self.assertFalse(diagnostics["complete"])

    async def test_config_entry_setup_retry_and_auth_failure(self):
        for error, expected in (
            (CannotConnect, ConfigEntryState.SETUP_RETRY),
            (InvalidAuth, ConfigEntryState.SETUP_ERROR),
        ):
            with self.subTest(error=error):
                data = {**DATA, "deviceName": "SYNTHETIC_" + error.__name__}
                self.stub.side_effect = [reading(), error()]
                result = await self.hass.config_entries.flow.async_init(
                    "cloud_intelligence", context={"source": "user"}, data=data
                )
                await self.hass.async_block_till_done()
                entry = result["result"]
                self.assertEqual(entry.state, expected)
                self.assertEqual(
                    len(er.async_entries_for_config_entry(er.async_get(self.hass), entry.entry_id)),
                    0,
                )
        self.assertTrue(
            any(
                flow["context"]["source"] == "reauth"
                for flow in self.hass.config_entries.flow.async_progress()
            )
        )

    async def test_auth_failure_poll_requests_reauthentication(self):
        entry = await self.add()
        self.stub.side_effect = InvalidAuth
        await entry.runtime_data.async_refresh()
        await self.hass.async_block_till_done()
        self.assertFalse(entry.runtime_data.last_update_success)
        self.assertTrue(
            any(
                flow["context"]["source"] == "reauth"
                for flow in self.hass.config_entries.flow.async_progress()
            )
        )

    async def test_form_validation_identity_error_and_secret_selectors(self):
        from homeassistant.helpers import selector

        from custom_components.cloud_intelligence.client import IdentityMismatch

        form = await self.hass.config_entries.flow.async_init(
            "cloud_intelligence", context={"source": "user"}
        )
        for key, field in form["data_schema"].schema.items():
            if str(key) in {"accessKey", "accessToken"}:
                self.assertIsInstance(field, selector.TextSelector)
                self.assertEqual(field.config["type"], "password")
        form = await self.hass.config_entries.flow.async_configure(
            form["flow_id"], {**DATA, "host": "8.8.8.8"}
        )
        self.assertEqual(form["errors"]["base"], "invalid_input")
        self.stub.side_effect = IdentityMismatch
        form = await self.hass.config_entries.flow.async_configure(form["flow_id"], DATA)
        self.assertEqual(form["errors"]["base"], "wrong_device")

    async def test_ha_loads_four_ui_locales_and_english_fallback(self):
        from homeassistant.helpers.translation import async_get_translations

        for language, title in [
            ("en", "Import local device authorization"),
            ("zh-Hans", "导入本地设备授权"),
            ("zh-Hant", "匯入本機裝置授權"),
            ("ja", "ローカル機器の認証情報をインポート"),
            ("de", "Import local device authorization"),
        ]:
            translations = await async_get_translations(
                self.hass, language, "config", {"cloud_intelligence"}
            )
            self.assertEqual(
                translations["component.cloud_intelligence.config.step.user.title"], title
            )

    async def test_failed_platform_unload_keeps_coordinator(self):
        entry = await self.add()
        with patch.object(
            self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)
        ):
            self.assertFalse(await self.hass.config_entries.async_unload(entry.entry_id))
        self.assertFalse(entry.runtime_data._shutdown_requested)

    async def test_entire_add_uses_real_client_with_independent_fake_udp(self):
        from custom_components.cloud_intelligence import telemetry
        from tests.protocol.fixtures import CREDS, report
        from tests.protocol.test_client import VALUES as WIRE_VALUES
        from tests.protocol.test_client import LanSocket

        self.patcher.stop()
        sockets = []

        def factory():
            sock = LanSocket(notifications=[(101, report(WIRE_VALUES))], content_format=b"")
            sockets.append(sock)
            return sock

        with patch.object(telemetry, "Socket", side_effect=factory):
            entry = await self.add({**DATA, **CREDS})
            self.assertTrue(entry.runtime_data.data.complete)
            self.assertTrue(entry.runtime_data.data.snapshot.powered)
            self.assertFalse(entry.runtime_data.data.snapshot.running)
            self.assertEqual(
                len(er.async_entries_for_config_entry(er.async_get(self.hass), entry.entry_id)), 12
            )
            self.assertEqual(len(sockets), 4)  # flow + setup, identity + session each
            self.assertTrue(all(sock.closed for sock in sockets))
            sessions = [sock for sock in sockets if len(sock.sent) == 3]
            self.assertEqual(len(sessions), 2)
            self.assertTrue(
                all(
                    sum(req["path"].endswith("/thing/service/property/set") for req in sock.sent)
                    == 1
                    for sock in sessions
                )
            )
