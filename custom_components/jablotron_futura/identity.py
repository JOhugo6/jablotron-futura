"""Stable identity helpers for Jablotron Futura."""

from __future__ import annotations

from hashlib import blake2s

from .const import DOMAIN, ENTRY_TITLE_PREFIX


def make_connection_unique_id(host: str, port: int, unit_id: int) -> str:
    """Return the config-entry unique id derived from the connection tuple."""
    return f"{host}:{port}:{unit_id}"


def make_entry_title(unit_id: int) -> str:
    """Return a user-facing title without leaking the network address."""
    return f"{ENTRY_TITLE_PREFIX} (unit {unit_id})"


def make_device_name(unit_id: int) -> str:
    """Return a stable device name for the controller."""
    return f"{ENTRY_TITLE_PREFIX} unit {unit_id}"


def make_device_identifier(
    entry_unique_id: str | None, fallback: str
) -> tuple[str, str]:
    """Return a stable device registry identifier."""
    return (DOMAIN, f"controller_{_stable_token(entry_unique_id, fallback)}")


def make_entity_unique_id(
    entry_unique_id: str | None, fallback: str, unique_suffix: str
) -> str:
    """Return a stable entity unique id derived from the controller identity."""
    return f"{_stable_token(entry_unique_id, fallback)}_{unique_suffix}"


def _stable_token(entry_unique_id: str | None, fallback: str) -> str:
    source = entry_unique_id or fallback
    return blake2s(source.encode("utf-8"), digest_size=10).hexdigest()


# v3 helpers deliberately do not inspect legacy configuration.
def normalize_host(host: str) -> str:
    """Normalize an IP literal or DNS label without resolving it."""
    from ipaddress import ip_address

    value = host.strip().rstrip(".").lower()
    try:
        return ip_address(value.strip("[]")).compressed
    except ValueError:
        return value


def identity_token(entry_unique_id: str | None, fallback: str) -> str:
    """Freeze the existing entity token once, independent of later IP edits."""
    return _stable_token(entry_unique_id, fallback)


def hardware_fingerprint(identity: dict) -> str:
    """Return the hardware duplicate key, separate from the registry token."""
    serial = str(identity.get("serial_number", "")).strip()
    mac = (
        str(identity.get("ethernet_mac", "")).replace(":", "").replace("-", "").lower()
    )
    if not serial or not mac or set(mac) <= {"0"} or set(mac) <= {"f"}:
        raise ValueError("cannot_read_identity")
    return blake2s(f"{serial}:{mac}".encode(), digest_size=16).hexdigest()
