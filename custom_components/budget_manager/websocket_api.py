"""WebSocket API used by the Budget Manager panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .manager import BudgetManager
from .model import BudgetValidationError


def _manager(hass: HomeAssistant) -> BudgetManager:
    managers = hass.data.get(DOMAIN, {}).get("entries", {})
    if not managers:
        raise BudgetValidationError("Budget Manager is not configured")
    return next(iter(managers.values()))


def _error(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], err: Exception
) -> None:
    connection.send_error(msg["id"], "invalid_request", str(err))


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register all panel commands."""
    for command in (
        ws_get_state,
        ws_subscribe,
        ws_export_data,
        ws_import_data,
        ws_update_settings,
        ws_create_month,
        ws_create_year,
        ws_update_month,
        ws_delete_month,
        ws_upsert_item,
        ws_delete_item,
        ws_set_item_status,
        ws_estonian_working_hours,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_state",
        vol.Optional("year"): vol.Coerce(int),
    }
)
@callback
def ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a complete selected-year snapshot."""
    try:
        connection.send_result(msg["id"], _manager(hass).snapshot(msg.get("year")))
    except BudgetValidationError as err:
        _error(connection, msg, err)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/estonian_working_hours",
        vol.Required("month"): str,
    }
)
@websocket_api.async_response
async def ws_estonian_working_hours(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return Estonia's standard working days and hours for one month."""
    try:
        result = await _manager(hass).async_estonian_working_hours(msg["month"])
    except (BudgetValidationError, TypeError, ValueError) as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/subscribe",
        vol.Optional("year"): vol.Coerce(int),
    }
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push fresh snapshots when data changes."""
    try:
        manager = _manager(hass)
    except BudgetValidationError as err:
        _error(connection, msg, err)
        return

    @callback
    def forward_update() -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], manager.snapshot(msg.get("year"))
            )
        )

    connection.subscriptions[msg["id"]] = manager.add_listener(forward_update)
    connection.send_result(msg["id"], manager.snapshot(msg.get("year")))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/export_data"}
)
@websocket_api.require_admin
@callback
def ws_export_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the complete portable budget document."""
    try:
        document = _manager(hass).export_data()
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"], document)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/import_data",
        vol.Required("document"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Validate and replace the budget from a portable document."""
    try:
        await _manager(hass).async_import_data(msg["document"])
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_settings",
        vol.Required("changes"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update daily-money and automatic-savings settings."""
    try:
        await _manager(hass).async_update_settings(msg["changes"])
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/create_month",
        vol.Required("target"): str,
        vol.Optional("source"): vol.Any(str, None),
        vol.Optional("overwrite", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_create_month(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or copy one month."""
    try:
        result = await _manager(hass).async_create_month(
            msg["target"], source=msg.get("source"), overwrite=msg["overwrite"]
        )
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/create_year",
        vol.Required("target_year"): vol.Coerce(int),
        vol.Optional("source_year"): vol.Any(vol.Coerce(int), None),
        vol.Optional("overwrite", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_create_year(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or copy all 12 months of a year."""
    try:
        result = await _manager(hass).async_create_year(
            msg["target_year"],
            source_year=msg.get("source_year"),
            overwrite=msg["overwrite"],
        )
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_month",
        vol.Required("month"): str,
        vol.Required("changes"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_month(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update manual balance or the payday cycle end."""
    try:
        await _manager(hass).async_update_month(msg["month"], msg["changes"])
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete_month",
        vol.Required("month"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_month(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a month."""
    try:
        await _manager(hass).async_delete_month(msg["month"])
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/upsert_item",
        vol.Required("month"): str,
        vol.Required("item"): dict,
        vol.Optional("scope", default="this"): vol.In(["this", "future"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_upsert_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create/edit one item or a bounded recurring series."""
    try:
        result = await _manager(hass).async_upsert_item(
            msg["month"], msg["item"], scope=msg["scope"]
        )
    except (BudgetValidationError, TypeError, ValueError) as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete_item",
        vol.Required("month"): str,
        vol.Required("item_id"): str,
        vol.Optional("scope", default="this"): vol.In(["this", "future"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one occurrence or its pending current-and-future series."""
    try:
        await _manager(hass).async_delete_item(
            msg["month"], msg["item_id"], scope=msg["scope"]
        )
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_item_status",
        vol.Required("month"): str,
        vol.Required("item_id"): str,
        vol.Required("status"): vol.In(
            ["pending", "paid", "received", "skipped"]
        ),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_item_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set the status of one item occurrence."""
    try:
        await _manager(hass).async_set_item_status(
            msg["month"], msg["item_id"], msg["status"]
        )
    except BudgetValidationError as err:
        _error(connection, msg, err)
    else:
        connection.send_result(msg["id"])
