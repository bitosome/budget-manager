"""Budget Manager integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, NAME, PLATFORMS
from .manager import BudgetManager
from .model import BudgetValidationError
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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Budget Manager config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        reminders = hass.data[DOMAIN]["reminders"].pop(entry.entry_id, None)
        if reminders is not None:
            reminders.async_stop()
        hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]["entries"] and hass.data[DOMAIN]["panel_registered"]:
            async_unregister_panel(hass)
            hass.data[DOMAIN]["panel_registered"] = False
    return unloaded
