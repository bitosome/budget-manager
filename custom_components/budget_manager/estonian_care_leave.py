"""Estonian child-care leave validation and planning estimates."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


CARE_LEAVE_TYPE = "child_care_leave"
GENERATED_BENEFIT_TYPE = "tervisekassa_care_benefit"
CARE_BENEFIT_RATE = Decimal("0.80")
CARE_BENEFIT_WITHHOLDING_RATE = Decimal("0.22")
CARE_BENEFIT_MAX_DAYS = 60
CARE_BENEFIT_DAILY_CAPS = {2026: Decimal("126.87")}
VALID_BENEFIT_BASIS_MODES = {
    "estimated_hourly",
    "actual_previous_year_income",
}


class EstonianCareLeaveError(ValueError):
    """Raised when a care-leave definition is invalid."""


def _decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise EstonianCareLeaveError(f"{label} must be a number") from err
    if not number.is_finite() or number < 0:
        raise EstonianCareLeaveError(
            f"{label} must be a non-negative finite number"
        )
    return number


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), ROUND_HALF_UP))


def iter_period_dates(start: date, end: date) -> Iterable[date]:
    """Yield every calendar date in an inclusive care-leave period."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def normalize_care_period(raw: Any, *, existing_id: str | None = None) -> dict[str, Any]:
    """Validate one inclusive care-leave period."""
    if not isinstance(raw, dict):
        raise EstonianCareLeaveError("Care-leave period must be an object")
    try:
        start = date.fromisoformat(str(raw.get("start", "")))
        end = date.fromisoformat(str(raw.get("end", "")))
    except ValueError as err:
        raise EstonianCareLeaveError(
            "Care-leave period requires valid start and end dates"
        ) from err
    if end < start:
        raise EstonianCareLeaveError(
            "Care-leave period end cannot be before its start"
        )
    calendar_days = (end - start).days + 1
    if calendar_days > CARE_BENEFIT_MAX_DAYS:
        raise EstonianCareLeaveError(
            f"One child-care leave period cannot exceed {CARE_BENEFIT_MAX_DAYS} days"
        )
    normalized = {
        "id": str(existing_id or raw.get("id") or ""),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "calculation": None,
    }
    calculation = raw.get("calculation")
    if isinstance(calculation, dict):
        normalized["calculation"] = dict(calculation)
    return normalized


def normalize_care_leave(raw: Any, *, enabled: bool) -> dict[str, Any] | None:
    """Validate a child-care leave container and its periods."""
    if not enabled:
        return None
    if not isinstance(raw, dict):
        raise EstonianCareLeaveError("Child-care leave settings are required")
    linked_income_item_id = str(raw.get("linked_income_item_id") or "")
    if not linked_income_item_id:
        raise EstonianCareLeaveError(
            "Child-care leave must be linked to an hourly income"
        )
    work_month = str(raw.get("work_month") or "")
    income_month = str(raw.get("income_month") or "")
    for label, month_key in (
        ("Care-leave work month", work_month),
        ("Care-leave income month", income_month),
    ):
        try:
            parsed_month = date.fromisoformat(f"{month_key}-01")
        except ValueError as err:
            raise EstonianCareLeaveError(
                f"{label} must use YYYY-MM format"
            ) from err
        if parsed_month.strftime("%Y-%m") != month_key:
            raise EstonianCareLeaveError(
                f"{label} must use YYYY-MM format"
            )
    periods_raw = raw.get("periods", [])
    if not isinstance(periods_raw, list) or len(periods_raw) > 100:
        raise EstonianCareLeaveError(
            "Child-care leave periods must be a list of at most 100 entries"
        )
    periods: list[dict[str, Any]] = []
    occupied: set[date] = set()
    seen_ids: set[str] = set()
    for period_raw in periods_raw:
        period = normalize_care_period(period_raw)
        if not period["id"] or period["id"] in seen_ids:
            raise EstonianCareLeaveError(
                "Every care-leave period requires a unique id"
            )
        seen_ids.add(period["id"])
        start = date.fromisoformat(period["start"])
        end = date.fromisoformat(period["end"])
        if start.strftime("%Y-%m") != work_month or end.strftime("%Y-%m") != work_month:
            raise EstonianCareLeaveError(
                "Care-leave periods must stay within the selected work month"
            )
        dates = set(iter_period_dates(start, end))
        if occupied.intersection(dates):
            raise EstonianCareLeaveError("Care-leave periods cannot overlap")
        occupied.update(dates)
        periods.append(period)
    periods.sort(key=lambda period: (period["start"], period["end"]))
    benefit_basis_mode = str(
        raw.get("benefit_basis_mode", "estimated_hourly")
    )
    if benefit_basis_mode not in VALID_BENEFIT_BASIS_MODES:
        raise EstonianCareLeaveError("Unsupported care-benefit income basis")
    actual_previous_year_income = _decimal(
        raw.get("actual_previous_year_income", 0),
        "Previous-year social-taxable income",
    )
    if benefit_basis_mode == "actual_previous_year_income" and actual_previous_year_income <= 0:
        raise EstonianCareLeaveError(
            "Previous-year social-taxable income must be greater than zero"
        )
    return {
        "linked_income_item_id": linked_income_item_id,
        "linked_income_series_id": str(raw.get("linked_income_series_id") or ""),
        "linked_income_name": str(raw.get("linked_income_name") or "").strip(),
        "work_month": work_month,
        "income_month": income_month,
        "periods": periods,
        "benefit_basis_mode": benefit_basis_mode,
        "actual_previous_year_income": _money(actual_previous_year_income),
        "estimated": True,
    }


def calculate_care_period(
    period: dict[str, Any],
    *,
    hourly_gross: float,
    previous_year_working_hours: float,
    benefit_basis_mode: str = "estimated_hourly",
    actual_previous_year_income: float = 0,
    public_holidays: Iterable[str],
    shortened_workdays: Iterable[str],
    benefit_year: int,
) -> dict[str, Any]:
    """Estimate missed salary hours and the net Tervisekassa benefit."""
    normalized = normalize_care_period(period, existing_id=str(period.get("id") or ""))
    start = date.fromisoformat(normalized["start"])
    end = date.fromisoformat(normalized["end"])
    dates = list(iter_period_dates(start, end))
    holidays = {date.fromisoformat(value) for value in public_holidays}
    shortened = {date.fromisoformat(value) for value in shortened_workdays}
    working_dates = [
        value for value in dates if value.weekday() < 5 and value not in holidays
    ]
    missed_hours = sum(
        (Decimal("5") if value in shortened else Decimal("8") for value in working_dates),
        Decimal("0"),
    )

    hourly_rate = _decimal(hourly_gross, "Hourly gross")
    annual_hours = _decimal(
        previous_year_working_hours, "Previous-year working hours"
    )
    if benefit_basis_mode not in VALID_BENEFIT_BASIS_MODES:
        raise EstonianCareLeaveError("Unsupported care-benefit income basis")
    if benefit_basis_mode == "actual_previous_year_income":
        estimated_annual_gross = _decimal(
            actual_previous_year_income,
            "Previous-year social-taxable income",
        )
        if estimated_annual_gross <= 0:
            raise EstonianCareLeaveError(
                "Previous-year social-taxable income must be greater than zero"
            )
    else:
        estimated_annual_gross = hourly_rate * annual_hours
    estimated_daily_income = estimated_annual_gross / Decimal("365")
    uncapped_daily_benefit = estimated_daily_income * CARE_BENEFIT_RATE
    known_cap_years = [year for year in CARE_BENEFIT_DAILY_CAPS if year <= benefit_year]
    cap_year = max(known_cap_years) if known_cap_years else None
    cap = CARE_BENEFIT_DAILY_CAPS[cap_year] if cap_year is not None else None
    daily_benefit = min(uncapped_daily_benefit, cap) if cap is not None else uncapped_daily_benefit
    gross_benefit = daily_benefit * len(dates)
    withholding = gross_benefit * CARE_BENEFIT_WITHHOLDING_RATE
    net_benefit = gross_benefit - withholding

    return {
        "calendar_days": len(dates),
        "missed_working_days": len(working_dates),
        "missed_working_hours": _money(missed_hours),
        "estimated_previous_year_working_hours": _money(annual_hours),
        "estimated_previous_year_gross": _money(estimated_annual_gross),
        "benefit_basis_mode": benefit_basis_mode,
        "estimated_daily_income": _money(estimated_daily_income),
        "benefit_rate": float(CARE_BENEFIT_RATE),
        "uncapped_daily_benefit": _money(uncapped_daily_benefit),
        "daily_cap": _money(cap) if cap is not None else None,
        "daily_cap_year": cap_year,
        "estimated_daily_benefit": _money(daily_benefit),
        "estimated_gross_benefit": _money(gross_benefit),
        "withholding_rate": float(CARE_BENEFIT_WITHHOLDING_RATE),
        "estimated_withholding": _money(withholding),
        "estimated_net_benefit": _money(net_benefit),
        "estimated_gross_salary_reduction": _money(hourly_rate * missed_hours),
        "estimated": True,
        "rules_year": 2026,
    }
