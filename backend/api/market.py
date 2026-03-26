"""
Market Research API endpoints.

GET  /api/market/{metro}              — Full market report by metro name
GET  /api/market/zip/{zipcode}        — Market report by ZIP code
GET  /api/market/county/{fips}        — Market report by 5-digit FIPS
GET  /api/market/macro                — Macro snapshot (FRED only, no geo required)
GET  /api/market/mortgage-rates       — Current mortgage rates + 52-week history
GET  /api/market/fmr/{fips}           — Fair Market Rents for a FIPS code
"""

from __future__ import annotations

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ..data.market_service import MarketService, MarketReport
from ..data.fred import FREDClient, MacroSnapshot, MortgageRates
from ..data.hud import HUDClient, FairMarketRents
from ..data.census import CensusClient, DemographicProfile

router = APIRouter(prefix="/api/market", tags=["market research"])


def _get_service() -> MarketService:
    """Instantiate MarketService with keys from environment."""
    return MarketService(
        census_key=os.getenv("CENSUS_API_KEY"),
        fred_key=os.getenv("FRED_API_KEY"),
        hud_token=os.getenv("HUD_API_TOKEN"),
    )


# ---------------------------------------------------------------------------
# Full market reports
# ---------------------------------------------------------------------------

@router.get("/metro/{metro}", summary="Market report for a metro area")
async def market_report_metro(
    metro: str,
    state_fips: Optional[str] = Query(None, description="2-digit state FIPS (e.g., '48' for TX)"),
    county_fips: Optional[str] = Query(None, description="3-digit county FIPS (e.g., '453')"),
    fips_code: Optional[str] = Query(None, description="5-digit combined FIPS (e.g., '48453')"),
) -> dict:
    """
    Fetch a complete market intelligence report for a metro area.

    Pulls Census demographics, FRED macro data, HUD Fair Market Rents,
    and Zillow rent/price trends in parallel.

    **Example:** `/api/market/metro/Austin%2C%20TX?state_fips=48&county_fips=453&fips_code=48453`

    At minimum, `metro` is required. Providing FIPS codes enables Census and HUD data.
    """
    try:
        service = _get_service()
        report = await service.get_market_report(
            metro=metro,
            state_fips=state_fips,
            county_fips=county_fips,
            fips_code=fips_code or (f"{state_fips}{county_fips}" if state_fips and county_fips else None),
        )
        return _serialize_report(report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/zip/{zipcode}", summary="Market report for a ZIP code")
async def market_report_zip(zipcode: str) -> dict:
    """
    Fetch a market intelligence report for a specific ZIP code.

    Provides hyper-local Zillow data (home values, rents) and Census
    demographics for the ZIP Code Tabulation Area.

    **Example:** `/api/market/zip/78701`
    """
    if not zipcode.isdigit() or len(zipcode) != 5:
        raise HTTPException(status_code=422, detail="zipcode must be a 5-digit number")
    try:
        service = _get_service()
        report = await service.get_market_report(metro=f"ZIP {zipcode}", zipcode=zipcode)
        return _serialize_report(report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/county/{fips_code}", summary="Market report by county FIPS")
async def market_report_county(fips_code: str) -> dict:
    """
    Fetch market report for a US county by 5-digit FIPS code.

    **Example:** `/api/market/county/48453` (Travis County, Austin TX)

    Common FIPS codes:
    - 48453 — Travis County (Austin), TX
    - 36061 — New York County (Manhattan), NY
    - 06037 — Los Angeles County, CA
    - 17031 — Cook County (Chicago), IL
    - 48201 — Harris County (Houston), TX
    """
    if len(fips_code) != 5 or not fips_code.isdigit():
        raise HTTPException(status_code=422, detail="fips_code must be a 5-digit number")

    state_fips = fips_code[:2]
    county_fips = fips_code[2:]

    try:
        service = _get_service()
        report = await service.get_market_report(
            metro=f"County FIPS {fips_code}",
            state_fips=state_fips,
            county_fips=county_fips,
            fips_code=fips_code,
        )
        return _serialize_report(report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Specialized endpoints
# ---------------------------------------------------------------------------

@router.get("/macro", summary="Macroeconomic snapshot (FRED)")
async def macro_snapshot() -> dict:
    """
    Get a complete macroeconomic snapshot from FRED.

    Returns current mortgage rates, Fed funds rate, CPI, GDP growth,
    unemployment, housing starts, and derived RE signals like rate
    environment assessment and cap rate pressure.

    **No geography required.** Updated hourly.
    """
    try:
        async with FREDClient(api_key=os.getenv("FRED_API_KEY")) as client:
            snapshot = await client.get_macro_snapshot()
            return _serialize(snapshot)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mortgage-rates", summary="Current mortgage rates + 52-week history")
async def mortgage_rates() -> dict:
    """
    Get current mortgage rates and 52-week weekly trend from FRED.

    Returns 30yr fixed, 15yr fixed, and 5/1 ARM rates plus:
    - Spread over 10yr Treasury
    - Year-over-year rate change
    - Weekly history for charts
    """
    try:
        async with FREDClient(api_key=os.getenv("FRED_API_KEY")) as client:
            rates = await client.get_mortgage_rates()
            return _serialize(rates)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fmr/{fips_code}", summary="HUD Fair Market Rents by FIPS")
async def fair_market_rents(fips_code: str) -> dict:
    """
    Get HUD Fair Market Rents for a county.

    Returns FMRs by bedroom count (studio through 4BR) — the 40th percentile
    of rents, used as a benchmarking floor for market rents.

    **Example:** `/api/market/fmr/48453` (Travis County, Austin TX)
    """
    try:
        async with HUDClient(api_token=os.getenv("HUD_API_TOKEN")) as client:
            fmr = await client.get_fair_market_rents(fips_code)
            return _serialize(fmr)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/demographics/{state_fips}/{county_fips}", summary="Census demographics for a county")
async def demographics(state_fips: str, county_fips: str) -> dict:
    """
    Get Census ACS demographic profile for a county.

    Returns population, income, housing, vacancy, homeownership rate,
    education level, and derived RE signals (price-to-rent, price-to-income).

    **Example:** `/api/market/demographics/48/453` (Travis County, TX)
    """
    try:
        async with CensusClient(api_key=os.getenv("CENSUS_API_KEY")) as client:
            profile = await client.get_county_profile(state_fips, county_fips)
            return _serialize(profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sample", summary="Sample market report (Austin, TX — no API keys needed)")
async def sample_market_report() -> dict:
    """
    Returns a pre-built sample market report for Austin, TX.

    Uses real data if API keys are configured; returns structured placeholder
    data otherwise. Useful for UI development and demos.
    """
    try:
        service = _get_service()
        report = await service.get_market_report(
            metro="Austin, TX",
            state_fips="48",
            county_fips="453",
            fips_code="48453",
        )
        return _serialize_report(report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize(obj) -> dict:
    """Convert a dataclass to a serializable dict, stripping None values."""
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if v is not None}
    return obj


def _serialize_report(report: MarketReport) -> dict:
    """Serialize a MarketReport, handling nested dataclasses."""
    result = {}

    for field_name in [
        "market", "geography_type", "market_score", "market_grade",
        "investment_thesis", "key_tailwinds", "key_headwinds",
        "suggested_rent_growth", "suggested_exit_cap_range",
        "data_sources", "warnings",
    ]:
        val = getattr(report, field_name, None)
        if val is not None:
            result[field_name] = val

    if report.demographics:
        result["demographics"] = _serialize(report.demographics)
    if report.macro:
        result["macro"] = _serialize_macro(report.macro)
    if report.fair_market_rents:
        result["fair_market_rents"] = _serialize(report.fair_market_rents)
    if report.zillow:
        result["zillow"] = _serialize_zillow(report.zillow)
    if report.rent_benchmarks:
        result["rent_benchmarks"] = _serialize(report.rent_benchmarks)

    return result


def _serialize_macro(macro: MacroSnapshot) -> dict:
    """Serialize MacroSnapshot including nested MortgageRates."""
    d = _serialize(macro)
    if macro.mortgage_rates:
        d["mortgage_rates"] = _serialize(macro.mortgage_rates)
    return d


def _serialize_zillow(z) -> dict:
    """Serialize ZillowMetrics (trim history to last 24 months for API response)."""
    d = _serialize(z)
    if "zhvi_history" in d and isinstance(d["zhvi_history"], list):
        d["zhvi_history"] = d["zhvi_history"][-24:]
    if "zori_history" in d and isinstance(d["zori_history"], list):
        d["zori_history"] = d["zori_history"][-24:]
    return d
