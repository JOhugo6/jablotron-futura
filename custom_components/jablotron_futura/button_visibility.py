"""Configuration-owned external button presentation with exact stable identities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .identity import make_entity_unique_id
from .models import eligible_button_members
from .sensor_visibility import ExternalSensorVisibility


class ExternalButtonVisibility(ExternalSensorVisibility):
    """Reuse durable association transitions with a separate button-only journal."""

    storage_name = "button_visibility"
    maximum_associations = 24

    def _unique_id(self, suffix: str) -> str:
        if token := self.entry.data.get("identity_token"):
            return f"{token}_{suffix}"
        return make_entity_unique_id(self.entry.unique_id, self.entry.entry_id, suffix)

    def _position(self, identity: str, domain: str) -> tuple[int, str] | None:
        # A customized action suffix must never grant ownership of fixed controls.
        if domain == "button" and identity in {
            self._unique_id("button_boost_60"),
            self._unique_id("button_circulation_30"),
        }:
            return None
        for slot in range(1, 9):
            for member, member_domain, suffix in (
                ("active", "binary_sensor", f"ext_btn_active_{slot}"),
                ("timer", "sensor", f"ext_btn_tm_{slot}"),
                (
                    "action",
                    "button",
                    self.config["button_slots"][str(slot)]["entity_identity_suffix"],
                ),
            ):
                if domain == member_domain and identity == self._unique_id(suffix):
                    return slot, member
        return None

    def _identity_domain(self, identity: str) -> str | None:
        domains = [
            domain
            for domain in ("sensor", "binary_sensor", "button")
            if self._position(identity, domain) is not None
        ]
        return domains[0] if len(domains) == 1 else None

    def _matches_domain(self, identity: str, domain: str) -> bool:
        return self._position(identity, domain) is not None

    def _marker_key(self, row: Any) -> str:
        return f"{row.domain}:{row.unique_id}"

    def _valid_marker_key(self, key: str) -> bool:
        domain, separator, identity = key.partition(":")
        return bool(separator and self._position(identity, domain) is not None)

    def _journal_data(self, markers: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {"format": 2, "associations": markers}

    def _load(self, saved: Any) -> None:
        if isinstance(saved, dict) and set(saved) == {"format", "associations"}:
            if type(saved["format"]) is not int or saved["format"] != 2:
                raise ValueError("visibility_shape")
            super()._load({"associations": saved["associations"]})
            return
        if not isinstance(saved, dict) or set(saved) != {"associations"}:
            raise ValueError("visibility_shape")
        legacy = saved["associations"]
        if not isinstance(legacy, dict) or len(legacy) > self.maximum_associations:
            raise ValueError("visibility_shape")
        rows = er.async_entries_for_config_entry(self._registry, self.entry.entry_id)
        converted = {}
        for identity, marker in legacy.items():
            if (
                not isinstance(identity, str)
                or not isinstance(marker, dict)
                or not isinstance(marker.get("registry_id"), str)
            ):
                raise ValueError("visibility_marker")
            exact = [
                row
                for row in rows
                if row.unique_id == identity
                and row.id == marker["registry_id"]
                and self._registry_position(row) is not None
            ]
            if len(exact) == 1:
                key = self._marker_key(exact[0])
            else:
                # Without the old row, only an unambiguous canonical domain is safe.
                domain = self._identity_domain(identity)
                if domain is None:
                    raise ValueError("visibility_legacy_identity_ambiguous")
                key = f"{domain}:{identity}"
            converted[key] = marker
        super()._load({"associations": converted})
        self._journal_needs_save = True

    def _registry_position(self, row: Any) -> tuple[int, str] | None:
        if row.config_entry_id != self.entry.entry_id or row.platform != DOMAIN:
            return None
        return self._position(row.unique_id, row.domain)

    def _eligible(self, slot: int) -> tuple[str, ...]:
        return eligible_button_members(self.config, slot)
