"""Persistent budget manager and mutation boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .estonian_care_leave import (
    CARE_LEAVE_TYPE,
    GENERATED_BENEFIT_TYPE,
    EstonianCareLeaveError,
    calculate_care_period,
    normalize_care_period,
)
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
                item.setdefault("expense_type", "standard")
                item.setdefault("care_leave", None)
                item.setdefault("generated_type", "")
                item.setdefault("generated", None)
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
        self._data["schema_version"] = 8
        await self._async_rebuild_all_care_leave_effects()
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
            previous = self._data
            self._data = imported
            try:
                await self._async_rebuild_all_care_leave_effects()
                await self._async_commit()
            except Exception:
                self._data = previous
                raise

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
            await self._async_rebuild_all_care_leave_effects()
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
            await self._async_rebuild_all_care_leave_effects()
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
            await self._async_rebuild_all_care_leave_effects()
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
            if existing and existing.get("generated_type") == GENERATED_BENEFIT_TYPE:
                raise BudgetValidationError(
                    "Automatic Tervisekassa income is managed from its care-leave period"
                )
            if raw.get("generated_type"):
                raise BudgetValidationError(
                    "Generated income cannot be created or edited directly"
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
            self._validate_care_leave_item(normalized)
            if existing:
                index = month["items"].index(existing)
                month["items"][index] = normalized
                await self._async_rebuild_all_care_leave_effects()
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
            await self._async_rebuild_all_care_leave_effects()
            await self._async_commit()
            return deepcopy(normalized)

    async def async_estonian_working_hours(self, month_key: str) -> dict[str, Any]:
        """Return standard Estonian working time for a calendar month."""
        validate_month_key(month_key)
        return await self._estonian_calendar.async_month(month_key)

    async def _async_prepare_calculated_income(
        self,
        raw: dict[str, Any],
        month_key: str,
        *,
        care_leave_hours: float = 0,
        care_leave_period_count: int = 0,
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
            standard_working_hours = float(working_time["working_hours"])
            config.update(
                {
                    "standard_working_hours": standard_working_hours,
                    "care_leave_hours": min(
                        standard_working_hours, float(care_leave_hours)
                    ),
                    "care_leave_period_count": int(care_leave_period_count),
                    "working_hours": max(
                        0, standard_working_hours - float(care_leave_hours)
                    ),
                    "working_days": working_time["working_days"],
                    "calendar_source": working_time["calendar_source"],
                }
            )
        else:
            config.update(
                {
                    "standard_working_hours": config["working_hours"],
                    "care_leave_hours": 0,
                    "care_leave_period_count": 0,
                }
            )
        try:
            calculation = calculate_estonian_payroll(
                config, payment_year=int(month_key[:4])
            )
            if config["care_leave_hours"]:
                original_config = {
                    **config,
                    "working_hours": config["standard_working_hours"],
                    "care_leave_hours": 0,
                    "care_leave_period_count": 0,
                }
                original = calculate_estonian_payroll(
                    original_config, payment_year=int(month_key[:4])
                )
                calculation["care_leave_original_net_income"] = original[
                    "net_income"
                ]
                calculation["care_leave_net_salary_reduction"] = round(
                    original["net_income"] - calculation["net_income"], 2
                )
            else:
                calculation["care_leave_original_net_income"] = calculation[
                    "net_income"
                ]
                calculation["care_leave_net_salary_reduction"] = 0.0
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

    def _resolve_care_leave_income(
        self, care_leave: dict[str, Any], *, required: bool
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve and validate the hourly income linked to care leave."""
        income_month = care_leave.get("income_month", "")
        month = self._data.get("months", {}).get(income_month)
        if month is None:
            if required:
                raise BudgetValidationError(
                    "The linked income month does not exist"
                )
            return None
        linked_id = care_leave.get("linked_income_item_id", "")
        linked_series = care_leave.get("linked_income_series_id", "")
        income = next(
            (
                item
                for item in month.get("items", [])
                if item.get("id") == linked_id
            ),
            None,
        )
        if income is None and linked_series:
            income = next(
                (
                    item
                    for item in month.get("items", [])
                    if item.get("series_id") == linked_series
                    and item.get("kind") == "income"
                ),
                None,
            )
        calculation = income.get("income_calculation") if income else None
        if (
            income is None
            or income.get("kind") != "income"
            or not calculation
            or calculation.get("working_hours_mode") != "automatic"
        ):
            if required:
                raise BudgetValidationError(
                    "Child-care leave requires an automatic Estonian hourly income"
                )
            return None
        working_time_month = income_working_time_month(
            income_month, calculation.get("work_period", "budget_month")
        )
        if working_time_month != care_leave.get("work_month"):
            if required:
                raise BudgetValidationError(
                    "The linked income does not use this care-leave work month"
                )
            return None
        care_leave["linked_income_item_id"] = income["id"]
        care_leave["linked_income_series_id"] = str(
            income.get("series_id") or ""
        )
        care_leave["linked_income_name"] = income.get("name", "")
        return income_month, income

    @staticmethod
    def _care_leave_links_income(
        care_leave: dict[str, Any], income: dict[str, Any], income_month: str
    ) -> bool:
        """Return whether a care container targets an income occurrence."""
        if care_leave.get("income_month") != income_month:
            return False
        if care_leave.get("linked_income_item_id") == income.get("id"):
            return True
        series_id = income.get("series_id")
        return bool(
            series_id
            and care_leave.get("linked_income_series_id") == series_id
        )

    async def _async_previous_year_working_hours(self, work_year: int) -> float:
        """Return standard hours used to approximate prior-year income."""
        total = 0.0
        previous_year = work_year - 1
        for month_number in range(1, 13):
            working_time = await self._estonian_calendar.async_month(
                f"{previous_year:04d}-{month_number:02d}"
            )
            total += float(working_time["working_hours"])
        return round(total, 2)

    async def _async_rebuild_all_care_leave_effects(self) -> None:
        """Recalculate linked salaries and generated benefit incomes."""
        generated_existing: dict[tuple[str, str], dict[str, Any]] = {}
        reset_references: list[dict[str, Any]] = []
        care_items: list[tuple[str, dict[str, Any]]] = []

        for month_key, month in self._data.get("months", {}).items():
            kept_items = []
            for item in month.get("items", []):
                if item.get("generated_type") == GENERATED_BENEFIT_TYPE:
                    generated = item.get("generated") or {}
                    key = (
                        str(generated.get("source_care_item_id") or ""),
                        str(generated.get("source_period_id") or ""),
                    )
                    generated_existing[key] = deepcopy(item)
                    reset_references.append(generated)
                    continue
                kept_items.append(item)
                if item.get("expense_type") == CARE_LEAVE_TYPE:
                    care_items.append((month_key, item))
                calculation = item.get("income_calculation") or {}
                if float(calculation.get("care_leave_hours", 0) or 0) > 0:
                    reset_references.append(
                        {
                            "income_month": month_key,
                            "linked_income_item_id": item.get("id"),
                            "linked_income_series_id": item.get("series_id"),
                            "work_month": calculation.get(
                                "working_time_month", ""
                            ),
                        }
                    )
            month["items"] = kept_items

        grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        targets: dict[tuple[str, str], dict[str, Any]] = {}
        for _source_month, care_item in care_items:
            care_leave = care_item.get("care_leave") or {}
            resolved = self._resolve_care_leave_income(
                care_leave, required=False
            )
            if resolved is None:
                continue
            income_month, income = resolved
            key = (income_month, income["id"])
            targets[key] = income
            grouped.setdefault(key, []).append((_source_month, care_item))

        for reference in reset_references:
            resolved = self._resolve_care_leave_income(
                {
                    "income_month": reference.get("income_month", ""),
                    "linked_income_item_id": reference.get(
                        "linked_income_item_id", ""
                    ),
                    "linked_income_series_id": reference.get(
                        "linked_income_series_id", ""
                    ),
                    "work_month": reference.get("work_month", ""),
                },
                required=False,
            )
            if resolved is not None:
                income_month, income = resolved
                targets[(income_month, income["id"])] = income

        annual_hours_cache: dict[int, float] = {}
        for key, income in targets.items():
            income_month, income_id = key
            calculation = income.get("income_calculation") or {}
            work_month = income_working_time_month(
                income_month, calculation.get("work_period", "budget_month")
            )
            working_time = await self._estonian_calendar.async_month(work_month)
            linked_care_items = grouped.get(key, [])
            missed_hours = 0.0
            period_count = 0

            for _source_month, care_item in linked_care_items:
                care_leave = care_item["care_leave"]
                if care_leave["benefit_basis_mode"] == "estimated_hourly":
                    work_year = int(work_month[:4])
                    if work_year not in annual_hours_cache:
                        annual_hours_cache[work_year] = (
                            await self._async_previous_year_working_hours(work_year)
                        )
                    previous_year_hours = annual_hours_cache[work_year]
                else:
                    previous_year_hours = 0.0

                for period in care_leave.get("periods", []):
                    period_count += 1
                    result = calculate_care_period(
                        period,
                        hourly_gross=calculation["hourly_gross"],
                        previous_year_working_hours=previous_year_hours,
                        benefit_basis_mode=care_leave["benefit_basis_mode"],
                        actual_previous_year_income=care_leave[
                            "actual_previous_year_income"
                        ],
                        public_holidays=working_time["public_holidays"],
                        shortened_workdays=working_time["shortened_workdays"],
                        benefit_year=int(work_month[:4]),
                    )
                    period["calculation"] = result
                    missed_hours += result["missed_working_hours"]

            prepared = await self._async_prepare_calculated_income(
                income,
                income_month,
                care_leave_hours=missed_hours,
                care_leave_period_count=period_count,
            )
            normalized_income = normalize_item(
                prepared, existing_id=income_id
            )
            target_month = self._data["months"][income_month]
            income_index = next(
                index
                for index, candidate in enumerate(target_month["items"])
                if candidate.get("id") == income_id
            )
            target_month["items"][income_index] = normalized_income

            for _source_month, care_item in linked_care_items:
                care_leave = care_item["care_leave"]
                for period in care_leave.get("periods", []):
                    existing_key = (care_item["id"], period["id"])
                    existing = generated_existing.get(existing_key, {})
                    result = period["calculation"]
                    date_label = (
                        period["start"]
                        if period["start"] == period["end"]
                        else f"{period['start']}–{period['end']}"
                    )
                    generated_item = normalize_item(
                        {
                            "id": existing.get("id") or new_id(),
                            "name": f"Tervisekassa care benefit · {date_label}",
                            "kind": "income",
                            "amount": result["estimated_net_benefit"],
                            "due_day": existing.get("due_day"),
                            "status": existing.get("status", STATUS_PENDING),
                            "paid_at": existing.get("paid_at"),
                            "category": "Tervisekassa",
                            "recurrence": RECURRENCE_SINGLE,
                            "notes": (
                                "Automatic approximation. Actual Tervisekassa "
                                "payment may differ from this estimate."
                            ),
                            "generated_type": GENERATED_BENEFIT_TYPE,
                            "generated": {
                                "source_care_item_id": care_item["id"],
                                "source_period_id": period["id"],
                                "linked_income_item_id": income_id,
                                "linked_income_series_id": normalized_income.get(
                                    "series_id"
                                ),
                                "income_month": income_month,
                                "work_month": work_month,
                                "period_start": period["start"],
                                "period_end": period["end"],
                                "estimated": True,
                                "calculation": deepcopy(result),
                            },
                        }
                    )
                    target_month["items"].append(generated_item)

    def _validate_care_leave_item(self, item: dict[str, Any]) -> None:
        """Validate a care container against its linked income."""
        if item.get("expense_type") != CARE_LEAVE_TYPE:
            return
        self._resolve_care_leave_income(item["care_leave"], required=True)

    def _assert_income_not_linked_to_care_leave(
        self, income: dict[str, Any], income_month: str
    ) -> None:
        """Prevent removing a salary that active care-leave planning depends on."""
        if income.get("kind") != "income":
            return
        for month in self._data.get("months", {}).values():
            for item in month.get("items", []):
                if item.get("expense_type") != CARE_LEAVE_TYPE:
                    continue
                if self._care_leave_links_income(
                    item.get("care_leave") or {}, income, income_month
                ):
                    raise BudgetValidationError(
                        "This income is linked to child-care leave. Delete or relink "
                        "the care-leave item first."
                    )

    async def async_upsert_care_leave_period(
        self, month_key: str, item_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or edit one calendar period inside a care container."""
        validate_month_key(month_key)
        async with self._lock:
            month = self._require_month(month_key)
            item = next(
                (candidate for candidate in month["items"] if candidate["id"] == item_id),
                None,
            )
            if item is None or item.get("expense_type") != CARE_LEAVE_TYPE:
                raise BudgetValidationError("Child-care leave item does not exist")
            raw_id = str(raw.get("id") or "")
            existing = next(
                (
                    period
                    for period in item["care_leave"]["periods"]
                    if period["id"] == raw_id
                ),
                None,
            )
            try:
                period = normalize_care_period(
                    {**(existing or {}), **raw, "id": raw_id or new_id()},
                    existing_id=raw_id or None,
                )
            except EstonianCareLeaveError as err:
                raise BudgetValidationError(str(err)) from err
            periods = [
                candidate
                for candidate in item["care_leave"]["periods"]
                if candidate["id"] != raw_id
            ]
            periods.append(period)
            candidate_item = normalize_item(
                {
                    **item,
                    "care_leave": {**item["care_leave"], "periods": periods},
                },
                existing_id=item["id"],
            )
            self._validate_care_leave_item(candidate_item)

            new_dates = set(
                date.fromisoformat(period["start"])
                + timedelta(days=offset)
                for offset in range(
                    (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
                )
            )
            for other_month in self._data["months"].values():
                for other_item in other_month.get("items", []):
                    if (
                        other_item.get("expense_type") != CARE_LEAVE_TYPE
                        or other_item.get("id") == item_id
                        or not self._care_leave_links_income(
                            other_item.get("care_leave") or {},
                            self._resolve_care_leave_income(
                                candidate_item["care_leave"], required=True
                            )[1],
                            candidate_item["care_leave"]["income_month"],
                        )
                    ):
                        continue
                    for other_period in other_item["care_leave"].get("periods", []):
                        other_start = date.fromisoformat(other_period["start"])
                        other_end = date.fromisoformat(other_period["end"])
                        other_dates = {
                            other_start + timedelta(days=offset)
                            for offset in range((other_end - other_start).days + 1)
                        }
                        if new_dates.intersection(other_dates):
                            raise BudgetValidationError(
                                "Care-leave periods linked to the same income cannot overlap"
                            )

            item_index = month["items"].index(item)
            month["items"][item_index] = candidate_item
            await self._async_rebuild_all_care_leave_effects()
            await self._async_commit()
            return deepcopy(period)

    async def async_delete_care_leave_period(
        self, month_key: str, item_id: str, period_id: str
    ) -> None:
        """Remove one care-leave period and rebuild generated effects."""
        validate_month_key(month_key)
        async with self._lock:
            month = self._require_month(month_key)
            item = next(
                (candidate for candidate in month["items"] if candidate["id"] == item_id),
                None,
            )
            if item is None or item.get("expense_type") != CARE_LEAVE_TYPE:
                raise BudgetValidationError("Child-care leave item does not exist")
            periods = item["care_leave"]["periods"]
            filtered = [period for period in periods if period["id"] != period_id]
            if len(filtered) == len(periods):
                raise BudgetValidationError("Care-leave period does not exist")
            item["care_leave"]["periods"] = filtered
            await self._async_rebuild_all_care_leave_effects()
            await self._async_commit()

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
            if item.get("generated_type") == GENERATED_BENEFIT_TYPE:
                raise BudgetValidationError(
                    "Delete the source care-leave period to remove this automatic income"
                )
            if scope == "future" and item.get("series_id"):
                series_id = item["series_id"]
                for key, stored_month in self._data["months"].items():
                    if key < month_key:
                        continue
                    for candidate in stored_month["items"]:
                        if (
                            candidate.get("series_id") == series_id
                            and candidate.get("status", STATUS_PENDING)
                            == STATUS_PENDING
                        ):
                            self._assert_income_not_linked_to_care_leave(
                                candidate, key
                            )
                    stored_month["items"] = [
                        candidate
                        for candidate in stored_month["items"]
                        if not (
                            candidate.get("series_id") == series_id
                            and candidate.get("status", STATUS_PENDING) == STATUS_PENDING
                        )
                    ]
            else:
                self._assert_income_not_linked_to_care_leave(item, month_key)
                month["items"].remove(item)
            await self._async_rebuild_all_care_leave_effects()
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
            if item.get("expense_type") == CARE_LEAVE_TYPE:
                raise BudgetValidationError(
                    "Child-care leave periods are managed from the care-leave editor"
                )
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
