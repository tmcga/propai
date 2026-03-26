"""
AI Investment Memo Generator

Uses the Anthropic Claude API to generate institutional-quality investment
memos from structured deal and market data.

The agent:
  1. Receives a UnderwritingResult + MarketReport
  2. Serializes the financial data into structured context
  3. Calls Claude with carefully crafted prompts per section
  4. Assembles sections into a complete InvestmentMemo object
  5. Renders to HTML via Jinja2 → PDF via WeasyPrint

Architecture note: We use the Anthropic SDK directly (not LangChain) for
clarity and to demonstrate direct API fluency — relevant for the GitHub audience.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# Path to Jinja2 templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class InvestmentMemo:
    """
    Complete AI-generated investment memo.

    Each section is a string of Markdown-formatted prose.
    The render() method converts to HTML/PDF.
    """

    # Deal identity
    deal_name: str
    prepared_date: str
    prepared_by: str = "PropAI"

    # AI-generated narrative sections
    executive_summary: str = ""
    investment_highlights: str = ""        # Bullet-point key metrics narrative
    property_overview: str = ""
    market_analysis: str = ""
    investment_thesis: str = ""
    financial_summary: str = ""            # Narrative around the numbers
    risk_factors: str = ""
    exit_strategy: str = ""

    # Structured data (passed through, not AI-generated)
    key_metrics: dict = field(default_factory=dict)
    pro_forma_table: list[dict] = field(default_factory=list)
    sensitivity_data: Optional[dict] = None

    # Metadata
    model_used: str = ""
    generation_time_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt library
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior real estate investment analyst at a top-tier private equity firm.
You write clear, precise, institutional-quality investment memos.

Your writing style:
- Direct and analytical — no fluff, no filler phrases
- Data-driven: always reference specific numbers from the deal data
- Balanced: acknowledge risks while building the investment case
- Professional but readable: avoid jargon unless it adds precision
- Concise: each section should be substantive but tight

You are generating one section of an investment memo at a time.
Respond with ONLY the section content — no preamble, no "Here is the section:" header.
Use markdown formatting where appropriate (bold for emphasis, bullet lists for risks/highlights).
"""

SECTION_PROMPTS = {

    "executive_summary": """Write a 3-4 paragraph executive summary for this real estate investment opportunity.

Cover:
1. The asset (type, location, size, key physical characteristics)
2. The investment thesis in 1-2 sentences — why this deal, why now
3. Key financial metrics (purchase price, equity required, going-in cap rate, projected IRR and equity multiple)
4. One sentence on the exit strategy

Deal Data:
{deal_context}

Market Context:
{market_context}

Write the executive summary now:""",

    "investment_highlights": """Write a structured Investment Highlights section listing the 5-7 most compelling reasons to invest.

Format as bold headers with 1-2 sentence explanations. Focus on:
- Financial returns vs. market benchmarks
- Market dynamics and demand drivers
- Asset quality and value-add potential
- Downside protection / defensive characteristics
- Timing / macro tailwinds

Deal Data:
{deal_context}

Market Context:
{market_context}

Write the investment highlights now:""",

    "market_analysis": """Write a Market Analysis section (3-4 paragraphs) covering:

1. Macro backdrop: interest rate environment and its impact on RE valuations
2. Local market fundamentals: population/job growth, supply/demand, rent trends
3. Submarket positioning: why this specific location within the metro
4. Competitive supply: new construction pipeline and its impact on the subject

Use the specific data points provided. If data is limited for a topic, note it briefly
and use reasonable market knowledge to fill in.

Deal Data:
{deal_context}

Market Data:
{market_context}

Write the market analysis now:""",

    "investment_thesis": """Write the Investment Thesis section (2-3 paragraphs).

This is the core argument for why this investment creates value. Cover:
1. The primary value creation strategy (income growth, stabilization, repositioning, etc.)
2. Why this asset is mispriced or presents an opportunity at this price
3. How the target returns are achievable given the market and asset fundamentals

Be specific and direct. This section should answer: "Why this deal, at this price, right now?"

Deal Data:
{deal_context}

Market Context:
{market_context}

Write the investment thesis now:""",

    "financial_summary": """Write a Financial Summary narrative (2-3 paragraphs) that interprets the numbers.

Don't just repeat the figures — explain what they mean:
- How the cap rate compares to market (is this priced fairly, aggressively, or attractively?)
- Whether the DSCR provides adequate debt coverage cushion
- What drives the projected IRR (income growth, leverage, or appreciation?)
- How sensitive returns are to key assumptions (reference the sensitivity analysis)
- Whether the equity multiple is compelling given the risk profile

Key financial metrics:
{metrics_context}

Market context for benchmarking:
{market_context}

Write the financial summary narrative now:""",

    "risk_factors": """Write a Risk Factors section listing the 4-6 most significant risks with mitigants.

Format each risk as:
**[Risk Name]**
*Risk:* [1-2 sentences describing the risk]
*Mitigant:* [1-2 sentences on how the risk is managed or underwritten]

Focus on risks that are material to THIS specific deal — avoid generic boilerplate.
Consider: interest rate risk, vacancy/credit risk, supply pipeline, execution risk,
market liquidity, concentration risk, and any deal-specific concerns flagged below.

Deal warnings/flags:
{warnings_context}

Deal Data:
{deal_context}

Market Context:
{market_context}

Write the risk factors now:""",

    "exit_strategy": """Write an Exit Strategy section (1-2 paragraphs) covering:

1. Primary exit path (sale to institutional buyer, 1031 exchange buyer, individual investor, etc.)
   — explain who the likely buyer is and why there will be demand
2. Expected hold period and what drives the exit timing
3. Exit pricing rationale: the assumed exit cap rate vs. going-in cap rate, and why
4. Secondary / fallback options if the primary exit is unavailable

Exit assumptions from the model:
{exit_context}

Market context:
{market_context}

Write the exit strategy now:""",
}


# ---------------------------------------------------------------------------
# Memo Agent
# ---------------------------------------------------------------------------

class MemoAgent:
    """
    Generates institutional investment memos using Claude.

    Uses a section-by-section generation approach for:
    - Better quality per section (focused context)
    - Streaming capability (show sections as they generate)
    - Graceful fallback (partial memo if one section fails)

    Usage:
        agent = MemoAgent()
        memo = await agent.generate(
            underwriting_result=result,
            market_report=report,
            deal_input=deal,
        )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-opus-4-6",
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client: Optional[anthropic.AsyncAnthropic] = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            if not self.api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is not set. "
                    "Get a free key at console.anthropic.com and add it to your .env file."
                )
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        underwriting_result,   # UnderwritingResult
        deal_input,            # DealInput
        market_report=None,    # Optional[MarketReport]
        sections: Optional[list[str]] = None,
    ) -> InvestmentMemo:
        """
        Generate a complete investment memo.

        Args:
            underwriting_result: Output from ProFormaEngine.underwrite()
            deal_input:          The original DealInput
            market_report:       Optional MarketReport from MarketService
            sections:            Specific sections to generate (default: all)

        Returns:
            InvestmentMemo with all sections populated
        """
        import time
        start = time.perf_counter()

        memo = InvestmentMemo(
            deal_name=deal_input.name,
            prepared_date=self._today(),
            model_used=self.model,
        )

        # Build context packages
        deal_ctx = self._build_deal_context(underwriting_result, deal_input)
        market_ctx = self._build_market_context(market_report)
        metrics_ctx = self._build_metrics_context(underwriting_result)
        exit_ctx = self._build_exit_context(underwriting_result, deal_input)
        warnings_ctx = self._build_warnings_context(underwriting_result)

        # Structured data (passed through unchanged)
        memo.key_metrics = metrics_ctx
        memo.pro_forma_table = self._build_pro_forma_table(underwriting_result)
        if underwriting_result.irr_sensitivity:
            memo.sensitivity_data = {
                "irr": underwriting_result.irr_sensitivity.__dict__,
                "coc": underwriting_result.coc_sensitivity.__dict__ if underwriting_result.coc_sensitivity else None,
            }

        # Sections to generate
        all_sections = [
            "executive_summary",
            "investment_highlights",
            "market_analysis",
            "investment_thesis",
            "financial_summary",
            "risk_factors",
            "exit_strategy",
        ]
        target_sections = sections or all_sections

        # Generate each section
        for section in target_sections:
            try:
                content = await self._generate_section(
                    section=section,
                    deal_ctx=deal_ctx,
                    market_ctx=market_ctx,
                    metrics_ctx=metrics_ctx,
                    exit_ctx=exit_ctx,
                    warnings_ctx=warnings_ctx,
                )
                setattr(memo, section, content)
                logger.info(f"Generated section: {section} ({len(content)} chars)")
            except Exception as e:
                msg = f"Section '{section}' generation failed: {str(e)}"
                logger.warning(msg)
                memo.warnings.append(msg)
                setattr(memo, section, f"*Section generation failed: {str(e)}*")

        memo.generation_time_seconds = round(time.perf_counter() - start, 2)
        return memo

    async def _generate_section(
        self,
        section: str,
        deal_ctx: str,
        market_ctx: str,
        metrics_ctx: dict,
        exit_ctx: str,
        warnings_ctx: str,
    ) -> str:
        """Generate a single memo section via Claude."""
        prompt_template = SECTION_PROMPTS.get(section)
        if not prompt_template:
            return ""

        prompt = prompt_template.format(
            deal_context=deal_ctx,
            market_context=market_ctx,
            metrics_context=json.dumps(metrics_ctx, indent=2),
            exit_context=exit_ctx,
            warnings_context=warnings_ctx,
        )

        client = self._get_client()
        message = await self._call_api(client, prompt)
        return message.content[0].text.strip()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.InternalServerError)),
        reraise=True,
    )
    async def _call_api(self, client: anthropic.AsyncAnthropic, prompt: str):
        return await client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

    # ------------------------------------------------------------------
    # Context builders — serialize structured data into LLM-friendly text
    # ------------------------------------------------------------------

    def _build_deal_context(self, result, deal) -> str:
        """Build a comprehensive deal context string for the LLM."""
        m = result.metrics
        lines = [
            f"DEAL: {deal.name}",
            f"Asset Class: {deal.asset_class.value.replace('_', ' ').title()}",
            f"Market: {deal.market or 'Not specified'}",
        ]
        if deal.units:
            lines.append(f"Units: {deal.units}")
        if deal.square_feet:
            lines.append(f"Square Footage: {deal.square_feet:,.0f} SF")
        if deal.year_built:
            lines.append(f"Year Built: {deal.year_built}")

        lines += [
            "",
            "ACQUISITION",
            f"Purchase Price: ${deal.purchase_price:,.0f}",
            f"Price Per Unit: ${m.price_per_unit:,.0f}" if m.price_per_unit else "",
            f"Price Per SF: ${m.price_per_sf:,.2f}/SF" if m.price_per_sf else "",
            f"Loan Amount: ${result.loan_amount:,.0f} ({deal.loan.ltv:.0%} LTV)",
            f"Equity Required: ${result.equity_invested:,.0f}",
            f"Interest Rate: {deal.loan.interest_rate:.2%} fixed, {deal.loan.amortization_years}-year amortization",
            "",
            "YEAR 1 OPERATING METRICS",
            f"Gross Scheduled Income: ${deal.operations.gross_scheduled_income:,.0f}/yr",
            f"Vacancy + Credit Loss: {deal.operations.vacancy_rate:.0%} + {deal.operations.credit_loss_rate:.0%}",
            f"Going-In Cap Rate: {m.going_in_cap_rate:.2%}",
            f"Year 1 Cash-on-Cash: {m.cash_on_cash_yr1:.2%}",
            f"DSCR (Year 1): {m.dscr_yr1:.2f}x",
            f"GRM: {m.gross_rent_multiplier:.1f}x",
            "",
            "PROJECTED RETURNS",
            f"Hold Period: {deal.exit.hold_period_years} years",
            f"Levered IRR: {m.levered_irr:.1%}",
            f"Equity Multiple: {m.equity_multiple:.2f}x",
            f"NPV (at {deal.exit.discount_rate:.0%} discount rate): ${m.npv:,.0f}",
            f"Average Cash-on-Cash: {m.average_cash_on_cash:.2%}/yr",
            "",
            "EXIT ASSUMPTIONS",
            f"Exit Cap Rate: {deal.exit.exit_cap_rate:.2%}",
            f"Projected Exit Price: ${m.exit_price:,.0f}",
            f"Net Sale Proceeds to Equity: ${m.net_sale_proceeds:,.0f}",
            "",
            "GROWTH ASSUMPTIONS",
            f"Annual Rent Growth: {deal.operations.rent_growth_rate:.1%}",
            f"Annual Expense Growth: {deal.operations.expense_growth_rate:.1%}",
        ]
        return "\n".join(l for l in lines if l is not None)

    def _build_market_context(self, market_report) -> str:
        """Serialize market report into LLM context."""
        if not market_report:
            return "Market data not available. Use general market knowledge."

        lines = [f"MARKET: {market_report.market}"]

        if market_report.investment_thesis:
            lines += ["", "Market Thesis:", market_report.investment_thesis]

        if market_report.demographics:
            d = market_report.demographics
            lines += ["", "DEMOGRAPHICS (Census ACS)"]
            if d.total_population:
                lines.append(f"Population: {d.total_population:,}")
            if d.median_household_income:
                lines.append(f"Median Household Income: ${d.median_household_income:,}")
            if d.vacancy_rate is not None:
                lines.append(f"Housing Vacancy Rate: {d.vacancy_rate:.1%}")
            if d.homeownership_rate:
                lines.append(f"Homeownership Rate: {d.homeownership_rate:.1%}")
            if d.renter_rate:
                lines.append(f"Renter Rate: {d.renter_rate:.1%}")
            if d.median_gross_rent:
                lines.append(f"Median Gross Rent (Census): ${d.median_gross_rent:,}/mo")
            if d.median_home_value:
                lines.append(f"Median Home Value: ${d.median_home_value:,}")
            if d.price_to_rent_ratio:
                lines.append(f"Price-to-Rent Ratio: {d.price_to_rent_ratio:.1f}x")
            if d.bachelors_plus_rate:
                lines.append(f"College-Educated (25+): {d.bachelors_plus_rate:.0%}")

        if market_report.zillow:
            z = market_report.zillow
            lines += ["", "ZILLOW MARKET DATA"]
            if z.current_zhvi:
                lines.append(f"Median Home Value (ZHVI): ${z.current_zhvi:,.0f}")
            if z.zhvi_yoy_pct is not None:
                lines.append(f"Home Value Growth YoY: {z.zhvi_yoy_pct:.1f}%")
            if z.zhvi_5yr_cagr:
                lines.append(f"Home Value 5-Yr CAGR: {z.zhvi_5yr_cagr:.1f}%")
            if z.current_zori:
                lines.append(f"Median Market Rent (ZORI): ${z.current_zori:,.0f}/mo")
            if z.zori_yoy_pct is not None:
                lines.append(f"Rent Growth YoY: {z.zori_yoy_pct:.1f}%")
            if z.zori_3yr_cagr:
                lines.append(f"Rent 3-Yr CAGR: {z.zori_3yr_cagr:.1f}%")
            if z.rent_growth_trend:
                lines.append(f"Rent Growth Trend: {z.rent_growth_trend.title()}")

        if market_report.fair_market_rents:
            fmr = market_report.fair_market_rents
            lines += ["", "HUD FAIR MARKET RENTS (40th percentile, utility-inclusive)"]
            if fmr.fmr_1br:
                lines.append(f"1BR FMR: ${fmr.fmr_1br:,}/mo")
            if fmr.fmr_2br:
                lines.append(f"2BR FMR: ${fmr.fmr_2br:,}/mo")
            if fmr.fmr_3br:
                lines.append(f"3BR FMR: ${fmr.fmr_3br:,}/mo")

        if market_report.macro:
            macro = market_report.macro
            lines += ["", "MACRO ENVIRONMENT (FRED)"]
            if macro.mortgage_rates and macro.mortgage_rates.rate_30yr:
                lines.append(f"30-Yr Fixed Mortgage Rate: {macro.mortgage_rates.rate_30yr:.2f}%")
            if macro.fed_funds_rate:
                lines.append(f"Fed Funds Rate: {macro.fed_funds_rate:.2f}%")
            if macro.treasury_10yr:
                lines.append(f"10-Yr Treasury: {macro.treasury_10yr:.2f}%")
            if macro.cpi_yoy:
                lines.append(f"CPI (YoY): {macro.cpi_yoy:.1f}%")
            if macro.unemployment_rate:
                lines.append(f"Unemployment Rate: {macro.unemployment_rate:.1f}%")
            if macro.rate_environment:
                lines.append(f"Rate Environment: {macro.rate_environment.title()}")
            if macro.cap_rate_pressure:
                lines.append(f"Cap Rate Pressure: {macro.cap_rate_pressure.title()}")

        if market_report.key_tailwinds:
            lines += ["", "KEY TAILWINDS:"]
            for t in market_report.key_tailwinds:
                lines.append(f"• {t}")

        if market_report.key_headwinds:
            lines += ["", "KEY HEADWINDS:"]
            for h in market_report.key_headwinds:
                lines.append(f"• {h}")

        return "\n".join(lines)

    def _build_metrics_context(self, result) -> dict:
        """Build a clean metrics dict for the financial summary section."""
        m = result.metrics
        return {
            "purchase_price": f"${result.purchase_price:,.0f}",
            "equity_invested": f"${result.equity_invested:,.0f}",
            "loan_amount": f"${result.loan_amount:,.0f}",
            "going_in_cap_rate": f"{m.going_in_cap_rate:.2%}",
            "cash_on_cash_yr1": f"{m.cash_on_cash_yr1:.2%}",
            "dscr_yr1": f"{m.dscr_yr1:.2f}x",
            "grm": f"{m.gross_rent_multiplier:.1f}x",
            "levered_irr": f"{m.levered_irr:.1%}",
            "unlevered_irr": f"{m.irr:.1%}",
            "equity_multiple": f"{m.equity_multiple:.2f}x",
            "npv": f"${m.npv:,.0f}",
            "avg_cash_on_cash": f"{m.average_cash_on_cash:.2%}",
            "exit_price": f"${m.exit_price:,.0f}",
            "net_sale_proceeds": f"${m.net_sale_proceeds:,.0f}",
            "total_profit": f"${m.total_profit:,.0f}",
            "break_even_occupancy": f"{m.break_even_occupancy:.1%}",
            "operating_expense_ratio": f"{m.operating_expense_ratio:.1%}",
        }

    def _build_exit_context(self, result, deal) -> str:
        m = result.metrics
        return "\n".join([
            f"Hold Period: {deal.exit.hold_period_years} years",
            f"Going-In Cap Rate: {m.going_in_cap_rate:.2%}",
            f"Exit Cap Rate Assumption: {deal.exit.exit_cap_rate:.2%}",
            f"Cap Rate Delta: {deal.exit.exit_cap_rate - m.going_in_cap_rate:+.2%} "
            f"({'compression' if deal.exit.exit_cap_rate < m.going_in_cap_rate else 'expansion'})",
            f"Exit NOI: ${m.exit_noi:,.0f}",
            f"Gross Exit Price: ${m.exit_price:,.0f}",
            f"Selling Costs: {deal.exit.selling_costs_pct:.1%}",
            f"Net Sale Proceeds to Equity: ${m.net_sale_proceeds:,.0f}",
            f"Total Equity Distributions: ${m.total_equity_distributions:,.0f}",
        ])

    def _build_warnings_context(self, result) -> str:
        if not result.warnings:
            return "No significant underwriting flags identified."
        return "\n".join(f"• {w}" for w in result.warnings)

    def _build_pro_forma_table(self, result) -> list[dict]:
        """Build a clean pro forma table for HTML rendering."""
        rows = []
        for yr in result.pro_forma:
            rows.append({
                "year": yr.year,
                "gsi": yr.gross_scheduled_income,
                "vacancy_loss": yr.vacancy_loss,
                "egi": yr.effective_gross_income,
                "total_opex": yr.total_operating_expenses,
                "noi": yr.net_operating_income,
                "debt_service": yr.debt_service,
                "btcf": yr.before_tax_cash_flow,
                "loan_balance": yr.loan_balance,
            })
        return rows

    @staticmethod
    def _today() -> str:
        from datetime import date
        return date.today().strftime("%B %d, %Y")
