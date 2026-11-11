"""Budget Manager integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, NAME, PLATFORMS
from .manager import BudgetManager
from .electricity_source import ElectricityCoordinator
from .model import BudgetValidationError, month_report, validate_month_key
from .notifications import BudgetReminderCoordinator
from .panel import async_register_panel, async_unregister_panel
from .websocket_api import async_register_websocket_api


def get_manager(hass: HomeAssistant) -> BudgetManager:
    """Return the single configured budget manager."""
    managers = hass.data.get(DOMAIN, {}).get("entries", {})
    if not managers:
        raise HomeAssistantError("Budget Manager is not configured")
    return next(iter(managers.values()))


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register integration-wide APIs and actions."""
    hass.data.setdefault(DOMAIN, {"entries": {}, "panel_registered": False})
    hass.data[DOMAIN].setdefault("reminders", {})
    hass.data[DOMAIN].setdefault("electricity_coordinators", {})
    async_register_websocket_api(hass)

    async def handle_set_balance(call: ServiceCall) -> None:
        try:
            await get_manager(hass).async_update_month(
                call.data["month"], {"account_balance": call.data["balance"]}
            )
        except BudgetValidationError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_mark_item(call: ServiceCall) -> None:
        try:
            await get_manager(hass).async_set_item_status(
                call.data["month"], call.data["item_id"], call.data["status"]
            )
        except BudgetValidationError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_copy_month(call: ServiceCall) -> None:
        try:
            await get_manager(hass).async_create_month(
                call.data["target_month"],
                source=call.data.get("source_month"),
                overwrite=call.data.get("overwrite", False),
            )
        except BudgetValidationError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_copy_year(call: ServiceCall) -> None:
        try:
            await get_manager(hass).async_create_year(
                call.data["target_year"],
                source_year=call.data.get("source_year"),
                overwrite=call.data.get("overwrite", False),
            )
        except BudgetValidationError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_get_month(call: ServiceCall) -> ServiceResponse:
        """Return every income, expense and savings item of one month."""
        manager = get_manager(hass)
        months = manager.data["months"]
        current = manager.current_month()
        current_key = current["month"] if current else None
        try:
            month_key = (
                validate_month_key(call.data["month"])
                if call.data.get("month")
                else current_key
            )
        except BudgetValidationError as err:
            raise HomeAssistantError(str(err)) from err
        if month_key is None or month_key not in months:
            raise HomeAssistantError(
                f"Budget month {month_key} does not exist. "
                f"Available months: {', '.join(sorted(months)) or 'none'}"
            )
        return {
            "currency": manager.data["settings"].get("currency", "EUR"),
            "current_month": current_key,
            "available_months": sorted(months),
            **month_report(
                months[month_key],
                settings=manager.data.get("settings"),
                today=manager.today(),
            ),
        }

    hass.services.async_register(
        DOMAIN,
        "get_month",
        handle_get_month,
        schema=vol.Schema({vol.Optional("month"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "set_balance",
        handle_set_balance,
        schema=vol.Schema(
            {vol.Required("month"): str, vol.Required("balance"): vol.Coerce(float)}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "mark_item",
        handle_mark_item,
        schema=vol.Schema(
            {
                vol.Required("month"): str,
                vol.Required("item_id"): str,
                vol.Required("status"): vol.In(
                    ["pending", "paid", "received", "skipped"]
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "copy_month",
        handle_copy_month,
        schema=vol.Schema(
            {
                vol.Required("target_month"): str,
                vol.Optional("source_month"): str,
                vol.Optional("overwrite", default=False): bool,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "copy_year",
        handle_copy_year,
        schema=vol.Schema(
            {
                vol.Required("target_year"): vol.Coerce(int),
                vol.Optional("source_year"): vol.Coerce(int),
                vol.Optional("overwrite", default=False): bool,
            }
        ),
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate existing entries to the current product name."""
    if entry.version < 2:
        hass.config_entries.async_update_entry(entry, title=NAME, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured Budget Manager instance."""
    manager = BudgetManager(hass, entry.entry_id)
    await manager.async_load()
    hass.data[DOMAIN]["entries"][entry.entry_id] = manager

    if not hass.data[DOMAIN]["panel_registered"]:
        await async_register_panel(hass)
        hass.data[DOMAIN]["panel_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    reminders = BudgetReminderCoordinator(hass, manager)
    reminders.async_start()
    hass.data[DOMAIN]["reminders"][entry.entry_id] = reminders
    electricity = ElectricityCoordinator(hass, manager)
    electricity.start()
    hass.data[DOMAIN]["electricity_coordinators"][entry.entry_id] = electricity
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Budget Manager config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        electricity = hass.data[DOMAIN]["electricity_coordinators"].pop(entry.entry_id, None)
        if electricity is not None:
            electricity.stop()
        reminders = hass.data[DOMAIN]["reminders"].pop(entry.entry_id, None)
        if reminders is not None:
            reminders.async_stop()
        hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]["entries"] and hass.data[DOMAIN]["panel_registered"]:
            async_unregister_panel(hass)
            hass.data[DOMAIN]["panel_registered"] = False
    return unloaded
