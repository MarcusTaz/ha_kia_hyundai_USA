"""Tests for removing vehicle devices that are no longer on the account."""

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_kia_hyundai import (
    async_remove_config_entry_device,
    async_remove_stale_vehicle_devices,
    async_setup_entry,
)
from custom_components.ha_kia_hyundai.const import (
    BRAND_KIA,
    CONF_BRAND,
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_VEHICLES,
    CONFIG_FLOW_VERSION,
    DOMAIN,
)

ACTIVE_ID = "active-1"
SOLD_ID = "sold-1"


def _stored_vehicle(vehicle_id: str, name: str) -> dict:
    return {
        "id": vehicle_id,
        "name": name,
        "model": "EV6",
        "year": "2024",
        "vin": f"VIN{vehicle_id}",
        "key": f"key-{vehicle_id}",
    }


def _api_vehicle(vehicle_id: str, name: str) -> dict:
    return {
        "vehicleIdentifier": vehicle_id,
        "nickName": name,
        "modelName": "EV6",
        "modelYear": "2024",
        "vin": f"VIN{vehicle_id}",
        "vehicleKey": f"key-{vehicle_id}",
    }


def _account_entry(hass: HomeAssistant, vehicles: list) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BRAND: BRAND_KIA,
            CONF_USERNAME: "owner@example.com",
            CONF_PASSWORD: "secret",
            CONF_DEVICE_ID: "device-1",
            CONF_REFRESH_TOKEN: "refresh-1",
            CONF_VEHICLES: vehicles,
        },
        title="owner@example.com",
        unique_id="kia_owner@example.com",
        version=CONFIG_FLOW_VERSION,
    )
    entry.add_to_hass(hass)
    return entry


def _add_device(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    identifier: tuple[str, str],
    name: str,
) -> dr.DeviceEntry:
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifier},
        name=name,
        manufacturer="Kia",
        model="EV6",
    )


def _add_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    device: dr.DeviceEntry,
    unique_id: str,
    *,
    disabled: bool = False,
) -> er.RegistryEntry:
    kwargs = {}
    if disabled:
        kwargs["disabled_by"] = er.RegistryEntryDisabler.USER
    return er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device.id,
        original_name=unique_id,
        **kwargs,
    )


def _vehicle_ids(entry: MockConfigEntry) -> list[str]:
    return [vehicle["id"] for vehicle in entry.data[CONF_VEHICLES]]


async def test_remove_config_entry_device_only_allows_sold_vehicles(
    hass: HomeAssistant,
) -> None:
    """Delete is offered for a vehicle missing from a non-empty account list."""
    # Stored list is what setup keeps after a successful account refresh.
    entry = _account_entry(hass, [_stored_vehicle(ACTIVE_ID, "Daily")])
    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")
    other = _add_device(hass, entry, ("other", "hub"), "Not a vehicle")

    assert await async_remove_config_entry_device(hass, entry, active) is False
    assert await async_remove_config_entry_device(hass, entry, sold) is True
    assert await async_remove_config_entry_device(hass, entry, other) is False

    empty_entry = _account_entry(hass, [])
    stale = _add_device(hass, empty_entry, (DOMAIN, SOLD_ID), "Sold")
    assert await async_remove_config_entry_device(hass, empty_entry, stale) is False


async def test_stale_cleanup_removes_sold_devices_and_entities(
    hass: HomeAssistant,
) -> None:
    """A sold vehicle's device and entities are removed; the active car stays."""
    entry = _account_entry(
        hass,
        [
            _stored_vehicle(ACTIVE_ID, "Daily"),
            _stored_vehicle(SOLD_ID, "Sold"),
        ],
    )
    other_entry = _account_entry(hass, [_stored_vehicle("elsewhere", "Other account")])

    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")
    unrelated = _add_device(hass, entry, ("other", "hub"), "Not a vehicle")
    other_account = _add_device(hass, other_entry, (DOMAIN, SOLD_ID), "Same id elsewhere")

    active_entity = _add_entity(hass, entry, active, "active-odometer")
    sold_entity = _add_entity(hass, entry, sold, "sold-odometer")
    sold_disabled = _add_entity(
        hass, entry, sold, "sold-range", disabled=True
    )

    async_remove_stale_vehicle_devices(hass, entry, {ACTIVE_ID})
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    assert device_registry.async_get(active.id) is not None
    assert entity_registry.async_get(active_entity.entity_id) is not None
    assert device_registry.async_get(sold.id) is None
    assert entity_registry.async_get(sold_entity.entity_id) is None
    assert entity_registry.async_get(sold_disabled.entity_id) is None
    assert device_registry.async_get(unrelated.id) is not None
    assert device_registry.async_get(other_account.id) is not None


async def test_stale_cleanup_keeps_devices_when_vehicle_list_is_empty(
    hass: HomeAssistant,
) -> None:
    """An empty id set must not wipe every device on the config entry."""
    entry = _account_entry(
        hass,
        [
            _stored_vehicle(ACTIVE_ID, "Daily"),
            _stored_vehicle(SOLD_ID, "Sold"),
        ],
    )
    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")

    async_remove_stale_vehicle_devices(hass, entry, set())
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(active.id) is not None
    assert device_registry.async_get(sold.id) is not None


async def test_stale_cleanup_keeps_vehicles_still_on_the_account(
    hass: HomeAssistant,
) -> None:
    """Devices whose ids are still in the account list are left alone."""
    entry = _account_entry(
        hass,
        [
            _stored_vehicle(ACTIVE_ID, "Daily"),
            _stored_vehicle(SOLD_ID, "Sold"),
        ],
    )
    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")

    async_remove_stale_vehicle_devices(hass, entry, {ACTIVE_ID, SOLD_ID})
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(active.id) is not None
    assert device_registry.async_get(sold.id) is not None


class _FakeApi:
    def __init__(self, vehicles):
        self.vehicles = vehicles
        self.device_id = "device-1"
        self.refresh_token = "refresh-1"
        self.session_id = "session"


class _FakeCoordinator:
    def __init__(self, **kwargs):
        self.vehicle_id = kwargs["vehicle_id"]

    async def async_config_entry_first_refresh(self):
        return None


def _patch_setup(monkeypatch, hass: HomeAssistant, vehicles) -> None:
    async def fake_connection(**_kwargs):
        return _FakeApi(vehicles)

    async def fake_forward(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "custom_components.ha_kia_hyundai._get_or_create_api_connection",
        fake_connection,
    )
    monkeypatch.setattr(
        "custom_components.ha_kia_hyundai.VehicleCoordinator",
        _FakeCoordinator,
    )
    monkeypatch.setattr(
        "custom_components.ha_kia_hyundai.async_setup_services",
        lambda _hass: None,
    )
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", fake_forward)


async def test_setup_entry_removes_vehicles_missing_from_account(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup drops stored vehicles the account no longer returns, and their devices."""
    entry = _account_entry(
        hass,
        [
            _stored_vehicle(ACTIVE_ID, "Daily"),
            _stored_vehicle(SOLD_ID, "Sold"),
        ],
    )
    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")
    sold_entity = _add_entity(hass, entry, sold, "sold-odometer")
    _patch_setup(monkeypatch, hass, [_api_vehicle(ACTIVE_ID, "Daily")])

    assert await async_setup_entry(hass, entry) is True
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert _vehicle_ids(entry) == [ACTIVE_ID]
    assert device_registry.async_get(active.id) is not None
    assert device_registry.async_get(sold.id) is None
    assert er.async_get(hass).async_get(sold_entity.entity_id) is None
    assert await async_remove_config_entry_device(hass, entry, active) is False

    leftover = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold again")
    assert await async_remove_config_entry_device(hass, entry, leftover) is True


@pytest.mark.parametrize("vehicles", [None, []])
async def test_setup_entry_keeps_devices_when_account_listing_is_empty(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, vehicles
) -> None:
    """A missing or empty account listing must not delete vehicles or their devices."""
    stored = [
        _stored_vehicle(ACTIVE_ID, "Daily"),
        _stored_vehicle(SOLD_ID, "Sold"),
    ]
    entry = _account_entry(hass, stored)
    active = _add_device(hass, entry, (DOMAIN, ACTIVE_ID), "Daily")
    sold = _add_device(hass, entry, (DOMAIN, SOLD_ID), "Sold")
    _patch_setup(monkeypatch, hass, vehicles)

    with pytest.raises(ConfigEntryError):
        await async_setup_entry(hass, entry)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert _vehicle_ids(entry) == [ACTIVE_ID, SOLD_ID]
    assert device_registry.async_get(active.id) is not None
    assert device_registry.async_get(sold.id) is not None
