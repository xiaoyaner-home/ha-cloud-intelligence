"""Synthetic physical I/O for real-client poll/control collision tests."""

import asyncio

from tests.protocol.fixtures import report
from tests.protocol.test_client import VALUES
from tests.protocol.test_power import PowerSocket


class PumpIO:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.active = 0
        self.maximum = 0
        self.sockets = []
        self.writes = []
        self.block_next = False
        self.failure_next = None
        self.entered = asyncio.Event()
        self.blocked = None

    def socket(self):
        pump = self

        class PhysicalSocket(PowerSocket):
            def __init__(self):
                super().__init__(
                    notifications=[(101, report({**VALUES, "switch": int(pump.enabled)}))]
                )
                self.hold = pump.block_next
                self.failure = pump.failure_next
                pump.block_next = False
                pump.failure_next = None
                self.release = asyncio.Event()
                self.bound_active = False

            def bind(self, address):
                assert pump.active == 0, "OVERLAPPING PHYSICAL SESSION"
                super().bind(address)
                self.bound_active = True
                pump.active += 1
                pump.maximum = max(pump.maximum, pump.active)

            async def recvfrom(self, size):
                if self.hold:
                    self.entered.set()
                    pump.blocked = self
                    pump.entered.set()
                    await self.release.wait()
                    self.hold = False
                    if self.failure is not None:
                        raise self.failure
                return await super().recvfrom(size)

            def sendto(self, packet, peer):
                count = super().sendto(packet, peer)
                if self.power_requests:
                    enabled = bool(self.power_requests[-1]["body"]["params"]["switch"])
                    pump.writes.append(enabled)
                    pump.enabled = enabled
                return count

            def close(self):
                if self.bound_active:
                    pump.active -= 1
                    self.bound_active = False
                super().close()

        sock = PhysicalSocket()
        self.sockets.append(sock)
        return sock
