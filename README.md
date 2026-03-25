# Jablotron Futura Bridge for Home Assistant

Custom integration for Jablotron Futura over Modbus TCP with:

- Home Assistant UI config flow
- profile-aware Modbus access for `futura_lms` and `futura_lp`
- external sensor bridge from HA entities to `ext_sens_*` slots
- diagnostics export
- Czech and English flow translations
- HACS-ready repository structure
- local Docker stack with Home Assistant and Modbus simulator

## HACS install

1. Add this repository as a custom repository in HACS.
2. Choose category `Integration`.
3. Install `Jablotron Futura Bridge`.
4. Restart Home Assistant.
5. Go to `Settings -> Devices & Services -> Add Integration`.
6. Search for `Jablotron Futura Bridge`.

## Initial setup

During config flow provide:

- `host`
- `port`
- `unit_id`
- `profile_mode`
- `scan_interval_s`

The integration validates connectivity during setup. In `auto` mode it performs a read-only profile probe and stores the resolved profile for runtime use.

## External sensor bridge

Options flow provides:

- global bridge configuration
- slots `1..8`
- entity mapping for:
  - temperature
  - humidity
  - CO2
  - floor temperature

The bridge writes one contiguous six-register Modbus block per slot and uses invalid bits when a source value is unavailable, stale, non-numeric, or out of range.

## Local development

Local stack is in [dev/homeassistant/README.md](dev/homeassistant/README.md).

Quick start:

```powershell
cd dev/homeassistant
docker compose up --build
```

Then add the integration in Home Assistant with:

- `host`: `futura-modbus-sim`
- `port`: `502`
- `unit_id`: `1`

Simulator status endpoint:

- `http://localhost:18080/status`

Reconnect smoke test for the persistent `T-10 / FR-7 / AC-9` scenario:

```powershell
python dev/homeassistant/reconnect_smoke.py
```

The smoke test expects an already active slot 1 in the local HA stack, restarts
`jablotron-futura-bridge-modbus-sim`, and waits for a fresh post-reconnect write
to reappear in the simulator status payload.

## Notes

- The integration does not replace MyCOMPANY commissioning.
- Analog control via `IN1/IN2` may override the practical effect of CO2/external sensor writes.
- Emergency shutdown may suppress normal runtime behavior independently of Home Assistant.
