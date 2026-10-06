"""The Jablotron Futura integration and ordered ownership transitions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .bridge import ExternalSensorBridge
from .const import CONFIG_VERSION, DOMAIN, PLATFORMS, PROFILE_FUTURA_LP
from .coordinator import FuturaCoordinator
from .models import FuturaConfigEntry, FuturaRuntimeData, load_v3_options, migrate_to_v3
from .persistence import async_flush_config_entries

_LOGGER = logging.getLogger(__name__)


def _repair(hass: HomeAssistant, entry: FuturaConfigEntry, reason: str) -> None:
    """Expose an actionable issue without including private error text."""
    from homeassistant.helpers import issue_registry as ir

    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{entry.entry_id}_{reason}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=reason,
    )


async def async_migrate_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> bool:
    """Transform copies and commit once; failure keeps the untouched original."""
    if entry.version == CONFIG_VERSION:
        return True
    if entry.version > CONFIG_VERSION:
        return False
    try:
        data, options = migrate_to_v3(
            dict(entry.data),
            dict(entry.options),
            entry.version,
            entry.unique_id,
            entry.entry_id,
        )
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=CONFIG_VERSION
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        _LOGGER.error("Migration failed; configuration retained")
        _repair(hass, entry, "migration_failed")
        return False
    if options.get("migration_needs_repair"):
        _repair(hass, entry, "migration_needs_repair")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> bool:
    """Start only validated canonical configuration on supported hardware."""
    if (
        entry.data.get("profile_mode") == PROFILE_FUTURA_LP
        or entry.data.get("resolved_profile") == PROFILE_FUTURA_LP
    ):
        raise ConfigEntryError("unsupported_profile")
    try:
        options = load_v3_options(entry.options)
    except ValueError as err:
        raise ConfigEntryError("invalid_v3_configuration") from err
    coordinator = FuturaCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await coordinator.async_close()
        if (
            getattr(coordinator, "identity_error", None)
            or isinstance(err, ValueError)
            or str(err)
            in (
                "identity_mismatch",
                "unsupported_profile",
                "not_futura_device",
                "cannot_read_identity",
            )
        ):
            raise ConfigEntryError("identity_or_profile_invalid") from err
        raise ConfigEntryNotReady("cannot_connect") from err
    bridge = ExternalSensorBridge(hass, entry, coordinator)
    runtime = FuturaRuntimeData(coordinator=coordinator, bridge=bridge)
    entry.runtime_data = runtime
    try:
        # Consume a deliberate recovery request durably before performing it;
        # restart can never replay takeover cleanup from an old saved request.
        recovery = list(options.pop("button_recovery_requests", []))
        if recovery:
            hass.config_entries.async_update_entry(entry, options=options)
            await async_flush_config_entries(hass.config_entries)
        await coordinator.async_start_runtime()
        if recovery:
            await coordinator.async_recover_buttons(recovery)
        await bridge.async_start()
        from .sensor_visibility import ExternalSensorVisibility

        runtime.sensor_visibility = ExternalSensorVisibility(hass, entry)
        await runtime.sensor_visibility.async_start()
        from .button_visibility import ExternalButtonVisibility

        runtime.button_visibility = ExternalButtonVisibility(hass, entry)
        await runtime.button_visibility.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        if runtime.button_visibility is not None:
            await runtime.button_visibility.async_stop()
        if runtime.sensor_visibility is not None:
            await runtime.sensor_visibility.async_stop()
        await _stop_runtime(entry)
        await coordinator.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    async def on_stop(_event: Any) -> None:
        if runtime.button_visibility is not None:
            await runtime.button_visibility.async_stop()
        if runtime.sensor_visibility is not None:
            await runtime.sensor_visibility.async_stop()
        await _freeze_runtime(entry)
        await _stop_runtime(entry)
        await coordinator.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop))
    if options.get("migration_needs_repair"):
        _repair(hass, entry, "migration_needs_repair")
    return True


async def _freeze_runtime(entry: FuturaConfigEntry) -> None:
    runtime = entry.runtime_data
    runtime.transition_state = "frozen"
    await runtime.coordinator.async_freeze()
    await runtime.bridge.async_freeze()


async def _resume_runtime(entry: FuturaConfigEntry) -> None:
    runtime = entry.runtime_data
    runtime.cleanup_complete = False
    await runtime.coordinator.async_resume()
    await runtime.bridge.async_resume()
    runtime.transition_state = "active"


async def _stop_runtime(entry: FuturaConfigEntry) -> None:
    """One shared clear deadline; producers were frozen before entering here."""
    runtime = entry.runtime_data
    if runtime.cleanup_complete:
        return
    try:
        async with asyncio.timeout(10):
            await runtime.bridge.async_stop()
            await runtime.coordinator.async_stop(clear=True)
    except TimeoutError:
        await runtime.coordinator.async_record_skipped_clear()
        _LOGGER.warning("Ownership cleanup deadline reached; verify device state")
        _repair(runtime.coordinator.hass, entry, "cleanup_failed")
    finally:
        runtime.cleanup_complete = True


async def async_commit_configuration(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    data: dict[str, Any],
    options: dict[str, Any],
) -> bool:
    """Do not let flow cancellation split the durable ownership transition."""
    task = asyncio.create_task(_commit_configuration(hass, entry, data, options))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A cancelled flow must wait for the known commit outcome and cleanup;
        # it may not abandon an in-flight atomic storage operation.
        await task
        raise


async def _commit_configuration(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    data: dict[str, Any],
    options: dict[str, Any],
) -> bool:
    """Freeze -> durable commit -> old ownership clear -> unload -> new setup."""
    candidate = load_v3_options(options)
    runtime = getattr(entry, "runtime_data", None)
    old_data, old_options = deepcopy(dict(entry.data)), deepcopy(dict(entry.options))
    if runtime:
        runtime.suppress_reload = True
        await _freeze_runtime(entry)
    try:
        hass.config_entries.async_update_entry(
            entry, data=deepcopy(data), options=candidate
        )
        await async_flush_config_entries(hass.config_entries)
    except Exception as err:
        hass.config_entries.async_update_entry(
            entry, data=old_data, options=old_options
        )
        if runtime:
            await _resume_runtime(entry)
            # Queued update listener tasks see suppression before it is lifted.
            await asyncio.sleep(0)
            runtime.suppress_reload = False
        raise ValueError("save_failed") from err
    if runtime:
        runtime.transition_state = "committed"
        try:
            await _stop_runtime(entry)
            # Controlled reload calls async_unload_entry below. Do not restore
            # old producers after a successful commit, even on storage errors.
            success = await hass.config_entries.async_reload(entry.entry_id)
        except Exception as err:
            runtime.transition_state = "transition_failed"
            _repair(hass, entry, "transition_failed")
            raise ValueError("transition_failed") from err
        if not success:
            runtime.transition_state = "transition_failed"
            _repair(hass, entry, "transition_failed")
            raise ValueError("transition_failed")
    else:
        await hass.config_entries.async_reload(entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> bool:
    """Stop and clear once, preserving the postcommit failure distinction."""
    runtime = entry.runtime_data
    committed = runtime.transition_state in ("committed", "transition_failed")
    await _freeze_runtime(entry)
    await _stop_runtime(entry)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if runtime.button_visibility is not None:
            await runtime.button_visibility.async_stop()
        if runtime.sensor_visibility is not None:
            await runtime.sensor_visibility.async_stop()
        await runtime.coordinator.async_close()
    elif committed:
        runtime.transition_state = "transition_failed"
        _repair(hass, entry, "transition_failed")
    else:
        await _resume_runtime(entry)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> None:
    """Controlled commits handle reload themselves; external changes still reload."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime and runtime.suppress_reload:
        return
    await hass.config_entries.async_reload(entry.entry_id)
