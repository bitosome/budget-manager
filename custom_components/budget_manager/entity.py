"""Shared entity base for Budget Manager."""

from __future__ import annotations

from datetime import datetime

from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN, NAME
from .manager import BudgetManager


class BudgetEntity(Entity):
    """Base entity backed by the local budget manager."""

    _attr_has_entity_name = True

    def __init__(self, manager: BudgetManager, key: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry_id)},
            name=NAME,
            manufacturer="Local",
            model=NAME,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.add_listener(self._handle_manager_update))
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_day_change,
                hour=0,
                minute=0,
                second=0,
            )
        )

    def _handle_day_change(self, _now: datetime) -> None:
        """Refresh date-dependent values at the local midnight boundary."""
        self.async_write_ha_state()

    def _handle_manager_update(self) -> None:
        """Refresh the entity from in-memory state."""
        self.async_write_ha_state()
