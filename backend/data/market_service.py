"""
Market Research Service — orchestrates all data sources into a unified report.

Combines Census, FRED, HUD, and Zillow data into a single MarketReport
object that powers both the UI market intelligence panel and the
AI investment memo generator.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from .census import CensusClient, DemographicProfile
from .fred import FREDClient, MacroSnapshot, MortgageRates
from .hud import HUDClient, FairMarketRents
from .zillow import ZillowClient, ZillowMetrics

logger = logging.getLogger(__name__)


@dataclass
class RentBenchmarks:
    """Aggregated rent benchmarks from all sources for a market."""

    # HUD Fair Market Rents (40th percentile, utility-inclusive)
    fmr_studio: Optional[int] = None
    fmr_1br: Optional[int] = None
    fmr_2br: Optional[int] = None
    fmr_3br: Optional[int] = None
    fmr_4br: Optional[int] = None

    # Zillow ZORI (current market median, utilities-exclusive)
    zori_current: Optional[float] = None
    zori_yoy_pct: Optional[float] = None
    zori_3yr_cagr: Optional[float] = None
    zori_trend: Optional[str] = None

    # Derived
    implied_rent_growth_assumption: Optional[float] = None  # Suggested underwriting assumption
    rent_environment: Optional[str] = None  # "strong", "moderate", "softening"


@dataclass
class MarketReport:
    """
    Complete market intelligence report for a geography.

    This is the single object that powers:
      - The market intelligence panel in the UI
      - The Market Analysis section of the AI investment memo
      - Underwriting assumption validation
    """

    # Identity
    market: str
    geography_type: str  # "metro", "county", "zip"

    # Sub-reports (populated independently, may be partial if APIs fail)
    demographics: Optional[DemographicProfile] = None
    macro: Optional[MacroSnapshot] = None
    fair_market_rents: Optional[FairMarketRents] = None
    zillow: Optional[ZillowMetrics] = None
    rent_benchmarks: Optional[RentBenchmarks] = None

    # Synthesized signals (derived from all sources)
    market_score: Optional[int] = None           # 1–100 composite score
    market_grade: Optional[str] = None           # "A+", "A", "B+", "B", "C", "D"
    investment_thesis: Optional[str] = None      # 2–3 sentence AI-ready summary
    key_tailwinds: list[str] = field(default_factory=list)
    key_headwinds: list[str] = field(default_factory=list)
    suggested_rent_growth: Optional[float] = None   # Suggested underwriting assumption
    suggested_exit_cap_range: Optional[tuple] = None  # (low, high) range

    warnings: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)


class MarketService:
    """
    Orchestrates parallel data fetching across all sources and assembles
    a unified MarketReport.

    Designed for resilience: if any single source fails, the others
    still populate. Partial reports are better than no reports.

    Usage:
        service = MarketService()
        report = await service.get_market_report(
            metro="Austin, TX",
            state_fips="48",
            county_fips="453",
            fips_code="48453",
        )
    """

    def __init__(
        self,
        census_key: Optional[str] = None,
        fred_key: Optional[str] = None,
        hud_token: Optional[str] = None,
    ):
        self.census_key = census_key
        self.fred_key = fred_key
        self.hud_token = hud_token

    async def get_market_report(
        self,
        metro: str,
        state_fips: Optional[str] = None,
        county_fips: Optional[str] = None,
        fips_code: Optional[str] = None,   # Combined state+county (5 digits)
        zipcode: Optional[str] = None,
    ) -> MarketReport:
        """
        Build a complete market report by fetching all sources in parallel.

        Args:
            metro:       Metro/city name (e.g., "Austin, TX")
            state_fips:  2-digit state FIPS (e.g., "48")
            county_fips: 3-digit county FIPS (e.g., "453")
            fips_code:   5-digit combined FIPS (e.g., "48453") — used for HUD
            zipcode:     ZIP code for hyper-local analysis

        The more geo identifiers you provide, the richer the report.
        At minimum, metro name is required for Zillow + FRED data.
        """
        report = MarketReport(
            market=metro,
            geography_type="metro" if not zipcode else "zip",
        )

        # ── Fetch all sources in parallel ────────────────────────────
        tasks = []

        # Always fetch macro (FRED) — no geo required
        tasks.append(("macro", self._fetch_macro()))

        # Zillow — metro name or ZIP
        if zipcode:
            tasks.append(("zillow", self._fetch_zillow_zip(zipcode)))
        else:
            tasks.append(("zillow", self._fetch_zillow_metro(metro)))

        # Census — requires FIPS codes
        if state_fips and county_fips:
            tasks.append(("census", self._fetch_census_county(state_fips, county_fips)))
        elif zipcode:
            tasks.append(("census", self._fetch_census_zip(zipcode)))

        # HUD — requires 5-digit FIPS
        if fips_code:
            tasks.append(("hud", self._fetch_hud(fips_code)))

        # Execute all in parallel with individual error handling
        results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True,
        )

        for (source_name, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                report.warnings.append(f"{source_name} data fetch failed: {str(result)}")
                logger.warning(f"MarketService {source_name} failed: {result}")
            else:
                if source_name == "macro":
                    report.macro = result
                    report.data_sources.append("FRED")
                elif source_name == "zillow":
                    report.zillow = result
                    report.data_sources.append("Zillow Research")
                elif source_name == "census":
                    report.demographics = result
                    report.data_sources.append("US Census Bureau (ACS)")
                elif source_name == "hud":
                    report.fair_market_rents = result
                    report.data_sources.append("HUD Fair Market Rents")

        # ── Synthesize rent benchmarks ────────────────────────────────
        report.rent_benchmarks = self._build_rent_benchmarks(report)

        # ── Compute market score and signals ─────────────────────────
        self._compute_market_signals(report)

        return report

    # ------------------------------------------------------------------
    # Individual fetch wrappers (each handles its own errors)
    # ------------------------------------------------------------------

    async def _fetch_macro(self) -> MacroSnapshot:
        async with FREDClient(api_key=self.fred_key) as client:
            return await client.get_macro_snapshot()

    async def _fetch_zillow_metro(self, metro: str) -> ZillowMetrics:
        async with ZillowClient() as client:
            return await client.get_metro_metrics(metro)

    async def _fetch_zillow_zip(self, zipcode: str) -> ZillowMetrics:
        async with ZillowClient() as client:
            return await client.get_zip_metrics(zipcode)

    async def _fetch_census_county(self, state_fips: str, county_fips: str) -> DemographicProfile:
        async with CensusClient(api_key=self.census_key) as client:
            return await client.get_county_profile(state_fips, county_fips)

    async def _fetch_census_zip(self, zipcode: str) -> DemographicProfile:
        async with CensusClient(api_key=self.census_key) as client:
            return await client.get_zip_profile(zipcode)

    async def _fetch_hud(self, fips_code: str) -> FairMarketRents:
        async with HUDClient(api_token=self.hud_token) as client:
            return await client.get_fair_market_rents(fips_code)

    # ------------------------------------------------------------------
    # Synthesis: rent benchmarks
    # ------------------------------------------------------------------

    def _build_rent_benchmarks(self, report: MarketReport) -> RentBenchmarks:
        """Combine HUD FMR and Zillow ZORI into a unified rent benchmark."""
        rb = RentBenchmarks()

        if report.fair_market_rents:
            fmr = report.fair_market_rents
            rb.fmr_studio = fmr.fmr_studio
            rb.fmr_1br = fmr.fmr_1br
            rb.fmr_2br = fmr.fmr_2br
            rb.fmr_3br = fmr.fmr_3br
            rb.fmr_4br = fmr.fmr_4br

        if report.zillow:
            z = report.zillow
            rb.zori_current = z.current_zori
            rb.zori_yoy_pct = z.zori_yoy_pct
            rb.zori_3yr_cagr = z.zori_3yr_cagr
            rb.zori_trend = z.rent_growth_trend

        # Suggested rent growth assumption for underwriting
        # Use 3yr CAGR trimmed toward long-run mean (3%)
        if rb.zori_3yr_cagr is not None:
            raw = rb.zori_3yr_cagr / 100
            # Regression toward long-run mean (3%)
            trimmed = raw * 0.6 + 0.03 * 0.4
            rb.implied_rent_growth_assumption = round(max(0.0, min(trimmed, 0.07)), 4)
        else:
            rb.implied_rent_growth_assumption = 0.03  # Default long-run assumption

        # Rent environment classification
        yoy = rb.zori_yoy_pct or 0
        if yoy > 5:
            rb.rent_environment = "strong"
        elif yoy > 2:
            rb.rent_environment = "moderate"
        elif yoy > 0:
            rb.rent_environment = "slowing"
        else:
            rb.rent_environment = "softening"

        return rb

    # ------------------------------------------------------------------
    # Synthesis: market score and investment signals
    # ------------------------------------------------------------------

    def _compute_market_signals(self, report: MarketReport) -> None:
        """
        Compute composite market score (1–100) and generate plain-English
        tailwinds/headwinds for the investment memo.
        """
        score_components = []
        tailwinds = []
        headwinds = []

        demo = report.demographics
        z = report.zillow
        macro = report.macro
        rb = report.rent_benchmarks

        # ── Population growth signal ──────────────────────────────────
        if demo and demo.total_population:
            # Can't compute growth from single snapshot — flag as available
            score_components.append(60)  # Neutral without trend

        # ── Income & affordability ────────────────────────────────────
        if demo and demo.median_household_income:
            hhi = demo.median_household_income
            if hhi > 80_000:
                tailwinds.append(f"High median household income (${hhi:,}) supports strong rent-paying capacity.")
                score_components.append(75)
            elif hhi > 60_000:
                score_components.append(60)
            else:
                headwinds.append(f"Below-average median income (${hhi:,}) may limit rent growth.")
                score_components.append(40)

        # ── Rent growth (Zillow ZORI) ─────────────────────────────────
        if z and z.zori_yoy_pct is not None:
            yoy = z.zori_yoy_pct
            if yoy > 5:
                tailwinds.append(f"Strong rent growth of {yoy:.1f}% YoY (Zillow ZORI).")
                score_components.append(85)
            elif yoy > 2:
                tailwinds.append(f"Moderate rent growth of {yoy:.1f}% YoY.")
                score_components.append(65)
            elif yoy > 0:
                score_components.append(50)
            else:
                headwinds.append(f"Rent growth is flat or negative ({yoy:.1f}% YoY) — monitor supply pipeline.")
                score_components.append(30)

        # ── Home value appreciation ───────────────────────────────────
        if z and z.zhvi_yoy_pct is not None:
            yoy = z.zhvi_yoy_pct
            if yoy > 5:
                tailwinds.append(f"Home values appreciating {yoy:.1f}% YoY, supporting exit values.")
                score_components.append(80)
            elif yoy > 0:
                score_components.append(60)
            else:
                headwinds.append(f"Home values declining ({yoy:.1f}% YoY) — exit cap rate risk elevated.")
                score_components.append(35)

        # ── Macro rate environment ────────────────────────────────────
        if macro and macro.rate_environment:
            if macro.rate_environment == "accommodative":
                tailwinds.append("Accommodative rate environment supports leveraged returns.")
                score_components.append(80)
            elif macro.rate_environment == "restrictive":
                headwinds.append(f"Restrictive rate environment ({macro.fed_funds_rate:.2f}% fed funds) compresses leveraged returns.")
                score_components.append(35)
            else:
                score_components.append(55)

        # ── Vacancy ───────────────────────────────────────────────────
        if demo and demo.vacancy_rate is not None:
            vac = demo.vacancy_rate
            if vac < 0.05:
                tailwinds.append(f"Tight housing supply ({vac:.1%} vacancy rate) supports rent growth.")
                score_components.append(80)
            elif vac < 0.08:
                score_components.append(60)
            else:
                headwinds.append(f"Elevated vacancy rate ({vac:.1%}) may cap rent upside.")
                score_components.append(35)

        # ── Education / workforce ─────────────────────────────────────
        if demo and demo.bachelors_plus_rate and demo.bachelors_plus_rate > 0.40:
            tailwinds.append(f"Highly educated workforce ({demo.bachelors_plus_rate:.0%} college-educated) drives tech/professional job demand.")
            score_components.append(75)

        # ── Compute composite score ───────────────────────────────────
        if score_components:
            report.market_score = round(sum(score_components) / len(score_components))
        else:
            report.market_score = 50  # Neutral default

        # ── Letter grade ──────────────────────────────────────────────
        score = report.market_score
        if score >= 80:
            report.market_grade = "A"
        elif score >= 70:
            report.market_grade = "B+"
        elif score >= 60:
            report.market_grade = "B"
        elif score >= 50:
            report.market_grade = "C+"
        else:
            report.market_grade = "C"

        report.key_tailwinds = tailwinds[:5]  # Top 5
        report.key_headwinds = headwinds[:5]

        # ── Suggested underwriting assumptions ───────────────────────
        if rb:
            report.suggested_rent_growth = rb.implied_rent_growth_assumption

        if macro and macro.treasury_10yr:
            t10 = macro.treasury_10yr
            # Rule of thumb: cap rates typically trade 150–300bps over 10yr
            report.suggested_exit_cap_range = (
                round(t10 / 100 + 0.015, 3),
                round(t10 / 100 + 0.030, 3),
            )

        # ── Investment thesis (text for AI memo seed) ─────────────────
        report.investment_thesis = self._build_thesis(report)

    def _build_thesis(self, report: MarketReport) -> str:
        """Build a 2–3 sentence market thesis for the investment memo."""
        parts = []

        z = report.zillow
        demo = report.demographics

        if z and z.zori_yoy_pct:
            parts.append(
                f"{report.market} has demonstrated {'strong' if z.zori_yoy_pct > 4 else 'moderate'} "
                f"rent growth of {z.zori_yoy_pct:.1f}% YoY (Zillow ZORI)."
            )

        if demo and demo.median_household_income:
            parts.append(
                f"With a median household income of ${demo.median_household_income:,} "
                f"and a {'tight' if (demo.vacancy_rate or 0.07) < 0.06 else 'balanced'} "
                f"housing supply ({(demo.vacancy_rate or 0.05):.1%} vacancy), "
                f"the market fundamentals support continued demand for quality rental housing."
            )

        if report.macro and report.macro.rate_environment == "restrictive":
            parts.append(
                "The current rate environment warrants conservative leverage assumptions "
                "and a well-supported exit cap rate."
            )
        elif report.macro and report.macro.rate_environment == "accommodative":
            parts.append(
                "The accommodative rate environment provides a favorable backdrop for leveraged acquisitions."
            )

        return " ".join(parts) if parts else f"Market analysis for {report.market}."
