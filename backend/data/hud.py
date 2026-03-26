"""
HUD (Dept. of Housing and Urban Development) API Client

Pulls Fair Market Rents (FMR) — the benchmark HUD uses to set
Section 8 voucher payments. FMRs are a reliable, government-published
proxy for market rents at the county / metro level.

No API key required for most HUD endpoints.
API docs: https://www.huduser.gov/portal/dataset/fmr-api.html

Also pulls:
  - Income limits (used for affordable housing analysis)
  - Comprehensive Housing Affordability Strategy (CHAS) data
"""

from __future__ import annotations

import os
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

HUD_BASE = "https://www.huduser.gov/hudapi/public"


@dataclass
class FairMarketRents:
    """
    HUD Fair Market Rents for a geography.

    FMRs represent the 40th percentile of gross rents for standard
    quality rental units occupied by recent movers. Published annually.
    """

    geography: str
    fips_code: str
    year: Optional[str] = None

    # FMRs by bedroom count (monthly, inclusive of utilities)
    fmr_studio: Optional[int] = None    # Efficiency / Studio
    fmr_1br: Optional[int] = None       # 1 Bedroom
    fmr_2br: Optional[int] = None       # 2 Bedroom
    fmr_3br: Optional[int] = None       # 3 Bedroom
    fmr_4br: Optional[int] = None       # 4 Bedroom

    # Median rent (weighted average, used for general benchmarking)
    median_fmr: Optional[float] = None

    # Area type
    area_name: Optional[str] = None
    metro_area: Optional[bool] = None

    source: str = "HUD Fair Market Rents"
    warnings: list[str] = field(default_factory=list)

    @property
    def by_bedroom(self) -> dict[str, Optional[int]]:
        return {
            "studio": self.fmr_studio,
            "1br": self.fmr_1br,
            "2br": self.fmr_2br,
            "3br": self.fmr_3br,
            "4br": self.fmr_4br,
        }

    def annual_rent(self, bedrooms: str = "2br") -> Optional[float]:
        """Annual rent for a given bedroom count."""
        monthly = self.by_bedroom.get(bedrooms)
        return monthly * 12 if monthly else None

    def rent_growth_commentary(self, market_rent: float, bedrooms: str = "2br") -> str:
        """
        Compare market rent to FMR and return a brief commentary.
        Useful for the AI memo generator.
        """
        fmr = self.by_bedroom.get(bedrooms)
        if not fmr or not market_rent:
            return "FMR comparison unavailable."
        pct = (market_rent - fmr) / fmr * 100
        if pct > 20:
            return f"Market rent of ${market_rent:,.0f}/mo is {pct:.0f}% above HUD FMR (${fmr:,}/mo), indicating a strong market."
        elif pct > 0:
            return f"Market rent of ${market_rent:,.0f}/mo is {pct:.0f}% above HUD FMR (${fmr:,}/mo)."
        elif pct > -10:
            return f"Market rent of ${market_rent:,.0f}/mo is near HUD FMR (${fmr:,}/mo)."
        else:
            return f"Market rent of ${market_rent:,.0f}/mo is {abs(pct):.0f}% below HUD FMR (${fmr:,}/mo) — may indicate soft market."


@dataclass
class IncomeLimits:
    """HUD income limits by household size, used for affordable housing analysis."""

    geography: str
    fips_code: str
    year: Optional[str] = None
    median_income: Optional[int] = None

    # Income limits as % of Area Median Income (AMI)
    # Very Low Income (50% AMI), Low Income (80% AMI)
    # Keys: household size 1–8 persons
    vli_50pct: dict = field(default_factory=dict)   # Very Low Income
    li_80pct: dict = field(default_factory=dict)    # Low Income
    eli_30pct: dict = field(default_factory=dict)   # Extremely Low Income

    source: str = "HUD Income Limits"
    warnings: list[str] = field(default_factory=list)


class HUDClient:
    """
    Async client for HUD public APIs.

    Note: HUD API does not require an API key for FMR and income limit data.
    An API token is required for some newer endpoints — register free at
    https://www.huduser.gov/hudapi/public/register?comingfrom=API

    Usage:
        async with HUDClient() as client:
            fmr = await client.get_fair_market_rents("48453")  # Travis County, TX
    """

    def __init__(self, api_token: Optional[str] = None, cache_ttl: int = 86400 * 30):
        """
        Args:
            api_token: HUD API token (defaults to HUD_API_TOKEN env var).
                       Some endpoints work without it.
            cache_ttl: Cache TTL (default 30 days — FMR data updates annually).
        """
        self.api_token = api_token or os.getenv("HUD_API_TOKEN", "")
        self.cache_ttl = cache_ttl
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        self._client = httpx.AsyncClient(timeout=30.0, headers=headers)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Fair Market Rents
    # ------------------------------------------------------------------

    async def get_fair_market_rents(
        self, fips_code: str, year: Optional[str] = None
    ) -> FairMarketRents:
        """
        Get Fair Market Rents for a county or metro area.

        Args:
            fips_code: 5-digit county FIPS (e.g., "48453" for Travis County, TX)
                       or 4-digit FMR area code for metros
            year:      FMR year (defaults to most recent available)

        Common FIPS codes:
            48453 — Travis County (Austin), TX
            36061 — New York County (Manhattan), NY
            06037 — Los Angeles County, CA
            17031 — Cook County (Chicago), IL
            48201 — Harris County (Houston), TX
            12086 — Miami-Dade County, FL
        """
        fmr = FairMarketRents(geography=fips_code, fips_code=fips_code)

        try:
            url = f"{HUD_BASE}/fmr/data/{fips_code}"
            params = {}
            if year:
                params["year"] = year

            data = await self._get(url, params)

            if not data or "data" not in data:
                fmr.warnings.append(f"No FMR data returned for FIPS {fips_code}")
                return fmr

            result = data["data"]

            # HUD returns different shapes for metro vs county — handle both
            if "basicdata" in result:
                basic = result["basicdata"]
                if isinstance(basic, list) and basic:
                    basic = basic[0]

                fmr.area_name = basic.get("areaname") or basic.get("countyname", fips_code)
                fmr.year = str(basic.get("year", ""))
                fmr.fmr_studio = self._safe_int(basic.get("Efficiency") or basic.get("efficiency"))
                fmr.fmr_1br = self._safe_int(basic.get("One-Bedroom") or basic.get("oneBR"))
                fmr.fmr_2br = self._safe_int(basic.get("Two-Bedroom") or basic.get("twoBR"))
                fmr.fmr_3br = self._safe_int(basic.get("Three-Bedroom") or basic.get("threeBR"))
                fmr.fmr_4br = self._safe_int(basic.get("Four-Bedroom") or basic.get("fourBR"))

            elif isinstance(result, list) and result:
                row = result[0]
                fmr.area_name = row.get("areaname", fips_code)
                fmr.year = str(row.get("year", ""))
                fmr.fmr_studio = self._safe_int(row.get("Efficiency"))
                fmr.fmr_1br = self._safe_int(row.get("One-Bedroom"))
                fmr.fmr_2br = self._safe_int(row.get("Two-Bedroom"))
                fmr.fmr_3br = self._safe_int(row.get("Three-Bedroom"))
                fmr.fmr_4br = self._safe_int(row.get("Four-Bedroom"))

            # Compute weighted median (rough approximation weighting 1br and 2br)
            prices = [
                v for v in [fmr.fmr_studio, fmr.fmr_1br, fmr.fmr_2br, fmr.fmr_3br, fmr.fmr_4br]
                if v is not None
            ]
            if prices:
                fmr.median_fmr = sorted(prices)[len(prices) // 2]

        except httpx.HTTPStatusError as e:
            msg = f"HUD API error {e.response.status_code} for FIPS {fips_code}"
            logger.warning(msg)
            fmr.warnings.append(msg)
        except httpx.RequestError as e:
            msg = f"HUD API connection error: {str(e)}"
            logger.warning(msg)
            fmr.warnings.append(msg)
        except Exception as e:
            msg = f"Unexpected error fetching HUD FMR: {str(e)}"
            logger.error(msg, exc_info=True)
            fmr.warnings.append(msg)

        return fmr

    async def get_state_fmr_summary(self, state_code: str) -> list[FairMarketRents]:
        """
        Get FMR data for all counties in a state.

        Args:
            state_code: 2-digit state FIPS or 2-letter abbreviation

        Returns:
            List of FairMarketRents, one per county / FMR area
        """
        results = []
        try:
            url = f"{HUD_BASE}/fmr/statedata/{state_code}"
            data = await self._get(url, {})

            if not data or "data" not in data:
                return results

            areas = data["data"].get("metroareas", []) + data["data"].get("counties", [])
            for area in areas:
                fmr = FairMarketRents(
                    geography=area.get("areaname", "Unknown"),
                    fips_code=area.get("fips_code", ""),
                    year=str(area.get("year", "")),
                    area_name=area.get("areaname"),
                    fmr_studio=self._safe_int(area.get("Efficiency")),
                    fmr_1br=self._safe_int(area.get("One-Bedroom")),
                    fmr_2br=self._safe_int(area.get("Two-Bedroom")),
                    fmr_3br=self._safe_int(area.get("Three-Bedroom")),
                    fmr_4br=self._safe_int(area.get("Four-Bedroom")),
                )
                results.append(fmr)

        except Exception as e:
            logger.warning(f"HUD state FMR fetch failed for {state_code}: {e}")

        return results

    # ------------------------------------------------------------------
    # Income Limits
    # ------------------------------------------------------------------

    async def get_income_limits(self, fips_code: str) -> IncomeLimits:
        """
        Get HUD income limits (AMI tiers) for a county.
        Useful for affordable housing and LIHTC analysis.
        """
        limits = IncomeLimits(geography=fips_code, fips_code=fips_code)

        try:
            url = f"{HUD_BASE}/il/data/{fips_code}"
            data = await self._get(url, {})

            if not data or "data" not in data:
                limits.warnings.append(f"No income limit data for FIPS {fips_code}")
                return limits

            result = data["data"]
            if "il50" in result:
                limits.vli_50pct = result["il50"]
            if "il80" in result:
                limits.li_80pct = result["il80"]
            if "il30" in result:
                limits.eli_30pct = result["il30"]

            # Median income
            limits.median_income = self._safe_int(
                result.get("median_income") or result.get("mediangross")
            )

        except Exception as e:
            limits.warnings.append(f"Income limits fetch failed: {str(e)}")

        return limits

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(float(str(val).replace(",", "")))
        except (ValueError, TypeError):
            return None

    async def _get(self, url: str, params: dict) -> dict:
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        finally:
            if not self._client:
                await client.aclose()
