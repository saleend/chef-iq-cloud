"""Name new cooks before sending them to the hub."""

from homeassistant.components.text import TextEntity, TextMode

from .cook_entity import CookEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_controls(hass, entry, async_add_entities, lambda m, a: [CookName(m, a)])


class CookName(CookEntity, TextEntity):
    _attr_native_min = 1
    _attr_native_max = 80
    _attr_mode = TextMode.TEXT

    def __init__(self, manager, address):
        super().__init__(manager, address, "name", "New cook name", "text")

    @property
    def native_value(self):
        return self.manager.settings[self.address]["name"]

    async def async_set_value(self, value):
        self.manager.set_setting(self.address, "name", value)
        self.async_write_ha_state()
