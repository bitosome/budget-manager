"""Summary sensors for Budget Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import BudgetEntity
from .manager import BudgetManager
from .model import calculate_month

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BudgetSensorDescription:
    key: str
    translation_key: str
    value_fn: Callable[[dict[str, Any]], float]


SENSORS = (
    BudgetSensorDescription(
        key="daily_allowance",
        translation_key="daily_allowance",
        value_fn=lambda summary: summary["daily_allowance"],
    ),
    BudgetSensorDescription(
        key="remaining",
        translation_key="remaining",
        value_fn=lambda summary: summary["remaining"],
    ),
    BudgetSensorDescription(
        key="unpaid_expenses",
        translation_key="unpaid_expenses",
        value_fn=lambda summary: summary["unpaid_expenses"],
    ),
    BudgetSensorDescription(
        key="expected_income",
        translation_key="expected_income",
        value_fn=lambda summary: summary["expected_income"],
    ),
    BudgetSensorDescription(
        key="planned_savings",
        translation_key="planned_savings",
        value_fn=lambda summary: summary["planned_savings"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up budget sensors."""
    manager: BudgetManager = hass.data[DOMAIN]["entries"][entry.entry_id]
    async_add_entities(BudgetSensor(manager, description) for description in SENSORS)


class BudgetSensor(BudgetEntity, SensorEntity):
    """One calculated budget metric."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    def __init__(
        self, manager: BudgetManager, description: BudgetSensorDescription
    ) -> None:
        super().__init__(manager, description.key)
        self.description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> float | None:
        """Return the current calculated value."""
        month = self.manager.current_month()
        if month is None:
            return None
        return self.description.value_fn(
            calculate_month(
                month,
                settings=self.manager.data.get("settings"),
                today=self.manager.today(),
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the active period and forecast drivers."""
        month = self.manager.current_month()
        if month is None:
            return {}
        summary = calculate_month(
            month,
            settings=self.manager.data.get("settings"),
            today=self.manager.today(),
        )
        return {
            "month": month["month"],
            "account_balance": summary["account_balance"],
            "expected_income": summary["expected_income"],
            "unpaid_expenses": summary["unpaid_expenses"],
            "days_divisor": summary["days_divisor"],
            "payday": month.get("payday"),
            "balance_updated_at": month.get("balance_updated_at"),
            "rag": summary["rag"],
            "daily_green_threshold": summary["green_threshold"],
            "daily_yellow_threshold": summary["yellow_threshold"],
            "savings_target_threshold": summary["savings_target_threshold"],
            "savings_floor_threshold": summary["savings_floor_threshold"],
            "planned_savings": summary["planned_savings"],
            "baseline_savings": summary["baseline_savings"],
            "savings_adjustment": summary["savings_adjustment"],
            "baseline_daily_allowance": summary["baseline_daily_allowance"],
        }
