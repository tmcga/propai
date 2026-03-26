"""
LP Communications Suite
-----------------------
Generates professional investor communications for real estate syndicators.

Communication types:
  - Monthly investor update
  - Quarterly report
  - Distribution announcement
  - Capital call notice
  - New deal announcement / deal one-pager
  - Annual report summary

Each output is a structured object with subject line, body (markdown),
and optional HTML for email clients. All numbers come from the caller —
Claude only writes prose.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from anthropic import AsyncAnthropic, APITimeoutError, RateLimitError, InternalServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


# ── Input types ───────────────────────────────────────────────────────────

@dataclass
class AssetSnapshot:
    """Current performance of a single asset for reporting."""
    property_name: str
    market: str
    asset_class: str
    units_or_sf: str                    # "24 units" or "40,000 SF"
    acquisition_date: str               # "March 2023"
    acquisition_price: float
    current_value_estimate: float | None = None

    # Period performance (current reporting period)
    period_noi: float = 0
    period_dscr: float = 0
    period_occupancy: float = 0
    period_coc_return: float = 0

    # YTD / cumulative
    ytd_distributions: float = 0
    total_distributions_to_date: float = 0
    cumulative_coc: float = 0
    equity_multiple_to_date: float = 0

    # vs. pro forma
    noi_vs_proforma_pct: float = 0       # e.g. 0.03 = 3% above pro forma
    occupancy_vs_proforma_pct: float = 0

    # Capex / notable events
    capex_spend_period: float = 0
    notable_updates: list[str] = field(default_factory=list)


@dataclass
class LPCommsInput:
    """Input for any LP communication."""
    comm_type: Literal[
        "monthly_update",
        "quarterly_report",
        "distribution_announcement",
        "capital_call",
        "new_deal_announcement",
        "annual_report",
    ]

    # Fund / GP info
    fund_name: str                       # "Acme Capital Fund I"
    gp_name: str                         # "Tom McGahan"
    gp_firm: str                         # "Acme Capital"

    # LP info (optional — personalizes the greeting)
    lp_name: str | None = None

    # Reporting period
    period: str = ""                     # "Q3 2025", "October 2025", "FY 2025"

    # Assets in this communication
    assets: list[AssetSnapshot] = field(default_factory=list)

    # Distribution info (for distribution_announcement, monthly_update)
    distribution_amount: float | None = None
    distribution_per_unit: float | None = None  # per LP unit/share
    distribution_date: str | None = None         # "November 15, 2025"
    distribution_type: str = "Preferred Return"  # or "Return of Capital", "Profit Distribution"

    # Capital call info (for capital_call)
    capital_call_amount: float | None = None
    capital_call_due_date: str | None = None
    capital_call_purpose: str | None = None

    # New deal info (for new_deal_announcement)
    new_deal_summary: dict[str, Any] = field(default_factory=dict)

    # Tone / style
    tone: Literal["formal", "professional", "warm"] = "professional"
    include_disclaimer: bool = True
    additional_context: str = ""        # GP's own notes or color


@dataclass
class LPCommOutput:
    comm_type: str
    subject_line: str
    body_markdown: str
    key_numbers: dict[str, str]         # formatted metrics for quick reference
    action_items: list[str]             # what the LP needs to do (if anything)
    disclaimer: str


# ── Agent ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert investor relations professional specializing in
real estate private equity. You write institutional-quality LP communications that are:
- Clear and direct — LPs are sophisticated; don't over-explain
- Numbers-first — lead with performance, then narrative
- Honest — acknowledge underperformance with context and path forward
- Professional but not cold — LPs are partners, not just check-writers

You never invent numbers. All figures come from the data provided.
Format output as clean markdown suitable for email or PDF."""

COMM_PROMPTS = {
    "monthly_update": """Write a monthly investor update email. Structure:
1. Opening (1-2 sentences — period, overall tone)
2. Portfolio Performance (table or bullets with key metrics)
3. Property Updates (brief narrative for each asset — occupancy, NOI, notable events)
4. Distribution Summary (if applicable)
5. Market Commentary (2-3 sentences on macro conditions relevant to the portfolio)
6. What's Next (upcoming milestones, expected decisions)
7. Closing""",

    "quarterly_report": """Write a formal quarterly investor report. Structure:
1. Executive Summary (quarter highlights, overall performance vs. proforma)
2. Financial Performance (detailed metrics per asset — NOI, occupancy, DSCR, distributions)
3. Asset-Level Updates (2-3 paragraphs per property)
4. Portfolio YTD Performance vs. Proforma
5. Capital Activity (any distributions, refinances, new investments)
6. Market Conditions (macro and local market context)
7. Outlook (next quarter priorities, any risks or opportunities)
8. Closing""",

    "distribution_announcement": """Write a distribution announcement email. Keep it concise.
Structure:
1. Subject line and opening announcement
2. Distribution details (amount, per-unit, date, type)
3. YTD cumulative distribution summary
4. Brief portfolio color (1 paragraph — what's driving performance)
5. Wire/payment instructions reminder
6. Closing""",

    "capital_call": """Write a capital call notice. This must be professional, clear, and include
all necessary details. Structure:
1. Clear subject line indicating capital call
2. Purpose of the capital call (specific and transparent)
3. Amount requested and calculation basis
4. Wire instructions and due date (use placeholders if not provided)
5. Timeline and use of proceeds
6. Impact on projected returns (if applicable)
7. Contact information for questions
8. Legal notice language""",

    "new_deal_announcement": """Write a new acquisition announcement / deal one-pager for LPs.
Structure:
1. Investment Headline (property name, market, asset class, price)
2. Investment Thesis (3-4 bullets — why this deal, why now)
3. Financial Summary (table: price, equity raise, projected returns)
4. Market Overview (2-3 sentences on the market dynamics)
5. Business Plan (what we plan to do with this asset)
6. Risk Factors (2-3 key risks and mitigants)
7. Next Steps (for LPs interested in co-investing or asking questions)""",

    "annual_report": """Write a comprehensive annual investor report. Structure:
1. Letter to Investors (from GP — personal, forward-looking)
2. Year in Review (portfolio highlights, key events)
3. Financial Performance Summary (full-year metrics for each asset)
4. Portfolio Return Summary (aggregate IRR, equity multiple, distributions)
5. Asset-Level Deep Dives (detailed section per property)
6. Market Overview (macro conditions and portfolio implications)
7. 2026 Priorities (asset management goals, potential exits, new opportunities)
8. Closing and thank you""",
}


class LPCommsAgent:

    def __init__(self) -> None:
        self.client = AsyncAnthropic()

    async def generate(self, inp: LPCommsInput) -> LPCommOutput:
        context = self._build_context(inp)
        comm_prompt = COMM_PROMPTS.get(inp.comm_type, COMM_PROMPTS["monthly_update"])

        response = await self._call_api(comm_prompt, context)

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("LPComms: failed to parse LLM JSON response")
            data = {
                "subject_line": f"{inp.fund_name} — {inp.period} Update",
                "body_markdown": "Communication generation failed. Please retry.",
                "key_numbers": {},
                "action_items": [],
            }

        disclaimer = ""
        if inp.include_disclaimer:
            disclaimer = (
                "This communication is intended solely for the addressee(s) and contains "
                "confidential information. Past performance is not indicative of future results. "
                "This is not an offer to sell or a solicitation of an offer to buy any securities. "
                f"© {inp.gp_firm}. All rights reserved."
            )

        return LPCommOutput(
            comm_type=inp.comm_type,
            subject_line=data.get("subject_line", ""),
            body_markdown=data.get("body_markdown", ""),
            key_numbers=data.get("key_numbers", {}),
            action_items=data.get("action_items", []),
            disclaimer=disclaimer,
        )

    def _build_context(self, inp: LPCommsInput) -> str:
        lines = [
            f"Fund: {inp.fund_name}",
            f"GP: {inp.gp_name}, {inp.gp_firm}",
            f"Period: {inp.period}",
            f"Tone: {inp.tone}",
        ]
        if inp.lp_name:
            lines.append(f"LP Addressee: {inp.lp_name}")

        if inp.assets:
            lines.append("\nPORTFOLIO ASSETS:")
            for a in inp.assets:
                lines.append(f"\n  {a.property_name} ({a.market} | {a.asset_class} | {a.units_or_sf})")
                lines.append(f"    Acquired: {a.acquisition_date} for ${a.acquisition_price:,.0f}")
                if a.current_value_estimate:
                    lines.append(f"    Current Est. Value: ${a.current_value_estimate:,.0f}")
                lines.append(f"    Period NOI: ${a.period_noi:,.0f}")
                lines.append(f"    Period Occupancy: {a.period_occupancy:.1%}")
                lines.append(f"    Period DSCR: {a.period_dscr:.2f}x")
                lines.append(f"    Period CoC: {a.period_coc_return:.1%}")
                lines.append(f"    NOI vs Pro Forma: {a.noi_vs_proforma_pct:+.1%}")
                lines.append(f"    YTD Distributions: ${a.ytd_distributions:,.0f}")
                lines.append(f"    Total Distributions to Date: ${a.total_distributions_to_date:,.0f}")
                lines.append(f"    Equity Multiple to Date: {a.equity_multiple_to_date:.2f}x")
                if a.capex_spend_period:
                    lines.append(f"    CapEx This Period: ${a.capex_spend_period:,.0f}")
                if a.notable_updates:
                    lines.append("    Notable Updates:")
                    for u in a.notable_updates:
                        lines.append(f"      - {u}")

        if inp.distribution_amount is not None:
            lines.append(f"\nDISTRIBUTION:")
            lines.append(f"  Amount: ${inp.distribution_amount:,.0f}")
            if inp.distribution_per_unit:
                lines.append(f"  Per Unit: ${inp.distribution_per_unit:,.4f}")
            if inp.distribution_date:
                lines.append(f"  Date: {inp.distribution_date}")
            lines.append(f"  Type: {inp.distribution_type}")

        if inp.capital_call_amount is not None:
            lines.append(f"\nCAPITAL CALL:")
            lines.append(f"  Amount: ${inp.capital_call_amount:,.0f}")
            if inp.capital_call_due_date:
                lines.append(f"  Due: {inp.capital_call_due_date}")
            if inp.capital_call_purpose:
                lines.append(f"  Purpose: {inp.capital_call_purpose}")

        if inp.new_deal_summary:
            lines.append("\nNEW DEAL:")
            for k, v in inp.new_deal_summary.items():
                lines.append(f"  {k}: {v}")

        if inp.additional_context:
            lines.append(f"\nGP NOTES / ADDITIONAL CONTEXT:\n{inp.additional_context}")

        return "\n".join(lines)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((APITimeoutError, RateLimitError, InternalServerError)),
        reraise=True,
    )
    async def _call_api(self, comm_prompt: str, context: str):
        return await self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""{comm_prompt}

COMMUNICATION CONTEXT:
{context}

Return a JSON object with these exact keys:
{{
  "subject_line": "Email subject line",
  "body_markdown": "Full communication body in markdown",
  "key_numbers": {{"metric name": "formatted value", ...}},
  "action_items": ["action 1", "action 2"]
}}

Return ONLY valid JSON."""
            }],
        )
