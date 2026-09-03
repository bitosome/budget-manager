"""UI setup flow for Budget Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DEFAULT_AUTOMATIC_SAVINGS_ENABLED,
    DEFAULT_CYCLE_END_DAY,
    DEFAULT_DAILY_GREEN_THRESHOLD,
    DEFAULT_DAILY_YELLOW_THRESHOLD,
    DEFAULT_SAVINGS_FLOOR_THRESHOLD,
    DEFAULT_SAVINGS_TARGET_THRESHOLD,
    DOMAIN,
    NAME,
)

CONF_CYCLE_END_DAY = "cycle_end_day"
CONF_GREEN = "daily_green_threshold"
CONF_YELLOW = "daily_yellow_threshold"
CONF_SAVINGS_TARGET = "savings_target_threshold"
CONF_SAVINGS_FLOOR = "savings_floor_threshold"
CONF_AUTOMATIC_SAVINGS = "automatic_savings_enabled"


class BudgetManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one local Budget Manager instance."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "BudgetOptionsFlow":
        """Return the budget calculation options flow."""
        return BudgetOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the single local instance without collecting settings."""
        return self.async_create_entry(title=NAME, data={})


class BudgetOptionsFlow(OptionsFlow):
    """Manage cycle and calculation settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show and save budget calculation options."""
        manager = self.hass.data.get(DOMAIN, {}).get("entries", {}).get(
            self.config_entry.entry_id
        )
        current = manager.data.get("settings", {}) if manager else {}
        errors: dict[str, str] = {}
        if user_input is not None:
            green = float(user_input[CONF_GREEN])
            yellow = float(user_input[CONF_YELLOW])
            savings_target = float(user_input[CONF_SAVINGS_TARGET])
            savings_floor = float(user_input[CONF_SAVINGS_FLOOR])
            if yellow > green:
                errors["base"] = "yellow_above_green"
            elif savings_floor > savings_target:
                errors["base"] = "savings_floor_above_target"
            else:
                if manager:
                    await manager.async_update_settings(user_input)
                return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CYCLE_END_DAY,
                    default=current.get(
                        CONF_CYCLE_END_DAY, DEFAULT_CYCLE_END_DAY
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
                vol.Required(
                    CONF_GREEN,
                    default=current.get(
                        CONF_GREEN, DEFAULT_DAILY_GREEN_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_YELLOW,
                    default=current.get(
                        CONF_YELLOW, DEFAULT_DAILY_YELLOW_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_SAVINGS_TARGET,
                    default=current.get(
                        CONF_SAVINGS_TARGET, DEFAULT_SAVINGS_TARGET_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_SAVINGS_FLOOR,
                    default=current.get(
                        CONF_SAVINGS_FLOOR, DEFAULT_SAVINGS_FLOOR_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_AUTOMATIC_SAVINGS,
                    default=current.get(
                        CONF_AUTOMATIC_SAVINGS,
                        DEFAULT_AUTOMATIC_SAVINGS_ENABLED,
                    ),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
