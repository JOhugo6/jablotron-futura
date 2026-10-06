"""Pinned HA persistence boundary for configuration ownership transitions."""

from __future__ import annotations

from typing import Any
from collections.abc import Callable


async def async_flush_config_entries(manager: Any) -> None:
    """Persist atomically and propagate errors before any ownership clear.

    HA2025.9 public async_update_entry schedules a delayed save. Store.async_save
    logs and swallows write errors. This narrow adapter intentionally uses the
    inspected Store write primitive under its own lock. Keep its real-HA contract
    test when raising the minimum supported HA version.
    """
    await _async_save(manager._store, manager._data_to_save)


async def async_save_store(store: Any, data: dict[str, Any]) -> None:
    """Durably save the ownership report, propagating storage failures."""
    await _async_save(store, lambda: data)


async def async_flush_entity_registry(registry: Any) -> None:
    """Persist association changes before completing their durable ownership marker.

    HA2025.9 postpones startup registry saves for 180 seconds. A process restart
    inside that window must not make an owned detachment appear user initiated.
    """
    await _async_save(registry._store, registry._data_to_save)


async def _async_save(store: Any, snapshot: Callable[[], Any]) -> None:
    async with store._write_lock:
        if store._read_only:
            raise OSError("storage_read_only")
        store._async_cleanup_delay_listener()
        store._async_cleanup_final_write_listener()
        payload = {
            "version": store.version,
            "minor_version": store.minor_version,
            "key": store.key,
            "data": snapshot(),
        }
        # Clear only the work consumed by this snapshot. Another integration may
        # schedule a save while disk I/O is awaited; preserve that newer work.
        store._data = None
        atomic_writes = store._atomic_writes
        store._atomic_writes = True
        try:
            await store._async_write_data(store.path, payload)
        finally:
            store._atomic_writes = atomic_writes
        store._manager.async_invalidate(store.key)
