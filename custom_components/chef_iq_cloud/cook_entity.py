"""Shared discovery and device metadata for cook controls."""

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from . import DOMAIN


async def setup_controls(hass, entry, add, factory):
    manager = hass.data[DOMAIN][entry.entry_id]
    known = set()

    @callback
    def discover():
        entities = []
        for address in manager.probes:
            if address not in known:
                known.add(address)
                entities.extend(factory(manager, address))
        if entities:
            add(entities)

    entry.async_on_unload(async_dispatcher_connect(hass, manager.signal, discover))
    discover()


class CookEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager, address, key, label, domain):
        self.manager = manager
        self.address = address
        self.key = key
        n = manager.probes[address].get("number", address[-5:])
        self._attr_unique_id = address + "_cook_" + key
        self._attr_name = label
        self.entity_id = f"{domain}.chef_iq_probe_{n}_cook_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "connections": {("bluetooth", address)},
            "manufacturer": "CHEF iQ",
            "model": "CQ60",
            "name": f"Probe {n}",
        }
        manager.settings.setdefault(
            address,
            {
                "name": "Home Assistant cook",
                "target": 165,
                "flip": 0,
                "wrap": 0,
                "rest": 0,
            },
        )

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.manager.signal, self.async_write_ha_state)
        )

    @property
    def available(self):
        return self.manager.connected
