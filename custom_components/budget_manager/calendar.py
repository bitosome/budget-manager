"""Payment and renewal calendar for Budget Manager."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, STATUS_PENDING
from .entity import BudgetEntity
from .manager import BudgetManager
from .model import event_rows, next_day

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the budget calendar."""
    manager: BudgetManager = hass.data[DOMAIN]["entries"][entry.entry_id]
    async_add_entities([BudgetCalendar(manager)])


class BudgetCalendar(BudgetEntity, CalendarEntity):
    """Calendar of income, expenses, and highlighted renewals."""

    _attr_translation_key = "payments"

    def __init__(self, manager: BudgetManager) -> None:
        super().__init__(manager, "payments")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next pending budget occurrence."""
        today = self.manager.today()
        rows = sorted(
            (
                row
                for row in event_rows(self.manager.data)
                if row["status"] == STATUS_PENDING and row["date"] >= today
            ),
            key=lambda row: row["date"],
        )
        return self._as_event(rows[0]) if rows else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return occurrences overlapping the requested range."""
        start = start_date.date()
        end = end_date.date()
        return [
            self._as_event(row)
            for row in event_rows(self.manager.data)
            if start <= row["date"] < end
        ]

    def _as_event(self, row: dict) -> CalendarEvent:
        prefix = {
            "income": "Income",
            "expense": "Expense",
            "savings": "Savings transfer",
        }.get(row["kind"], "Budget")
        if row["special"]:
            prefix = row["special_label"] or "Renewal"
        return CalendarEvent(
            start=row["date"],
            end=next_day(row["date"]),
            summary=f"{prefix}: {row['name']} · €{row['amount']:.2f}",
            description=f"Status: {row['status']}\n{row['notes']}".strip(),
            uid=row["uid"],
        )

    def _handle_manager_update(self) -> None:
        """Refresh entity and active calendar subscriptions."""
        super()._handle_manager_update()
