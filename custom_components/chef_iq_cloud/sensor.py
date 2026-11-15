"""Wi-Fi and combined sensors; original Bluetooth entities stay intact."""

import time
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import DOMAIN
from .selection import choose, number

METRICS = {"food_temperature": "internal_temp", "ambient_temperature": "ambient_temp"}


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data[DOMAIN][entry.entry_id]
    known = set()

    @callback
    def discover():
        new = []
        for address, p in manager.probes.items():
            if address in known:
                continue
            known.add(address)
            new.append(CookSensor(manager, address))
            for metric in METRICS:
                for mode in ("wifi", "combined"):
                    new.append(ProbeSensor(manager, address, metric, mode))
        if new:
            async_add_entities(new)

    entry.async_on_unload(async_dispatcher_connect(hass, manager.signal, discover))
    discover()


class ProbeSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, manager, address, metric, mode):
        self.manager = manager
        self.address = address
        self.metric = metric
        self.mode = mode
        p = manager.probes[address]
        n = p.get("number", address[-5:])
        self._ble_id = None
        self._attr_unique_id = address + "_" + metric + "_" + mode
        self._attr_name = (
            ("Food temperature" if metric == "food_temperature" else "Ambient temperature")
            + " ("
            + mode
            + ")"
        )
        self.entity_id = f"sensor.chef_iq_probe_{n}_{metric}_{mode}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "connections": {("bluetooth", address)},
            "manufacturer": "CHEF iQ",
            "model": "CQ60",
            "name": f"Probe {n}",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.manager.signal, self.async_write_ha_state)
        )

    def ble_entity(self):
        registry = er.async_get(self.hass)
        if self._ble_id:
            entity = registry.async_get(self._ble_id)
            if entity and entity.platform == "chef_iq":
                return self._ble_id
            self._ble_id = None
        devices = dr.async_get(self.hass).async_get_devices(
            connections={("bluetooth", self.address)}
        )
        for device in devices:
            for entity in er.async_entries_for_device(registry, device.id):
                if (
                    entity.platform == "chef_iq"
                    and entity.domain == "sensor"
                    and (
                        entity.entity_id.endswith("_" + self.metric)
                        or entity.unique_id.endswith("_" + self.metric)
                        or entity.unique_id.endswith("-" + self.metric)
                    )
                ):
                    self._ble_id = entity.entity_id
                    return self._ble_id
        # Deterministic fallback remains restricted to the official BLE integration.
        suffix = self.address.replace(":", "")[-4:].lower()
        entity_id = f"sensor.cq60_{suffix}_{self.metric}"
        entity = registry.async_get(entity_id)
        if entity and entity.platform == "chef_iq":
            self._ble_id = entity_id
            return entity_id
        return None

    def candidates(self):
        p = self.manager.probes[self.address]
        c = []
        v = number(p.get(METRICS[self.metric]))
        if p.get("is_active") and not p.get("is_sensor_fail") and v is not None:
            c.append(
                {
                    "value": v,
                    "unit": "°F",
                    "timestamp": p["sample_timestamp"],
                    "source": "wifi",
                }
            )
        entity_id = self.ble_entity()
        state = self.hass.states.get(entity_id) if entity_id else None
        if state:
            t = getattr(state, "last_reported", state.last_updated).timestamp()
            c.append(
                {
                    "value": state.state,
                    "unit": state.attributes.get("unit_of_measurement"),
                    "timestamp": t,
                    "source": "bluetooth",
                }
            )
        return c

    def selected(self):
        return choose(
            [c for c in self.candidates() if self.mode == "combined" or c["source"] == "wifi"],
            time.time(),
        )

    @property
    def available(self):
        return self.selected() is not None

    @property
    def native_value(self):
        selected = self.selected()
        return selected["value"] if selected else None

    @property
    def extra_state_attributes(self):
        selected = self.selected()
        p = self.manager.probes[self.address]
        attrs = {
            "selected_source": selected["source"] if selected else None,
            "sample_timestamp": iso(selected["timestamp"]) if selected else None,
            "bluetooth_entity": self.ble_entity(),
            "wifi_connected": self.manager.connected,
            "max_age_seconds": 180,
            "probe_number": p.get("number"),
            "wifi_timestamp_basis": "probe_measurement",
            "bluetooth_timestamp_basis": "home_assistant_last_reported",
        }
        for c in self.candidates():
            attrs[c["source"] + "_timestamp"] = iso(c["timestamp"])
            attrs[c["source"] + "_raw_value"] = c["value"]
            attrs[c["source"] + "_raw_unit"] = c["unit"]
        return attrs


class CookSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:chef-hat"

    def __init__(self, manager, address):
        self.manager = manager
        self.address = address
        n = manager.probes[address].get("number", address[-5:])
        self._attr_unique_id = address + "_cook"
        self._attr_name = "Active cook"
        self.entity_id = f"sensor.chef_iq_probe_{n}_cook"
        self._attr_device_info = {"identifiers": {(DOMAIN, address)}}

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.manager.signal, self.async_write_ha_state)
        )

    @property
    def available(self):
        return self.manager.connected

    @property
    def native_value(self):
        cook = self.manager.cook_for(self.address)
        return cook.get("name", "Cooking") if cook else "Idle"

    @property
    def extra_state_attributes(self):
        from .cooks import current_step_status, public_cook

        cook = self.manager.cook_for(self.address)
        if not cook:
            return {"active": False}
        attrs = public_cook(cook)
        attrs["active"] = True
        attrs["temperature_unit"] = "°F"
        attrs.update(current_step_status(cook))
        attrs["updated_at"] = iso(cook.get("updated_at"))
        return attrs
