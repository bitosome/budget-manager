"""Persistent budget manager and mutation boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .estonian_calendar import EstonianWorkingHoursProvider
from .estonian_payroll import (
    EstonianPayrollError,
    calculate_estonian_payroll,
    income_working_time_month,
    normalize_income_calculation,
)
from .const import (
    DEFAULT_CYCLE_END_DAY,
    DEFAULT_DAILY_GREEN_THRESHOLD,
    DEFAULT_DAILY_YELLOW_THRESHOLD,
    DEFAULT_SAVINGS_FLOOR_THRESHOLD,
    DEFAULT_SAVINGS_TARGET_THRESHOLD,
    KIND_SAVINGS,
    RECURRENCE_SINGLE,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_RECEIVED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    VALID_STATUSES,
)
from .model import (
    BudgetValidationError,
    calculate_month,
    calculate_year,
    copy_month_data,
    current_month_key,
    default_payday,
    empty_data,
    export_data_document,
    iter_recurrence_months,
    make_month,
    money,
    new_id,
    normalize_item,
    normalize_cycle_end_day,
    normalize_import_document,
    normalize_savings_thresholds,
    normalize_thresholds,
    validate_month_key,
)


class BudgetManager:
    """Own budget state, persistence, and updates."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._data: dict[str, Any] = empty_data()
        self._lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()
        self._estonian_calendar = EstonianWorkingHoursProvider(hass)

    @property
    def data(self) -> dict[str, Any]:
        """Return the in-memory storage document."""
        return self._data

    async def async_load(self) -> None:
        """Load storage and migrate older data without auto-creating a plan."""
        stored = await self._store.async_load()
        self._data = stored if isinstance(stored, dict) else empty_data()
        defaults = empty_data()["settings"]
        settings = self._data.setdefault("settings", {})
        for key, value in defaults.items():
            settings.setdefault(key, value)
        try:
            cycle_end_day = normalize_cycle_end_day(settings["cycle_end_day"])
        except BudgetValidationError:
            cycle_end_day = DEFAULT_CYCLE_END_DAY
        settings["cycle_end_day"] = cycle_end_day
        settings["configured"] = True
        self._data.setdefault("months", {})
        for month_key, month in self._data["months"].items():
            month.pop("note", None)
            month["payday"] = default_payday(month_key, cycle_end_day)
            migrated_items = []
            for item in month.get("items", []):
                item.setdefault("needs_review", False)
                try:
                    item["income_calculation"] = normalize_income_calculation(
                        item.get("income_calculation"),
                        is_income=item.get("kind") == "income",
                    )
                except EstonianPayrollError:
                    # Preserve unexpected legacy data for export/recovery rather
                    # than silently discarding a user's calculation settings.
                    item.setdefault("income_calculation", None)
                if (
                    item.get("kind") == "expense"
                    and item.get("name", "").strip().casefold() == "savings"
                ):
                    item["kind"] = KIND_SAVINGS
                    item["dynamic"] = True
                elif item.get("kind") == KIND_SAVINGS:
                    item.setdefault("dynamic", True)
                else:
                    item.setdefault("dynamic", False)
                migrated_items.append(item)
            month["items"] = migrated_items
        self._data["schema_version"] = 7
        await self._store.async_save(self._data)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to in-memory changes."""
        self._listeners.add(listener)

        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    async def _async_commit(self) -> None:
        await self._store.async_save(self._data)
        for listener in tuple(self._listeners):
            listener()

    def snapshot(self, year: int | None = None) -> dict[str, Any]:
        """Return panel-ready state and calculations."""
        today = self.today()
        available_years = sorted({int(key[:4]) for key in self._data["months"]})
        current = current_month_key(self._data, today=today)
        selected_year = year or today.year
        plan_years = (selected_year, selected_year + 1)
        return {
            "settings": deepcopy(self._data["settings"]),
            "configured": True,
            "available_years": available_years,
            "available_months": sorted(self._data["months"]),
            "current_month": current,
            "selected_year": selected_year,
            "plan_years": list(plan_years),
            "year": calculate_year(self._data, selected_year, today=today),
            "months": {
                key: self._month_payload(value, today=today)
                for key, value in self._data["months"].items()
                if int(key[:4]) in plan_years
            },
        }

    def _month_payload(
        self, month: dict[str, Any], *, today: date | None = None
    ) -> dict[str, Any]:
        payload = deepcopy(month)
        payload["summary"] = calculate_month(
            month,
            settings=self._data.get("settings"),
            today=today or self.today(),
        )
        effective_amounts = payload["summary"]["effective_amounts"]
        for item in payload["items"]:
            item["effective_amount"] = effective_amounts.get(
                item["id"], item.get("amount", 0)
            )
        payload["items"].sort(
            key=lambda item: (
                {"income": 0, "expense": 1, "savings": 2}.get(
                    item.get("kind"), 3
                ),
                item.get("sort_order", 0),
                item.get("due_day") or 0,
                item.get("name", "").casefold(),
            )
        )
        return payload

    def export_data(self) -> dict[str, Any]:
        """Return the complete budget as a portable JSON document."""
        return export_data_document(self._data)

    def today(self) -> date:
        """Return today in Home Assistant's configured local timezone."""
        return dt_util.now().date()

    async def async_import_data(self, document: dict[str, Any]) -> None:
        """Validate and replace the budget from a portable JSON document."""
        imported = normalize_import_document(document)
        async with self._lock:
            self._data = imported
            await self._async_commit()

    async def async_update_settings(self, changes: dict[str, Any]) -> None:
        """Update cycle, daily-money, and automatic-savings settings."""
        settings = self._data.setdefault("settings", empty_data()["settings"])
        green = changes.get(
            "daily_green_threshold",
            settings.get("daily_green_threshold", DEFAULT_DAILY_GREEN_THRESHOLD),
        )
        yellow = changes.get(
            "daily_yellow_threshold",
            settings.get("daily_yellow_threshold", DEFAULT_DAILY_YELLOW_THRESHOLD),
        )
        green, yellow = normalize_thresholds(
            {
                "daily_green_threshold": green,
                "daily_yellow_threshold": yellow,
            }
        )
        savings_target = changes.get(
            "savings_target_threshold",
            settings.get(
                "savings_target_threshold", DEFAULT_SAVINGS_TARGET_THRESHOLD
            ),
        )
        savings_floor = changes.get(
            "savings_floor_threshold",
            settings.get("savings_floor_threshold", DEFAULT_SAVINGS_FLOOR_THRESHOLD),
        )
        savings_target, savings_floor = normalize_savings_thresholds(
            {
                "savings_target_threshold": savings_target,
                "savings_floor_threshold": savings_floor,
            }
        )
        cycle_end_day = normalize_cycle_end_day(
            changes.get(
                "cycle_end_day",
                settings.get("cycle_end_day", DEFAULT_CYCLE_END_DAY),
            )
        )
        async with self._lock:
            settings["cycle_end_day"] = cycle_end_day
            settings["daily_green_threshold"] = green
            settings["daily_yellow_threshold"] = yellow
            settings["savings_target_threshold"] = savings_target
            settings["savings_floor_threshold"] = savings_floor
            for month_key, month in self._data["months"].items():
                month["payday"] = default_payday(month_key, cycle_end_day)
            await self._async_commit()

    def current_month(self) -> dict[str, Any] | None:
        """Return the current or nearest budget month."""
        key = current_month_key(self._data, today=self.today())
        return self._data["months"].get(key) if key else None

    async def async_create_month(
        self,
        target: str,
        *,
        source: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create a blank month or a clean copy of another month."""
        validate_month_key(target)
        if source is not None:
            validate_month_key(source)
        async with self._lock:
            if target in self._data["months"] and not overwrite:
                raise BudgetValidationError(f"Month {target} already exists")
            cycle_end_day = normalize_cycle_end_day(
                self._data["settings"].get(
                    "cycle_end_day", DEFAULT_CYCLE_END_DAY
                )
            )
            if source:
                source_month = self._data["months"].get(source)
                if source_month is None:
                    raise BudgetValidationError(f"Source month {source} does not exist")
                month = copy_month_data(
                    source_month,
                    source,
                    target,
                    cycle_end_day=cycle_end_day,
                )
                await self._async_refresh_calculated_income(month, target)
            else:
                month = make_month(target, cycle_end_day=cycle_end_day)
            self._data["months"][target] = month
            await self._async_commit()
            return self._month_payload(month)

    async def async_create_year(
        self,
        target_year: int,
        *,
        source_year: int | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create 12 blank months or copy an entire source year."""
        if not 2000 <= int(target_year) <= 2200:
            raise BudgetValidationError("Target year is outside the supported range")
        if source_year is not None and not 2000 <= int(source_year) <= 2200:
            raise BudgetValidationError("Source year is outside the supported range")
        targets = [f"{int(target_year):04d}-{month:02d}" for month in range(1, 13)]
        async with self._lock:
            cycle_end_day = normalize_cycle_end_day(
                self._data["settings"].get(
                    "cycle_end_day", DEFAULT_CYCLE_END_DAY
                )
            )
            series_map: dict[str, str] = {}
            for month_number, target in enumerate(targets, start=1):
                if target in self._data["months"] and not overwrite:
                    continue
                source = (
                    f"{int(source_year):04d}-{month_number:02d}"
                    if source_year is not None
                    else None
                )
                if source and source in self._data["months"]:
                    self._data["months"][target] = copy_month_data(
                        self._data["months"][source],
                        source,
                        target,
                        series_map=series_map,
                        cycle_end_day=cycle_end_day,
                    )
                    await self._async_refresh_calculated_income(
                        self._data["months"][target], target
                    )
                else:
                    self._data["months"][target] = make_month(
                        target,
                        source=source,
                        cycle_end_day=cycle_end_day,
                    )
            await self._async_commit()
            return calculate_year(
                self._data, int(target_year), today=self.today()
            )

    async def async_update_month(self, month_key: str, changes: dict[str, Any]) -> None:
        """Update a month's manual balance or payday cycle end."""
        validate_month_key(month_key)
        async with self._lock:
            month = self._require_month(month_key)
            if "account_balance" in changes:
                month["account_balance"] = money(changes["account_balance"])
                month["balance_updated_at"] = datetime.now(timezone.utc).isoformat()
            if "payday" in changes:
                payday = str(changes["payday"])
                try:
                    datetime.fromisoformat(payday)
                except ValueError as err:
                    raise BudgetValidationError("Payday must be an ISO date") from err
                month["payday"] = payday
            await self._async_commit()

    async def async_delete_month(self, month_key: str) -> None:
        """Delete a complete month."""
        validate_month_key(month_key)
        async with self._lock:
            if self._data["months"].pop(month_key, None) is None:
                raise BudgetValidationError(f"Month {month_key} does not exist")
            await self._async_commit()

    async def async_upsert_item(
        self,
        month_key: str,
        raw: dict[str, Any],
        *,
        scope: str = "this",
    ) -> dict[str, Any]:
        """Create or edit one item or its current-and-future recurrence."""
        validate_month_key(month_key)
        if scope not in {"this", "future"}:
            raise BudgetValidationError("Scope must be this or future")
        async with self._lock:
            month = self._require_month(month_key)
            raw_id = str(raw.get("id") or "")
            existing = next(
                (item for item in month["items"] if item["id"] == raw_id), None
            )

            if existing and scope == "future" and existing.get("series_id"):
                series_id = existing["series_id"]
                for key, stored_month in self._data["months"].items():
                    if key < month_key:
                        continue
                    stored_month["items"] = [
                        item
                        for item in stored_month["items"]
                        if not (
                            item.get("series_id") == series_id
                            and item.get("status", STATUS_PENDING) == STATUS_PENDING
                        )
                    ]
                raw = {**raw, "series_id": series_id}
                existing = None
                raw_id = ""

            merged = {**(existing or {}), **raw}
            normalized = normalize_item(
                await self._async_prepare_calculated_income(merged, month_key),
                existing_id=existing["id"] if existing else None,
            )
            if existing:
                index = month["items"].index(existing)
                month["items"][index] = normalized
                await self._async_commit()
                return deepcopy(normalized)

            if normalized["recurrence"] == RECURRENCE_SINGLE:
                normalized["id"] = raw_id or new_id()
                month["items"].append(normalized)
            else:
                months = iter_recurrence_months(
                    month_key,
                    normalized["recurrence"],
                    normalized["recurrence_end"],
                )
                series_id = normalized.get("series_id") or new_id()
                for target in months:
                    target_month = self._data["months"].setdefault(
                        target,
                        make_month(
                            target,
                            cycle_end_day=self._data["settings"].get(
                                "cycle_end_day", DEFAULT_CYCLE_END_DAY
                            ),
                        ),
                    )
                    occurrence = normalize_item(
                        await self._async_prepare_calculated_income(
                            deepcopy(normalized), target
                        )
                    )
                    occurrence["id"] = new_id()
                    occurrence["series_id"] = series_id
                    occurrence["status"] = STATUS_PENDING
                    occurrence["paid_at"] = None
                    target_month["items"].append(occurrence)
                normalized["series_id"] = series_id
            await self._async_commit()
            return deepcopy(normalized)

    async def async_estonian_working_hours(self, month_key: str) -> dict[str, Any]:
        """Return standard Estonian working time for a calendar month."""
        validate_month_key(month_key)
        return await self._estonian_calendar.async_month(month_key)

    async def _async_prepare_calculated_income(
        self, raw: dict[str, Any], month_key: str
    ) -> dict[str, Any]:
        """Resolve automatic working hours and calculate an income amount."""
        try:
            config = normalize_income_calculation(
                raw.get("income_calculation"),
                is_income=raw.get("kind") == "income",
            )
        except EstonianPayrollError as err:
            raise BudgetValidationError(str(err)) from err
        prepared = {**raw, "income_calculation": config}
        if config is None:
            return prepared
        working_time_month = income_working_time_month(
            month_key, config["work_period"]
        )
        config["working_time_month"] = working_time_month
        if config["working_hours_mode"] == "automatic":
            working_time = await self._estonian_calendar.async_month(
                working_time_month
            )
            config.update(
                {
                    "working_hours": working_time["working_hours"],
                    "working_days": working_time["working_days"],
                    "calendar_source": working_time["calendar_source"],
                }
            )
        try:
            calculation = calculate_estonian_payroll(
                config, payment_year=int(month_key[:4])
            )
        except EstonianPayrollError as err:
            raise BudgetValidationError(str(err)) from err
        prepared["income_calculation"] = calculation
        prepared["amount"] = calculation["net_income"]
        return prepared

    async def _async_refresh_calculated_income(
        self, month: dict[str, Any], month_key: str
    ) -> None:
        """Recalculate copied hourly income for the target month."""
        for index, item in enumerate(month.get("items", [])):
            if not item.get("income_calculation"):
                continue
            prepared = await self._async_prepare_calculated_income(item, month_key)
            month["items"][index] = normalize_item(
                prepared, existing_id=item["id"]
            )

    async def async_delete_item(
        self, month_key: str, item_id: str, *, scope: str = "this"
    ) -> None:
        """Delete one occurrence or pending current-and-future series occurrences."""
        validate_month_key(month_key)
        if scope not in {"this", "future"}:
            raise BudgetValidationError("Scope must be this or future")
        async with self._lock:
            month = self._require_month(month_key)
            item = next((item for item in month["items"] if item["id"] == item_id), None)
            if item is None:
                raise BudgetValidationError("Item does not exist")
            if scope == "future" and item.get("series_id"):
                series_id = item["series_id"]
                for key, stored_month in self._data["months"].items():
                    if key < month_key:
                        continue
                    stored_month["items"] = [
                        candidate
                        for candidate in stored_month["items"]
                        if not (
                            candidate.get("series_id") == series_id
                            and candidate.get("status", STATUS_PENDING) == STATUS_PENDING
                        )
                    ]
            else:
                month["items"].remove(item)
            await self._async_commit()

    async def async_set_item_status(
        self, month_key: str, item_id: str, status: str
    ) -> None:
        """Mark an occurrence paid, received, skipped, or pending."""
        validate_month_key(month_key)
        if status not in VALID_STATUSES:
            raise BudgetValidationError("Invalid status")
        async with self._lock:
            month = self._require_month(month_key)
            item = next((item for item in month["items"] if item["id"] == item_id), None)
            if item is None:
                raise BudgetValidationError("Item does not exist")
            if item["kind"] == "income" and status == STATUS_PAID:
                status = STATUS_RECEIVED
            if item["kind"] in {"expense", KIND_SAVINGS} and status == STATUS_RECEIVED:
                status = STATUS_PAID
            if (
                item["kind"] == KIND_SAVINGS
                and item.get("dynamic", True)
                and status == STATUS_PAID
                and item.get("status") == STATUS_PENDING
            ):
                summary = calculate_month(
                    month,
                    settings=self._data.get("settings"),
                    today=self.today(),
                )
                item["amount"] = summary["effective_amounts"].get(
                    item["id"], item.get("amount", 0)
                )
            item["status"] = status
            item["paid_at"] = (
                datetime.now(timezone.utc).isoformat()
                if status in {STATUS_PAID, STATUS_RECEIVED}
                else None
            )
            await self._async_commit()

    def _require_month(self, month_key: str) -> dict[str, Any]:
        month = self._data["months"].get(month_key)
        if month is None:
            raise BudgetValidationError(f"Month {month_key} does not exist")
        return month
