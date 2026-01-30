# Kia/Hyundai/Genesis (USA) - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/MarcusTaz/ha_kia_hyundai_USA.svg)](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
[![License](https://img.shields.io/github/license/MarcusTaz/ha_kia_hyundai_USA.svg)](LICENSE)

A Home Assistant integration for **Kia, Hyundai, and Genesis vehicles registered in the United States**. This is a community-maintained fork with active development.

## Requirements

- **USA Only** - Vehicles must be registered in the United States
- **Active Subscription** - Kia Connect, Hyundai Blue Link, or Genesis Connected Services
- **Home Assistant** - Version 2023.1.0 or newer
- **HACS** - For easy installation (recommended)

## Features

- Remote lock/unlock
- Remote climate start/stop
- Climate temperature control
- Steering wheel heat control
- Seat heating and cooling
- Vehicle location tracking
- Battery and charging status (EV/hybrid)
- Charge limit control (AC/DC)
- Door, trunk, and hood status
- Tire pressure warnings
- Odometer and range
- 12V battery level

## Installation

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu in the top right
3. Select "Custom repositories"
4. Add: `https://github.com/MarcusTaz/ha_kia_hyundai_USA`
5. Category: Integration
6. Click "Add"
7. Search for "Kia/Hyundai/Genesis (USA)" and install
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from [Releases](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
2. Extract to `/config/custom_components/ha_kia_hyundai/`
3. Restart Home Assistant

## Configuration

### Step 1: Add the Integration

1. Go to Settings > Devices & Services
2. Click "+ Add Integration"
3. Search for "Kia/Hyundai/Genesis (USA)"
4. Select your vehicle brand (Kia, Hyundai, or Genesis)

### Step 2: Authentication (Brand-Specific)

**Kia Vehicles:**
- Enter your Kia Connect email and password
- Select OTP delivery method (Email or SMS)
- Enter the OTP code sent to your email or phone
- Your vehicles will be discovered automatically

**Hyundai Vehicles:**
- Enter your Hyundai Blue Link email and password
- Enter your 4-digit PIN (the same PIN you use in the Blue Link app)
- Your vehicles will be discovered automatically

**Genesis Vehicles:**
- Enter your Genesis Connected Services email and password
- Enter your 4-digit PIN (the same PIN you use in the Genesis app)
- Your vehicles will be discovered automatically

### Step 3: Confirm Vehicles

After authentication, the integration will display all vehicles found in your account. Confirm to add them to Home Assistant.

## Entities Created

### Sensors
- Battery level (12V)
- EV battery level (if applicable)
- Charging status
- Plugged in status
- Odometer
- Estimated range
- Last update timestamp
- Tire pressure warnings
- Low fuel warning

### Controls
- Door lock (lock/unlock)
- Climate control (on/off, temperature)
- Charging switch (start/stop when plugged in)
- AC/DC charge limits
- Seat heating/cooling selectors
- Steering wheel heat selector
- Defrost switches

### Buttons
- Remote Start (starts vehicle with configured climate settings)
- Remote Stop (stops remote-started vehicle)
- Force Update (requests fresh data from vehicle - use sparingly)

## Important Warnings

### Rate Limiting

The vehicle APIs have rate limits to prevent excessive requests. Making too many API calls in a short period can temporarily block your access.

**Symptoms of rate limiting:**
- "Please try again later" errors
- Failed commands or status updates
- Temporary inability to control vehicle

**Prevention:**
- Avoid rapidly pressing buttons or refreshing
- Use the Force Update button sparingly
- If blocked, wait before trying again (timeout varies by brand, up to 3 hours for some)

### Battery Drain

Frequent API calls can wake your vehicle and drain the 12V battery. The default 10-minute polling interval is designed to minimize this impact. Avoid excessive use of the Force Update button.

## Troubleshooting

### Authentication Failed

**Kia:**
- Verify your Kia Connect credentials work in the official app
- Check your email/phone for the OTP code
- OTP codes expire after a few minutes

**Hyundai/Genesis:**
- Verify your credentials work in the official Blue Link or Genesis app
- Ensure your PIN is exactly 4 digits
- The PIN is the same one you use in the official app

### Vehicle Not Found

- Verify the vehicle appears in your official app (Kia Connect, Blue Link, or Genesis)
- Ensure your connected services subscription is active
- Some older vehicles with pre-ccOS infotainment may not be compatible

### Commands Not Working

- Check that the vehicle has cellular connectivity
- Wait a few minutes and try again (rate limiting may be active)
- Verify the feature works in the official app

### Enable Debug Logging

1. Go to Settings > Devices & Services
2. Find the integration and click the three dots menu
3. Click "Enable debug logging"
4. Reproduce the issue
5. Go to Settings > System > Logs
6. Look for entries mentioning `ha_kia_hyundai`

## Known Limitations

### Kia EV Climate Control

For Kia electric vehicles (EV6, EV9, etc.), the remote climate API has the following behavior:

**What works from Home Assistant:**
- Starting/stopping climate
- Seat heating and cooling settings
- Steering wheel heat settings

**What must be set in the official Kia app:**
- Climate duration (how long climate runs)
- Target temperature

This is a Kia API limitation. The vehicle uses your "Custom Climate" profile settings stored in the official Kia Connect app for duration and temperature. To change these values, update your Custom Climate settings in the Kia app.

**Workaround:** Set your preferred duration and temperature in the Kia Connect app's Custom Climate section. Home Assistant can then trigger climate start, and the vehicle will use your stored preferences.

## Update Frequency

- **Default polling**: Every 10 minutes (configurable in integration options)
- **After commands**: Automatic refresh after lock/unlock, climate start/stop

## Vehicle Compatibility

**Supported:**
- Kia vehicles with Kia Connect (USA)
- Hyundai vehicles with Blue Link (USA)
- Genesis vehicles with Genesis Connected Services (USA)
- Most 2020+ model year vehicles

**Limited Support:**
- Older vehicles with pre-ccOS infotainment systems may have reduced functionality

**Not Supported:**
- Vehicles outside the USA (use [kia_uvo](https://github.com/Hyundai-Kia-Connect/kia_uvo) for other regions)
- Vehicles without active connected services subscriptions

## Why This Fork Exists

The original [dahlb/ha_kia_hyundai](https://github.com/dahlb/ha_kia_hyundai) repository was archived in December 2024. This fork continues development with:

- Fixed authentication for all three brands
- Embedded API libraries (no external dependencies)
- Active maintenance and bug fixes
- Multi-brand support in a single integration

## Credits

- **Original Author**: [Bren Dahl (@dahlb)](https://github.com/dahlb)
- **Community Maintainer**: [MarcusTaz](https://github.com/MarcusTaz)
- **Contributors**: mmase, and the Hyundai-Kia-Connect community

## Contributing

Contributions are welcome:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file

## Disclaimer

This integration is not affiliated with, endorsed by, or connected to Kia Motors, Hyundai Motor Company, or Genesis Motor. Use at your own risk.

## Support

- [GitHub Issues](https://github.com/MarcusTaz/ha_kia_hyundai_USA/issues)
- [GitHub Discussions](https://github.com/MarcusTaz/ha_kia_hyundai_USA/discussions)
