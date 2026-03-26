"""
US Census Bureau API Client

Pulls demographic, income, and housing data from the American Community Survey (ACS).
Free API key required — register at: https://api.census.gov/data/key_signup.html

Key datasets used:
  - ACS 5-Year Estimates (B-series tables) — most reliable, covers all geographies
  - Population Estimates (latest year available)

ACS variable reference: https://api.census.gov/data/2022/acs/acs5/variables.json
"""

from __future__ import annotations

import os
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

CENSUS_BASE = "https://api.census.gov/data"
ACS_YEAR = "2022"  # Most recent stable ACS 5-year vintage

# ── ACS 5-Year variable codes ──────────────────────────────────────────────
ACS_VARS = {
    # Population
    "total_population": "B01003_001E",
    # Age
    "median_age": "B01002_001E",
    # Income
    "median_hh_income": "B19013_001E",
    "per_capita_income": "B19301_001E",
    "poverty_rate_pop": "B17001_002E",  # Pop below poverty level
    "total_pop_poverty_denom": "B17001_001E",  # Denominator for poverty %
    # Housing
    "total_housing_units": "B25001_001E",
    "occupied_units": "B25002_002E",
    "vacant_units": "B25002_003E",
    "owner_occupied": "B25003_002E",
    "renter_occupied": "B25003_003E",
    "median_home_value": "B25077_001E",
    "median_gross_rent": "B25064_001E",
    "median_rooms": "B25018_001E",
    # Education
    "bachelors_or_higher": "B15003_022E",  # Pop 25+ with bachelor's
    "pop_25_plus": "B15003_001E",  # Denominator for education %
}


@dataclass
class DemographicProfile:
    """Demographic and housing snapshot for a geography."""

    geography: str
    geography_type: str  # "county", "place", "zip", "metro"

    # Population
    total_population: Optional[int] = None
    median_age: Optional[float] = None
    population_growth_pct: Optional[float] = None  # Populated by multi-year comparison

    # Income
    median_household_income: Optional[int] = None
    per_capita_income: Optional[int] = None
    poverty_rate: Optional[float] = None

    # Housing
    total_housing_units: Optional[int] = None
    vacancy_rate: Optional[float] = None
    homeownership_rate: Optional[float] = None
    renter_rate: Optional[float] = None
    median_home_value: Optional[int] = None
    median_gross_rent: Optional[int] = None

    # Education
    bachelors_plus_rate: Optional[float] = None

    # Derived signals
    rent_to_income_ratio: Optional[float] = None  # Annual rent / HH income
    price_to_income_ratio: Optional[float] = None  # Home value / HH income
    price_to_rent_ratio: Optional[float] = None  # Home value / (annual rent)

    # Metadata
    data_year: str = ACS_YEAR
    source: str = "US Census Bureau, ACS 5-Year Estimates"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class CensusClient:
    """
    Async client for the US Census Bureau ACS API.

    Supports lookup by:
      - County (state FIPS + county FIPS)
      - Place / City (state FIPS + place FIPS)
      - ZIP Code Tabulation Area (ZCTA)
      - Metro Area (CBSA code)

    Usage:
        async with CensusClient() as client:
            profile = await client.get_county_profile("48", "453")  # Travis County, TX
    """

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 86400):
        """
        Args:
            api_key:   Census API key (defaults to CENSUS_API_KEY env var).
                       Without a key, requests still work but are rate-limited to 500/day.
            cache_ttl: Cache TTL in seconds (default 24 hours — data changes annually).
        """
        self.api_key = api_key or os.getenv("CENSUS_API_KEY", "")
        self.cache_ttl = cache_ttl
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public: Geography-specific lookups
    # ------------------------------------------------------------------

    async def get_county_profile(
        self, state_fips: str, county_fips: str
    ) -> DemographicProfile:
        """
        Fetch demographic profile for a US county.

        Args:
            state_fips:   2-digit state FIPS (e.g., "48" for Texas)
            county_fips:  3-digit county FIPS (e.g., "453" for Travis County)

        Example:
            await client.get_county_profile("48", "453")  # Travis County (Austin), TX
            await client.get_county_profile("36", "061")  # New York County, NY
            await client.get_county_profile("17", "031")  # Cook County (Chicago), IL
        """
        geo_params = {"for": f"county:{county_fips}", "in": f"state:{state_fips}"}
        geography = f"County {county_fips}, State {state_fips}"
        return await self._fetch_profile(geo_params, geography, "county")

    async def get_place_profile(
        self, state_fips: str, place_fips: str
    ) -> DemographicProfile:
        """
        Fetch demographic profile for a Census place (city/town).

        Args:
            state_fips:  2-digit state FIPS
            place_fips:  5-digit place FIPS

        Example:
            await client.get_place_profile("48", "05000")  # Austin city, TX
        """
        geo_params = {"for": f"place:{place_fips}", "in": f"state:{state_fips}"}
        geography = f"Place {place_fips}, State {state_fips}"
        return await self._fetch_profile(geo_params, geography, "place")

    async def get_zip_profile(self, zipcode: str) -> DemographicProfile:
        """
        Fetch demographic profile for a ZIP Code Tabulation Area (ZCTA).

        Args:
            zipcode: 5-digit ZIP code (e.g., "78701" for downtown Austin)

        Note: ZCTAs don't perfectly match ZIP codes but are close enough for analysis.
        """
        geo_params = {"for": f"zip code tabulation area:{zipcode}"}
        return await self._fetch_profile(geo_params, f"ZIP {zipcode}", "zip")

    async def get_metro_profile(self, cbsa_code: str) -> DemographicProfile:
        """
        Fetch demographic profile for a Core Based Statistical Area (metro).

        Args:
            cbsa_code: 5-digit CBSA code (e.g., "12420" for Austin-Round Rock, TX)

        Common CBSA codes:
            12420 — Austin-Round Rock, TX
            35620 — New York-Newark-Jersey City, NY-NJ-PA
            31080 — Los Angeles-Long Beach-Anaheim, CA
            16980 — Chicago-Naperville-Elgin, IL-IN-WI
            19100 — Dallas-Fort Worth-Arlington, TX
            26420 — Houston-The Woodlands-Sugar Land, TX
            33100 — Miami-Fort Lauderdale-Pompano Beach, FL
            41860 — San Francisco-Oakland-Berkeley, CA
            38060 — Phoenix-Mesa-Chandler, AZ
            42660 — Seattle-Tacoma-Bellevue, WA
        """
        geo_params = {
            "for": f"metropolitan statistical area/micropolitan statistical area:{cbsa_code}"
        }
        return await self._fetch_profile(geo_params, f"Metro {cbsa_code}", "metro")

    # ------------------------------------------------------------------
    # Core fetch logic
    # ------------------------------------------------------------------

    async def _fetch_profile(
        self,
        geo_params: dict,
        geography: str,
        geography_type: str,
    ) -> DemographicProfile:
        """Fetch ACS variables and assemble a DemographicProfile."""
        profile = DemographicProfile(
            geography=geography,
            geography_type=geography_type,
        )

        var_list = ",".join(ACS_VARS.values())
        params = {
            "get": f"NAME,{var_list}",
            **geo_params,
        }
        if self.api_key:
            params["key"] = self.api_key

        url = f"{CENSUS_BASE}/{ACS_YEAR}/acs/acs5"

        try:
            data = await self._get(url, params)
            if not data or len(data) < 2:
                profile.warnings.append("No Census data returned for this geography.")
                return profile

            # data[0] = headers, data[1] = values
            headers = data[0]
            values = data[1]
            row = dict(zip(headers, values))

            # Update geography name from Census canonical name
            if "NAME" in row:
                profile.geography = row["NAME"]

            def safe_int(key: str) -> Optional[int]:
                val = row.get(ACS_VARS.get(key, ""), -1)
                try:
                    v = int(val)
                    return v if v >= 0 else None
                except (ValueError, TypeError):
                    return None

            def safe_float(key: str) -> Optional[float]:
                val = row.get(ACS_VARS.get(key, ""), -1)
                try:
                    v = float(val)
                    return v if v >= 0 else None
                except (ValueError, TypeError):
                    return None

            # ── Population ────────────────────────────────────────────
            profile.total_population = safe_int("total_population")
            profile.median_age = safe_float("median_age")

            # ── Income ────────────────────────────────────────────────
            profile.median_household_income = safe_int("median_hh_income")
            profile.per_capita_income = safe_int("per_capita_income")

            poverty_pop = safe_int("poverty_rate_pop")
            total_pop_pov = safe_int("total_pop_poverty_denom")
            if poverty_pop and total_pop_pov and total_pop_pov > 0:
                profile.poverty_rate = round(poverty_pop / total_pop_pov, 4)

            # ── Housing ───────────────────────────────────────────────
            profile.total_housing_units = safe_int("total_housing_units")
            profile.median_home_value = safe_int("median_home_value")
            profile.median_gross_rent = safe_int("median_gross_rent")

            vacant = safe_int("vacant_units")
            total_units = safe_int("total_housing_units")
            if vacant is not None and total_units and total_units > 0:
                profile.vacancy_rate = round(vacant / total_units, 4)

            owner = safe_int("owner_occupied")
            renter = safe_int("renter_occupied")
            occupied = safe_int("occupied_units")
            if occupied and occupied > 0:
                if owner:
                    profile.homeownership_rate = round(owner / occupied, 4)
                if renter:
                    profile.renter_rate = round(renter / occupied, 4)

            # ── Education ─────────────────────────────────────────────
            bach = safe_int("bachelors_or_higher")
            pop_25 = safe_int("pop_25_plus")
            if bach and pop_25 and pop_25 > 0:
                profile.bachelors_plus_rate = round(bach / pop_25, 4)

            # ── Derived RE signals ────────────────────────────────────
            if profile.median_gross_rent and profile.median_household_income:
                annual_rent = profile.median_gross_rent * 12
                profile.rent_to_income_ratio = round(
                    annual_rent / profile.median_household_income, 4
                )

            if profile.median_home_value and profile.median_household_income:
                profile.price_to_income_ratio = round(
                    profile.median_home_value / profile.median_household_income, 2
                )

            if profile.median_home_value and profile.median_gross_rent:
                annual_rent = profile.median_gross_rent * 12
                if annual_rent > 0:
                    profile.price_to_rent_ratio = round(
                        profile.median_home_value / annual_rent, 1
                    )

        except httpx.HTTPStatusError as e:
            msg = f"Census API error {e.response.status_code}: {e.response.text[:200]}"
            logger.warning(msg)
            profile.warnings.append(msg)
        except httpx.RequestError as e:
            msg = f"Census API connection error: {str(e)}"
            logger.warning(msg)
            profile.warnings.append(msg)
        except Exception as e:
            msg = f"Unexpected error fetching Census data: {str(e)}"
            logger.error(msg, exc_info=True)
            profile.warnings.append(msg)

        return profile

    async def _get(self, url: str, params: dict) -> list[list[str]]:
        """Execute a GET request, using internal client or creating one."""
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        finally:
            if not self._client:
                await client.aclose()

    # ------------------------------------------------------------------
    # Utility: FIPS lookup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def state_fips(state_abbr: str) -> Optional[str]:
        """Convert state abbreviation to 2-digit FIPS code."""
        mapping = {
            "AL": "01",
            "AK": "02",
            "AZ": "04",
            "AR": "05",
            "CA": "06",
            "CO": "08",
            "CT": "09",
            "DE": "10",
            "FL": "12",
            "GA": "13",
            "HI": "15",
            "ID": "16",
            "IL": "17",
            "IN": "18",
            "IA": "19",
            "KS": "20",
            "KY": "21",
            "LA": "22",
            "ME": "23",
            "MD": "24",
            "MA": "25",
            "MI": "26",
            "MN": "27",
            "MS": "28",
            "MO": "29",
            "MT": "30",
            "NE": "31",
            "NV": "32",
            "NH": "33",
            "NJ": "34",
            "NM": "35",
            "NY": "36",
            "NC": "37",
            "ND": "38",
            "OH": "39",
            "OK": "40",
            "OR": "41",
            "PA": "42",
            "RI": "44",
            "SC": "45",
            "SD": "46",
            "TN": "47",
            "TX": "48",
            "UT": "49",
            "VT": "50",
            "VA": "51",
            "WA": "53",
            "WV": "54",
            "WI": "55",
            "WY": "56",
            "DC": "11",
        }
        return mapping.get(state_abbr.upper())
