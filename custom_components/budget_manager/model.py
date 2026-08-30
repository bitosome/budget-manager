"""Pure budget model, validation, calculations, and period-copy operations."""

from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
import re
from typing import Any
from uuid import uuid4

from .const import (
    DEFAULT_CYCLE_END_DAY,
    DEFAULT_CURRENCY,
    DEFAULT_DAILY_GREEN_THRESHOLD,
    DEFAULT_DAILY_YELLOW_THRESHOLD,
    DEFAULT_SAVINGS_FLOOR_THRESHOLD,
    DEFAULT_SAVINGS_TARGET_THRESHOLD,
    DEFAULT_LOCALE,
    EXPORT_FORMAT,
    EXPORT_VERSION,
    KIND_EXPENSE,
    KIND_INCOME,
    KIND_SAVINGS,
    RECURRENCE_SINGLE,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_RECEIVED,
    STATUS_SKIPPED,
    VALID_KINDS,
    VALID_RECURRENCES,
    VALID_STATUSES,
)

MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class BudgetValidationError(ValueError):
    """Raised when budget data is invalid."""


def new_id() -> str:
    """Return a stable random identifier."""
    return uuid4().hex


def validate_month_key(value: str) -> str:
    """Validate and normalize a YYYY-MM month key."""
    if not isinstance(value, str) or MONTH_PATTERN.fullmatch(value) is None:
        raise BudgetValidationError("Month must use YYYY-MM format")
    return value


def month_parts(month_key: str) -> tuple[int, int]:
    """Return year and month from a validated month key."""
    validate_month_key(month_key)
    year, month = month_key.split("-")
    return int(year), int(month)


def money(value: Any) -> float:
    """Normalize money to two decimal places."""
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as err:
        raise BudgetValidationError("Amount must be a number") from err
    if not number.is_finite() or number < 0:
        raise BudgetValidationError("Amount must be a non-negative finite number")
    return float(number)


def clamp_day(year: int, month: int, day: int) -> int:
    """Clamp a day-of-month to the target month."""
    return min(max(1, int(day)), monthrange(year, month)[1])


def normalize_cycle_end_day(value: Any = DEFAULT_CYCLE_END_DAY) -> int:
    """Validate the day in the following month that ends a budget cycle."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise BudgetValidationError("Cycle end day must be a number") from err
    if not number.is_finite() or number != number.to_integral_value():
        raise BudgetValidationError("Cycle end day must be a whole number")
    cycle_end_day = int(number)
    if not 1 <= cycle_end_day <= 31:
        raise BudgetValidationError("Cycle end day must be between 1 and 31")
    return cycle_end_day


def due_date(month_key: str, due_day: int | None) -> date:
    """Return an item's concrete due date within a budget month."""
    year, month = month_parts(month_key)
    day = clamp_day(year, month, due_day or 1)
    return date(year, month, day)


def default_payday(
    month_key: str, cycle_end_day: int = DEFAULT_CYCLE_END_DAY
) -> str:
    """Return the configured cycle end in the month after a budget month."""
    year, month = month_parts(month_key)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    day = clamp_day(next_year, next_month, normalize_cycle_end_day(cycle_end_day))
    return date(next_year, next_month, day).isoformat()


def shift_period_date(source_month: str, target_month: str, value: str | None) -> str:
    """Shift an ISO date preserving its month offset and day within a period."""
    if not value:
        return default_payday(target_month)
    try:
        source_date = date.fromisoformat(value)
    except ValueError:
        return default_payday(target_month)

    source_year, source_month_number = month_parts(source_month)
    target_year, target_month_number = month_parts(target_month)
    source_index = source_year * 12 + source_month_number - 1
    date_index = source_date.year * 12 + source_date.month - 1
    month_offset = date_index - source_index
    target_index = target_year * 12 + target_month_number - 1 + month_offset
    shifted_year, shifted_zero_month = divmod(target_index, 12)
    shifted_month = shifted_zero_month + 1
    shifted_day = clamp_day(shifted_year, shifted_month, source_date.day)
    return date(shifted_year, shifted_month, shifted_day).isoformat()


def empty_data() -> dict[str, Any]:
    """Return a new empty storage document."""
    return {
        "schema_version": 4,
        "settings": {
            "currency": DEFAULT_CURRENCY,
            "locale": DEFAULT_LOCALE,
            "configured": True,
            "cycle_end_day": DEFAULT_CYCLE_END_DAY,
            "daily_green_threshold": DEFAULT_DAILY_GREEN_THRESHOLD,
            "daily_yellow_threshold": DEFAULT_DAILY_YELLOW_THRESHOLD,
            "savings_target_threshold": DEFAULT_SAVINGS_TARGET_THRESHOLD,
            "savings_floor_threshold": DEFAULT_SAVINGS_FLOOR_THRESHOLD,
        },
        "months": {},
    }


def make_month(
    month_key: str,
    *,
    source: str | None = None,
    cycle_end_day: int = DEFAULT_CYCLE_END_DAY,
) -> dict[str, Any]:
    """Create a blank budget month."""
    validate_month_key(month_key)
    return {
        "month": month_key,
        "account_balance": 0.0,
        "balance_updated_at": None,
        "payday": default_payday(month_key, cycle_end_day),
        "created_from": source,
        "items": [],
    }


def normalize_item(raw: dict[str, Any], *, existing_id: str | None = None) -> dict[str, Any]:
    """Validate and normalize one income or expense occurrence."""
    if not isinstance(raw, dict):
        raise BudgetValidationError("Item must be an object")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise BudgetValidationError("Item name is required")
    kind = str(raw.get("kind", KIND_EXPENSE))
    if kind not in VALID_KINDS:
        raise BudgetValidationError("Item kind must be income, expense, or savings")
    status = str(raw.get("status", STATUS_PENDING))
    if status not in VALID_STATUSES:
        raise BudgetValidationError("Invalid item status")
    if kind == KIND_INCOME and status == STATUS_PAID:
        status = STATUS_RECEIVED
    if kind in {KIND_EXPENSE, KIND_SAVINGS} and status == STATUS_RECEIVED:
        status = STATUS_PAID

    due_day_raw = raw.get("due_day")
    try:
        due_day = None if due_day_raw in (None, "") else int(due_day_raw)
    except (TypeError, ValueError) as err:
        raise BudgetValidationError("Due day must be a number") from err
    if due_day is not None and not 1 <= due_day <= 31:
        raise BudgetValidationError("Due day must be between 1 and 31")

    recurrence = str(raw.get("recurrence", RECURRENCE_SINGLE))
    if recurrence not in VALID_RECURRENCES:
        raise BudgetValidationError("Recurrence must be single, monthly, or yearly")
    recurrence_end = raw.get("recurrence_end")
    if recurrence != RECURRENCE_SINGLE:
        if not recurrence_end:
            raise BudgetValidationError("Recurring items require an end date")
        try:
            recurrence_end_date = date.fromisoformat(str(recurrence_end))
        except ValueError as err:
            raise BudgetValidationError("Recurrence end must be an ISO date") from err
        recurrence_end = recurrence_end_date.isoformat()
    else:
        recurrence_end = None

    paid_at = raw.get("paid_at")
    if paid_at is not None:
        try:
            datetime.fromisoformat(str(paid_at).replace("Z", "+00:00"))
        except ValueError as err:
            raise BudgetValidationError("paid_at must be an ISO timestamp") from err

    try:
        sort_order = int(raw.get("sort_order", 0))
    except (TypeError, ValueError) as err:
        raise BudgetValidationError("Sort order must be a number") from err

    return {
        "id": existing_id or str(raw.get("id") or new_id()),
        "name": name,
        "kind": kind,
        "amount": money(raw.get("amount", 0)),
        "due_day": due_day,
        "status": status,
        "paid_at": paid_at,
        "category": str(raw.get("category", "")).strip(),
        "special": bool(raw.get("special", False)),
        "special_label": str(raw.get("special_label", "Renewal")).strip()
        if raw.get("special", False)
        else "",
        "notes": str(raw.get("notes", "")).strip(),
        "sort_order": sort_order,
        "series_id": str(raw.get("series_id") or new_id())
        if recurrence != RECURRENCE_SINGLE
        else None,
        "recurrence": recurrence,
        "recurrence_end": recurrence_end,
        "dynamic": bool(raw.get("dynamic", kind == KIND_SAVINGS))
        if kind == KIND_SAVINGS
        else False,
    }


def copy_month_data(
    source_month: dict[str, Any],
    source_key: str,
    target_key: str,
    *,
    series_map: dict[str, str] | None = None,
    cycle_end_day: int = DEFAULT_CYCLE_END_DAY,
) -> dict[str, Any]:
    """Copy a month as a clean future plan."""
    validate_month_key(source_key)
    validate_month_key(target_key)
    target = make_month(
        target_key, source=source_key, cycle_end_day=cycle_end_day
    )
    target["items"] = []
    for raw in source_month.get("items", []):
        item = deepcopy(raw)
        item["id"] = new_id()
        item["status"] = STATUS_PENDING
        item["paid_at"] = None
        if item.get("series_id"):
            series_map = series_map if series_map is not None else {}
            item["series_id"] = series_map.setdefault(item["series_id"], new_id())
            if item.get("recurrence_end"):
                item["recurrence_end"] = shift_period_date(
                    source_key, target_key, item["recurrence_end"]
                )
        target["items"].append(normalize_item(item))
    return target


def iter_recurrence_months(
    start_month: str, recurrence: str, recurrence_end: str
) -> list[str]:
    """Return inclusive month keys for a bounded recurrence."""
    validate_month_key(start_month)
    if recurrence not in VALID_RECURRENCES - {RECURRENCE_SINGLE}:
        raise BudgetValidationError("A recurring frequency is required")
    try:
        end_date = date.fromisoformat(recurrence_end)
    except ValueError as err:
        raise BudgetValidationError("Recurrence end must be an ISO date") from err
    end_month = end_date.strftime("%Y-%m")
    if end_month < start_month:
        raise BudgetValidationError("Recurrence end cannot be before its start month")

    start_year, start_month_number = month_parts(start_month)
    end_year, end_month_number = month_parts(end_month)
    start_index = start_year * 12 + start_month_number - 1
    end_index = end_year * 12 + end_month_number - 1
    step = 1 if recurrence == "monthly" else 12
    result: list[str] = []
    for index in range(start_index, end_index + 1, step):
        year, zero_month = divmod(index, 12)
        result.append(f"{year:04d}-{zero_month + 1:02d}")
    return result


def item_is_open(item: dict[str, Any]) -> bool:
    """Return whether an item still contributes to the forecast."""
    return item.get("status", STATUS_PENDING) == STATUS_PENDING


def normalize_thresholds(settings: dict[str, Any] | None = None) -> tuple[float, float]:
    """Validate and return green/yellow daily allowance thresholds."""
    settings = settings or {}
    try:
        green = float(
            settings.get("daily_green_threshold", DEFAULT_DAILY_GREEN_THRESHOLD)
        )
        yellow = float(
            settings.get("daily_yellow_threshold", DEFAULT_DAILY_YELLOW_THRESHOLD)
        )
    except (TypeError, ValueError) as err:
        raise BudgetValidationError("Daily thresholds must be numbers") from err
    if not isfinite(green) or not isfinite(yellow) or green < 0 or yellow < 0:
        raise BudgetValidationError("Daily thresholds must be finite and non-negative")
    if yellow > green:
        raise BudgetValidationError("Yellow threshold cannot exceed green threshold")
    return green, yellow


def normalize_savings_thresholds(
    settings: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Validate and return the automatic-savings target and floor."""
    settings = settings or {}
    try:
        target = float(
            settings.get(
                "savings_target_threshold", DEFAULT_SAVINGS_TARGET_THRESHOLD
            )
        )
        floor = float(
            settings.get("savings_floor_threshold", DEFAULT_SAVINGS_FLOOR_THRESHOLD)
        )
    except (TypeError, ValueError) as err:
        raise BudgetValidationError("Savings thresholds must be numbers") from err
    if not isfinite(target) or not isfinite(floor) or target < 0 or floor < 0:
        raise BudgetValidationError("Savings thresholds must be finite and non-negative")
    if floor > target:
        raise BudgetValidationError("Savings floor cannot exceed savings target")
    return target, floor


def export_data_document(data: dict[str, Any]) -> dict[str, Any]:
    """Return a portable, versioned Budget Manager JSON document."""
    defaults = empty_data()["settings"]
    settings = data.get("settings", {})
    portable_settings = {
        "currency": str(settings.get("currency", defaults["currency"])),
        "locale": str(settings.get("locale", defaults["locale"])),
        "cycle_end_day": normalize_cycle_end_day(
            settings.get("cycle_end_day", defaults["cycle_end_day"])
        ),
        "daily_green_threshold": float(
            settings.get(
                "daily_green_threshold", defaults["daily_green_threshold"]
            )
        ),
        "daily_yellow_threshold": float(
            settings.get(
                "daily_yellow_threshold", defaults["daily_yellow_threshold"]
            )
        ),
        "savings_target_threshold": float(
            settings.get(
                "savings_target_threshold", defaults["savings_target_threshold"]
            )
        ),
        "savings_floor_threshold": float(
            settings.get(
                "savings_floor_threshold", defaults["savings_floor_threshold"]
            )
        ),
    }
    months: dict[str, Any] = {}
    for month_key, raw_month in sorted(data.get("months", {}).items()):
        months[month_key] = {
            "month": month_key,
            "account_balance": money(raw_month.get("account_balance", 0)),
            "balance_updated_at": raw_month.get("balance_updated_at"),
            "payday": raw_month.get("payday") or default_payday(month_key),
            "items": deepcopy(raw_month.get("items", [])),
        }
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "settings": portable_settings,
        "months": months,
    }


def normalize_import_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate a portable JSON document and return internal storage data."""
    if not isinstance(document, dict):
        raise BudgetValidationError("Import must contain a JSON object")
    if document.get("format") != EXPORT_FORMAT:
        raise BudgetValidationError("Not a Budget Manager export")
    try:
        version = int(document.get("version"))
    except (TypeError, ValueError) as err:
        raise BudgetValidationError("Import version must be a number") from err
    if version != EXPORT_VERSION:
        raise BudgetValidationError(f"Unsupported import version: {version}")

    raw_settings = document.get("settings", {})
    if not isinstance(raw_settings, dict):
        raise BudgetValidationError("Import settings must be an object")
    defaults = empty_data()["settings"]
    green, yellow = normalize_thresholds(raw_settings)
    savings_target, savings_floor = normalize_savings_thresholds(raw_settings)
    cycle_end_day = normalize_cycle_end_day(
        raw_settings.get("cycle_end_day", defaults["cycle_end_day"])
    )
    currency = str(raw_settings.get("currency", defaults["currency"])).strip()
    locale = str(raw_settings.get("locale", defaults["locale"])).strip()
    if not currency or not locale:
        raise BudgetValidationError("Currency and locale cannot be empty")

    raw_months = document.get("months")
    if not isinstance(raw_months, dict):
        raise BudgetValidationError("Import months must be an object")
    if len(raw_months) > 2400:
        raise BudgetValidationError("Import cannot contain more than 2400 months")
    result = empty_data()
    result["settings"].update(
        {
            "currency": currency,
            "locale": locale,
            "configured": True,
            "cycle_end_day": cycle_end_day,
            "daily_green_threshold": green,
            "daily_yellow_threshold": yellow,
            "savings_target_threshold": savings_target,
            "savings_floor_threshold": savings_floor,
        }
    )
    seen_item_ids: set[str] = set()
    for month_key, raw_month in sorted(raw_months.items()):
        validate_month_key(month_key)
        if not isinstance(raw_month, dict):
            raise BudgetValidationError(f"Month {month_key} must be an object")
        embedded_key = raw_month.get("month", month_key)
        if embedded_key != month_key:
            raise BudgetValidationError(
                f"Month key {month_key} does not match {embedded_key}"
            )
        month = make_month(month_key, cycle_end_day=cycle_end_day)
        month["account_balance"] = money(raw_month.get("account_balance", 0))
        balance_updated_at = raw_month.get("balance_updated_at")
        if balance_updated_at is not None:
            try:
                datetime.fromisoformat(str(balance_updated_at).replace("Z", "+00:00"))
            except ValueError as err:
                raise BudgetValidationError(
                    f"Month {month_key} has an invalid balance timestamp"
                ) from err
            month["balance_updated_at"] = str(balance_updated_at)
        raw_items = raw_month.get("items", [])
        if not isinstance(raw_items, list):
            raise BudgetValidationError(f"Month {month_key} items must be a list")
        if len(raw_items) > 10000:
            raise BudgetValidationError(
                f"Month {month_key} cannot contain more than 10000 items"
            )
        for raw_item in raw_items:
            try:
                item = normalize_item(raw_item)
            except BudgetValidationError as err:
                raise BudgetValidationError(
                    f"Month {month_key} contains an invalid item: {err}"
                ) from err
            if item["id"] in seen_item_ids:
                raise BudgetValidationError(f"Duplicate item id: {item['id']}")
            seen_item_ids.add(item["id"])
            month["items"].append(item)
        result["months"][month_key] = month
    return result


def calculate_month(
    month: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Calculate forecast and daily allowance for a budget month."""
    today = today or date.today()
    month_key = validate_month_key(month["month"])
    year, month_number = month_parts(month_key)
    items = month.get("items", [])
    green_threshold, yellow_threshold = normalize_thresholds(settings)
    savings_target_threshold, savings_floor_threshold = (
        normalize_savings_thresholds(settings)
    )

    expected_income = sum(
        money(item.get("amount", 0))
        for item in items
        if item.get("kind") == KIND_INCOME and item_is_open(item)
    )
    unpaid_expenses = sum(
        money(item.get("amount", 0))
        for item in items
        if item.get("kind") == KIND_EXPENSE and item_is_open(item)
    )
    total_income = sum(
        money(item.get("amount", 0))
        for item in items
        if item.get("kind") == KIND_INCOME
    )
    total_expenses = sum(
        money(item.get("amount", 0))
        for item in items
        if item.get("kind") == KIND_EXPENSE
    )
    account_balance = money(month.get("account_balance", 0))

    try:
        payday = date.fromisoformat(month.get("payday") or default_payday(month_key))
    except ValueError:
        cycle_end_day = normalize_cycle_end_day(
            (settings or {}).get("cycle_end_day", DEFAULT_CYCLE_END_DAY)
        )
        payday = date.fromisoformat(default_payday(month_key, cycle_end_day))
    days_in_month = monthrange(year, month_number)[1]
    days_until_payday = max(1, (payday - today).days + 1)
    divisor = min(days_in_month, days_until_payday)

    open_savings = [
        item
        for item in items
        if item.get("kind") == KIND_SAVINGS and item_is_open(item)
    ]
    fixed_savings = sum(
        money(item.get("amount", 0))
        for item in open_savings
        if not item.get("dynamic", True)
    )
    dynamic_savings_items = [
        item for item in open_savings if item.get("dynamic", True)
    ]
    baseline_dynamic_savings = sum(
        money(item.get("amount", 0)) for item in dynamic_savings_items
    )
    before_dynamic_savings = (
        account_balance + expected_income - unpaid_expenses - fixed_savings
    )
    minimum_dynamic_savings = max(
        0.0, before_dynamic_savings - savings_target_threshold * divisor
    )
    maximum_dynamic_savings = max(
        0.0, before_dynamic_savings - savings_floor_threshold * divisor
    )
    dynamic_savings = (
        min(
            max(baseline_dynamic_savings, minimum_dynamic_savings),
            maximum_dynamic_savings,
        )
        if dynamic_savings_items
        else 0.0
    )
    dynamic_savings = round(dynamic_savings, 2)
    effective_amounts = {
        item["id"]: money(item.get("amount", 0)) for item in items
    }
    if dynamic_savings_items:
        remaining_cents = round(dynamic_savings * 100)
        for index, item in enumerate(dynamic_savings_items):
            if index == len(dynamic_savings_items) - 1:
                item_cents = remaining_cents
            elif baseline_dynamic_savings:
                item_cents = round(
                    dynamic_savings
                    * money(item.get("amount", 0))
                    / baseline_dynamic_savings
                    * 100
                )
            else:
                item_cents = round(
                    dynamic_savings / len(dynamic_savings_items) * 100
                )
            item_cents = max(0, min(item_cents, remaining_cents))
            effective_amounts[item["id"]] = item_cents / 100
            remaining_cents -= item_cents
    planned_savings = fixed_savings + dynamic_savings
    baseline_remaining = before_dynamic_savings - baseline_dynamic_savings
    total_savings = sum(
        effective_amounts[item["id"]]
        for item in items
        if item.get("kind") == KIND_SAVINGS
    )
    remaining = before_dynamic_savings - dynamic_savings
    daily_allowance = remaining / divisor if divisor else 0
    rag = (
        "green"
        if daily_allowance >= green_threshold
        else "yellow"
        if daily_allowance >= yellow_threshold
        else "red"
    )

    paid_count = sum(
        1
        for item in items
        if item.get("status") in (STATUS_PAID, STATUS_RECEIVED)
    )
    pending_count = sum(1 for item in items if item_is_open(item))

    return {
        "month": month_key,
        "account_balance": round(account_balance, 2),
        "expected_income": round(expected_income, 2),
        "unpaid_expenses": round(unpaid_expenses, 2),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "planned_savings": round(planned_savings, 2),
        "baseline_savings": round(fixed_savings + baseline_dynamic_savings, 2),
        "dynamic_savings": round(dynamic_savings, 2),
        "savings_adjustment": round(
            dynamic_savings - baseline_dynamic_savings, 2
        ),
        "baseline_remaining": round(baseline_remaining, 2),
        "baseline_daily_allowance": round(
            baseline_remaining / divisor if divisor else 0, 2
        ),
        "total_savings": round(total_savings, 2),
        "remaining": round(remaining, 2),
        "daily_allowance": round(daily_allowance, 2),
        "rag": rag,
        "green_threshold": green_threshold,
        "yellow_threshold": yellow_threshold,
        "savings_target_threshold": savings_target_threshold,
        "savings_floor_threshold": savings_floor_threshold,
        "effective_amounts": effective_amounts,
        "days_divisor": divisor,
        "pending_count": pending_count,
        "paid_count": paid_count,
    }


def calculate_year(
    data: dict[str, Any], year: int, *, today: date | None = None
) -> dict[str, Any]:
    """Return all 12 month slots and full-year totals."""
    months: list[dict[str, Any]] = []
    totals = {
        "expected_income": 0.0,
        "unpaid_expenses": 0.0,
        "total_income": 0.0,
        "total_expenses": 0.0,
        "planned_savings": 0.0,
        "total_savings": 0.0,
        "remaining": 0.0,
    }
    stored_months = data.get("months", {})
    for month_number in range(1, 13):
        month_key = f"{year:04d}-{month_number:02d}"
        raw = stored_months.get(month_key)
        if raw is None:
            months.append({"month": month_key, "exists": False})
            continue
        summary = calculate_month(raw, settings=data.get("settings"), today=today)
        summary["exists"] = True
        months.append(summary)
        for key in totals:
            totals[key] += summary[key]
    return {
        "year": year,
        "months": months,
        "totals": {key: round(value, 2) for key, value in totals.items()},
    }


def current_month_key(data: dict[str, Any], *, today: date | None = None) -> str | None:
    """Return current month, nearest future month, or latest available month."""
    today = today or date.today()
    keys = sorted(data.get("months", {}))
    if not keys:
        return None
    current = today.strftime("%Y-%m")
    if current in keys:
        return current
    return next((key for key in keys if key > current), keys[-1])


def event_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand stored items into calendar-friendly event rows."""
    events: list[dict[str, Any]] = []
    for month_key, month in sorted(data.get("months", {}).items()):
        summary = calculate_month(month, settings=data.get("settings"))
        for item in month.get("items", []):
            if item.get("status") == STATUS_SKIPPED or item.get("due_day") is None:
                continue
            events.append(
                {
                    "uid": item["id"],
                    "month": month_key,
                    "date": due_date(month_key, item.get("due_day")),
                    "name": item["name"],
                    "kind": item["kind"],
                    "amount": summary["effective_amounts"].get(
                        item["id"], money(item.get("amount", 0))
                    ),
                    "status": item.get("status", STATUS_PENDING),
                    "special": bool(item.get("special", False)),
                    "special_label": item.get("special_label", ""),
                    "notes": item.get("notes", ""),
                }
            )
    return events


def next_day(value: date) -> date:
    """Return the exclusive end date for an all-day calendar event."""
    return value + timedelta(days=1)
