"""Manual account balance control for Budget Manager."""

from __future__ import annotations

from decimal import Decimal

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import BudgetEntity
from .manager import BudgetManager

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the manual balance number."""
    manager: BudgetManager = hass.data[DOMAIN]["entries"][entry.entry_id]
    async_add_entities([BudgetBalanceNumber(manager)])


class BudgetBalanceNumber(BudgetEntity, NumberEntity):
    """Writable account balance for the current budget month."""

    _attr_translation_key = "account_balance"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1_000_000_000.0
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = "EUR"
    _attr_mode = NumberMode.BOX

    def __init__(self, manager: BudgetManager) -> None:
        super().__init__(manager, "account_balance")

    @property
    def native_value(self) -> float | None:
        """Return the manually maintained current balance."""
        month = self.manager.current_month()
        return float(month.get("account_balance", 0)) if month else None

    async def async_set_native_value(self, value: float) -> None:
        """Persist a manually entered account balance."""
        month = self.manager.current_month()
        if month is None:
            return
        await self.manager.async_update_month(
            month["month"], {"account_balance": float(Decimal(str(value)))}
        )
