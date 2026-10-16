"""Narrow power outcomes. No identity, credentials or raw packets in errors."""

import asyncio
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


class PowerDisabled(PermissionError):
    """Explicit experimental power permission is absent."""


class PowerOutcomeUnknown(Exception):
    """A physical send was attempted; never automatically retry or infer state."""

    sent = True  # Attempted, NOT a delivery acknowledgement.
    uncertain = True

    def __init__(self):
        super().__init__("Power outcome unknown; read state before any recovery decision")


class PowerCancelled(asyncio.CancelledError):
    """Cancellation after the send boundary, retaining normal cancellation semantics."""

    sent = True
    uncertain = True

    def __init__(self):
        super().__init__("Power outcome unknown after cancellation")


@dataclass(frozen=True)
class PowerResult:
    sent: bool
    snapshot: Any = field(repr=False)
    before: MappingProxyType = field(repr=False)
    uncertain: bool = False


@dataclass
class _PowerAttempt:
    """Private per-call state; mark the send boundary synchronously, before sendto."""

    enabled: bool
    started: bool = False
    before: dict = field(default_factory=dict, repr=False)
