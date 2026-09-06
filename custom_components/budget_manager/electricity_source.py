"""Read reset-safe Home Assistant Recorder statistics, never raw cost states."""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.util import dt as dt_util

from .electricity import fixed_fees, shift_month


def aggregate_statistics(cost_rows, energy_rows, now, settings):
    """Pair complete hourly deltas; reject gaps instead of treating them as zero."""
    def indexed(rows):
        return {float(row["start"]): float(row["change"]) for row in rows
            if isinstance(row.get("change"), (int, float)) and isfinite(row["change"])}
    costs, energy = indexed(cost_rows), indexed(energy_rows)
    groups = {}; recent_cost = recent_energy = 0.0; recent_hours = 0
    local_now = dt_util.as_local(now)
    current = local_now.strftime("%Y-%m")
    for stamp in costs.keys() & energy.keys():
        if stamp + 3600 > now.timestamp() or energy[stamp] < 0:
            continue
        local = dt_util.as_local(datetime.fromtimestamp(stamp, tz=dt_util.UTC))
        key = local.strftime("%Y-%m")
        group = groups.setdefault(key, {"grid_cost": 0.0, "kwh": 0.0, "hours": 0})
        group["grid_cost"] += costs[stamp]; group["kwh"] += energy[stamp]; group["hours"] += 1
        if now.timestamp() - 7 * 86400 <= stamp:
            recent_cost += costs[stamp]; recent_energy += energy[stamp]; recent_hours += 1
    observations = {}; live = {"month": current, "recent_days": recent_hours / 24,
        "recent_unit_price": recent_cost / recent_energy if recent_energy > 0 else None,
        "as_of": now.isoformat(), "month_coverage": 0}
    for key, group in groups.items():
        start = datetime.fromisoformat(f"{key}-01").replace(tzinfo=local_now.tzinfo)
        end = datetime.fromisoformat(f"{shift_month(key, 1)}-01").replace(tzinfo=local_now.tzinfo)
        expected = (end.timestamp() - start.timestamp()) / 3600
        if key < current and group["hours"] >= expected:
            observations[key] = {"month": key, "grid_cost": round(group["grid_cost"], 2),
                "kwh": group["kwh"], "fixed_fees": fixed_fees(settings, key),
                "source": "recorder", "enabled": True}
        elif key == current:
            elapsed = max(0, int((now.timestamp() - start.timestamp()) / 3600))
            live.update({"grid_cost": round(group["grid_cost"], 2), "kwh": group["kwh"],
                "elapsed_days": elapsed / expected * monthrange(start.year, start.month)[1],
                "month_coverage": min(1, group["hours"] / elapsed) if elapsed else 0})
    return observations, live


async def async_read_statistics(hass, settings, *, full=False):
    """Use the public Recorder query on its own executor (compatible with resets)."""
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import list_statistic_ids, statistics_during_period

    cost, energy = settings["cost_statistic_id"], settings["energy_statistic_id"]
    if not cost or not energy:
        return {}, {}, "Select both grid-cost and consumption statistics in Electricity settings"
    metadata = await get_instance(hass).async_add_executor_job(list_statistic_ids, hass, {cost, energy}, "sum")
    units = {row["statistic_id"]: row.get("unit_of_measurement") for row in metadata}
    if units.get(cost) not in {"EUR", "€"} or units.get(energy) != "kWh":
        return {}, {}, "Selected statistics must provide accumulated cost in EUR and consumption in kWh (with sum statistics)"
    now = dt_util.now()
    first = shift_month(now.strftime("%Y-%m"), -settings["history_months"] if full else -2)
    start = datetime.fromisoformat(f"{first}-01").replace(tzinfo=now.tzinfo)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, dt_util.as_utc(start), dt_util.as_utc(now),
        {cost, energy}, "hour", None, {"change"})
    observations, live = aggregate_statistics(rows.get(cost, []), rows.get(energy, []), now, settings)
    if settings["price_entity_id"]:
        state = hass.states.get(settings["price_entity_id"])
        if state is not None:
            live["price_sensor_state"] = state.state
            live["price_sensor_unit"] = state.attributes.get("unit_of_measurement")
    warning = "" if live.get("month_coverage", 0) >= .95 else "Incomplete current-month statistics; using the model without partial accrual"
    return observations, live, warning


class ElectricityCoordinator:
    """One hourly update per configured budget; startup queries run in background."""
    def __init__(self, hass, manager):
        self.hass, self.manager = hass, manager
        self._unsubscribe = None
        self._task = None

    def start(self):
        from homeassistant.helpers.event import async_track_time_interval
        self._unsubscribe = async_track_time_interval(self.hass, self._update, timedelta(hours=1))
        self._task = self.hass.async_create_task(self.manager.async_refresh_electricity(full=True))

    async def _update(self, _now):
        await self.manager.async_refresh_electricity()

    def stop(self):
        if self._unsubscribe:
            self._unsubscribe()
        if self._task and not self._task.done():
            self._task.cancel()
