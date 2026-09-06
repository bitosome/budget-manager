"""Small local seasonal regression model and electricity bill calculations.

No network, ML runtime, or personal training data is bundled. Training uses only
completed observations, never the model's own forecasts or partial months.
"""
from __future__ import annotations

from calendar import monthrange
from math import cos, exp, isfinite, log, pi, sin
import re

ELECTRICITY_TYPE = "electricity"
HISTORY_FORMAT = "budget-manager-electricity-history"


def month_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", value):
        raise ValueError("Electricity month must be YYYY-MM (2000–2099)")
    return value


def shift_month(key, offset):
    year, month = map(int, key.split("-"))
    year, month = divmod(year * 12 + month - 1 + offset, 12)
    return f"{year:04d}-{month + 1:02d}"


def number(value, label, minimum=0, maximum=1e8):
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{label} must be a number") from err
    if isinstance(value, bool) or not isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return result


def normalize_settings(raw=None):
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("Electricity settings must be an object")
    result = {}
    for key in ("cost_statistic_id", "energy_statistic_id", "price_entity_id"):
        value = str(raw.get(key) or "").strip()
        if value and not re.fullmatch(r"[a-z0-9_]+[.:][a-z0-9_]+", value):
            raise ValueError(f"Invalid {key}")
        result[key] = value
    result["method"] = raw.get("method", "adaptive")
    if result["method"] not in {"adaptive", "recent_average"}:
        raise ValueError("Unknown electricity estimation method")
    result["learning_enabled"] = raw.get("learning_enabled", True)
    if not isinstance(result["learning_enabled"], bool):
        raise ValueError("Learning enabled must be true or false")
    for key, default, low, high in (
        ("buffer_percent", 15, 0, 200), ("history_months", 36, 3, 60),
        ("half_life_months", 6, 1, 36), ("live_price_weight", 50, 0, 100),
        ("fallback_monthly_kwh", 0, 0, 100000), ("fallback_price", 0, 0, 10),
    ):
        result[key] = number(raw.get(key, default), key, low, high)
    if result["history_months"] != int(result["history_months"]):
        raise ValueError("History window must be whole months")
    result["history_months"] = int(result["history_months"])
    fees = raw.get("fees", [])
    if not isinstance(fees, list) or len(fees) > 50:
        raise ValueError("Provide at most 50 fixed monthly fees")
    result["fees"] = []
    for fee in fees:
        if not isinstance(fee, dict) or not str(fee.get("name", "")).strip():
            raise ValueError("Each fixed fee needs a name")
        result["fees"].append({"name": str(fee["name"]).strip()[:100],
            "amount": round(number(fee.get("amount"), "Fixed fee"), 2),
            "from_month": month_key(fee["from_month"]) if fee.get("from_month") else None,
            "to_month": month_key(fee["to_month"]) if fee.get("to_month") else None})
        if fee.get("from_month") and fee.get("to_month") and fee["to_month"] < fee["from_month"]:
            raise ValueError("Fee end month precedes its start")
    return result


def normalize_history(records):
    if not isinstance(records, list) or len(records) > 1200:
        raise ValueError("Electricity history must be a list of at most 1200 months")
    result = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Each history row must be an object")
        key = month_key(row.get("month"))
        if key in result:
            raise ValueError(f"Duplicate electricity month: {key}; combine partial bills first")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("History enabled must be true or false")
        result[key] = {"month": key, "kwh": number(row.get("kwh"), "Consumption (kWh)"),
            "grid_cost": round(number(row.get("grid_cost"), "Variable grid cost", -1e6), 2),
            "fixed_fees": round(number(row.get("fixed_fees", 0), "Billed fixed fees"), 2),
            "enabled": enabled, "source": str(row.get("source", "bill"))[:80]}
    return result


def fixed_fees(settings, month):
    return round(sum(fee["amount"] for fee in settings["fees"]
        if (not fee["from_month"] or fee["from_month"] <= month)
        and (not fee["to_month"] or fee["to_month"] >= month)), 2)


def _features(month):
    angle = (int(month[5:7]) - 1) * 2 * pi / 12
    return [1.0, sin(angle), cos(angle)]


def _days(month):
    return monthrange(*map(int, month.split("-")))[1]


def _age(a, b):
    ay, am = map(int, a.split("-")); by, bm = map(int, b.split("-"))
    return (ay - by) * 12 + am - bm


def _solve(matrix, vector):
    """Pivoted elimination for a regularized 3x3 linear system."""
    a = [row[:] + [value] for row, value in zip(matrix, vector)]
    for i in range(3):
        pivot = max(range(i, 3), key=lambda j: abs(a[j][i]))
        a[i], a[pivot] = a[pivot], a[i]
        divisor = a[i][i]
        a[i] = [value / divisor for value in a[i]]
        for j in range(3):
            if j != i:
                factor = a[j][i]
                a[j] = [x - factor * y for x, y in zip(a[j], a[i])]
    return [row[-1] for row in a]


def train(history, settings, current_month):
    rows = [r for key, r in sorted(history.items()) if key < current_month
        and 0 < _age(current_month, key) <= settings["history_months"]
        and r.get("enabled", True) and r["kwh"] > 0]
    if not rows:
        return {"samples": 0, "method": settings["method"], "trained_through": None}
    weights = [2 ** (-_age(current_month, r["month"]) / settings["half_life_months"]) for r in rows]
    matrix = [[0.0] * 3 for _ in range(3)]; vector = [0.0] * 3; price_vector = [0.0] * 3
    for r, w in zip(rows, weights):
        x = _features(r["month"]); y = log(max(0.01, r["kwh"] / _days(r["month"])))
        price_y = log(max(0.001, r["grid_cost"] / r["kwh"]))
        for i in range(3):
            vector[i] += w * x[i] * y
            price_vector[i] += w * x[i] * price_y
            for j in range(3):
                matrix[i][j] += w * x[i] * x[j]
    for i in range(3):
        matrix[i][i] += 0.000001 if i == 0 else 1.0  # Shrink seasonality on sparse history.
    coefficients = _solve(matrix, vector)
    price_coefficients = _solve(matrix, price_vector)
    daily = sum(w * r["kwh"] / _days(r["month"]) for r, w in zip(rows, weights)) / sum(weights)
    price = sum(w * r["grid_cost"] for r, w in zip(rows, weights)) / sum(w * r["kwh"] for r, w in zip(rows, weights))
    model = {"samples": len(rows), "coefficients": coefficients, "daily_kwh": daily,
        "price_coefficients": price_coefficients,
        "unit_price": price, "method": settings["method"], "trained_through": rows[-1]["month"],
        "trained_at_month": current_month, "history_months": settings["history_months"]}
    return model


def predict_usage(model, month, settings):
    if not model.get("samples"):
        return settings["fallback_monthly_kwh"]
    daily = model["daily_kwh"]
    if model.get("method") == "adaptive" and model["samples"] >= 6:
        fitted = exp(max(-5, min(15, sum(a * b for a, b in zip(model["coefficients"], _features(month))))))
        daily = min(daily * 3, max(daily * 0.25, fitted))
    return daily * _days(month)


def forecast(payment_month, settings, history, model, live, today):
    """Previous consumption month, observed cost + buffered unobserved cost + fees."""
    consumption = shift_month(payment_month, -1)
    current = today.strftime("%Y-%m")
    row = history.get(consumption)
    fees = fixed_fees(settings, consumption)
    if row and consumption < current:
        total = row["grid_cost"] + row["fixed_fees"]
        return {"amount": round(max(0, total), 2), "status": "measured" if row["source"] == "recorder" else "actual", "consumption_month": consumption,
            "grid_cost": row["grid_cost"], "fixed_fees": row["fixed_fees"], "buffer": 0,
            "source": row["source"], "kwh": row["kwh"], "warning": "Net electricity credit; budget expense is zero" if total < 0 else ""}
    usage = predict_usage(model, consumption, settings)
    price = predict_price(model, consumption, settings)
    # Use a multi-day consumption-weighted average, never a single cheap/expensive hour.
    recent_price = live.get("recent_unit_price")
    if recent_price is not None and live.get("recent_days", 0) >= 3:
        blend = settings["live_price_weight"] / 100
        price = price * (1 - blend) + recent_price * blend if model.get("samples") else recent_price
    observed = 0.0; observed_kwh = 0.0; fraction = 0.0
    if consumption == current and live.get("month") == current and live.get("month_coverage", 0) >= .95:
        observed = live.get("grid_cost", 0); observed_kwh = live.get("kwh", 0)
        fraction = min(1, live.get("elapsed_days", 0) / _days(current))
        if fraction >= 3 / _days(current) and observed_kwh > 0:
            # Gradually adapt expected consumption to this month's actual run rate.
            usage = usage * (1 - fraction) + (observed_kwh / fraction) * fraction
    if usage <= 0 or (not model.get("samples") and price <= 0):
        return {"amount": 0, "status": "missing", "consumption_month": consumption,
            "warning": "Import electricity history or configure fallback consumption and price"}
    remaining_kwh = max(0, usage - observed_kwh) if fraction else usage
    remainder = max(0, remaining_kwh * price)
    buffer = remainder * settings["buffer_percent"] / 100
    total = observed + remainder + buffer + fees
    return {"amount": round(max(0, total), 2), "status": "estimated", "consumption_month": consumption,
        "grid_cost": round(observed, 2), "projected_grid_cost": round(observed + remainder, 2),
        "fixed_fees": fees, "buffer": round(buffer, 2), "kwh": round(usage, 2),
        "unit_price": round(price, 5), "samples": model.get("samples", 0),
        "warning": "Historical month has no complete measured data" if consumption < current else
            "Limited training history" if model.get("samples", 0) < 6 else ""}


def backtest(history, settings):
    """Walk-forward MAE: every prediction is fitted only to earlier months."""
    errors = []
    for key, row in sorted(history.items()):
        model = train(history, settings, key)
        if model["samples"] >= 6 and row.get("enabled", True):
            predicted = predict_usage(model, key, settings) * predict_price(model, key, settings)
            errors.append(abs(predicted - row["grid_cost"]))
    return {"evaluated_months": len(errors), "mae_eur": round(sum(errors) / len(errors), 2) if errors else None}


def predict_price(model, month, settings):
    price = model.get("unit_price", settings["fallback_price"])
    if model.get("method") == "adaptive" and model.get("samples", 0) >= 6 and model.get("price_coefficients"):
        fitted = exp(max(-10, min(5, sum(a * b for a, b in zip(model["price_coefficients"], _features(month))))))
        price = min(max(0.001, price) * 3, max(max(0.001, price) * .5, fitted))
    return price


def empty_state():
    return {"history": {}, "observations": {}, "ignored_months": [], "model": {}, "live": {}, "diagnostics": {}}


def combined_history(state):
    # Manually confirmed/imported bills take priority over Recorder observations.
    ignored = set(state.get("ignored_months", []))
    return {**{key: row for key, row in state.get("observations", {}).items() if key not in ignored},
        **state.get("history", {})}


def normalize_state(raw):
    if not isinstance(raw, dict):
        raise ValueError("Electricity data must be an object")
    state = empty_state()
    ignored = raw.get("ignored_months", [])
    if not isinstance(ignored, list) or len(ignored) > 1200:
        raise ValueError("Invalid ignored electricity months")
    state["ignored_months"] = sorted({month_key(key) for key in ignored})
    for key in ("history", "observations"):
        rows = raw.get(key, {})
        if not isinstance(rows, dict):
            raise ValueError("Invalid electricity history")
        state[key] = normalize_history(list(rows.values()))
    # Rebuild model on import: do not trust executable or arbitrary model payloads.
    return state
