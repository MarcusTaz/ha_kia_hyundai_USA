# Kia Connect (USA) - Community Maintained

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/MarcusTaz/ha_kia_hyundai_USA.svg)](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
[![License](https://img.shields.io/github/license/MarcusTaz/ha_kia_hyundai_USA.svg)](LICENSE)

A Home Assistant integration for **Kia Connect (USA)** with **OTP authentication support**. Community-maintained fork with active development after the original repository was archived.

## Features

- **Battery & Charging** - EV battery level, charging status, plugged-in state, AC/DC charge limits
- **Climate Control** - Start/stop HVAC remotely, set temperature, defrost, heated seats
- **Steering Wheel Heat** - Off/Low/High control (for supported vehicles)
- **Door Locks** - Lock/unlock remotely
- **Vehicle Location** - GPS tracking
- **Vehicle Status** - Doors, trunk, hood, tire pressure, odometer, range

## Requirements

- **USA Only** - Kia vehicles registered in the United States
- **Active Kia Connect Subscription** - Required for API access
- **OTP Authentication** - Supports SMS or Email verification

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

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"Kia US"**
3. Enter your Kia Connect credentials
4. Choose OTP delivery method (SMS or Email)
5. Enter the OTP code when prompted
6. Your vehicles will be automatically added

## Beta Testing (v2.1.0-beta1)

New features being tested:

- **Steering Wheel Heat Control** - Off/Low/High settings via dropdown selector
- Uses vehicle's `steeringWheelStepLevel` to show correct options per vehicle

**To install beta:**
1. In HACS, find the integration
2. Click **⋮** → **Redownload**
3. Select version **2.1.0-beta1**
4. Restart Home Assistant

**Tested on:** EV6, EV9 (2024-2025 models)

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

The integration supports multiple vehicles per account. Due to Kia API rate limiting:
- Up to 2 vehicles are added per login session
- Wait 24 hours if you have 3+ vehicles, then log in again to add more
- Older vehicles (pre-ccOS infotainment) may have limited compatibility

## Troubleshooting

**OTP not arriving?**
- Verify phone/email is correct in Kia Connect app
- Check spam folder for email OTP
- Codes expire after a few minutes

**"Please try again later" errors?**
- Kia API rate limit reached - wait 24 hours
- Avoid rapid repeated login attempts

**Vehicle not appearing?**
- Verify vehicle works in official Kia Connect app
- Older infotainment systems may not be compatible
- Check Kia Connect subscription is active

**Enable debug logging:**
Settings → Devices & Services → Kia US → ⋮ → Enable debug logging

## Why This Fork?

The original [dahlb/ha_kia_hyundai](https://github.com/dahlb/ha_kia_hyundai) was archived in December 2024. This fork provides:
- Fixed OTP authentication
- Active bug fixes and maintenance
- New features (steering wheel heat, etc.)

## Credits

- **Original Author**: [Bren Dahl (@dahlb)](https://github.com/dahlb)
- **OTP Fix**: mmase
- **Community Maintainer**: MarcusTaz

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test thoroughly
4. Submit a pull request

## Disclaimer

This integration is not affiliated with Kia Motors. Use at your own risk. Excessive API calls may drain your vehicle's 12V battery.

## Support

- [GitHub Issues](https://github.com/MarcusTaz/ha_kia_hyundai_USA/issues)
- [GitHub Discussions](https://github.com/MarcusTaz/ha_kia_hyundai_USA/discussions)

---

**If this helps you, please ⭐ star the repo!**
