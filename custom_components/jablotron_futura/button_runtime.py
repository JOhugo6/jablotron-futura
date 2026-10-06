"""Generation-owned button commands and durable, bounded cleanup."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class ButtonRuntime:
    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.states = {
            str(slot): {"state": "startup", "activation_generation": 0}
            for slot in range(1, 9)
        }
        self.tasks: dict[str, asyncio.Task] = {}
        self.owned: set[str] = set()
        self.frozen = False

    def restore(self) -> None:
        for key, saved in self.coordinator.button_recovery.items():
            if key in self.states:
                self.states[key].update(saved)

    async def observe_startup(self, key: str, block: dict) -> None:
        cfg = self.coordinator.config["button_slots"][key]
        state = self.states[key]
        if (
            self.frozen
            or not cfg["enabled"]
            or cfg["ownership"] != "ha_control"
            or state["state"] != "startup"
        ):
            return
        if not block.get("available"):
            return
        if block.get("present") or block.get("active"):
            self.owned.add(key)
            state["state"] = "clear_pending"
            await self._cleanup(
                key, state["activation_generation"], self.coordinator.generation
            )
        else:
            state["state"] = "ready"

    async def activate(self, slot: int, duration: int | None = None) -> None:
        key = str(slot)
        cfg = self.coordinator.config["button_slots"].get(key)
        if cfg is None or not cfg["enabled"] or cfg["ownership"] != "ha_control":
            raise ValueError("slot_not_owned")
        duration = cfg["default_timer_seconds"] if duration is None else duration
        if type(duration) is not int or not 1 <= duration <= cfg["max_active_seconds"]:
            raise ValueError("invalid_duration")
        state = self.states[key]
        if (
            self.frozen
            or self.coordinator._frozen
            or self.coordinator.config.get("migration_needs_repair")
            or state["state"] not in ("ready", "active")
        ):
            raise ValueError("button_unavailable")
        # No await before the busy state: concurrent presses cannot both enter.
        state["activation_generation"] += 1
        generation = state["activation_generation"]
        lifecycle = self.coordinator.generation
        state["state"] = "sending"
        self._cancel(key)
        self.owned.add(key)  # a timeout has an unknown wire outcome
        try:
            await self.coordinator.async_write_external_button_block(
                slot, [1, int(cfg["button_mode"] == "digestor"), duration, 1]
            )
        except asyncio.CancelledError:
            state["state"] = "clear_pending"
            if not self.frozen and lifecycle == self.coordinator.generation:
                # Caller cancellation cannot abandon a possibly accepted command.
                # Keep strong ownership of the one cleanup task even if the caller
                # is cancelled again; freeze transfers it to lifecycle cleanup.
                cleanup = asyncio.create_task(self._cleanup(key, generation, lifecycle))
                self.tasks[key] = cleanup
                try:
                    await asyncio.shield(cleanup)
                except Exception as err:
                    # Storage failures already freeze the coordinator and raise a
                    # repair issue; preserve the service caller's cancellation.
                    raise asyncio.CancelledError from err
                finally:
                    if cleanup.done() and self.tasks.get(key) is cleanup:
                        self.tasks.pop(key, None)
            raise
        except Exception as err:
            state["state"] = "clear_pending"
            await self._cleanup(key, generation, lifecycle)
            raise ValueError("activation_failed") from err
        # An acknowledged command retains its original expiry even when a
        # configuration transaction froze producers while the write completed.
        # Rollback resumes this deadline; committed transitions clear ownership.
        state.update(state="active", deadline=time.monotonic() + duration)
        if self.frozen or lifecycle != self.coordinator.generation:
            return
        self.tasks[key] = asyncio.create_task(
            self._expire(key, state["deadline"], generation, lifecycle)
        )
        self.coordinator.async_update_listeners()

    def _cancel(self, key: str) -> None:
        task = self.tasks.pop(key, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _expire(
        self, key: str, deadline: float, generation: int, lifecycle: int
    ) -> None:
        await asyncio.sleep(max(0.0, deadline - time.monotonic()))
        if (
            self.states[key]["activation_generation"] != generation
            or self.coordinator.generation != lifecycle
        ):
            return
        self.states[key]["state"] = "clear_pending"
        await self._cleanup(key, generation, lifecycle)

    async def _cleanup(
        self, key: str, generation: int, lifecycle: int, *, takeover: bool = False
    ) -> None:
        state = self.states[key]
        if (
            state["activation_generation"] != generation
            or self.coordinator.generation != lifecycle
        ):
            return
        result = "ok"
        try:
            async with asyncio.timeout(10):
                await self.coordinator.async_write_external_button_block(
                    int(key), [0, 0, 0, 0], cleanup=True
                )
        except asyncio.CancelledError:
            result = "skipped_timeout"
            raise
        except Exception:
            result = "failed"
        finally:
            if state["activation_generation"] == generation:
                state["state"] = "ready" if result == "ok" else "cleanup_failed"
                state["cleanup_result"] = result
                state.pop("deadline", None)
                if result == "ok":
                    self.owned.discard(key)
                    self.coordinator.button_recovery.pop(key, None)
                else:
                    self.coordinator.button_recovery[key] = dict(state)
                await self.coordinator.async_record_clear(
                    {
                        "kind": "button",
                        "slot": int(key),
                        "generation": lifecycle,
                        "result": result,
                        "error_code": None if result == "ok" else "cleanup_failed",
                    }
                )
                self.coordinator.async_update_listeners()

    async def takeover(self, slot: int) -> None:
        """Only called after a persisted, explicit recovery request."""
        key = str(slot)
        if self.states[key]["state"] != "cleanup_failed":
            return
        self.states[key]["activation_generation"] += 1
        self.states[key]["state"] = "clear_pending"
        await self._cleanup(
            key,
            self.states[key]["activation_generation"],
            self.coordinator.generation,
            takeover=True,
        )

    async def freeze(self) -> None:
        self.frozen = True
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def resume(self) -> None:
        """Rollback resumes live ownership, never startup reconciliation/replay."""
        if not self.frozen:
            return
        self.frozen = False
        lifecycle = self.coordinator.generation
        for key, state in self.states.items():
            generation = state["activation_generation"]
            if state["state"] == "active":
                self.tasks[key] = asyncio.create_task(
                    self._expire(key, state["deadline"], generation, lifecycle)
                )
            elif state["state"] in ("sending", "clear_pending"):
                state["state"] = "clear_pending"
                self.tasks[key] = asyncio.create_task(
                    self._cleanup(key, generation, lifecycle)
                )

    async def clear_owned(self) -> None:
        for key in sorted(self.owned):
            if self.states[key]["state"] == "cleanup_failed":
                continue
            self.states[key]["state"] = "clear_pending"
            await self._cleanup(
                key,
                self.states[key]["activation_generation"],
                self.coordinator.generation,
            )
