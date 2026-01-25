# Kia Hyundai Genesis (USA) - Community Maintained

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/MarcusTaz/ha_kia_hyundai_USA.svg)](https://github.com/MarcusTaz/ha_kia_hyundai_USA/releases)
[![License](https://img.shields.io/github/license/MarcusTaz/ha_kia_hyundai_USA.svg)](LICENSE)

A Home Assistant integration for **Kia, Hyundai, and Genesis vehicles (USA)** with full authentication support. This is a community-maintained fork that fixes critical issues after the original repository was archived.

## 🚗 What This Integration Does

Connect your USA Kia, Hyundai, or Genesis vehicle to Home Assistant and control:
- 🔋 Battery level & charging status
- 🌡️ Climate control (start/stop HVAC remotely)
- 🔒 Door locks (lock/unlock)
- 📍 Vehicle location
- ⚡ Charge limits (AC/DC)
- 🚪 Door, trunk, and hood status
- 🔧 Tire pressure warnings
- 📊 Odometer & range
- 🔌 Charging switch (start/stop charging when plugged in)

## ⚠️ Important Notes

- **USA ONLY** - This integration only works with vehicles registered in the United States
- **Active Subscription Required** - Your vehicle must have an active Kia Connect, Hyundai Blue Link, or Genesis Connected Services subscription

## 🔧 Why This Fork Exists

The original [dahlb/ha_kia_hyundai](https://github.com/dahlb/ha_kia_hyundai) repository was **archived in December 2024** due to API challenges. However, the community still needs this integration!

**This fork provides:**
- ✅ **Fixed authentication** (works with current APIs)
- ✅ **Bug fixes** for config flow errors
- ✅ **Active maintenance** for the community
- ✅ **Embedded API** (no external dependencies)
- ✅ **Multi-brand support** (Kia, Hyundai, Genesis)

## 📦 Installation

### Via HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click the **three dots** (⋮) in the top right
3. Select **"Custom repositories"**
4. Add this repository URL: `https://github.com/MarcusTaz/ha_kia_hyundai_USA`
5. Category: **Integration**
6. Click **"Add"**
7. Search for **"Kia Hyundai Genesis (USA)"** and install
8. **Restart Home Assistant**

### Manual Installation

1. Download the latest release
2. Extract to `/config/custom_components/ha_kia_hyundai/`
3. Restart Home Assistant

## ⚙️ Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"Kia Hyundai Genesis (USA)"**
4. Enter your **account username and password** (Kia Connect, Hyundai Blue Link, or Genesis Connected Services)
5. Choose **OTP delivery method** (SMS or Email)
6. Enter the **OTP code** when prompted
7. Your vehicle(s) will be automatically added!

### Multiple Vehicles

**Current Behavior:** The integration will automatically detect and add up to 2 vehicles per login session. If you have 3 or more vehicles:
- First 2 vehicles will be added successfully on initial login
- Additional vehicles can be added after the API rate limit clears (wait time varies, but 24 hours is a safe estimate)
- Simply log in again after waiting to add remaining vehicles

**Known Limitation:** Vehicles with older infotainment systems (pre-ccOS) may not be detected during the initial vehicle discovery. This is a compatibility issue with the underlying API, not a rate limiting issue. If you have a mix of newer and older vehicles:
- Newer vehicles (with ccOS) will typically be detected first
- Older vehicles may not appear in the available vehicle list at all
- Currently investigating solutions for better older vehicle support

## 🔄 Update Frequency

- **Cached data fetch**: Every 10 minutes (configurable)
- **Force update**: Not recommended frequently to avoid draining 12V battery

## 🎛️ Services

### Climate Control
- `climate.set_temperature` - Set target temperature
- `climate.turn_on` - Start climate (uses preset defrost/heating settings)
- `climate.turn_off` - Stop climate

### Charging
- `switch.turn_on` / `switch.turn_off` - Start/stop charging (when plugged in)
- `number.set_value` - Set AC/DC charge limits

### Vehicle Actions
- `lock.lock` / `lock.unlock` - Lock/unlock doors
- `button.press` - Request vehicle status update (use sparingly!)

## 🛠 Troubleshooting

### Authentication Issues
- Make sure you select the correct OTP method (SMS or Email)
- Check your phone/email for the code
- Code expires after a few minutes - request a new one if needed

### Rate Limiting
If you see "Please try again later" errors:
- The API has rate limits to prevent excessive requests
- Wait 24 hours before attempting to add additional vehicles
- Avoid making multiple login attempts in quick succession

### Multiple Vehicles Not Appearing
**If only 2 of your 3+ vehicles were added:**
- This is due to API rate limiting (max 2 vehicles per session)
- Wait for the rate limit to clear (wait time varies, but 24 hours is a safe estimate), then log in again
- Each login session can add up to 2 vehicles

**If a specific vehicle never appears in the list:**
- May be due to older infotainment system (pre-ccOS) incompatibility
- Verify the vehicle has an active subscription
- Check if the vehicle appears in the official app
- If it works in the official app but not here, this may be an API limitation

### Enable Debug Logging

1. Go to **Settings** → **Devices & Services**
2. Find the integration
3. Click the **three dots** (⋮) on the integration card
4. Click **"Enable debug logging"**
5. Reproduce the issue
6. Go to **Settings** → **System** → **Logs**
7. Look for entries mentioning `ha_kia_hyundai`
8. Click the three dots again and **"Disable debug logging"** to download logs

## 📝 Supported Entities

### Sensors
- Battery level (12V)
- EV battery level
- Charging status
- Plugged in status
- Odometer
- EV range
- Last update timestamp
- Tire pressure warnings
- Door/trunk/hood status
- Low fuel warning

### Controls
- Door locks
- Climate control
- Charging switch
- Charge limit numbers (AC/DC)
- Heated steering wheel (if supported)
- Heated rear window (if supported)
- Defrost/heating acc switches

### Buttons
- Force update (requests fresh data from vehicle)

## 🚗 Vehicle Compatibility

**Fully Supported (Newer ccOS-equipped vehicles):**
- Most 2024+ Kia, Hyundai, and Genesis models with newer infotainment systems
- Vehicles with ccOS (Connected Car Operating System)

**Limited Support:**
- Some older model year vehicles may not appear during setup
- Vehicles with pre-ccOS infotainment systems may have reduced features or detection issues

**Not Supported:**
- Non-USA vehicles (use [kia_uvo](https://github.com/Hyundai-Kia-Connect/kia_uvo) for other regions)
- Vehicles without active subscriptions

## ⚖️ License

MIT License - see [LICENSE](LICENSE) file

## 🙏 Credits

- **Original Author**: [Bren Dahl (@dahlb)](https://github.com/dahlb) - Thank you for creating this integration!
- **Community Maintainer**: MarcusTaz - Keeping it alive for the community
- **Special Thanks**: mmase, Cursor AI, and the Hyundai-Kia-Connect community

## 🤝 Contributing

This is a community-maintained project! Contributions are welcome:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 💡 Known Issues & Limitations

- **Multi-vehicle limit**: Only 2 vehicles added per login session due to API rate limiting
- **Older vehicles**: Pre-ccOS vehicles (older infotainment systems) may not be detected
- **Rate limit wait**: After adding 2 vehicles, must wait for rate limit to clear (typically within 24 hours) to add additional vehicles
- **Feature differences**: Older vehicles show fewer entities (e.g., no seat temperature control)

## ⚠️ Disclaimer

This integration is not affiliated with, endorsed by, or connected to Kia Motors, Hyundai Motor Company, or Genesis Motor. Use at your own risk. Excessive API calls may drain your vehicle's 12V battery.

## 🔧 Support

- **Issues**: [GitHub Issues](https://github.com/MarcusTaz/ha_kia_hyundai_USA/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MarcusTaz/ha_kia_hyundai_USA/discussions)

---

**If this integration helps you, please ⭐ star the repo to show support!**

## 🔮 Future Improvements

We're actively investigating:
- Better multi-vehicle support
- Compatibility with older vehicle models
- Enhanced rate limit handling
- Automatic retry logic for failed additions

Stay tuned for updates!
