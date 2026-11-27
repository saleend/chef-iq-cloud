"""Explicit hub actions. No cook changes are made automatically."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import entity_registry as er

from . import DOMAIN
from .cook_entity import CookEntity, setup_controls
from .cook_sync import RESOLVED_PHASES


async def async_setup_entry(hass, entry, async_add_entities):
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.platform == DOMAIN
            and entity.domain == "button"
            and entity.unique_id.endswith("_cook_cancel")
        ):
            registry.async_remove(entity.entity_id)
    await setup_controls(
        hass,
        entry,
        async_add_entities,
        lambda m, a: [
            CookButton(m, a, k, label)
            for k, label in [
                ("start", "Start synced cook"),
                ("acknowledge", "Continue current step"),
                ("finish", "End cook"),
                ("reconcile", "Check previous cook start"),
            ]
        ],
    )


class CookButton(CookEntity, ButtonEntity):
    def __init__(self, manager, address, key, label):
        super().__init__(manager, address, key, label, "button")

    @property
    def available(self):
        if not super().available or self.manager.controls_fault:
            return False
        cook = self.manager.cook_for(self.address)
        if self.key == "reconcile":
            return any(
                x.get("phase") not in RESOLVED_PHASES for x in self.manager.cook_journal.values()
            )
        if self.key == "start":
            return cook is None and not any(
                x.get("phase") not in RESOLVED_PHASES for x in self.manager.cook_journal.values()
            )
        if self.key == "acknowledge":
            return bool(
                cook
                and cook.get("state_notification", {}).get("notification_id")
                and cook.get("state_notification", {}).get("is_running") is False
            )
        return cook is not None

    async def async_press(self):
        if self.key == "start":
            await self.manager.start_cook(self.address)
        elif self.key == "reconcile":
            await self.manager.reconcile_starts()
        else:
            await self.manager.cook_action(self.address, self.key)
