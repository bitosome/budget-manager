"""On-demand Estonian public-holiday and working-hours provider."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .estonian_payroll import estonian_working_time, statutory_estonian_holidays


_LOGGER = logging.getLogger(__name__)
_NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/EE"


class EstonianWorkingHoursProvider:
    """Fetch and cache Estonian holidays, with a statutory offline fallback."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._cache: dict[int, tuple[set[date], str]] = {}

    async def async_month(self, month_key: str) -> dict[str, Any]:
        """Return standard working time for one Estonian calendar month."""
        year, month = (int(part) for part in month_key.split("-"))
        years = {year, year + 1} if month == 12 else {year}
        holidays: set[date] = set()
        sources: set[str] = set()
        for holiday_year in years:
            year_holidays, source = await self._async_year(holiday_year)
            holidays.update(year_holidays)
            sources.add(source)
        result = estonian_working_time(month_key, holidays)
        result["calendar_source"] = (
            "nager_date" if sources == {"nager_date"} else "statutory_fallback"
        )
        return result

    async def _async_year(self, year: int) -> tuple[set[date], str]:
        if year in self._cache:
            return self._cache[year]
        try:
            session = async_get_clientsession(self._hass)
            async with session.get(_NAGER_URL.format(year=year), timeout=10) as response:
                response.raise_for_status()
                payload = await response.json()
            holidays = {
                date.fromisoformat(str(row["date"]))
                for row in payload
                if isinstance(row, dict)
                and row.get("countryCode") == "EE"
                and row.get("global", True)
                and "Public" in row.get("types", ["Public"])
            }
            if not holidays:
                raise ValueError("holiday response was empty")
            result = (holidays, "nager_date")
        except Exception as err:  # Home Assistant must remain usable offline.
            _LOGGER.warning(
                "Unable to load Estonian holidays for %s from Nager.Date; using statutory fallback: %s",
                year,
                err,
            )
            result = (statutory_estonian_holidays(year), "statutory_fallback")
        self._cache[year] = result
        return result
