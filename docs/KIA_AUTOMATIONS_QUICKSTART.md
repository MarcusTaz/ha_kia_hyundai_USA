# KIA Vehicle Automations Quick Start Guide

This guide helps you set up Home Assistant automations for your KIA vehicles (EV9, EV6 EMMA, EV6 Ava) using the `ha_kia_hyundai` integration.

## Step 1: Find Your Entity IDs

Your actual entity IDs depend on how you named your vehicles during setup. Here's how to find them:

### Method 1: Developer Tools
1. Go to **Settings** → **Devices & Services** → **ha_kia_hyundai**
2. Click on each vehicle device to see all its entities
3. Note the entity IDs (e.g., `sensor.ev9_ev_battery`)

### Method 2: States Page
1. Go to **Developer Tools** → **States**
2. Filter by typing your vehicle name (e.g., "ev9", "emma", "ava")

### Expected Entity Pattern
Based on vehicle names, your entities should follow this pattern:

| Vehicle | Example Entity IDs |
|---------|-------------------|
| EV9 | `sensor.ev9_ev_battery`, `lock.ev9_door_lock`, `device_tracker.ev9_location` |
| EV6 EMMA | `sensor.ev6_emma_ev_battery`, `lock.ev6_emma_door_lock`, `device_tracker.ev6_emma_location` |
| EV6 Ava | `sensor.ev6_ava_ev_battery`, `lock.ev6_ava_door_lock`, `device_tracker.ev6_ava_location` |

## Step 2: Find Your Device IDs (for Services)

The `ha_kia_hyundai.start_climate` and `ha_kia_hyundai.set_charge_limits` services require a `device_id`.

1. Go to **Developer Tools** → **Services**
2. Select `ha_kia_hyundai.start_climate`
3. Click the device picker and select your vehicle
4. Click **"Go to YAML mode"**
5. Copy the `device_id` value shown

## Step 3: Create Helper Entities

Add these to your Home Assistant for the automations to work:

### Via UI (Settings → Devices & Services → Helpers)

**Toggle Helpers:**
- `input_boolean.road_trip_mode` - Enable 100% charge limit for trips
- `input_boolean.ev9_defrost` - Defrost setting for EV9
- `input_boolean.ev9_heating` - Heated steering for EV9

**Number Helpers:**
- `input_number.ev9_climate_temp` - Target climate temp (62-82°F)

**Button Helpers:**
- `input_button.precondition_ev9` - Manual pre-condition trigger

### Via configuration.yaml

```yaml
input_boolean:
  road_trip_mode:
    name: Road Trip Mode
    icon: mdi:car-sports
  ev9_defrost:
    name: EV9 Defrost Enabled
    icon: mdi:car-defrost-front

input_number:
  ev9_climate_temp:
    name: EV9 Climate Temperature
    min: 62
    max: 82
    step: 1
    unit_of_measurement: "°F"

input_button:
  precondition_ev9:
    name: Pre-Condition EV9
    icon: mdi:car-electric
```

## Step 4: Define Zones

Create zones for geofencing automations:

1. Go to **Settings** → **Areas & Zones** → **Zones**
2. Add zones for:
   - Home (if not already defined)
   - Work
   - School (if applicable)

## Quick Copy-Paste Automations

### Auto-Lock at Night

```yaml
alias: "All Vehicles - Auto Lock at Night"
trigger:
  - platform: time
    at: "23:00:00"
action:
  - service: lock.lock
    target:
      entity_id:
        - lock.ev9_door_lock
        - lock.ev6_emma_door_lock
        - lock.ev6_ava_door_lock
```

### Low Battery Alert

```yaml
alias: "EV9 - Low Battery Alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.ev9_ev_battery
    below: 20
condition:
  - condition: state
    entity_id: binary_sensor.ev9_ev_battery_charging
    state: "off"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "EV9 Low Battery!"
      message: "Battery at {{ states('sensor.ev9_ev_battery') }}%"
```

### Morning Pre-Condition (Weekdays)

```yaml
alias: "EV9 - Morning Pre-Condition"
trigger:
  - platform: time
    at: "07:00:00"
condition:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
  - condition: zone
    entity_id: device_tracker.ev9_location
    zone: zone.home
  - condition: numeric_state
    entity_id: sensor.ev9_ev_battery
    above: 30
action:
  - service: ha_kia_hyundai.start_climate
    data:
      device_id: YOUR_DEVICE_ID_HERE
      climate: true
      temperature: 72
      defrost: false
      heating: true
      driver_seat: "Medium Heat"
```

### Off-Peak Charging

```yaml
alias: "EV9 - Off-Peak Charging"
trigger:
  - platform: time
    at: "00:00:00"
condition:
  - condition: state
    entity_id: binary_sensor.ev9_ev_plugged_in
    state: "on"
  - condition: numeric_state
    entity_id: sensor.ev9_ev_battery
    below: 80
action:
  - service: switch.turn_on
    target:
      entity_id: switch.ev9_ev_battery_charging
```

### Geofence - Arriving Home

```yaml
alias: "EV9 - Arriving Home"
trigger:
  - platform: zone
    entity_id: device_tracker.ev9_location
    zone: zone.home
    event: enter
action:
  - service: cover.open_cover
    target:
      entity_id: cover.garage_door
```

## Available Entities Reference

### Sensors
| Entity Key | Description |
|------------|-------------|
| `ev_battery` | EV Battery percentage |
| `ev_remaining_range_value` | Estimated range in miles |
| `car_battery_level` | 12V battery percentage |
| `odometer` | Total miles |
| `ev_charge_current_remaining_duration` | Minutes to full charge |
| `climate_temperature_value` | Set climate temperature |

### Binary Sensors
| Entity Key | Description |
|------------|-------------|
| `locked` | Doors locked state |
| `ev_battery_charging` | Currently charging |
| `ev_plugged_in` | Charger connected |
| `engine_on` | Engine/motor running |
| `climate_hvac_on` | Climate active |
| `door_*_open` | Door states |
| `tire_all_on` | Tire pressure warning |

### Controls
| Entity | Action |
|--------|--------|
| `lock.{vehicle}_door_lock` | Lock/unlock vehicle |
| `switch.{vehicle}_ev_battery_charging` | Start/stop charging |
| `climate.{vehicle}_climate` | Climate control |
| `switch.{vehicle}_climate_desired_defrost` | Defrost toggle |
| `switch.{vehicle}_climate_desired_heating_acc` | Heated steering toggle |

### Services
| Service | Description |
|---------|-------------|
| `ha_kia_hyundai.start_climate` | Start climate with options |
| `ha_kia_hyundai.set_charge_limits` | Set AC/DC charge limits |

## Tips

1. **Avoid over-polling**: The integration syncs every 10 minutes by default. Don't add automations that constantly request updates - this drains the 12V battery.

2. **Use conditions**: Always add battery level conditions before starting climate (requires energy).

3. **Zone accuracy**: GPS location updates may be delayed. Use zone radius of 150-300m for reliability.

4. **Test in Developer Tools**: Test service calls in Developer Tools → Services before creating automations.

5. **Check logs**: If automations don't work, check **Settings** → **System** → **Logs** for errors.

## Full Examples

See `kia_vehicle_automations.yaml` in this folder for comprehensive automation examples including:
- Auto-lock scenarios
- Climate pre-conditioning (weather-based)
- Charging schedules (off-peak, staggered)
- Geofencing (home arrival, work departure)
- Maintenance alerts (12V battery, tire pressure)
- Multi-vehicle coordination
