# Jablotron Futura Bridge for Home Assistant

A local Modbus TCP integration for **Futura L/M/S**, with native Home Assistant setup in Czech and English, eight external sensor slots, eight external button slots, standard controls and redacted diagnostics. **Futura L+ is not supported** and is rejected before runtime writes.

## Installation and compatibility

The integration uses the HACS integration layout. Software checks cover **Home Assistant 2025.9.0 / pymodbus 3.11.1** and **Home Assistant 2026.11.1 / pymodbus 3.13.1**. The dependency requirement is `pymodbus>=3.11.1,<3.14.0`, allowing Home Assistant to select its own compatible shared version. Other HA versions and physical firmware combinations have not been qualified by these software tests.

Version **0.3.0** pinned pymodbus 3.11.1, which prevents setup on HA 2026.11.1 because HA requires 3.13.1. Version **0.3.1** removes that conflict and adapts durable configuration storage to HA 2026.11. If setup reports HTTP 500 and the log reports these incompatible requirements, update the integration through HACS and restart Home Assistant before opening setup again.

Version **0.3.2** corrects automatic VarioBreeze zone and equipment detection. After updating and restarting HA, close any unfinished setup wizard and start a new setup to regenerate its discovery defaults. Reconfiguration preserves saved zone names, areas and enabled/disabled choices.

Version **0.3.3** uses each configured external sensor name for its measurements and presence entity. Saving a new slot name in the integration options updates these automatic names through the normal reload. Individual entity names set by the user keep priority, and existing entity IDs are preserved.

Version **0.3.4** sets the default maximum source age to **60 minutes = 3600 seconds** for new or missing settings. Existing saved limits, including 120 seconds, are preserved. After updating, an existing entry still using 120 seconds must be changed explicitly in **integration options → Intervals and bridge → Maximum source age (s)**: enter **3600** and confirm saving. This setting keeps integer seconds from 1 to 86400; it does not change the write interval or write-on-change choice. Missing, unknown, unavailable and invalid measurements are still invalidated when evaluated, regardless of this age limit.

Version **0.3.5** corrects word order for the read-only mode/error/warning bitmaps and exposes all error/warning flags documented in register map v5.0 with Czech/English names. Nonzero reserved or unknown bits keep the summary active; summary attributes and diagnostics identify known/unknown bits and original register words. Invalid or failed status reads are unavailable. This status correction does not clear a unit warning or commission its physical configuration.

For configured **HA Control** buttons, version **0.3.5** registers presence/mode during runtime setup **after configuration is saved**, and keeps that registration while idle. Browsing an unsaved setup draft does not register or activate a button. An explicit press writes only timer/active; normal expiry clears that command pair, while ownership release/unload attempts stop and unregister. The existing duration sensor now shows the remaining **HA request** from its local deadline (`countdown_source: ha_activation_deadline`), with unavailable states for unconfirmed/pending/failed operations. Futura-owned timers remain raw register values. This is not confirmation of actual fan operation. Target-firmware acceptance of the separate two-word writes and any relationship to the manual's physical-button minimum remain unverified hardware questions.

Once a reviewed v3 release is published, add this repository to HACS as a custom repository of category **Integration**, install **Jablotron Futura Bridge**, restart HA, and select **Settings → Devices & services → Add integration**. The local working candidate is not automatically available through GitHub/HACS. Installer tests use actual HACS 2.0.5 installation/upgrade code with controlled archive downloads; they do not establish publication, HACS onboarding or a live GitHub download.

The device must already be commissioned. The integration does not perform MyCOMPANY commissioning, firmware updates or service-register configuration. Modbus readback confirms register values, not the physical effect on ventilation; IN1/IN2, emergency states and the unit's own regulation can affect the result.

## Setup

1. Enter the unit's host, port (default 502) and Modbus unit ID (default 1). The connection step performs read-only identity and supported-profile checks.
2. Review the reported identity and detected VarioBreeze support, then choose whether to configure zones. The detected bit indicates support, not proof of physical installation.
3. If using zones, edit the eight supply and eight exhaust zone records, names, areas and existing equipment metadata, then review readings. Zone bindings are organizational; changing a binding does not change the unit's physical interpretation of a register slot.
4. Configure sensor slots 1–8 and button slots 1–8. Both lists are available with or without VarioBreeze.
5. Review the summary and confirm saving. Runtime intervals and bridge settings are available through the runtime settings step. Editing a detail only changes the draft; cancellation does not save it.

For each enabled sensor slot choose **None**, **Read**, or **HA Write-back**. Read observes the unit's holding registers. HA Write-back sends values from `sensor`, `number` or `input_number` entities and also reads them back. It requires at least one source: temperature, relative humidity, CO₂ or floor temperature. Temperatures accept Celsius or Fahrenheit, humidity requires percent and CO₂ requires ppm. A source without a unit needs an explicit target-unit assumption. Missing, invalid or stale measurements are invalidated rather than replaced by apparently valid zeroes.

For buttons choose **None**, **Futura** (read-only), or **HA Control**. HA Control creates an HA button independently of physical-button discovery. Configure Boost or Digestor, the default duration (180 s or 300 s) and the permitted maximum (up to 10800 s). Selecting HA Write-back or HA Control is the ownership choice; there is no additional ownership checkbox. Avoid another client writing the same slots.

The sensor bridge switch stops sensor writes; HA-controlled buttons are independent. Leaving an owned mode or unloading attempts a bounded deactivation. If a button's cleanup fails, it remains unavailable until an explicit successful recovery through reconfiguration. Reconnection does not replay an activation.

## Editing and upgrades

Use the integration entry's **Reconfigure** action for the connection, topology, sources, modes and slot bindings. **Options** provides runtime settings, names/areas and timers, with a route to full reconfiguration. Both use a draft and final confirmation. Changing the address of the same verified unit preserves entity identity; replacing it with a different unit is rejected.

Version 1/2 entries migrate to the canonical version 3 model. Original choices are archived. Conflicting mappings or invalid saved settings open a repair path and block all writes until explicitly resolved; valid reads can continue. A repair must not silently overwrite an occupied disabled slot. The repair UI shows the original choices and any temporary defaults.

## External button action

Use ordinary `button.press` to apply a configured default duration. For an explicit duration, call `jablotron_futura.activate_external_button` targeting an **HA Control external button entity**:

```yaml
action: jablotron_futura.activate_external_button
target:
  entity_id: button.your_futura_external_button
data:
  duration_seconds: 180
```

The required `duration_seconds` field is an integer from 1 to 10800, additionally limited by that slot's configured maximum. Futura-owned slots and standard fixed-action buttons cannot be activated through this action. An acknowledged write is not a guarantee of physical ventilation.

## Development and verification

The local engineering workspace contains an [isolated validation Runbook](docs/PRDs/futura-ha-zone-setup-v3/Runbook.md). Its unit, native HA, fault and HACS harnesses create their own disposable environments; they do not restart a shared user stack.

Those `docs/`, `tests/` and local harness artifacts follow the workspace's existing ignore policy and may not be included in a published repository or HACS package. The installable integration is under `custom_components/jablotron_futura/`. Do not treat a missing local harness link in a packaged release as installation content.

Physical sensor influence, six-word write acceptance on supported firmware, button behavior without physical hardware, expiry/deactivation and humidity target scaling still require hardware qualification before corresponding release claims.


