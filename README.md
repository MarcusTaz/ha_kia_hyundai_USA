# Kia / Hyundai / Genesis Connect (USA) - Community Maintained

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/v/release/MarcusTaz/ha_kia_hyundai_USA?include_prereleases)](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
[![License](https://img.shields.io/github/license/MarcusTaz/ha_kia_hyundai_USA.svg)](LICENSE)

A Home Assistant integration for **Kia Connect**, **Hyundai BlueLink**, and **Genesis Connected Services** (USA) with multi-brand authentication support. Community-maintained fork with active development after the original repository was archived.

## Features

- **Multi-Brand Support** - Kia, Hyundai, and Genesis vehicles
- **Battery & Charging** - EV battery level, charging status, plugged-in state, AC/DC charge limits
- **Climate Control** - Start/stop HVAC remotely, set temperature, defrost, heated seats
- **Steering Wheel Heat** - Off/Low/High control (for supported vehicles)
- **Door Locks** - Lock/unlock remotely
- **Vehicle Location** - GPS tracking
- **Vehicle Status** - Doors, trunk, hood, tire pressure, odometer, range

## Requirements

- **USA Only** - Vehicles registered in the United States
- **Active Subscription** - Kia Connect, Hyundai BlueLink, or Genesis Connected Services
- **Authentication**:
  - **Kia**: OTP via SMS or Email
  - **Hyundai/Genesis**: 4-digit PIN (same PIN used in the mobile app)

## Installation

### Via HACS (Recommended)

1. Open **HACS** → Click **⋮** (three dots) → **Custom repositories**
2. Add: `https://github.com/MarcusTaz/ha_kia_hyundai_USA`
3. Category: **Integration**
4. Search for **"Kia/Hyundai US"** and install
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from [Releases](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
2. Extract to `/config/custom_components/ha_kia_hyundai/`
3. Restart Home Assistant

## Configuration

### Kia Setup
1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"Kia US"**
3. Select **Kia** as your brand
4. Enter your Kia Connect credentials
5. Choose OTP delivery method (SMS or Email)
6. Enter the OTP code when prompted
7. Your vehicles will be automatically added

### Hyundai / Genesis Setup
1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"Kia US"**
3. Select **Hyundai** or **Genesis** as your brand
4. Enter your BlueLink / Connected Services credentials
5. Enter your 4-digit PIN (same PIN used in the mobile app)
6. Your vehicles will be automatically added

## Beta Testing (v2.1.0-beta2)

New features being tested:

- **Hyundai BlueLink Support** - Full integration with PIN-based authentication
- **Genesis Connected Services Support** - Full integration with PIN-based authentication
- **Steering Wheel Heat Control** - Off/Low/High settings via dropdown selector
- Uses vehicle's `steeringWheelStepLevel` to show correct options per vehicle

**To install beta:**
1. In HACS, find the integration
2. Click **⋮** → **Redownload**
3. Select version **2.1.0-beta2**
4. Restart Home Assistant

**Kia tested on:** EV6, EV9 (2024-2025 models)
**Hyundai/Genesis:** Seeking testers!

## Entities

| Type | Entities |
|------|----------|
| Sensors | Battery (12V & EV), charging status, odometer, range, tire pressure, last update |
| Climate | Temperature control, HVAC on/off |
| Switches | Front defrost, rear defrost, charging |
| Selects | Steering wheel heat, seat heating/cooling (driver, passenger, rear) |
| Locks | Door lock/unlock |
| Buttons | Request vehicle wake-up |
| Numbers | AC/DC charge limits |

## Multiple Vehicles

The integration fully supports multiple vehicles per account. All vehicles linked to your Kia Connect account will be automatically discovered and added.

## Troubleshooting

**Kia OTP not arriving?**
- Verify phone/email is correct in Kia Connect app
- Check spam folder for email OTP
- Codes expire after a few minutes

**Hyundai/Genesis login failing?**
- Verify credentials work in the official mobile app
- Ensure you're using the correct 4-digit PIN
- PIN is case-sensitive (numbers only)

**Vehicle not appearing?**
- Verify vehicle works in official mobile app
- Older infotainment systems may not be compatible
- Check your subscription is active

**Enable debug logging:**
Settings → Devices & Services → Kia US → ⋮ → Enable debug logging

## Why This Fork?

The original [dahlb/ha_kia_hyundai](https://github.com/dahlb/ha_kia_hyundai) and its underlying [kia-hyundai-api](https://github.com/dahlb/kia-hyundai-api) PyPI package were archived in December 2024. 

### How We Fixed It

Rather than depending on the abandoned PyPI package, we **embedded the API code directly** into this integration. This allows us to:
- Make fixes without waiting for PyPI updates
- Incorporate working code from other libraries
- Maintain full control over the API layer

We studied the **[Hyundai-Kia-Connect/hyundai-kia-connect-api](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api)** (EU) library which had working implementations and applied their approaches to fix the USA API:

- **Fixed OTP authentication** - Reliable SMS/Email verification
- **Fixed rate limiting** - All vehicles discovered in single session
- **Steering wheel heat control** - Full Off/Low/High support
- **Seat climate controls** - Heat and ventilation working
- **Improved UI** - Renamed defrost controls for clarity (Front/Rear Defrost), fixed rear defrost icon
- **Active maintenance** - Ongoing bug fixes and community-driven development

The embedded API code lives in `custom_components/ha_kia_hyundai/kia_hyundai_api/`.

## Credits

- **Original Author**: [Bren Dahl (@dahlb)](https://github.com/dahlb)
- **OTP Fix**: mmase
- **Fork Maintainer & Developer**: [MarcusTaz](https://github.com/MarcusTaz) - Revived the abandoned US integration, implemented EU API fixes, added steering wheel heat control, seat climate controls, and ongoing development

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test thoroughly
4. Submit a pull request

## Disclaimer

This integration is not affiliated with Kia, Hyundai, or Genesis Motors. Use at your own risk. Excessive API calls may drain your vehicle's 12V battery.

## Support

- [GitHub Issues](https://github.com/MarcusTaz/ha_kia_hyundai_USA/issues)
- [GitHub Discussions](https://github.com/MarcusTaz/ha_kia_hyundai_USA/discussions)

---

**If this helps you, please ⭐ star the repo!**
