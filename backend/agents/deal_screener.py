"""
Deal Screener Agent
-------------------
Fast go/no-go on a deal before committing to full underwriting.
Takes listing-level info (price, units, rents, market) and returns
a structured verdict with reasoning in ~5 seconds.

Designed for top-of-funnel deal flow where an investor might see
20–50 deals per week and needs to filter to the 2–3 worth underwriting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from anthropic import AsyncAnthropic

from engine.financial import metrics as m
from engine.financial.models import DealInput, LoanInput, OperatingAssumptions, ExitAssumptions


# ── Pydantic-free dataclass for lightweight screening input ───────────────

@dataclass
class ScreenInput:
    """Minimal inputs needed for a 30-second deal screen."""
    asset_class: str
    purchase_price: float
    market: str

    # Income
    gross_scheduled_income: float         # annual, or 0 if unknown
    units: int | None = None
    avg_unit_rent: float | None = None    # monthly; auto-computes GSI if provided
    square_feet: float | None = None
    asking_rent_per_sf: float | None = None  # annual NNN

    # Expense estimates (optional — defaults applied)
    vacancy_rate: float = 0.05
    expense_ratio: float | None = None    # overrides individual items if provided
    noi_override: float | None = None     # if seller provides NOI directly

    # Financing assumptions
    ltv: float = 0.70
    interest_rate: float = 0.0675
    amortization_years: int = 30

    # Exit
    hold_period_years: int = 5
    exit_cap_rate: float | None = None    # estimated from market if not provided

    # Context
    additional_notes: str = ""            # broker notes, property description, etc.

    def __post_init__(self) -> None:
        # Auto-compute GSI from unit count + avg rent
        if self.gross_scheduled_income == 0 and self.units and self.avg_unit_rent:
            self.gross_scheduled_income = self.units * self.avg_unit_rent * 12
        # Auto-compute GSI from SF + rent/SF (NNN)
        if self.gross_scheduled_income == 0 and self.square_feet and self.asking_rent_per_sf:
            self.gross_scheduled_income = self.square_feet * self.asking_rent_per_sf


@dataclass
class ScreenVerdict:
    verdict: Literal["GO", "SOFT_GO", "PASS"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]

    # Quick metrics
    estimated_cap_rate: float
    estimated_dscr: float
    estimated_coc: float
    estimated_irr_range: tuple[float, float]
    price_per_unit: float | None
    price_per_sf: float | None
    grm: float

    # Reasoning
    headline: str                          # one-line verdict
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    suggested_max_price: float | None = None
    full_reasoning: str = ""


# ── Market cap rate benchmarks (fallback when exit cap not provided) ──────

MARKET_CAP_BENCHMARKS: dict[str, float] = {
    "multifamily": 0.055,
    "small_multifamily": 0.060,
    "sfr": 0.065,
    "office": 0.075,
    "retail": 0.070,
    "industrial": 0.055,
    "self_storage": 0.060,
    "mixed_use": 0.065,
    "str": 0.070,
    "development": 0.055,
}

EXPENSE_RATIO_BENCHMARKS: dict[str, float] = {
    "multifamily": 0.45,
    "small_multifamily": 0.40,
    "sfr": 0.35,
    "office": 0.40,
    "retail": 0.30,      # NNN — tenant pays most
    "industrial": 0.25,  # NNN
    "self_storage": 0.35,
    "mixed_use": 0.42,
    "str": 0.55,
    "development": 0.45,
}

SCREENING_THRESHOLDS = {
    "min_cap_rate": 0.045,
    "min_dscr": 1.15,
    "min_coc": 0.04,
    "min_irr": 0.10,
    "target_cap_rate": 0.055,
    "target_dscr": 1.25,
    "target_coc": 0.07,
    "target_irr": 0.15,
}


class DealScreener:
    """
    Two-pass screener:
      1. Math pass — compute quick metrics from inputs
      2. AI pass — Claude interprets results + market context + notes
    """

    def __init__(self) -> None:
        self.client = AsyncAnthropic()

    async def screen(self, inp: ScreenInput) -> ScreenVerdict:
        math = self._math_pass(inp)
        verdict = await self._ai_pass(inp, math)
        return verdict

    # ── Pass 1: pure math ─────────────────────────────────────────────────

    def _math_pass(self, inp: ScreenInput) -> dict:
        """Compute metrics from the minimal inputs available."""
        egi = inp.gross_scheduled_income * (1 - inp.vacancy_rate)
        expense_ratio = inp.expense_ratio or EXPENSE_RATIO_BENCHMARKS.get(inp.asset_class, 0.45)
        estimated_noi = inp.noi_override or (egi * (1 - expense_ratio))
        cap_rate = estimated_noi / inp.purchase_price if inp.purchase_price else 0

        exit_cap = inp.exit_cap_rate or MARKET_CAP_BENCHMARKS.get(inp.asset_class, 0.055)
        loan_amount = inp.purchase_price * inp.ltv
        equity = inp.purchase_price * (1 - inp.ltv) + inp.purchase_price * 0.01  # rough closing

        # Debt service
        r = inp.interest_rate / 12
        n = inp.amortization_years * 12
        monthly_payment = loan_amount * (r * (1 + r) ** n) / ((1 + r) ** n - 1) if r > 0 else 0
        annual_ds = monthly_payment * 12

        dscr = estimated_noi / annual_ds if annual_ds > 0 else 0
        btcf = estimated_noi - annual_ds
        coc = btcf / equity if equity > 0 else 0

        # Rough IRR range (low: no rent growth, high: 3% rent growth)
        def rough_irr(rent_growth: float) -> float:
            noi_exit = estimated_noi * ((1 + rent_growth) ** inp.hold_period_years) * (1 + rent_growth)
            exit_value = noi_exit / exit_cap
            sale_proceeds = exit_value * (1 - 0.03) - loan_amount
            total_cfs = [btcf * (1 + rent_growth) ** y for y in range(inp.hold_period_years)]
            total_cfs[-1] += sale_proceeds
            # simple approximation
            total_return = sum(total_cfs) / equity
            annualized = (1 + total_return) ** (1 / inp.hold_period_years) - 1
            return min(max(annualized, -0.5), 1.0)

        irr_low = rough_irr(0.0)
        irr_high = rough_irr(0.035)

        grm = inp.purchase_price / inp.gross_scheduled_income if inp.gross_scheduled_income else 0
        ppu = inp.purchase_price / inp.units if inp.units else None
        ppsf = inp.purchase_price / inp.square_feet if inp.square_feet else None

        # Suggested max price to hit target cap
        target_cap = SCREENING_THRESHOLDS["target_cap_rate"]
        max_price = estimated_noi / target_cap if estimated_noi > 0 else None

        return {
            "egi": egi,
            "estimated_noi": estimated_noi,
            "cap_rate": cap_rate,
            "loan_amount": loan_amount,
            "equity_required": equity,
            "annual_debt_service": annual_ds,
            "dscr": dscr,
            "btcf": btcf,
            "coc": coc,
            "irr_low": irr_low,
            "irr_high": irr_high,
            "grm": grm,
            "price_per_unit": ppu,
            "price_per_sf": ppsf,
            "exit_cap": exit_cap,
            "expense_ratio_used": expense_ratio,
            "max_price_at_target_cap": max_price,
        }

    # ── Pass 2: AI interpretation ─────────────────────────────────────────

    async def _ai_pass(self, inp: ScreenInput, math: dict) -> ScreenVerdict:
        thresholds = SCREENING_THRESHOLDS

        prompt = f"""You are a senior real estate acquisitions analyst. Screen this deal and return a JSON verdict.

DEAL INPUTS:
- Asset class: {inp.asset_class}
- Market: {inp.market}
- Purchase price: ${inp.purchase_price:,.0f}
- Units: {inp.units or 'N/A'}
- Square feet: {inp.square_feet or 'N/A'}
- Gross scheduled income: ${inp.gross_scheduled_income:,.0f}/yr
- Vacancy assumption: {inp.vacancy_rate:.0%}
- LTV: {inp.ltv:.0%} @ {inp.interest_rate:.2%}
- Hold period: {inp.hold_period_years} years
- Additional notes: {inp.additional_notes or 'None'}

COMPUTED METRICS:
- Estimated NOI: ${math['estimated_noi']:,.0f} (using {math['expense_ratio_used']:.0%} expense ratio)
- Going-in cap rate: {math['cap_rate']:.2%}
- DSCR: {math['dscr']:.2f}x
- Cash-on-cash (Yr 1): {math['coc']:.1%}
- IRR range: {math['irr_low']:.1%} – {math['irr_high']:.1%}
- GRM: {math['grm']:.1f}x
- Price/unit: ${math['price_per_unit']:,.0f} {f"" if math['price_per_unit'] else "(N/A)"}
- Price/SF: ${math['price_per_sf']:.2f} {f"" if math['price_per_sf'] else "(N/A)"}
- Suggested max price (at {thresholds['target_cap_rate']:.1%} cap): ${math['max_price_at_target_cap']:,.0f if math['max_price_at_target_cap'] else 'N/A'}

SCREENING THRESHOLDS:
- Minimum: {thresholds['min_cap_rate']:.1%} cap, {thresholds['min_dscr']:.2f}x DSCR, {thresholds['min_coc']:.0%} CoC, {thresholds['min_irr']:.0%} IRR
- Target: {thresholds['target_cap_rate']:.1%} cap, {thresholds['target_dscr']:.2f}x DSCR, {thresholds['target_coc']:.0%} CoC, {thresholds['target_irr']:.0%} IRR

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "verdict": "GO" | "SOFT_GO" | "PASS",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "headline": "One sentence verdict with the most important reason",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "concerns": ["concern 1", "concern 2"],
  "missing_info": ["what would change this verdict if known"],
  "full_reasoning": "2-3 paragraph analysis referencing specific numbers"
}}

Verdict definitions:
- GO: Pencils at or above targets. Worth full underwriting.
- SOFT_GO: Close to targets. Worth underwriting if market/story is compelling.
- PASS: Doesn't pencil. Move on unless major upside not captured in inputs.

Be direct. Real investors don't need hedging — they need a clear signal."""

        response = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        ai = json.loads(raw)

        return ScreenVerdict(
            verdict=ai["verdict"],
            confidence=ai["confidence"],
            estimated_cap_rate=math["cap_rate"],
            estimated_dscr=math["dscr"],
            estimated_coc=math["coc"],
            estimated_irr_range=(math["irr_low"], math["irr_high"]),
            price_per_unit=math["price_per_unit"],
            price_per_sf=math["price_per_sf"],
            grm=math["grm"],
            headline=ai["headline"],
            strengths=ai.get("strengths", []),
            concerns=ai.get("concerns", []),
            missing_info=ai.get("missing_info", []),
            suggested_max_price=math["max_price_at_target_cap"],
            full_reasoning=ai.get("full_reasoning", ""),
        )
