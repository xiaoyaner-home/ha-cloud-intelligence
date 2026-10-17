"""Optional offline composition: frozen native HA policy plus actual power client.

Run in the cached HA container with --network none. --policy-source is read-only;
only its public package and test Rig are used. No production config is accepted.
"""

import argparse
import asyncio
import importlib.util
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(policy, predeadline=False):
    from homeassistant.core import callback
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.entity_component import DATA_INSTANCES

    from custom_components.cloud_intelligence import telemetry
    from custom_components.cloud_intelligence.client import LocalClient
    from custom_components.cloud_intelligence.coordinator import LocalCoordinator
    from custom_components.cloud_intelligence.switch import PowerSwitch
    from tests.ha.poll_fixture import PumpIO
    from tests.protocol.test_client import DATA

    spec = importlib.util.spec_from_file_location("policy_e2e", policy / "tests/e2e.py")
    e2e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2e)
    target = "switch.synthetic_wilo_pump"
    package = yaml.safe_load(
        (policy / "packages/refill_guard.yaml").read_text().replace("switch.synthetic_pump", target)
    )
    pump = PumpIO(enabled=True)
    evidence = {"policy_io_budget": 12, "policy_limit": 120, "manual_retry": False}
    with tempfile.TemporaryDirectory(prefix="pollrace-policy-") as td:
        root = Path(td)
        (root / "custom_components").symlink_to(
            ROOT / "custom_components", target_is_directory=True
        )
        rig = e2e.Rig(package, root)
        with patch.object(telemetry, "Socket", side_effect=pump.socket):
            try:
                await rig.boot()
                result = await rig.hass.config_entries.flow.async_init(
                    "cloud_intelligence", context={"source": "user"}, data=dict(DATA)
                )
                assert result["type"] == "create_entry", result
                await rig.idle()
                entry = result["result"]
                rig.hass.config_entries.async_update_entry(
                    entry, options={"enable_power_control": True}
                )
                await rig.idle()
                registry = er.async_get(rig.hass)
                switch = next(
                    e
                    for e in er.async_entries_for_config_entry(registry, entry.entry_id)
                    if e.domain == "switch"
                )
                registry.async_update_entity(switch.entity_id, new_entity_id=target)
                await rig.idle()
                entity = rig.hass.data[DATA_INSTANCES]["switch"].get_entity(target)
                coordinator = entity.coordinator
                client = coordinator.client
                assert isinstance(entity, PowerSwitch)
                assert isinstance(coordinator, LocalCoordinator)
                assert isinstance(client, LocalClient)
                e2e.PUMP = target
                assert rig.state("input_number.refill_guard_limit_seconds") == "120.0"
                assert rig.state("input_number.refill_guard_confirm_seconds") == "12.0"
                await rig.boolean("input_verified", True)
                await rig.boolean("enabled", True)
                await rig.set_flushing("unknown")
                await rig.set_flushing("off")
                await rig.until(lambda: rig.state(e2e.PREFIX + "seen_off") == "on", "baseline")
                await rig.begin()
                await rig.until(
                    lambda: rig.state("script.refill_guard_step") == "off", "close done"
                )
                assert pump.writes == [False] and not pump.enabled and rig.pending()
                evidence["close"] = {"pump": rig.state(target), "pending": rig.pending()}
                ended = rig.hass.states.get(e2e.FLUSHING).last_changed.timestamp()
                deadline = rig.hass.states.get("input_datetime.refill_guard_deadline").attributes[
                    "timestamp"
                ]
                assert 119 <= deadline - ended <= 120
                evidence["deadline_minus_flush_end"] = deadline - ended
                polls = []
                restore_started = asyncio.Event()

                @callback
                def inject(event):
                    data = event.data
                    if (
                        data.get("domain") == "input_text"
                        and data.get("service") == "set_value"
                        and data.get("service_data", {}).get("entity_id")
                        == ["input_text.refill_guard_owned_context"]
                        and rig.state(e2e.PREFIX + "restore_attempted") == "on"
                        and not restore_started.is_set()
                    ):
                        # Native restore has finished its refresh; insert the periodic
                        # read in the service scheduling gap BEFORE PowerSwitch runs.
                        if not predeadline:
                            pump.block_next = True
                            polls.append(
                                asyncio.create_task(coordinator.async_refresh(), eager_start=True)
                            )
                        restore_started.set()

                remove = rig.hass.bus.async_listen("call_service", inject)
                if predeadline:
                    pump.block_next = True
                    polls.append(asyncio.create_task(coordinator.async_refresh(), eager_start=True))
                    await asyncio.wait_for(pump.entered.wait(), 1)
                evidence["injection"] = "before_deadline" if predeadline else "before_restore_write"
                try:
                    # Advance the persisted deadline, not pending/attempt state. No
                    # automation.trigger, script step invocation or manual retry.
                    await rig.hass.services.async_call(
                        "input_datetime",
                        "set_datetime",
                        {
                            "entity_id": "input_datetime.refill_guard_deadline",
                            "timestamp": time.time() - 1,
                        },
                        blocking=True,
                    )
                    await asyncio.wait_for(restore_started.wait(), 4)
                    await asyncio.wait_for(pump.entered.wait(), 1)
                    assert coordinator.pending is not None
                    await asyncio.sleep(0.15)
                    evidence["inflight_at_restore"] = coordinator.pending is not None
                    evidence["claimed_while_read_blocked"] = coordinator.power_pending is not None
                    evidence["writes_while_blocked"] = list(pump.writes)
                    pump.blocked.release.set()
                    await asyncio.wait_for(asyncio.gather(*polls), 2)
                    await rig.until(
                        lambda: rig.state("script.refill_guard_step") == "off",
                        "restore done",
                        timeout=14,
                    )
                    await asyncio.sleep(1.2)
                    await rig.idle()
                    evidence["after"] = {
                        "pump": rig.state(target),
                        "physical": pump.enabled,
                        "pending": rig.pending(),
                        "attempted": rig.state(e2e.PREFIX + "restore_attempted"),
                        "diagnostic": rig.state("input_text.refill_guard_status"),
                    }
                    evidence["writes"] = pump.writes
                    evidence["max_active_physical_sessions"] = pump.maximum
                    evidence["same_client"] = coordinator.client is client
                    evidence["passed"] = (
                        pump.writes == [False, True]
                        and pump.enabled
                        and not rig.pending()
                        and rig.state(target) == "on"
                        and pump.maximum == 1
                        and pump.active == 0
                        and evidence["claimed_while_read_blocked"]
                    )
                finally:
                    remove()
                    if pump.blocked is not None:
                        pump.blocked.release.set()
                    await asyncio.gather(*polls, return_exceptions=True)
            finally:
                await rig.stop()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--predeadline", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    evidence = asyncio.run(run(args.policy_source, args.predeadline))
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
