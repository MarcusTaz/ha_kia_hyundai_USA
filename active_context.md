# Active Context: MarcusTaz/ha_kia_hyundai_USA

## Repository
- **GitHub:** https://github.com/MarcusTaz/ha_kia_hyundai_USA
- **Current Version:** v3.1.3
- **Domain:** `ha_kia_hyundai`
- **Home Assistant Min Version:** 2023.1.0

## Current Status
- **Kia:** Fully working (OTP authentication)
- **Hyundai:** Fully working (PIN authentication)
- **Genesis:** Fully working (PIN authentication)
- **HACS Submission:** Pending - validation fixes pushed, need to rerun and resubmit PR

## HACS Submission Status
**Previous PR rejected due to:**
1. Old cached hacs.json with invalid keys (`domains`, `iot_class`, `filename`)
2. Missing `country` key

**Fixes applied (already pushed to main):**
- hacs.json now contains only valid keys:
```json
{
  "name": "Kia/Hyundai/Genesis (USA)",
  "content_in_root": false,
  "render_readme": true,
  "homeassistant": "2023.1.0",
  "country": ["US"]
}
```

**Next steps to complete HACS submission:**
1. Run validation workflow: Actions → Validate → Run workflow
2. Sync fork at https://github.com/MarcusTaz/default
3. Create new branch (not master)
4. Ensure `"MarcusTaz/ha_kia_hyundai_USA",` is alphabetically sorted (after `MarcoGos/kleenex_pollenradar`, before `marcolivierarsenault/moonraker-home-assistant`)
5. Submit PR with description containing 3 links:
   - Repository: https://github.com/MarcusTaz/ha_kia_hyundai_USA
   - Latest Release: https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases/tag/v3.1.2
   - CI Actions: https://github.com/MarcusTaz/ha_kia_hyundai_USA/actions/workflows/validate.yml

## Technical Architecture

### Directory Structure
```
custom_components/ha_kia_hyundai/
├── __init__.py              # Entry point, coordinator setup
├── kia_hyundai_api/         # Embedded API clients
│   ├── __init__.py
│   ├── us_kia.py            # Kia Connect API (OTP auth)
│   ├── us_hyundai.py        # Hyundai BlueLink API (PIN auth)
│   ├── us_genesis.py        # Genesis Connected API (PIN auth)
│   ├── errors.py            # Custom exceptions (AuthError, PINLockedError, TokenExpiredError)
│   └── util_http.py         # HTTP decorators, request handling
├── vehicle_coordinator.py   # DataUpdateCoordinator for vehicle data
├── config_flow.py           # Setup wizard (brand selection, auth)
├── sensor.py                # Sensor entities
├── binary_sensor.py         # Binary sensor entities
├── switch.py                # Switch entities (charging, defrost)
├── climate.py               # Climate entity
├── lock.py                  # Lock entity
├── button.py                # Button entities (remote start/stop)
├── select.py                # Select entities (seat heat/cool, steering wheel)
├── number.py                # Number entities (charge limits)
├── device_tracker.py        # GPS location
├── services.py              # Custom services
├── services.yaml            # Service definitions
├── const.py                 # Constants
├── util.py                  # Utilities
├── manifest.json
├── strings.json
└── translations/en.json
```

### API Client Architecture

#### Authentication Flow
- **Kia (us_kia.py):** Email/password → OTP sent via email/SMS → OTP verification → Session ID
- **Hyundai (us_hyundai.py):** Email/password/PIN → Token with expiration → Proactive refresh
- **Genesis (us_genesis.py):** Email/password/PIN → Token with expiration → Proactive refresh

#### Token Refresh (Hyundai/Genesis)
```python
TOKEN_REFRESH_BUFFER_SECONDS = 300  # Refresh 5 min before expiry

async def _ensure_token_valid(self):
    if not self._is_token_valid():
        await self.login()

def _is_token_valid(self) -> bool:
    if self.token_expires_at is None:
        return False
    return datetime.now(timezone.utc) < self.token_expires_at - timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)
```

#### Data Transformation
Hyundai/Genesis API responses are transformed to match Kia format for coordinator compatibility. Key transformation in `get_cached_vehicle_status()`:
- Vehicle status from `/rcs/rvs/vehicleStatus`
- Vehicle details from `/enrollment/details/{username}`
- Location from `/rcs/rfc/findMyCar`

### Vehicle Coordinator (vehicle_coordinator.py)

#### Key Properties
- `is_ev` - True if evStatus exists in data (used to hide EV entities for ICE vehicles)
- `ev_battery_level` - EV battery percentage
- `can_remote_climate` - True if vehicle supports remote start
- `front_seat_options` / `rear_seat_options` - Seat heat/cool capabilities from API
- `has_climate_seats` - True if any seat has heat/cool

#### Desired Climate Settings (stored in coordinator)
```python
climate_desired_defrost: bool = False
climate_desired_heating_acc: bool = False
desired_temperature: int = 72
desired_steering_wheel_heat: int = 0  # 0=off, 1=low, 2=high
desired_driver_seat_comfort: SeatSettings | None = None
desired_passenger_seat_comfort: SeatSettings | None = None
desired_left_rear_seat_comfort: SeatSettings | None = None
desired_right_rear_seat_comfort: SeatSettings | None = None
```

### Entity Creation Logic

#### EV Entity Gating (sensor.py, switch.py)
```python
# sensor.py - EV sensors only created if is_ev=True
KiaSensorEntityDescription(
    key="ev_battery_level",
    exists_fn=lambda c: c.is_ev,
    ...
)

# switch.py - Charging switch only for EVs
if coordinator.is_ev:
    switches.append(ChargingSwitch(coordinator=coordinator))
```

#### Seat Entity Gating
Rear seats only created if API reports they exist:
```python
exists_fn=lambda seat: bool(seat.rear_seat_options.get(HEAT_VENT_TYPE, 0))
```

### Services (services.py, services.yaml)

#### start_climate Service
```yaml
start_climate:
  fields:
    duration:
      required: false
      selector:
        number:
          min: 1
          max: 60
          unit_of_measurement: minutes
```

**Duration parameter behavior:**
- If provided: Passed to API
- If not provided: API uses vehicle's stored "Custom Climate" setting
- **Kia EV limitation:** Duration and temperature are ignored by Kia EV API; uses Custom Climate settings from official Kia app

### Known Limitations

#### Kia EV Climate Control
- **What works:** Starting/stopping climate, seat heat/cool, steering wheel heat
- **What doesn't work:** Temperature and duration (controlled by official Kia app's "Custom Climate" profile)
- Documented in README under "Known Limitations"

### Release Management
- **One visible release:** Only latest version visible in HACS
- **Archived releases:** Previous versions kept as drafts for rollback
- Current releases:
  - v3.1.2 (Latest, visible)
  - v3.1.1, v3.1.0, v3.0.0 (Drafts, archived)

### GitHub Actions (.github/workflows/validate.yml)
```yaml
jobs:
  hassfest:
    uses: "home-assistant/actions/hassfest@master"
  hacs:
    uses: "hacs/action@main"
    with:
      category: "integration"
```

## User Preferences
- ALWAYS discuss before making code changes
- No unnecessary branches or betas
- Keep one release visible in HACS dropdown
- No emojis in code or communication
- Minimize token usage

## Files Modified in Recent Sessions
1. `hacs.json` - Removed invalid keys, added `country`
2. `manifest.json` - Version bumps
3. `vehicle_coordinator.py` - Added `is_ev` property
4. `sensor.py` - Added `exists_fn` for EV sensors
5. `switch.py` - Added `is_ev` check for ChargingSwitch
6. `us_hyundai.py` / `us_genesis.py` - Token refresh logic
7. `us_kia.py` - Duration parameter (removed hardcoded value)
8. `services.py` / `services.yaml` - Duration parameter for climate service

## Immediate Next Actions
1. User runs validation workflow on repo
2. User syncs fork of hacs/default
3. User creates new branch and submits HACS PR
4. Wait for HACS maintainer review
