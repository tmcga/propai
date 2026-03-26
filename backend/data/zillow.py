"""
Zillow Research Data Client

Zillow publishes free bulk research data (CSV downloads) updated monthly:
  - ZHVI: Zillow Home Value Index (home values by geography and type)
  - ZORI: Zillow Observed Rent Index (market rents by geography and type)
  - Market heat / inventory metrics

No API key needed. Data is downloaded from Zillow's research page:
https://www.zillow.com/research/data/

On first use, data is downloaded and cached locally. Subsequent requests
are served from the local cache (refreshed monthly).

We use the "smoothed, seasonally adjusted" versions for cleaner trend data.
"""

from __future__ import annotations

import os
import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Local cache directory
CACHE_DIR = Path(os.getenv("DATA_CACHE_DIR", "/tmp/propai_data_cache"))
CACHE_TTL_DAYS = 30  # Zillow updates monthly

# Zillow Research CSV download URLs
# Smoothed, seasonally adjusted, all homes (most useful for analysis)
ZILLOW_URLS = {
    # ZHVI — Home Values
    "zhvi_zip": "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zhvi_metro": "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zhvi_county": "https://files.zillowstatic.com/research/public_csvs/zhvi/County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zhvi_state": "https://files.zillowstatic.com/research/public_csvs/zhvi/State_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    # ZORI — Observed Rents (multifamily focus)
    "zori_zip": "https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_sm_month.csv",
    "zori_metro": "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_sm_month.csv",
    "zori_county": "https://files.zillowstatic.com/research/public_csvs/zori/County_zori_sm_month.csv",
    "zori_state": "https://files.zillowstatic.com/research/public_csvs/zori/State_zori_sm_month.csv",
}


@dataclass
class ZillowMetrics:
    """Zillow market metrics for a geography."""

    geography: str
    geography_type: str  # "zip", "metro", "county", "state"
    region_id: Optional[str] = None

    # ZHVI (Home Values)
    current_zhvi: Optional[float] = None  # Most recent month
    zhvi_1yr_ago: Optional[float] = None
    zhvi_3yr_ago: Optional[float] = None
    zhvi_5yr_ago: Optional[float] = None
    zhvi_yoy_pct: Optional[float] = None  # Year-over-year %
    zhvi_3yr_cagr: Optional[float] = None  # 3-year CAGR
    zhvi_5yr_cagr: Optional[float] = None  # 5-year CAGR
    zhvi_history: list[dict] = field(
        default_factory=list
    )  # {"date": "2023-01", "value": 450000}

    # ZORI (Rents)
    current_zori: Optional[float] = None  # Current median market rent
    zori_1yr_ago: Optional[float] = None
    zori_yoy_pct: Optional[float] = None
    zori_3yr_cagr: Optional[float] = None
    zori_history: list[dict] = field(default_factory=list)

    # Derived RE signals
    price_to_rent_ratio: Optional[float] = None  # ZHVI / (ZORI * 12)
    rent_growth_trend: Optional[str] = None  # "accelerating", "stable", "decelerating"

    data_as_of: Optional[str] = None
    source: str = "Zillow Research"
    warnings: list[str] = field(default_factory=list)


class ZillowClient:
    """
    Client for Zillow Research bulk data.

    Downloads and caches CSVs locally, then queries them in memory.
    No API key required.

    Usage:
        client = ZillowClient()
        metrics = await client.get_metro_metrics("Austin, TX")
        metrics = await client.get_zip_metrics("78701")
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=120.0,  # Zillow CSVs can be large
            follow_redirects=True,
            headers={"User-Agent": "PropAI/0.1 (research purposes)"},
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public: Geography lookups
    # ------------------------------------------------------------------

    async def get_metro_metrics(self, metro_name: str) -> ZillowMetrics:
        """
        Get ZHVI + ZORI for a metro area by name.

        Args:
            metro_name: Metro name as it appears in Zillow data.
                        Partial matches work (e.g., "Austin" matches "Austin, TX")

        Examples:
            await client.get_metro_metrics("Austin, TX")
            await client.get_metro_metrics("New York")
            await client.get_metro_metrics("Chicago")
            await client.get_metro_metrics("Los Angeles")
        """
        metrics = ZillowMetrics(geography=metro_name, geography_type="metro")
        await self._enrich_with_zhvi(metrics, "zhvi_metro", metro_name)
        await self._enrich_with_zori(metrics, "zori_metro", metro_name)
        self._compute_derived(metrics)
        return metrics

    async def get_zip_metrics(self, zipcode: str) -> ZillowMetrics:
        """
        Get ZHVI + ZORI for a ZIP code.

        Args:
            zipcode: 5-digit US ZIP code (e.g., "78701")
        """
        metrics = ZillowMetrics(geography=f"ZIP {zipcode}", geography_type="zip")
        await self._enrich_with_zhvi(
            metrics, "zhvi_zip", zipcode, match_field="RegionName"
        )
        await self._enrich_with_zori(
            metrics, "zori_zip", zipcode, match_field="RegionName"
        )
        self._compute_derived(metrics)
        return metrics

    async def get_county_metrics(self, county_name: str, state: str) -> ZillowMetrics:
        """
        Get ZHVI + ZORI for a county.

        Args:
            county_name: County name (e.g., "Travis")
            state:       State abbreviation (e.g., "TX")
        """
        search_term = county_name
        metrics = ZillowMetrics(
            geography=f"{county_name} County, {state}", geography_type="county"
        )
        await self._enrich_with_zhvi(metrics, "zhvi_county", search_term)
        await self._enrich_with_zori(metrics, "zori_county", search_term)
        self._compute_derived(metrics)
        return metrics

    async def get_state_metrics(self, state: str) -> ZillowMetrics:
        """
        Get state-level ZHVI + ZORI trends.

        Args:
            state: State name (e.g., "Texas") or abbreviation (e.g., "TX")
        """
        metrics = ZillowMetrics(geography=state, geography_type="state")
        await self._enrich_with_zhvi(metrics, "zhvi_state", state)
        await self._enrich_with_zori(metrics, "zori_state", state)
        self._compute_derived(metrics)
        return metrics

    # ------------------------------------------------------------------
    # Internals: CSV download and parsing
    # ------------------------------------------------------------------

    async def _get_csv(self, dataset_key: str) -> list[dict]:
        """
        Download or load from cache a Zillow Research CSV.
        Returns list of row dicts.
        """
        cache_file = self.cache_dir / f"{dataset_key}.csv"

        # Check cache freshness
        if cache_file.exists():
            age_days = (
                datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            ).days
            if age_days < CACHE_TTL_DAYS:
                logger.debug(f"Serving {dataset_key} from cache ({age_days}d old)")
                return self._parse_csv(cache_file.read_text(encoding="utf-8"))

        # Download fresh copy
        url = ZILLOW_URLS.get(dataset_key)
        if not url:
            logger.warning(f"Unknown Zillow dataset key: {dataset_key}")
            return []

        try:
            client = self._client or httpx.AsyncClient(
                timeout=120.0,
                follow_redirects=True,
                headers={"User-Agent": "PropAI/0.1"},
            )
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text

            # Cache it
            cache_file.write_text(text, encoding="utf-8")
            logger.info(f"Downloaded and cached {dataset_key} ({len(text):,} bytes)")
            return self._parse_csv(text)

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"Zillow CSV download failed ({dataset_key}): HTTP {e.response.status_code}"
            )
            # Try serving stale cache if available
            if cache_file.exists():
                logger.info(f"Serving stale cache for {dataset_key}")
                return self._parse_csv(cache_file.read_text(encoding="utf-8"))
            return []
        except Exception as e:
            logger.warning(f"Zillow CSV download failed ({dataset_key}): {e}")
            if cache_file.exists():
                return self._parse_csv(cache_file.read_text(encoding="utf-8"))
            return []

    @staticmethod
    def _parse_csv(text: str) -> list[dict]:
        """Parse CSV text into list of dicts."""
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def _find_row(
        self,
        rows: list[dict],
        search_term: str,
        match_field: str = "RegionName",
    ) -> Optional[dict]:
        """
        Find a row matching the search term (case-insensitive partial match).
        Prefers exact matches over partial matches.
        """
        term_lower = search_term.lower().strip()

        # Try exact match first
        for row in rows:
            if row.get(match_field, "").lower().strip() == term_lower:
                return row

        # Fall back to partial match
        for row in rows:
            if term_lower in row.get(match_field, "").lower():
                return row

        # Try matching just the city name (e.g., "Austin" from "Austin, TX")
        city_part = term_lower.split(",")[0].strip()
        for row in rows:
            region = row.get(match_field, "").lower()
            if city_part in region:
                return row

        return None

    def _extract_history(self, row: dict, limit_months: int = 60) -> list[dict]:
        """
        Extract the time-series columns from a Zillow row.
        Columns named like "2000-01", "2000-02", etc.
        """
        history = []
        for col, val in row.items():
            # Zillow date columns are "YYYY-MM" format
            if len(col) == 7 and col[4] == "-":
                try:
                    datetime.strptime(col, "%Y-%m")
                    if val and val.strip():
                        history.append({"date": col, "value": float(val)})
                except (ValueError, AttributeError):
                    continue

        history.sort(key=lambda x: x["date"])
        return history[-limit_months:]  # Return most recent N months

    async def _enrich_with_zhvi(
        self,
        metrics: ZillowMetrics,
        dataset_key: str,
        search_term: str,
        match_field: str = "RegionName",
    ) -> None:
        """Populate ZHVI fields on a ZillowMetrics object."""
        rows = await self._get_csv(dataset_key)
        if not rows:
            metrics.warnings.append(
                f"ZHVI data unavailable (could not download {dataset_key})"
            )
            return

        row = self._find_row(rows, search_term, match_field)
        if not row:
            metrics.warnings.append(
                f"No ZHVI match for '{search_term}' in {dataset_key}"
            )
            return

        history = self._extract_history(row)
        if not history:
            return

        metrics.zhvi_history = history
        metrics.current_zhvi = history[-1]["value"] if history else None
        metrics.data_as_of = history[-1]["date"] if history else None

        # Historical snapshots
        metrics.zhvi_1yr_ago = self._value_n_months_ago(history, 12)
        metrics.zhvi_3yr_ago = self._value_n_months_ago(history, 36)
        metrics.zhvi_5yr_ago = self._value_n_months_ago(history, 60)

        # YoY %
        if metrics.current_zhvi and metrics.zhvi_1yr_ago:
            metrics.zhvi_yoy_pct = round(
                (metrics.current_zhvi - metrics.zhvi_1yr_ago)
                / metrics.zhvi_1yr_ago
                * 100,
                2,
            )

        # CAGRs
        if metrics.current_zhvi and metrics.zhvi_3yr_ago:
            metrics.zhvi_3yr_cagr = round(
                ((metrics.current_zhvi / metrics.zhvi_3yr_ago) ** (1 / 3) - 1) * 100, 2
            )
        if metrics.current_zhvi and metrics.zhvi_5yr_ago:
            metrics.zhvi_5yr_cagr = round(
                ((metrics.current_zhvi / metrics.zhvi_5yr_ago) ** (1 / 5) - 1) * 100, 2
            )

    async def _enrich_with_zori(
        self,
        metrics: ZillowMetrics,
        dataset_key: str,
        search_term: str,
        match_field: str = "RegionName",
    ) -> None:
        """Populate ZORI (rent) fields on a ZillowMetrics object."""
        rows = await self._get_csv(dataset_key)
        if not rows:
            metrics.warnings.append(
                f"ZORI data unavailable (could not download {dataset_key})"
            )
            return

        row = self._find_row(rows, search_term, match_field)
        if not row:
            metrics.warnings.append(
                f"No ZORI match for '{search_term}' in {dataset_key}"
            )
            return

        history = self._extract_history(row)
        if not history:
            return

        metrics.zori_history = history
        metrics.current_zori = history[-1]["value"] if history else None
        metrics.zori_1yr_ago = self._value_n_months_ago(history, 12)

        if metrics.current_zori and metrics.zori_1yr_ago:
            metrics.zori_yoy_pct = round(
                (metrics.current_zori - metrics.zori_1yr_ago)
                / metrics.zori_1yr_ago
                * 100,
                2,
            )

        if metrics.current_zori:
            zori_3yr = self._value_n_months_ago(history, 36)
            if zori_3yr:
                metrics.zori_3yr_cagr = round(
                    ((metrics.current_zori / zori_3yr) ** (1 / 3) - 1) * 100, 2
                )

    @staticmethod
    def _value_n_months_ago(history: list[dict], n: int) -> Optional[float]:
        """Get value from N months ago in a history list."""
        if len(history) < n:
            return None
        return history[-n]["value"] if history else None

    def _compute_derived(self, metrics: ZillowMetrics) -> None:
        """Compute price-to-rent ratio and trend signals."""
        if metrics.current_zhvi and metrics.current_zori and metrics.current_zori > 0:
            metrics.price_to_rent_ratio = round(
                metrics.current_zhvi / (metrics.current_zori * 12), 1
            )

        # Rent growth trend: compare last 6mo CAGR to 12mo CAGR
        if metrics.zori_history and len(metrics.zori_history) >= 13:
            recent_6m = self._value_n_months_ago(metrics.zori_history, 6)
            current = metrics.current_zori
            if recent_6m and current and recent_6m > 0:
                recent_ann = ((current / recent_6m) ** 2 - 1) * 100
                yoy = metrics.zori_yoy_pct or 0
                if recent_ann > yoy * 1.2:
                    metrics.rent_growth_trend = "accelerating"
                elif recent_ann < yoy * 0.8:
                    metrics.rent_growth_trend = "decelerating"
                else:
                    metrics.rent_growth_trend = "stable"
