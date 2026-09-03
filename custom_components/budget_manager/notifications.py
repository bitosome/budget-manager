"""User-targeted mobile reminders for Budget Manager."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

from .manager import BudgetManager
from .model import event_summary, reminder_rows

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_DOMAIN = "mobile_app"


def mobile_notify_targets(hass: HomeAssistant) -> dict[str, list[str]]:
    """Return enabled mobile-app notify entities grouped by HA user ID."""
    registry = er.async_get(hass)
    targets: dict[str, list[str]] = {}
    for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
        user_id = str(entry.data.get("user_id") or "").strip()
        if not user_id or entry.disabled_by is not None:
            continue
        entity_ids = [
            entity.entity_id
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
            if entity.entity_id.startswith("notify.")
            and entity.disabled_by is None
            and hass.states.get(entity.entity_id) is not None
        ]
        if entity_ids:
            targets.setdefault(user_id, []).extend(entity_ids)
    return targets


async def async_notification_assignees(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return active HA users that have at least one mobile notification target."""
    targets = mobile_notify_targets(hass)
    users = await hass.auth.async_get_users()
    return sorted(
        (
            {
                "id": user.id,
                "name": user.name or "Home Assistant user",
                "device_count": len(targets[user.id]),
            }
            for user in users
            if user.id in targets and user.is_active and not user.system_generated
        ),
        key=lambda user: user["name"].casefold(),
    )


class BudgetReminderCoordinator:
    """Send assigned budget reminders from their due time until day end."""

    def __init__(self, hass: HomeAssistant, manager: BudgetManager) -> None:
        self.hass = hass
        self.manager = manager
        self._unsubscribe: Callable[[], None] | None = None
        self._sent: set[tuple[str, str]] = set()

    def async_start(self) -> None:
        """Start checking assigned reminders every minute."""
        if self._unsubscribe is None:
            self._unsubscribe = async_track_time_change(
                self.hass, self._async_check, second=0
            )

    def async_stop(self) -> None:
        """Stop checking reminders."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._sent.clear()

    async def _async_check(self, now: datetime) -> None:
        """Send each reminder once for the current scheduled minute."""
        minute_key = now.replace(second=0, microsecond=0).isoformat()
        today_prefix = now.date().isoformat()
        self._sent = {
            sent for sent in self._sent if sent[1].startswith(today_prefix)
        }
        targets = mobile_notify_targets(self.hass)
        for row in reminder_rows(self.manager.data, now):
            sent_key = (row["uid"], minute_key)
            if sent_key in self._sent:
                continue
            entity_ids = targets.get(row["assignee_user_id"], [])
            if not entity_ids:
                continue
            self._sent.add(sent_key)
            try:
                await self.hass.services.async_call(
                    "notify",
                    "send_message",
                    {
                        "title": "Budget Manager reminder",
                        "message": (
                            f"{event_summary(row)} is due today. "
                            "Mark it complete in Budget Manager to stop reminders."
                        ),
                    },
                    target={"entity_id": entity_ids},
                    blocking=False,
                )
            except HomeAssistantError:
                _LOGGER.exception(
                    "Could not send Budget Manager reminder for item %s",
                    row["uid"],
                )
