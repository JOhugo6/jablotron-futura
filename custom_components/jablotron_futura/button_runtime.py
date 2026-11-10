"""Registered HA buttons, generation-owned commands and local request deadlines."""

from __future__ import annotations
import asyncio
from collections.abc import Callable
import math
import time
from typing import Any
from .readback import decode_button


class ButtonRuntime:
    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.states = {
            str(slot): {
                "state": "startup",
                "activation_generation": 0,
                "registered": False,
                "registration_pending": False,
            }
            for slot in range(1, 9)
        }
        self.tasks: dict[str, asyncio.Task] = {}
        self.owned: set[str] = set()
        self.frozen = False
        self._locks = {key: asyncio.Lock() for key in self.states}
        self._countdown_task: asyncio.Task | None = None
        self._countdown_listeners: set[Callable[[], None]] = set()
        self._release_attempts: set[tuple[str, int]] = set()

    def _configured(self, key: str) -> bool:
        cfg = self.coordinator.config["button_slots"].get(key, {})
        return bool(
            cfg.get("enabled")
            and cfg.get("ownership") == "ha_control"
            and not self.coordinator.config.get("migration_needs_repair")
        )

    @property
    def has_configured_slots(self) -> bool:
        return any(self._configured(key) for key in self.states)

    def _session(self) -> int:
        transport = getattr(self.coordinator, "_transport", None)
        return (
            transport.generation
            if transport is not None
            else getattr(self.coordinator, "reconnect_generation", 0)
        )

    def registration_known(self, key: str) -> bool:
        state = self.states[key]
        transport = getattr(self.coordinator, "_transport", None)
        connected = transport is None or bool(
            transport.client and transport.client.connected
        )
        return bool(
            connected
            and state.get("registered")
            and not state.get("registration_pending")
            and state.get("registration_generation") == self._session()
        )

    def can_activate(self, slot: int) -> bool:
        key = str(slot)
        return bool(
            key in self.states
            and self._configured(key)
            and not self.frozen
            and not self.coordinator._frozen
            and self.states[key]["state"] in ("ready", "active")
            and self.registration_known(key)
        )

    def remaining(self, slot: int) -> int | None:
        key = str(slot)
        if not self.can_activate(slot):
            return None
        state = self.states[key]
        if state["state"] == "ready":
            return 0
        deadline = state.get("deadline")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            return None
        left = deadline - time.monotonic()
        return math.ceil(left) if left > 0 else None

    def async_add_countdown_listener(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        self._countdown_listeners.add(callback)
        return lambda: self._countdown_listeners.discard(callback)

    def _notify_sensors(self) -> None:
        for callback in tuple(self._countdown_listeners):
            callback()

    def _notify(self) -> None:
        self._notify_sensors()
        self.coordinator.async_update_listeners()

    def _start_countdown(self) -> None:
        if not self.frozen and (
            self._countdown_task is None or self._countdown_task.done()
        ):
            self._countdown_task = asyncio.create_task(self._countdown_loop())

    async def _countdown_loop(self) -> None:
        while (
            not self.frozen
            and not self.coordinator._frozen
            and any(state["state"] == "active" for state in self.states.values())
        ):
            await asyncio.sleep(1)
            if not self.frozen:
                # Only duration sensors subscribe; never publish ButtonEntity ticks.
                self._notify_sensors()

    def restore(self) -> None:
        for key, saved in self.coordinator.button_recovery.items():
            if key in self.states:
                self.states[key].update(saved)
                self.states[key].update(
                    state="cleanup_failed", registered=False, registration_pending=False
                )
                self.states[key].pop("deadline", None)
        # Persisted failures alone do not grant this runtime release ownership.

    def _guard(
        self,
        key: str,
        generation: int,
        lifecycle: int,
        *,
        cleanup: bool = False,
        deadline: float | None = None,
    ) -> None:
        if (
            self.states[key]["activation_generation"] != generation
            or self.coordinator.generation != lifecycle
        ):
            raise ValueError("button_unavailable")
        if cleanup:
            if key not in self.owned:
                raise ValueError("slot_not_owned")
        elif self.frozen or self.coordinator._frozen or not self._configured(key):
            raise ValueError("button_unavailable")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("cleanup_deadline")

    @staticmethod
    def _raw(block: dict) -> list[int] | None:
        if not block.get("available"):
            return None
        try:
            return decode_button(block.get("raw", []))["raw"]
        except (ValueError, TypeError):
            return None

    def _live_request(self, key: str) -> bool:
        state = self.states[key]
        deadline = state.get("deadline")
        return bool(
            state["state"] == "active"
            and type(deadline) in (int, float)
            and math.isfinite(deadline)
            and deadline > time.monotonic()
        )

    async def _failure(self, key: str, lifecycle: int, code: str) -> None:
        state = self.states[key]
        deadline = state.get("deadline")
        preserve_deadline = (
            key in self.tasks
            and type(deadline) in (int, float)
            and math.isfinite(deadline)
        )
        state.update(
            state="cleanup_failed",
            registered=False,
            registration_pending=False,
            cleanup_result="failed",
        )
        if not preserve_deadline:
            state.pop("deadline", None)
            self._cancel(key)
        self.coordinator.button_recovery[key] = dict(state)
        try:
            await self.coordinator.async_record_clear(
                {
                    "kind": "button",
                    "slot": int(key),
                    "generation": lifecycle,
                    "result": "failed",
                    "error_code": code,
                }
            )
        finally:
            self._notify()

    async def _register_locked(
        self,
        key: str,
        generation: int,
        lifecycle: int,
        block: dict | None = None,
        *,
        cleanup_deadline: float | None = None,
    ) -> bool:
        state = self.states[key]
        mode = int(
            self.coordinator.config["button_slots"][key]["button_mode"] == "digestor"
        )
        had_local_request = self._live_request(key)
        state["registration_pending"], state["registered"] = True, False
        self._notify()
        budget = (
            cleanup_deadline if cleanup_deadline is not None else time.monotonic() + 10
        )
        try:
            async with asyncio.timeout(max(0, budget - time.monotonic())):
                if block is None:
                    block = await self.coordinator.async_read_external_button(int(key))
                raw = self._raw(block)
                if raw is None:
                    raise ValueError("invalid_button_block")
                self._guard(key, generation, lifecycle, deadline=budget)
                if raw[:2] != [1, mode]:
                    self.owned.add(key)
                    await self.coordinator.async_register_external_button(
                        int(key),
                        mode,
                        extra_guard=lambda: self._guard(
                            key, generation, lifecycle, deadline=budget
                        ),
                    )
                    raw = self._raw(
                        await self.coordinator.async_read_external_button(int(key))
                    )
                self._guard(key, generation, lifecycle, deadline=budget)
                if (
                    raw is None
                    or raw[:2] != [1, mode]
                    or (not had_local_request and (raw[2] or raw[3]))
                ):
                    raise ValueError("registration_not_confirmed")
                self.owned.add(key)
                state.update(registered=True, registration_generation=self._session())
                return True
        except asyncio.CancelledError:
            if not self.frozen and lifecycle == self.coordinator.generation:
                await self._failure(key, lifecycle, "registration_failed")
            raise
        except Exception:
            if not self.frozen and lifecycle == self.coordinator.generation:
                await self._failure(key, lifecycle, "registration_failed")
            return False
        finally:
            state["registration_pending"] = False
            self._notify()

    async def observe_startup(self, key: str, block: dict) -> None:
        state = self.states[key]
        if (
            self.frozen
            or self.coordinator._frozen
            or not self._configured(key)
            or state["state"] not in ("startup", "ready", "active")
            or state.get("registration_pending")
        ):
            return
        raw = self._raw(block)
        if raw is None:
            state["registered"] = False
            self._notify()
            return
        async with self._locks[key]:
            if (
                self.frozen
                or self.coordinator._frozen
                or state["state"] not in ("startup", "ready", "active")
                or state.get("registration_pending")
            ):
                return
            generation, lifecycle = (
                state["activation_generation"],
                self.coordinator.generation,
            )
            self._guard(key, generation, lifecycle)
            mode = int(
                self.coordinator.config["button_slots"][key]["button_mode"]
                == "digestor"
            )
            state.update(
                registered=raw[:2] == [1, mode], registration_generation=self._session()
            )
            if raw[0]:
                self.owned.add(key)
            if not self._live_request(key) and (raw[2] or raw[3]):
                self.owned.add(key)
                state["state"] = "clear_pending"
                self._notify()
                await self._cleanup_locked(key, generation, lifecycle)
                if state["state"] == "cleanup_failed":
                    return
                block = await self.coordinator.async_read_external_button(int(key))
            if self.registration_known(key):
                if state["state"] == "startup":
                    state["state"] = "ready"
                self.owned.add(key)
            elif await self._register_locked(key, generation, lifecycle, block):
                if state["state"] == "startup":
                    state["state"] = "ready"
            self._notify()

    async def activate(self, slot: int, duration: int | None = None) -> None:
        key = str(slot)
        cfg = self.coordinator.config["button_slots"].get(key)
        if cfg is None or not cfg["enabled"] or cfg["ownership"] != "ha_control":
            raise ValueError("slot_not_owned")
        duration = cfg["default_timer_seconds"] if duration is None else duration
        if type(duration) is not int or not 1 <= duration <= cfg["max_active_seconds"]:
            raise ValueError("invalid_duration")
        if not self.can_activate(slot):
            raise ValueError("button_unavailable")
        state = self.states[key]
        state["activation_generation"] += 1
        generation, lifecycle = (
            state["activation_generation"],
            self.coordinator.generation,
        )
        state["state"] = "sending"
        state.pop("deadline", None)
        state.pop("cleanup_deadline", None)
        self._cancel(key)
        self.owned.add(key)
        self._notify()
        try:
            async with self._locks[key]:
                await self.coordinator.async_command_external_button(
                    slot,
                    [duration, 1],
                    extra_guard=lambda: self._guard(key, generation, lifecycle),
                )
        except asyncio.CancelledError:
            state["state"] = "clear_pending"
            state["cleanup_deadline"] = time.monotonic() + 10
            if not self.frozen and lifecycle == self.coordinator.generation:
                cleanup = asyncio.create_task(self._cleanup(key, generation, lifecycle))
                self.tasks[key] = cleanup
                try:
                    await asyncio.shield(cleanup)
                except Exception as err:
                    raise asyncio.CancelledError from err
                finally:
                    if cleanup.done() and self.tasks.get(key) is cleanup:
                        self.tasks.pop(key, None)
            raise
        except Exception as err:
            state["state"] = "clear_pending"
            state["cleanup_deadline"] = time.monotonic() + 10
            await self._cleanup(key, generation, lifecycle)
            raise ValueError("activation_failed") from err
        state.update(state="active", deadline=time.monotonic() + duration)
        if self.frozen or lifecycle != self.coordinator.generation:
            return
        self.tasks[key] = asyncio.create_task(
            self._expire(key, state["deadline"], generation, lifecycle)
        )
        self._start_countdown()
        self._notify()

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
        preserve_failure = self.states[key]["state"] == "cleanup_failed"
        self.states[key]["state"] = "clear_pending"
        self._notify()
        await self._cleanup(
            key,
            generation,
            lifecycle,
            preserve_failure=preserve_failure,
            cleanup_deadline=deadline + 10,
        )

    async def _cleanup(
        self,
        key: str,
        generation: int,
        lifecycle: int,
        *,
        takeover: bool = False,
        preserve_failure: bool = False,
        cleanup_deadline: float | None = None,
    ) -> None:
        state = self.states[key]
        if (
            state["activation_generation"] != generation
            or self.coordinator.generation != lifecycle
        ):
            return
        budget = (
            cleanup_deadline
            if cleanup_deadline is not None
            else state.get("cleanup_deadline", time.monotonic() + 10)
        )
        state["cleanup_deadline"] = budget
        lock = self._locks[key]
        try:
            # Queue wait and I/O consume one original deadline, not two windows.
            async with asyncio.timeout(max(0, budget - time.monotonic())):
                await lock.acquire()
        except TimeoutError:
            if (
                state["activation_generation"] == generation
                and self.coordinator.generation == lifecycle
            ):
                state.update(state="cleanup_failed", cleanup_result="skipped_timeout")
                state.pop("deadline", None)
                state.pop("cleanup_deadline", None)
                self.coordinator.button_recovery[key] = dict(state)
                try:
                    await self.coordinator.async_record_clear(
                        {
                            "kind": "button",
                            "slot": int(key),
                            "generation": lifecycle,
                            "result": "skipped_timeout",
                            "error_code": "deadline",
                        }
                    )
                finally:
                    self._notify()
            return
        try:
            await self._cleanup_locked(
                key,
                generation,
                lifecycle,
                takeover=takeover,
                preserve_failure=preserve_failure,
                cleanup_deadline=budget,
            )
        finally:
            lock.release()

    async def _cleanup_locked(
        self,
        key: str,
        generation: int,
        lifecycle: int,
        *,
        takeover: bool = False,
        preserve_failure: bool = False,
        cleanup_deadline: float | None = None,
    ) -> None:
        state = self.states[key]
        if (
            state["activation_generation"] != generation
            or self.coordinator.generation != lifecycle
        ):
            return
        preserve_failure = preserve_failure or (
            key in self.coordinator.button_recovery and not takeover
        )
        budget = (
            cleanup_deadline if cleanup_deadline is not None else time.monotonic() + 10
        )
        result = "ok"
        try:
            async with asyncio.timeout(max(0, budget - time.monotonic())):
                self._guard(key, generation, lifecycle, cleanup=True, deadline=budget)
                await self.coordinator.async_command_external_button(
                    int(key),
                    [0, 0],
                    cleanup=True,
                    extra_guard=lambda: self._guard(
                        key, generation, lifecycle, cleanup=True, deadline=budget
                    ),
                )
                # A late ACK must not turn a timed-out request into Ready/ok.
                self._guard(key, generation, lifecycle, cleanup=True, deadline=budget)
                block = await self.coordinator.async_read_external_button(int(key))
                self._guard(key, generation, lifecycle, cleanup=True, deadline=budget)
                raw = self._raw(block)
                mode = int(
                    self.coordinator.config["button_slots"][key]["button_mode"]
                    == "digestor"
                )
                if raw is None or raw[2] or raw[3]:
                    raise ValueError("command_stop_not_confirmed")
                state.update(
                    registered=raw[:2] == [1, mode],
                    registration_generation=self._session(),
                )
                if takeover and not await self._register_locked(
                    key, generation, lifecycle, block, cleanup_deadline=budget
                ):
                    raise ValueError("registration_failed")
                self._guard(key, generation, lifecycle, cleanup=True, deadline=budget)
        except TimeoutError:
            result = "skipped_timeout"
        except asyncio.CancelledError:
            result = "skipped_timeout"
            raise
        except Exception:
            result = "skipped_timeout" if time.monotonic() >= budget else "failed"
        finally:
            if state["activation_generation"] == generation:
                state.pop("deadline", None)
                state.pop("cleanup_deadline", None)
                state["cleanup_result"] = result
                if result == "ok" and not preserve_failure:
                    state["state"] = (
                        "ready" if self.registration_known(key) else "startup"
                    )
                    self.coordinator.button_recovery.pop(key, None)
                else:
                    state["state"] = "cleanup_failed"
                    self.coordinator.button_recovery[key] = dict(state)
                try:
                    # Persist the outcome after the bounded control operation ends.
                    await self.coordinator.async_record_clear(
                        {
                            "kind": "button",
                            "slot": int(key),
                            "generation": lifecycle,
                            "result": result,
                            "error_code": None if result == "ok" else "cleanup_failed",
                        }
                    )
                finally:
                    self._notify()

    async def takeover(self, slot: int) -> None:
        key = str(slot)
        if not self._configured(key) or self.states[key]["state"] != "cleanup_failed":
            return
        self._cancel(key)
        self.states[key]["activation_generation"] += 1
        self.states[key]["state"] = "clear_pending"
        self.states[key]["cleanup_deadline"] = time.monotonic() + 10
        self.owned.add(key)
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
        if self._countdown_task is not None:
            tasks.append(self._countdown_task)
            self._countdown_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._notify_sensors()

    async def resume(self) -> None:
        if not self.frozen:
            return
        self.frozen = False
        lifecycle = self.coordinator.generation
        for key, state in self.states.items():
            generation = state["activation_generation"]
            if state["state"] == "active" or (
                state["state"] == "cleanup_failed" and "deadline" in state
            ):
                self.tasks[key] = asyncio.create_task(
                    self._expire(key, state["deadline"], generation, lifecycle)
                )
                self._start_countdown()
            elif state["state"] in ("sending", "clear_pending"):
                state["state"] = "clear_pending"
                self.tasks[key] = asyncio.create_task(
                    self._cleanup(key, generation, lifecycle)
                )
        self._notify()

    async def clear_owned(self) -> None:
        lifecycle = self.coordinator.generation
        for key in sorted(tuple(self.owned)):
            if (key, lifecycle) in self._release_attempts:
                continue
            self._release_attempts.add((key, lifecycle))
            state = self.states[key]
            was_failed = (
                state["state"] == "cleanup_failed"
                or key in self.coordinator.button_recovery
            )
            generation = state["activation_generation"]
            self._cancel(key)
            state["state"] = "clear_pending"
            result = "ok"
            try:
                async with self._locks[key], asyncio.timeout(10):
                    await self.coordinator.async_write_external_button_block(
                        int(key),
                        [0, 0, 0, 0],
                        cleanup=True,
                        extra_guard=lambda: self._guard(
                            key, generation, lifecycle, cleanup=True
                        ),
                    )
            except asyncio.CancelledError:
                result = "skipped_timeout"
                raise
            except Exception:
                result = "failed"
            finally:
                state.pop("deadline", None)
                state.update(
                    registered=False, registration_pending=False, cleanup_result=result
                )
                if result == "ok":
                    self.owned.discard(key)
                state["state"] = (
                    "cleanup_failed" if was_failed or result != "ok" else "startup"
                )
                if state["state"] == "cleanup_failed":
                    self.coordinator.button_recovery[key] = dict(state)
                else:
                    self.coordinator.button_recovery.pop(key, None)
                try:
                    await self.coordinator.async_record_clear(
                        {
                            "kind": "button",
                            "slot": int(key),
                            "generation": lifecycle,
                            "result": result,
                            "error_code": None if result == "ok" else "cleanup_failed",
                        }
                    )
                finally:
                    self._notify()
