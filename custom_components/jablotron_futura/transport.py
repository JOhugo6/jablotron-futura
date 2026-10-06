"""One serialized, bounded Modbus session per resolved endpoint."""

from __future__ import annotations

import asyncio
import inspect
import socket
import time
from typing import Any, Callable

from pymodbus.client import AsyncModbusTcpClient

from .readback import valid_words


class TransportError(Exception):
    """Sanitized transport failure; never contains endpoint or response text."""


class TransportPolicyError(TransportError):
    """Pre-wire denial: no failed network operation and no new cooldown."""


class EndpointTransport:
    def __init__(
        self, host: str, port: int, factory: Callable[..., Any] = AsyncModbusTcpClient
    ) -> None:
        self.host, self.port, self.factory = host, port, factory
        self.lock = asyncio.Lock()
        self.client: Any = None
        self.generation = 0
        self.retry_at = 0.0
        self.retry_interval = 5.0
        self.last_lock_wait = 0.0
        self.users = 0

    async def _drop(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            result = client.close()
            if inspect.isawaitable(result):
                await result

    async def close(self) -> None:
        async with self.lock:
            await self._drop()

    async def _ensure(self) -> Any:
        if self.client is not None and self.client.connected:
            return self.client
        if time.monotonic() < self.retry_at:
            raise TransportPolicyError("reconnect_backoff")
        await self._drop()
        self.retry_at = time.monotonic() + self.retry_interval
        self.client = self.factory(
            self.host, port=self.port, timeout=5, retries=0, reconnect_delay=0
        )
        await self.client.connect()
        if not self.client.connected:
            raise TransportError("cannot_connect")
        self.generation += 1
        self.retry_at = 0.0
        return self.client

    async def request(
        self,
        unit: int,
        method: str,
        address: int,
        *,
        guard: Callable[[], None] | None = None,
        expected_generation: int | None = None,
        **kwargs: Any,
    ) -> Any:
        started = time.monotonic()
        async with self.lock:
            self.last_lock_wait = time.monotonic() - started
            try:
                async with asyncio.timeout(5):
                    client = await self._ensure()
                    if (
                        expected_generation is not None
                        and self.generation != expected_generation
                    ):
                        raise TransportPolicyError("session_changed")
                    if guard:
                        try:
                            guard()
                        except TransportError as err:
                            raise TransportPolicyError(str(err)) from err
                        except Exception as err:
                            raise TransportPolicyError("request_rejected") from err
                    operation = getattr(client, method)
                    parameter = (
                        "device_id"
                        if "device_id" in inspect.signature(operation).parameters
                        else "slave"
                    )
                    response = await operation(address, **kwargs, **{parameter: unit})
                    if response.isError():
                        raise TransportError("modbus_error")
                    if method.startswith("read_"):
                        words = list(response.registers)
                        if not valid_words(words, kwargs["count"]):
                            raise TransportError("invalid_response")
                        return words
                    return None
            except asyncio.CancelledError:
                await self._drop()
                raise
            except TransportPolicyError:
                # A cooldown read or a denied writer must not keep pushing the
                # recovery deadline forward or disconnect a healthy reader.
                raise
            except Exception as err:
                await self._drop()
                self.retry_at = time.monotonic() + self.retry_interval
                if isinstance(err, TransportError):
                    raise
                raise TransportError("transport_failure") from err


_REGISTRY: dict[tuple[int, str, int], EndpointTransport] = {}
_REGISTRY_LOCKS: dict[int, asyncio.Lock] = {}


async def acquire_transport(
    host: str, port: int, *, factory: Callable[..., Any] = AsyncModbusTcpClient
) -> EndpointTransport:
    """Resolve aliases before allocation; flow/runtime share this registry."""
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(5):
            addresses = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, TimeoutError, UnicodeError) as err:
        raise TransportError("cannot_connect") from err
    if not addresses:
        raise TransportError("cannot_connect")
    resolved = sorted({item[4][0] for item in addresses})[0]
    key = (id(loop), resolved, port)
    lock = _REGISTRY_LOCKS.setdefault(id(loop), asyncio.Lock())
    async with lock:
        transport = _REGISTRY.setdefault(
            key, EndpointTransport(resolved, port, factory)
        )
        transport.users += 1
        return transport


async def release_transport(transport: EndpointTransport) -> None:
    loop = asyncio.get_running_loop()
    async with _REGISTRY_LOCKS.setdefault(id(loop), asyncio.Lock()):
        transport.users -= 1
        if transport.users <= 0:
            await transport.close()
            for key, value in list(_REGISTRY.items()):
                if value is transport:
                    del _REGISTRY[key]
