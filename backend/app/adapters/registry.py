"""Adapter registry.

Adding a store is a new class and one `register()` call. Nothing in the
detection pipeline changes.
"""

from __future__ import annotations

import logging

from app.adapters.base import StoreAdapter
from app.adapters.generic import GenericAdapter
from app.adapters.stores import (
    AdidasAdapter,
    AjioAdapter,
    AmazonAdapter,
    HmAdapter,
    MyntraAdapter,
    NikeAdapter,
    NykaaFashionAdapter,
    UniqloAdapter,
    ZaraAdapter,
)
from app.detection.layers import PageContext

logger = logging.getLogger(__name__)


class AdapterRegistry:
    def __init__(self, fallback: StoreAdapter | None = None) -> None:
        self._adapters: list[StoreAdapter] = []
        self._fallback = fallback or GenericAdapter()

    def register(self, adapter: StoreAdapter) -> AdapterRegistry:
        if any(existing.slug == adapter.slug for existing in self._adapters):
            raise ValueError(f"Adapter {adapter.slug!r} is already registered.")
        self._adapters.append(adapter)
        return self

    def resolve(self, ctx: PageContext) -> StoreAdapter:
        for adapter in self._adapters:
            try:
                if adapter.can_handle(ctx):
                    return adapter
            except Exception:  # noqa: BLE001 - a broken adapter must not break detection
                logger.exception("Adapter %s raised in can_handle", adapter.slug)
        return self._fallback

    def all(self) -> list[StoreAdapter]:
        return [*self._adapters, self._fallback]


registry = AdapterRegistry()
for _adapter in (
    ZaraAdapter(),
    HmAdapter(),
    NykaaFashionAdapter(),
    MyntraAdapter(),
    AjioAdapter(),
    AmazonAdapter(),
    NikeAdapter(),
    AdidasAdapter(),
    UniqloAdapter(),
):
    registry.register(_adapter)
