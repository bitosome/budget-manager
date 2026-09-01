"""Estonian working-time and payroll calculations."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


PAYROLL_MODE = "estonian_hourly"
DEFAULT_HOURS_PER_DAY = Decimal("8")
DEFAULT_TAX_FREE_INCOME = Decimal("700")
INCOME_TAX_RATE = Decimal("22")
SOCIAL_TAX_RATE = Decimal("33")
SOCIAL_TAX_MINIMUM_BASE = Decimal("886")
EMPLOYEE_UNEMPLOYMENT_RATE = Decimal("1.6")
EMPLOYER_UNEMPLOYMENT_RATE = Decimal("0.8")
VALID_FUNDED_PENSION_RATES = {0, 2, 4, 6}
KNOWN_TAX_RULES_YEAR = 2026


class EstonianPayrollError(ValueError):
    """Raised when an Estonian payroll input is invalid."""


def _decimal(value: Any, label: str, *, allow_zero: bool = True) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise EstonianPayrollError(f"{label} must be a number") from err
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise EstonianPayrollError(f"{label} must be a {qualifier} finite number")
    return number


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), ROUND_HALF_UP))


def easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the anonymous algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    length = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * length) // 451
    month = (h + length - 7 * m + 114) // 31
    day = (h + length - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def statutory_estonian_holidays(year: int) -> set[date]:
    """Return Estonian national/public holidays established by law."""
    easter = easter_sunday(year)
    return {
        date(year, 1, 1),
        date(year, 2, 24),
        easter - timedelta(days=2),
        easter,
        date(year, 5, 1),
        easter + timedelta(days=49),
        date(year, 6, 23),
        date(year, 6, 24),
        date(year, 8, 20),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def _previous_working_day(value: date, holidays: set[date]) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate -= timedelta(days=1)
    return candidate


def estonian_working_time(
    month_key: str,
    holidays: Iterable[date],
    *,
    hours_per_day: float | Decimal = DEFAULT_HOURS_PER_DAY,
) -> dict[str, Any]:
    """Calculate the standard Estonian work-time fund for one month."""
    try:
        year, month = (int(part) for part in month_key.split("-"))
        date(year, month, 1)
    except (TypeError, ValueError) as err:
        raise EstonianPayrollError("Month must use YYYY-MM format") from err
    daily_hours = _decimal(hours_per_day, "Hours per workday", allow_zero=False)
    holiday_set = set(holidays)
    days = [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]
    working_days = [day for day in days if day.weekday() < 5 and day not in holiday_set]

    shortened_dates: set[date] = set()
    for rule_year in (year, year + 1):
        for holiday in (
            date(rule_year, 1, 1),
            date(rule_year, 2, 24),
            date(rule_year, 6, 23),
            date(rule_year, 12, 24),
        ):
            shortened = _previous_working_day(holiday, holiday_set)
            if shortened.year == year and shortened.month == month:
                shortened_dates.add(shortened)

    working_hours = daily_hours * len(working_days) - Decimal("3") * len(shortened_dates)
    month_holidays = sorted(day.isoformat() for day in holiday_set if day.year == year and day.month == month)
    return {
        "month": month_key,
        "working_days": len(working_days),
        "working_hours": _money(working_hours),
        "hours_per_day": _money(daily_hours),
        "public_holidays": month_holidays,
        "shortened_workdays": sorted(day.isoformat() for day in shortened_dates),
    }


def normalize_income_calculation(raw: Any, *, is_income: bool) -> dict[str, Any] | None:
    """Validate the optional Estonian hourly-income configuration."""
    if not is_income or raw in (None, {}, False):
        return None
    if not isinstance(raw, dict) or raw.get("mode") != PAYROLL_MODE:
        raise EstonianPayrollError("Unsupported income calculation mode")
    hourly_gross = _decimal(raw.get("hourly_gross"), "Hourly gross", allow_zero=False)
    working_hours_mode = str(raw.get("working_hours_mode", "automatic"))
    if working_hours_mode not in {"automatic", "manual"}:
        raise EstonianPayrollError("Working hours mode must be automatic or manual")
    working_hours = _decimal(raw.get("working_hours", 0), "Working hours")
    if working_hours_mode == "manual" and working_hours == 0:
        raise EstonianPayrollError("Manual working hours must be greater than zero")
    tax_free_income = _decimal(
        raw.get("tax_free_income", DEFAULT_TAX_FREE_INCOME), "Tax-free income"
    )
    try:
        pension_rate = int(raw.get("funded_pension_rate", 0))
    except (TypeError, ValueError) as err:
        raise EstonianPayrollError("Funded pension rate must be 0, 2, 4, or 6") from err
    if pension_rate not in VALID_FUNDED_PENSION_RATES:
        raise EstonianPayrollError("Funded pension rate must be 0, 2, 4, or 6")
    try:
        working_days = int(raw.get("working_days", 0) or 0)
    except (TypeError, ValueError) as err:
        raise EstonianPayrollError("Working days must be a number") from err
    if working_days < 0:
        raise EstonianPayrollError("Working days must be non-negative")

    normalized = {
        "mode": PAYROLL_MODE,
        "hourly_gross": _money(hourly_gross),
        "working_hours_mode": working_hours_mode,
        "working_hours": _money(working_hours),
        "working_days": working_days,
        "calendar_source": str(
            raw.get(
                "calendar_source",
                "manual" if working_hours_mode == "manual" else "pending",
            )
        ),
        "apply_social_tax_minimum": bool(raw.get("apply_social_tax_minimum", True)),
        "apply_tax_free_income": bool(raw.get("apply_tax_free_income", True)),
        "tax_free_income": _money(tax_free_income),
        "employee_unemployment": bool(raw.get("employee_unemployment", True)),
        "employer_unemployment": bool(raw.get("employer_unemployment", True)),
        "funded_pension_rate": pension_rate,
    }
    for key in (
        "tax_year",
        "rates_year",
        "gross_income",
        "employee_unemployment_amount",
        "funded_pension_amount",
        "taxable_income",
        "income_tax_amount",
        "net_income",
        "social_tax_amount",
        "employer_unemployment_amount",
        "employer_cost",
    ):
        if key in raw:
            normalized[key] = raw[key]
    return normalized


def calculate_estonian_payroll(
    config: dict[str, Any], *, payment_year: int
) -> dict[str, Any]:
    """Calculate monthly net pay and employer cost from hourly gross pay."""
    normalized = normalize_income_calculation(config, is_income=True)
    assert normalized is not None
    hourly_gross = Decimal(str(normalized["hourly_gross"]))
    working_hours = Decimal(str(normalized["working_hours"]))
    gross = Decimal(str(_money(hourly_gross * working_hours)))

    employee_unemployment = (
        Decimal(str(_money(gross * EMPLOYEE_UNEMPLOYMENT_RATE / 100)))
        if normalized["employee_unemployment"]
        else Decimal("0")
    )
    funded_pension = Decimal(
        str(_money(gross * Decimal(normalized["funded_pension_rate"]) / 100))
    )
    exemption = (
        min(gross, Decimal(str(normalized["tax_free_income"])))
        if normalized["apply_tax_free_income"]
        else Decimal("0")
    )
    taxable = max(Decimal("0"), gross - employee_unemployment - funded_pension - exemption)
    income_tax = Decimal(str(_money(taxable * INCOME_TAX_RATE / 100)))
    net = gross - employee_unemployment - funded_pension - income_tax

    social_base = (
        max(gross, SOCIAL_TAX_MINIMUM_BASE)
        if normalized["apply_social_tax_minimum"]
        else gross
    )
    social_tax = Decimal(str(_money(social_base * SOCIAL_TAX_RATE / 100)))
    employer_unemployment = (
        Decimal(str(_money(gross * EMPLOYER_UNEMPLOYMENT_RATE / 100)))
        if normalized["employer_unemployment"]
        else Decimal("0")
    )
    employer_cost = gross + social_tax + employer_unemployment

    return {
        **normalized,
        "tax_year": int(payment_year),
        "rates_year": KNOWN_TAX_RULES_YEAR,
        "gross_income": _money(gross),
        "employee_unemployment_amount": _money(employee_unemployment),
        "funded_pension_amount": _money(funded_pension),
        "taxable_income": _money(taxable),
        "income_tax_amount": _money(income_tax),
        "net_income": _money(net),
        "social_tax_amount": _money(social_tax),
        "employer_unemployment_amount": _money(employer_unemployment),
        "employer_cost": _money(employer_cost),
    }
