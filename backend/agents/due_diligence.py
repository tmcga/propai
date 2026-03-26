"""
Due Diligence Red Flag Detector
--------------------------------
Analyzes T-12s, rent rolls, and underwriting assumptions to surface
anomalies, seller manipulation, and risks before closing.

Designed for the period between LOI and contract — when you have
documents but are still deciding whether to proceed.

Red flag categories:
  - Income manipulation (inflated GSI, hidden vacancies, one-time items)
  - Expense scrubbing (missing line items, below-market costs)
  - Rent roll issues (loss-to-lease, rollover risk, below-market leases)
  - Market/valuation concerns (over-priced vs. comps, cap rate compression)
  - Physical/deferred capex (items that will hit NOI post-close)
  - Financing risks (rate sensitivity, refinance risk at exit)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from anthropic import AsyncAnthropic, APITimeoutError, RateLimitError, InternalServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

from agents.document_parser import T12Summary, RentRollSummary
from engine.financial.models import DealInput


# ── Flag severity levels ──────────────────────────────────────────────────

SEVERITY = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


@dataclass
class RedFlag:
    severity: SEVERITY
    category: str       # "Income", "Expenses", "Rent Roll", "Market", "Financing", "Physical"
    title: str
    detail: str
    suggested_action: str
    financial_impact: str = ""   # e.g. "~$45K/yr NOI impact if corrected"


@dataclass
class DDReport:
    overall_risk: Literal["HIGH", "MEDIUM", "LOW"]
    proceed_recommendation: Literal["PROCEED", "PROCEED_WITH_CONDITIONS", "PAUSE", "PASS"]
    headline_summary: str

    red_flags: list[RedFlag]
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

    # Adjusted NOI (after applying conservative corrections to seller's numbers)
    seller_noi: float | None = None
    adjusted_noi: float | None = None
    noi_haircut_pct: float | None = None

    # Key questions for seller
    diligence_questions: list[str] = field(default_factory=list)

    # What to request from seller
    document_requests: list[str] = field(default_factory=list)

    full_analysis: str = ""


# ── Benchmark data for anomaly detection ─────────────────────────────────

# Market expense ratios by asset class (used to flag outliers)
EXPENSE_RATIO_NORMS = {
    "multifamily": (0.35, 0.55),       # (low, high) expected range
    "small_multifamily": (0.30, 0.50),
    "sfr": (0.25, 0.45),
    "office": (0.30, 0.50),
    "retail": (0.15, 0.35),            # NNN leases keep this low
    "industrial": (0.10, 0.30),        # NNN
    "self_storage": (0.25, 0.45),
    "mixed_use": (0.35, 0.50),
    "str": (0.45, 0.65),
    "development": (0.40, 0.60),
}

# Expense line items that MUST be present (their absence is a red flag)
REQUIRED_EXPENSE_LINES = {
    "multifamily": ["property_taxes", "insurance", "management_fees", "repairs_maintenance"],
    "office": ["property_taxes", "insurance", "management_fees", "utilities"],
    "retail": ["property_taxes", "insurance", "management_fees"],
    "industrial": ["property_taxes", "insurance"],
    "self_storage": ["property_taxes", "insurance", "management_fees", "utilities"],
}


class DueDiligenceAgent:

    def __init__(self) -> None:
        self.client = AsyncAnthropic()

    async def analyze(
        self,
        deal: DealInput,
        t12: T12Summary | None = None,
        rent_roll: RentRollSummary | None = None,
        additional_docs: str = "",      # free-text inspection notes, broker remarks, etc.
    ) -> DDReport:
        """Run full due diligence analysis. Returns structured DDReport."""
        math_flags = self._math_pass(deal, t12, rent_roll)
        ai_report = await self._ai_pass(deal, t12, rent_roll, math_flags, additional_docs)
        return ai_report

    # ── Pass 1: Rule-based math checks ───────────────────────────────────

    def _math_pass(
        self,
        deal: DealInput,
        t12: T12Summary | None,
        rent_roll: RentRollSummary | None,
    ) -> list[dict]:
        """Run deterministic checks — things the math can catch without AI."""
        flags: list[dict] = []
        ops = deal.operations
        asset_class = str(deal.asset_class)

        # ── Expense ratio check ───────────────────────────────────────────
        noi = ops.gross_scheduled_income * (1 - ops.vacancy_rate) - (
            ops.property_taxes + ops.insurance + ops.maintenance_reserves +
            ops.capex_reserves + ops.utilities + ops.other_expenses +
            ops.gross_scheduled_income * ops.management_fee_pct
        )
        egi = ops.gross_scheduled_income * (1 - ops.vacancy_rate) + ops.other_income
        if egi > 0:
            expense_ratio = 1 - (noi / egi)
            low, high = EXPENSE_RATIO_NORMS.get(asset_class, (0.35, 0.55))
            if expense_ratio < low:
                flags.append({
                    "type": "expense_ratio_low",
                    "expense_ratio": expense_ratio,
                    "expected_low": low,
                    "estimated_missing_expenses": egi * (low - expense_ratio),
                })
            elif expense_ratio > high:
                flags.append({
                    "type": "expense_ratio_high",
                    "expense_ratio": expense_ratio,
                    "expected_high": high,
                })

        # ── Management fee check ──────────────────────────────────────────
        if ops.management_fee_pct < 0.03:
            flags.append({
                "type": "management_fee_missing",
                "fee_pct": ops.management_fee_pct,
                "market_rate": 0.05,
                "annual_impact": egi * (0.05 - ops.management_fee_pct),
            })

        # ── CapEx reserves check ──────────────────────────────────────────
        if deal.units and ops.capex_reserves < deal.units * 300:
            flags.append({
                "type": "capex_reserves_low",
                "capex_per_unit": ops.capex_reserves / deal.units if deal.units else 0,
                "market_minimum_per_unit": 300,
            })

        # ── DSCR check ────────────────────────────────────────────────────
        r = deal.loan.interest_rate / 12
        n = deal.loan.amortization_years * 12
        loan = deal.loan_amount
        monthly_ds = loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1) if r > 0 else 0
        annual_ds = monthly_ds * 12
        dscr = noi / annual_ds if annual_ds > 0 else 0
        if dscr < 1.20:
            flags.append({"type": "dscr_tight", "dscr": dscr})

        # ── T-12 specific checks ──────────────────────────────────────────
        if t12:
            # Check if T-12 NOI matches underwriting NOI
            if t12.net_operating_income > 0:
                variance = (noi - t12.net_operating_income) / t12.net_operating_income
                if variance > 0.10:
                    flags.append({
                        "type": "noi_variance",
                        "underwriting_noi": noi,
                        "t12_noi": t12.net_operating_income,
                        "variance_pct": variance,
                    })

            # Missing expense lines
            required = REQUIRED_EXPENSE_LINES.get(asset_class, [])
            if "property_taxes" in required and t12.property_taxes == 0:
                flags.append({"type": "missing_expense", "line": "property_taxes"})
            if "insurance" in required and t12.insurance == 0:
                flags.append({"type": "missing_expense", "line": "insurance"})
            if "management_fees" in required and t12.management_fees == 0:
                flags.append({"type": "missing_expense", "line": "management_fees (possible self-management)"})

            # Annualized partial year
            if t12.annualized and t12.months_of_data < 10:
                flags.append({
                    "type": "partial_year_annualized",
                    "months": t12.months_of_data,
                })

        # ── Rent roll specific checks ─────────────────────────────────────
        if rent_roll:
            # Physical vacancy vs. underwriting assumption
            rr_vacancy = rent_roll.physical_vacancy
            uw_vacancy = ops.vacancy_rate
            if rr_vacancy > uw_vacancy + 0.05:
                flags.append({
                    "type": "vacancy_underestimated",
                    "rent_roll_vacancy": rr_vacancy,
                    "underwriting_vacancy": uw_vacancy,
                    "annual_impact": rent_roll.scheduled_income_annual * (rr_vacancy - uw_vacancy),
                })

            # Loss-to-lease
            if rent_roll.loss_to_lease > 0:
                ltl_pct = rent_roll.loss_to_lease / rent_roll.scheduled_income_annual if rent_roll.scheduled_income_annual else 0
                if ltl_pct > 0.03:
                    flags.append({
                        "type": "loss_to_lease",
                        "annual_amount": rent_roll.loss_to_lease,
                        "pct_of_gsi": ltl_pct,
                    })

            # Income mismatch between rent roll and T-12
            if t12 and rent_roll.actual_income_annual > 0:
                income_variance = abs(t12.gross_scheduled_income - rent_roll.scheduled_income_annual)
                if income_variance / rent_roll.scheduled_income_annual > 0.05:
                    flags.append({
                        "type": "income_mismatch",
                        "rent_roll_gsi": rent_roll.scheduled_income_annual,
                        "t12_gsi": t12.gross_scheduled_income,
                        "variance": income_variance,
                    })

        return flags

    # ── Pass 2: AI analysis ───────────────────────────────────────────────

    async def _ai_pass(
        self,
        deal: DealInput,
        t12: T12Summary | None,
        rent_roll: RentRollSummary | None,
        math_flags: list[dict],
        additional_docs: str,
    ) -> DDReport:

        context = self._build_context(deal, t12, rent_roll, math_flags, additional_docs)

        response = await self._call_api(context)

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("DueDiligence: failed to parse LLM JSON response")
            return DDReport(
                overall_risk="MEDIUM",
                proceed_recommendation="PAUSE",
                headline_summary="AI analysis could not be parsed. Review deal data manually.",
                red_flags=[],
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                full_analysis="The AI response could not be parsed into structured data.",
            )

        flags = [
            RedFlag(
                severity=f["severity"],
                category=f["category"],
                title=f["title"],
                detail=f["detail"],
                suggested_action=f["suggested_action"],
                financial_impact=f.get("financial_impact", ""),
            )
            for f in data.get("red_flags", [])
        ]

        return DDReport(
            overall_risk=data["overall_risk"],
            proceed_recommendation=data["proceed_recommendation"],
            headline_summary=data["headline_summary"],
            red_flags=flags,
            critical_count=sum(1 for f in flags if f.severity == "CRITICAL"),
            high_count=sum(1 for f in flags if f.severity == "HIGH"),
            medium_count=sum(1 for f in flags if f.severity == "MEDIUM"),
            low_count=sum(1 for f in flags if f.severity == "LOW"),
            seller_noi=data.get("seller_noi"),
            adjusted_noi=data.get("adjusted_noi"),
            noi_haircut_pct=data.get("noi_haircut_pct"),
            diligence_questions=data.get("diligence_questions", []),
            document_requests=data.get("document_requests", []),
            full_analysis=data.get("full_analysis", ""),
        )

    def _build_context(
        self,
        deal: DealInput,
        t12: T12Summary | None,
        rent_roll: RentRollSummary | None,
        math_flags: list[dict],
        additional_docs: str,
    ) -> str:
        ops = deal.operations
        lines = [
            "DEAL OVERVIEW:",
            f"  Property: {deal.name}",
            f"  Market: {deal.market}",
            f"  Asset Class: {deal.asset_class}",
            f"  Purchase Price: ${deal.purchase_price:,.0f}",
            f"  Units: {deal.units or 'N/A'}",
            f"  Square Feet: {deal.square_feet or 'N/A'}",
            "",
            "UNDERWRITING ASSUMPTIONS (from deal input):",
            f"  Gross Scheduled Income: ${ops.gross_scheduled_income:,.0f}/yr",
            f"  Vacancy Rate: {ops.vacancy_rate:.1%}",
            f"  Other Income: ${ops.other_income:,.0f}/yr",
            f"  Property Taxes: ${ops.property_taxes:,.0f}/yr",
            f"  Insurance: ${ops.insurance:,.0f}/yr",
            f"  Management Fee: {ops.management_fee_pct:.1%}",
            f"  Maintenance/Reserves: ${ops.maintenance_reserves:,.0f}/yr",
            f"  CapEx Reserves: ${ops.capex_reserves:,.0f}/yr",
            f"  Utilities: ${ops.utilities:,.0f}/yr",
            f"  Other Expenses: ${ops.other_expenses:,.0f}/yr",
            f"  LTV: {deal.loan.ltv:.0%} @ {deal.loan.interest_rate:.2%}",
            f"  Hold Period: {deal.exit.hold_period_years} years",
            f"  Exit Cap Rate: {deal.exit.exit_cap_rate:.2%}",
        ]

        if math_flags:
            lines.append("\nRULE-BASED FLAGS (pre-computed):")
            for f in math_flags:
                lines.append(f"  {json.dumps(f)}")

        if t12:
            lines.append("\nTRAILING-12 INCOME STATEMENT:")
            lines.append(f"  Months of data: {t12.months_of_data} ({'annualized' if t12.annualized else 'actual'})")
            lines.append(f"  Gross Scheduled Income: ${t12.gross_scheduled_income:,.0f}")
            lines.append(f"  Vacancy Loss: ${t12.vacancy_loss:,.0f}")
            lines.append(f"  Other Income: ${t12.other_income:,.0f}")
            lines.append(f"  EGI: ${t12.effective_gross_income:,.0f}")
            lines.append(f"  Property Taxes: ${t12.property_taxes:,.0f}")
            lines.append(f"  Insurance: ${t12.insurance:,.0f}")
            lines.append(f"  Management Fees: ${t12.management_fees:,.0f}")
            lines.append(f"  Repairs/Maintenance: ${t12.repairs_maintenance:,.0f}")
            lines.append(f"  Utilities: ${t12.utilities:,.0f}")
            lines.append(f"  Payroll: ${t12.payroll:,.0f}")
            lines.append(f"  Other Expenses: ${t12.other_expenses:,.0f}")
            lines.append(f"  Total Expenses: ${t12.total_expenses:,.0f}")
            lines.append(f"  NOI (T-12): ${t12.net_operating_income:,.0f}")
            if t12.red_flags:
                lines.append(f"  Pre-flagged: {t12.red_flags}")

        if rent_roll:
            lines.append("\nRENT ROLL SUMMARY:")
            lines.append(f"  Total Units: {rent_roll.total_units}")
            lines.append(f"  Occupied Units: {rent_roll.occupied_units}")
            lines.append(f"  Physical Vacancy: {rent_roll.physical_vacancy:.1%}")
            lines.append(f"  Scheduled Income (annual): ${rent_roll.scheduled_income_annual:,.0f}")
            lines.append(f"  Actual Income (annual): ${rent_roll.actual_income_annual:,.0f}")
            lines.append(f"  Loss-to-Lease (annual): ${rent_roll.loss_to_lease:,.0f}")
            if rent_roll.unit_mix:
                lines.append("  Unit Mix:")
                for u in rent_roll.unit_mix:
                    lines.append(f"    {u.get('type')}: {u.get('count')} units @ ${u.get('avg_market_rent', 0):,.0f}/mo avg")

        if additional_docs:
            lines.append(f"\nADDITIONAL DOCUMENTS / NOTES:\n{additional_docs}")

        return "\n".join(lines)

    DD_SYSTEM_PROMPT = (
        "You are a veteran real estate due diligence analyst with 20 years of experience "
        "catching seller manipulation, hidden liabilities, and underwriting errors before closing.\n\n"
        "You are direct and specific. When you identify a red flag, you explain exactly what number "
        "doesn't add up and what it likely means. You distinguish between deal-killers and items "
        "that can be negotiated or priced into the deal.\n\n"
        "Your job is to protect the investor's capital."
    )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((APITimeoutError, RateLimitError, InternalServerError)),
        reraise=True,
    )
    async def _call_api(self, context: str):
        return await self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=self.DD_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""Analyze this real estate deal for red flags and risks. Return structured JSON.

{context}

Return ONLY valid JSON matching this schema:
{{
  "overall_risk": "HIGH|MEDIUM|LOW",
  "proceed_recommendation": "PROCEED|PROCEED_WITH_CONDITIONS|PAUSE|PASS",
  "headline_summary": "2-3 sentence executive summary of findings",
  "seller_noi": null,
  "adjusted_noi": null,
  "noi_haircut_pct": null,
  "red_flags": [
    {{
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "Income|Expenses|Rent Roll|Market|Financing|Physical",
      "title": "Short flag title",
      "detail": "Specific explanation with numbers",
      "suggested_action": "What to do about this",
      "financial_impact": "Estimated annual NOI or value impact"
    }}
  ],
  "diligence_questions": ["Question to ask seller 1", "..."],
  "document_requests": ["Document to request 1", "..."],
  "full_analysis": "3-5 paragraph detailed analysis"
}}"""
            }],
        )
