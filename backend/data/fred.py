"""
FRED (Federal Reserve Economic Data) API Client

Pulls macroeconomic indicators critical for real estate analysis:
mortgage rates, CPI, unemployment, interest rates, GDP.

Free API key — register at: https://fred.stlouisfed.org/docs/api/api_key.html
Rate limit: 120 requests/minute (very generous for our use case).

FRED series browser: https://fred.stlouisfed.org/
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

# ── Key FRED series IDs ────────────────────────────────────────────────────
SERIES = {
    # Mortgage rates
    "mortgage_30yr":          "MORTGAGE30US",     # 30-year fixed, weekly
    "mortgage_15yr":          "MORTGAGE15US",     # 15-year fixed, weekly
    "mortgage_5_1_arm":       "MORTGAGE5US",      # 5/1 ARM, weekly

    # Policy & benchmark rates
    "fed_funds_rate":         "FEDFUNDS",          # Federal funds effective rate
    "sofr":                   "SOFR",              # SOFR overnight rate
    "treasury_10yr":          "DGS10",             # 10-year Treasury yield
    "treasury_2yr":           "DGS2",              # 2-year Treasury yield

    # Inflation
    "cpi_all_items":          "CPIAUCSL",          # CPI, all urban consumers
    "core_cpi":               "CPILFESL",          # Core CPI (ex food & energy)
    "pce":                    "PCEPI",             # PCE Price Index (Fed's preferred)
    "inflation_expectations": "T10YIE",            # 10yr breakeven inflation

    # Economy
    "gdp_growth":             "A191RL1Q225SBEA",   # Real GDP growth rate (QoQ %)
    "national_unemployment":  "UNRATE",            # National unemployment rate
    "job_openings":           "JTSJOL",            # Job openings (JOLTS)
    "consumer_sentiment":     "UMCSENT",           # U Michigan consumer sentiment

    # Housing
    "housing_starts":         "HOUST",             # Total housing starts (thousands)
    "building_permits":       "PERMIT",            # New private housing permits
    "existing_home_sales":    "EXHOSLUSM495S",     # Existing home sales
    "new_home_sales":         "HSN1F",             # New single-family home sales
    "case_shiller_national":  "CSUSHPINSA",        # Case-Shiller national HPI
    "median_home_price":      "MSPUS",             # Median sales price, all homes
    "homeownership_rate":     "RHORUSQ156N",       # US homeownership rate
    "rental_vacancy_rate":    "RRVRUSQ156N",       # Rental vacancy rate

    # Cap rate proxy
    "cap_rate_proxy":         "REAINTRATREARAT10Y", # Real 10yr rate (proxy for cap rates)
}


@dataclass
class MortgageRates:
    """Current and trended mortgage rate data."""
    rate_30yr: Optional[float] = None
    rate_15yr: Optional[float] = None
    rate_5_1_arm: Optional[float] = None
    date_as_of: Optional[str] = None
    spread_30_10yr: Optional[float] = None   # 30yr mortgage minus 10yr Treasury
    yoy_change_30yr: Optional[float] = None  # Rate change vs 1 year ago
    history_52w: list[dict] = field(default_factory=list)  # Weekly history


@dataclass
class MacroSnapshot:
    """Macroeconomic environment snapshot for real estate underwriting context."""

    # Rates
    mortgage_rates: Optional[MortgageRates] = None
    fed_funds_rate: Optional[float] = None
    treasury_10yr: Optional[float] = None
    treasury_2yr: Optional[float] = None
    yield_curve_spread: Optional[float] = None  # 10yr - 2yr (negative = inverted)

    # Inflation
    cpi_yoy: Optional[float] = None           # CPI year-over-year %
    core_cpi_yoy: Optional[float] = None
    inflation_expectations_10yr: Optional[float] = None

    # Economy
    gdp_growth_latest: Optional[float] = None  # Most recent quarter QoQ %
    unemployment_rate: Optional[float] = None
    unemployment_trend: Optional[str] = None   # "improving", "stable", "worsening"

    # Housing market
    housing_starts_annualized: Optional[int] = None   # Thousands of units
    building_permits_annualized: Optional[int] = None
    existing_home_sales_annualized: Optional[int] = None
    median_home_price_us: Optional[int] = None
    case_shiller_yoy: Optional[float] = None
    rental_vacancy_rate: Optional[float] = None

    # RE context signals (derived)
    rate_environment: Optional[str] = None    # "accommodative", "neutral", "restrictive"
    cap_rate_pressure: Optional[str] = None   # "expanding", "stable", "compressing"

    data_as_of: Optional[str] = None
    source: str = "Federal Reserve Bank of St. Louis (FRED)"
    warnings: list[str] = field(default_factory=list)


class FREDClient:
    """
    Async client for the FRED API.

    Usage:
        async with FREDClient() as client:
            snapshot = await client.get_macro_snapshot()
            rates = await client.get_mortgage_rates()
    """

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 3600):
        """
        Args:
            api_key:   FRED API key (defaults to FRED_API_KEY env var).
            cache_ttl: Cache TTL in seconds (default 1 hour — data updates daily/weekly).
        """
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.cache_ttl = cache_ttl
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=15.0)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_macro_snapshot(self) -> MacroSnapshot:
        """
        Fetch a complete macroeconomic snapshot.
        Makes ~8 parallel-style requests to build the full picture.
        """
        snapshot = MacroSnapshot(data_as_of=datetime.utcnow().strftime("%Y-%m-%d"))

        # Mortgage rates
        try:
            snapshot.mortgage_rates = await self.get_mortgage_rates()
        except Exception as e:
            snapshot.warnings.append(f"Mortgage rate fetch failed: {e}")

        # Key rates
        fed_funds = await self._latest_value("fed_funds_rate")
        t10 = await self._latest_value("treasury_10yr")
        t2 = await self._latest_value("treasury_2yr")

        snapshot.fed_funds_rate = fed_funds
        snapshot.treasury_10yr = t10
        snapshot.treasury_2yr = t2
        if t10 and t2:
            snapshot.yield_curve_spread = round(t10 - t2, 3)

        # Inflation — compute YoY from recent observations
        snapshot.cpi_yoy = await self._yoy_change("cpi_all_items")
        snapshot.core_cpi_yoy = await self._yoy_change("core_cpi")
        snapshot.inflation_expectations_10yr = await self._latest_value("inflation_expectations")

        # Economy
        snapshot.gdp_growth_latest = await self._latest_value("gdp_growth")
        snapshot.unemployment_rate = await self._latest_value("national_unemployment")
        snapshot.unemployment_trend = await self._compute_trend("national_unemployment", periods=6)

        # Housing
        housing_starts_raw = await self._latest_value("housing_starts")
        permits_raw = await self._latest_value("building_permits")
        snapshot.housing_starts_annualized = int(housing_starts_raw * 1000) if housing_starts_raw else None
        snapshot.building_permits_annualized = int(permits_raw * 1000) if permits_raw else None
        snapshot.median_home_price_us = await self._latest_int("median_home_price")
        snapshot.case_shiller_yoy = await self._yoy_change("case_shiller_national")
        rental_vacancy = await self._latest_value("rental_vacancy_rate")
        snapshot.rental_vacancy_rate = rental_vacancy / 100 if rental_vacancy else None

        # Derived signals
        snapshot.rate_environment = self._assess_rate_environment(
            snapshot.fed_funds_rate, snapshot.treasury_10yr
        )
        snapshot.cap_rate_pressure = self._assess_cap_rate_pressure(
            snapshot.treasury_10yr, snapshot.cpi_yoy
        )

        return snapshot

    async def get_mortgage_rates(self) -> MortgageRates:
        """
        Fetch current and historical mortgage rates.
        Returns 52-week weekly history for trend charts.
        """
        rates = MortgageRates()

        # Current rates
        rates.rate_30yr = await self._latest_value("mortgage_30yr")
        rates.rate_15yr = await self._latest_value("mortgage_15yr")
        rates.rate_5_1_arm = await self._latest_value("mortgage_5_1_arm")

        # Date
        obs_30 = await self._observations("mortgage_30yr", limit=1)
        if obs_30:
            rates.date_as_of = obs_30[-1].get("date")

        # Spread over 10yr Treasury
        t10 = await self._latest_value("treasury_10yr")
        if rates.rate_30yr and t10:
            rates.spread_30_10yr = round(rates.rate_30yr - t10, 3)

        # 52-week history
        obs_52w = await self._observations("mortgage_30yr", limit=52)
        rates.history_52w = [
            {"date": o["date"], "rate": float(o["value"])}
            for o in obs_52w
            if o.get("value") not in (None, ".", "")
        ]

        # YoY change
        if len(rates.history_52w) >= 2:
            current = rates.history_52w[-1]["rate"] if rates.history_52w else None
            year_ago = rates.history_52w[0]["rate"] if rates.history_52w else None
            if current and year_ago:
                rates.yoy_change_30yr = round(current - year_ago, 3)

        return rates

    async def get_series_history(
        self,
        series_key: str,
        periods: int = 60,
    ) -> list[dict]:
        """
        Get historical observations for any named series.

        Args:
            series_key: Key from SERIES dict (e.g., "mortgage_30yr", "cpi_all_items")
            periods:    Number of most recent observations to return

        Returns:
            List of {"date": str, "value": float} dicts
        """
        obs = await self._observations(series_key, limit=periods)
        return [
            {"date": o["date"], "value": float(o["value"])}
            for o in obs
            if o.get("value") not in (None, ".", "")
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _observations(self, series_key: str, limit: int = 12) -> list[dict]:
        """Fetch the most recent N observations for a series."""
        if not self.api_key:
            return []

        series_id = SERIES.get(series_key)
        if not series_id:
            return []

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }

        try:
            data = await self._get(f"{FRED_BASE}/series/observations", params)
            obs = data.get("observations", [])
            # Return in chronological order
            return list(reversed(obs))
        except Exception as e:
            logger.warning(f"FRED series {series_id} fetch failed: {e}")
            return []

    async def _latest_value(self, series_key: str) -> Optional[float]:
        """Get the most recent valid value for a series."""
        obs = await self._observations(series_key, limit=5)
        for o in reversed(obs):
            val = o.get("value")
            if val and val not in (".", ""):
                try:
                    return float(val)
                except ValueError:
                    continue
        return None

    async def _latest_int(self, series_key: str) -> Optional[int]:
        val = await self._latest_value(series_key)
        return int(val) if val is not None else None

    async def _yoy_change(self, series_key: str) -> Optional[float]:
        """Compute year-over-year percentage change for a monthly series."""
        obs = await self._observations(series_key, limit=14)
        valid = [o for o in obs if o.get("value") not in (None, ".", "")]
        if len(valid) < 13:
            return None
        try:
            current = float(valid[-1]["value"])
            year_ago = float(valid[-13]["value"])
            if year_ago != 0:
                return round((current - year_ago) / year_ago * 100, 2)
        except (ValueError, IndexError):
            pass
        return None

    async def _compute_trend(
        self, series_key: str, periods: int = 6
    ) -> Optional[str]:
        """Classify the recent trend as 'improving', 'stable', or 'worsening'."""
        obs = await self._observations(series_key, limit=periods + 1)
        valid = [
            float(o["value"]) for o in obs
            if o.get("value") not in (None, ".", "")
        ]
        if len(valid) < 3:
            return None
        avg_first_half = sum(valid[:len(valid)//2]) / (len(valid)//2)
        avg_second_half = sum(valid[len(valid)//2:]) / len(valid[len(valid)//2:])
        delta = avg_second_half - avg_first_half
        # For unemployment: lower = better (improving)
        if abs(delta) < 0.2:
            return "stable"
        return "improving" if delta < 0 else "worsening"

    @staticmethod
    def _assess_rate_environment(
        fed_funds: Optional[float], t10yr: Optional[float]
    ) -> Optional[str]:
        """
        Classify the rate environment for RE investors.
        Accommodative = good for leveraged RE; Restrictive = challenging.
        """
        if fed_funds is None:
            return None
        if fed_funds < 2.0:
            return "accommodative"
        elif fed_funds < 4.0:
            return "neutral"
        else:
            return "restrictive"

    @staticmethod
    def _assess_cap_rate_pressure(
        t10yr: Optional[float], cpi_yoy: Optional[float]
    ) -> Optional[str]:
        """
        Infer cap rate directional pressure from macro conditions.
        Rising real rates → cap rate expansion (values down).
        """
        if t10yr is None:
            return None
        real_rate = t10yr - (cpi_yoy or 2.5)
        if real_rate > 2.0:
            return "expanding"   # Cap rates rising, values under pressure
        elif real_rate > 0.5:
            return "stable"
        else:
            return "compressing"  # Cap rates falling, values supported

    async def _get(self, url: str, params: dict) -> dict:
        """Execute a GET request."""
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        finally:
            if not self._client:
                await client.aclose()
