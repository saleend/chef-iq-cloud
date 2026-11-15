"""Cook targets and optional step settings, in Fahrenheit and minutes."""

from homeassistant.components.number import NumberEntity, NumberMode

from .cook_entity import CookEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_controls(
        hass,
        entry,
        async_add_entities,
        lambda m, a: [
            CookNumber(m, a, k, label)
            for k, label in [
                ("target", "Cook target"),
                ("flip", "Flip at (0 disables)"),
                ("wrap", "Wrap at (0 disables)"),
                ("rest", "Rest minutes (0 disables)"),
            ]
        ],
    )


class CookNumber(CookEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, manager, address, key, label):
        super().__init__(manager, address, key, label, "number")
        self._attr_native_min_value = 32 if key == "target" else 0
        self._attr_native_max_value = 240 if key == "rest" else 212
        self._attr_native_unit_of_measurement = "min" if key == "rest" else "°F"

    @property
    def native_value(self):
        return self.manager.settings[self.address][self.key]

    async def async_set_native_value(self, value):
        self.manager.set_setting(self.address, self.key, value)
        self.async_write_ha_state()
