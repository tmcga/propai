"""
AI API endpoints.

POST /api/ai/memo           — Generate investment memo from deal + market data
POST /api/ai/parse          — Parse natural language deal description → DealInput
POST /api/ai/analyze        — Full pipeline: parse NL → underwrite → generate memo
GET  /api/ai/memo/demo      — Demo memo (no API key required, uses cached content)
"""

from __future__ import annotations

import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from engine.financial import ProFormaEngine, WaterfallEngine
from engine.financial.models import DealInput
from agents.memo_agent import MemoAgent, InvestmentMemo
from agents.deal_parser import DealParser
from data.market_service import MarketService

router = APIRouter(prefix="/api/ai", tags=["AI"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class MemoRequest(BaseModel):
    deal: DealInput
    include_market_data: bool = True
    sections: Optional[list[str]] = None  # Generate specific sections only
    format: str = "json"  # "json" | "html" | "pdf"


class ParseRequest(BaseModel):
    text: str
    underwrite: bool = True  # Also run underwriting on the parsed deal


class AnalyzeRequest(BaseModel):
    text: str
    include_memo: bool = True
    include_market_data: bool = True
    memo_format: str = "json"  # "json" | "html"


class AnalyzeResponse(BaseModel):
    parse_result: dict
    underwriting: Optional[dict] = None
    memo: Optional[dict] = None
    assumed_values: dict = {}
    clarifications_needed: list[str] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/memo", summary="Generate AI investment memo")
async def generate_memo(request: MemoRequest):
    """
    Generate an institutional-quality investment memo for a deal.

    The memo includes AI-written narrative sections (executive summary,
    market analysis, investment thesis, risk factors, exit strategy) combined
    with structured financial tables (pro forma, sensitivity analysis, waterfall).

    **Requires:** `ANTHROPIC_API_KEY` in environment.

    **format options:**
    - `json` — memo sections as JSON (default, best for React UI)
    - `html` — rendered HTML suitable for display or PDF conversion
    """
    try:
        # 1. Run underwriting
        engine = ProFormaEngine(request.deal)
        result = engine.underwrite(include_sensitivity=True)

        if request.deal.equity_structure:
            wf = WaterfallEngine(
                equity_structure=request.deal.equity_structure,
                total_equity=result.equity_invested,
                cash_flows=engine._equity_cfs,
            )
            result.waterfall = wf.compute()

        # 2. Optionally fetch market data
        market_report = None
        if request.include_market_data and request.deal.market:
            try:
                service = MarketService(
                    census_key=os.getenv("CENSUS_API_KEY"),
                    fred_key=os.getenv("FRED_API_KEY"),
                    hud_token=os.getenv("HUD_API_TOKEN"),
                )
                market_report = await service.get_market_report(
                    metro=request.deal.market
                )
            except Exception:
                # Market data is nice-to-have; don't fail the memo for it
                pass

        # 3. Generate memo
        agent = MemoAgent(api_key=os.getenv("ANTHROPIC_API_KEY"))
        memo = await agent.generate(
            underwriting_result=result,
            deal_input=request.deal,
            market_report=market_report,
            sections=request.sections,
        )

        # 4. Return in requested format
        if request.format == "html":
            html = _render_memo_html(memo, result, request.deal, market_report)
            return HTMLResponse(content=html)

        return _memo_to_dict(memo)

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/parse", response_model=dict, summary="Parse natural language deal description"
)
async def parse_deal(request: ParseRequest):
    """
    Convert a free-text deal description into a structured DealInput object.

    Claude extracts all stated values, infers market-standard defaults for
    anything not mentioned, and flags what it had to assume.

    **Example input:**
    ```
    "24-unit apartment in Austin TX asking $4.8M. Average rents $2,000/mo.
    70% LTV at 6.75%, 5-year hold, exit at 5.5 cap."
    ```

    **Requires:** `ANTHROPIC_API_KEY` in environment.
    """
    try:
        parser = DealParser(api_key=os.getenv("ANTHROPIC_API_KEY"))
        parse_result = await parser.parse(request.text)

        if not parse_result.success:
            raise HTTPException(status_code=422, detail=parse_result.error)

        response = {
            "success": True,
            "deal": parse_result.deal_input.model_dump()
            if parse_result.deal_input
            else None,
            "extracted_values": parse_result.extracted_values,
            "assumed_values": parse_result.assumed_values,
            "clarifications_needed": parse_result.clarifications_needed,
        }

        # Optionally run underwriting immediately
        if request.underwrite and parse_result.deal_input:
            try:
                engine = ProFormaEngine(parse_result.deal_input)
                result = engine.underwrite(include_sensitivity=False)
                response["underwriting"] = {
                    "going_in_cap_rate": result.metrics.going_in_cap_rate,
                    "cash_on_cash_yr1": result.metrics.cash_on_cash_yr1,
                    "dscr_yr1": result.metrics.dscr_yr1,
                    "levered_irr": result.metrics.levered_irr,
                    "equity_multiple": result.metrics.equity_multiple,
                    "equity_invested": result.equity_invested,
                    "warnings": result.warnings,
                }
            except Exception as e:
                response["underwriting_error"] = str(e)

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", summary="Full pipeline: NL input → underwrite → memo")
async def analyze_deal(request: AnalyzeRequest):
    """
    The full PropAI pipeline in one call:

    1. **Parse** natural language description → structured DealInput
    2. **Underwrite** the deal → pro forma, IRR, sensitivity tables
    3. **Generate** AI investment memo → all narrative sections

    This is the primary endpoint for the demo and the "wow" moment.

    **Requires:** `ANTHROPIC_API_KEY` in environment.

    **Example:**
    ```json
    {
      "text": "24-unit apartment in Austin TX at $4.8M. Rents $2k/mo. 70% LTV at 6.75%, 5yr hold."
    }
    ```
    """
    try:
        # Step 1: Parse
        parser = DealParser(api_key=os.getenv("ANTHROPIC_API_KEY"))
        parse_result = await parser.parse(request.text)

        if not parse_result.success or not parse_result.deal_input:
            raise HTTPException(
                status_code=422, detail=f"Could not parse deal: {parse_result.error}"
            )

        deal = parse_result.deal_input

        # Step 2: Underwrite
        engine = ProFormaEngine(deal)
        result = engine.underwrite(include_sensitivity=True)

        if deal.equity_structure:
            wf = WaterfallEngine(
                equity_structure=deal.equity_structure,
                total_equity=result.equity_invested,
                cash_flows=engine._equity_cfs,
            )
            result.waterfall = wf.compute()

        # Step 3: Market data (parallel with memo if not needed for memo)
        market_report = None
        if request.include_market_data and deal.market:
            try:
                service = MarketService(
                    census_key=os.getenv("CENSUS_API_KEY"),
                    fred_key=os.getenv("FRED_API_KEY"),
                    hud_token=os.getenv("HUD_API_TOKEN"),
                )
                market_report = await service.get_market_report(metro=deal.market)
            except Exception:
                pass

        # Step 4: Generate memo
        response_data: dict = {
            "deal": deal.model_dump(),
            "assumed_values": parse_result.assumed_values,
            "clarifications_needed": parse_result.clarifications_needed,
            "underwriting": {
                "purchase_price": result.purchase_price,
                "equity_invested": result.equity_invested,
                "loan_amount": result.loan_amount,
                "metrics": result.metrics.model_dump(),
                "warnings": result.warnings,
            },
        }

        if request.include_memo:
            agent = MemoAgent(api_key=os.getenv("ANTHROPIC_API_KEY"))
            memo = await agent.generate(
                underwriting_result=result,
                deal_input=deal,
                market_report=market_report,
            )

            if request.memo_format == "html":
                response_data["memo_html"] = _render_memo_html(
                    memo, result, deal, market_report
                )
            else:
                response_data["memo"] = _memo_to_dict(memo)

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/memo/demo", response_class=HTMLResponse, summary="Demo memo (no API key needed)"
)
async def demo_memo():
    """
    Returns a pre-rendered demo investment memo for the Austin, TX sample deal.

    Uses placeholder narrative text so no API key is required.
    Perfect for UI development and showcasing the design.
    """
    from api.underwriting import sample_deal

    deal = await sample_deal()
    engine = ProFormaEngine(deal)
    result = engine.underwrite(include_sensitivity=True)

    if deal.equity_structure:
        wf = WaterfallEngine(
            equity_structure=deal.equity_structure,
            total_equity=result.equity_invested,
            cash_flows=engine._equity_cfs,
        )
        result.waterfall = wf.compute()

    # Build demo memo with placeholder text
    demo_memo_obj = InvestmentMemo(
        deal_name=deal.name,
        prepared_date="March 25, 2026",
        prepared_by="PropAI Demo",
        model_used="demo",
        executive_summary="""**The Austin Arms** is a 24-unit garden-style apartment community located in Austin, Texas,
offered at $4,800,000 ($200,000/unit). The property presents a compelling value-add opportunity in one of the
nation's strongest multifamily markets, supported by a diversified employment base, above-average population growth,
and persistently constrained housing supply.

The investment offers a **5.03% going-in cap rate**, **7.2% levered IRR**, and **1.52x equity multiple** over a
5-year hold. Year 1 cash-on-cash of **5.8%** provides current income while a 3% annual rent growth assumption
drives NOI appreciation toward an exit at a 5.5% cap rate, generating approximately **$2.1M** in net sale proceeds.

Equity required is approximately **$1,626,000** (33.9% of purchase price including closing costs and immediate CapEx),
financed by a $3,360,000 senior loan at 6.75% fixed over 30 years. DSCR of **1.23x** in Year 1 provides adequate
debt coverage with limited margin of safety — conservative rent growth assumptions are warranted.""",
        investment_highlights="""**Prime Austin Submarket Location**
Austin consistently ranks among the top US markets for population and employment growth, driven by the technology
sector, University of Texas, and state government. The subject market benefits from this demand without the
premium pricing of core Austin submarkets.

**Attractive Going-In Basis at $200,000/Unit**
The purchase price represents a compelling entry point relative to replacement cost (estimated $280,000–320,000/unit
for new construction), providing meaningful downside protection and making rent growth assumptions conservative.

**Stable 24-Unit Scale with Institutional-Quality Operations**
At 24 units, the property is large enough for professional management economics while remaining below the threshold
that attracts institutional competition at acquisition, providing pricing inefficiency.

**Clear Value-Add Pathway**
Current rents of $2,000/unit are approximately 8% below comparable renovated units in the submarket, providing
an identifiable pathway to $2,150–$2,200/unit rents through targeted unit upgrades and amenity improvements funded
by the $120,000 immediate CapEx budget.

**Strong Market Fundamentals Support Hold Period Assumptions**
Austin's 3-year rent CAGR of approximately 4.2% (Zillow ZORI) supports the underwritten 3% rent growth assumption,
which represents a deliberate haircut to actual market trends as a margin of safety.""",
        market_analysis="""Austin, Texas has emerged as one of the premier US real estate investment markets over the
past decade, driven by structural tailwinds that remain firmly intact. The Austin-Round Rock MSA added approximately
65,000 residents in the most recent measurement period, ranking among the fastest-growing large metros in the country.
This population growth is underpinned by net migration from higher-cost coastal markets and a technology employment
base anchored by Apple, Tesla, Google, Oracle, and hundreds of smaller firms.

From a supply/demand perspective, the Austin multifamily market has experienced elevated deliveries in 2024–2025 as
projects underwritten during the 2021–2022 boom have come online. This has moderated near-term rent growth and
created selective buying opportunities for well-located assets at prices that reflect near-term uncertainty rather
than long-term fundamentals. The subject property's vintage and location insulate it from direct new supply competition,
as new deliveries are concentrated in urban core and Class A suburban submarkets.

The macro environment presents a mixed backdrop. The Federal Reserve's rate cycle has pushed 30-year mortgage rates
above 6.5%, which has dampened owner-occupied demand and redirected would-be buyers into the rental pool — a net
positive for multifamily fundamentals. HUD Fair Market Rents for the Austin MSA confirm that the subject's asking rents
of $2,000/unit are broadly consistent with a market that supports this pricing across the full rent spectrum.""",
        investment_thesis="""The Austin Arms represents an opportunity to acquire a stabilized, cash-flowing multifamily
asset at a basis that reflects current market uncertainty rather than long-term fundamentals. The going-in cap rate of
5.03% is attractive relative to the 10-year Treasury (approximately 4.2%), providing a meaningful spread that compensates
for real estate illiquidity and execution risk.

The primary value creation strategy is operational stabilization combined with selective unit renovation. Current
management has not maximized rental income relative to comparable properties in the submarket, creating an identifiable
opportunity to improve occupancy consistency, reduce credit loss, and selectively upgrade units to capture $150–$200/month
rental premiums. The $120,000 immediate CapEx budget is targeted at common area improvements and 6–8 unit renovations
that support this rent repositioning.

The exit underwriting assumes a 5.5% cap rate — 47 basis points above the going-in cap rate — representing a
deliberately conservative assumption. In a benign interest rate environment, exits at 5.0–5.25% are achievable;
the buffer provides meaningful IRR protection in a scenario where cap rates remain elevated or expand modestly.""",
        financial_summary="""The financial return profile is compelling given the conservative underwriting assumptions employed.
The 7.2% levered IRR and 1.52x equity multiple are driven roughly equally by operating cash flows (averaging 5.4%
cash-on-cash over the hold period) and exit proceeds, which represents a balanced and defensive return structure
relative to deals that are more dependent on terminal value.

The going-in cap rate of 5.03% is approximately 83 basis points above the 10-year Treasury at the time of underwriting —
a spread that is slightly below the historical average of 150–200 bps but reasonable given Austin's growth premium.
The DSCR of 1.23x in Year 1 is tight by traditional lender standards (typical minimum: 1.20–1.25x); this reflects
the current rate environment and underscores the importance of achieving even modest rent growth to improve coverage
in Year 2 and beyond.

The sensitivity analysis demonstrates that the investment generates positive returns across the range of tested scenarios,
with levered IRRs ranging from approximately 5% (worst case: exit cap 6.0%, rent growth 1%) to 11%+ (best case: exit
cap 5.0%, rent growth 5%). The base case sits comfortably in the middle of this range, suggesting the underwriting
is balanced rather than optimistic.""",
        risk_factors="""**Interest Rate and Refinancing Risk**
*Risk:* Persistently elevated interest rates could compress exit multiples and limit refinancing options at hold period end.
*Mitigant:* The 5-year fixed-rate loan eliminates near-term refinancing risk. Exit underwriting assumes a 5.5% cap rate
(conservative) and does not assume cap rate compression from current levels.

**Austin Supply Pipeline**
*Risk:* Austin has experienced elevated multifamily deliveries, which could moderate rent growth below underwritten assumptions.
*Mitigant:* The subject's 1998 vintage and price point (Class B) compete in a different segment from new Class A deliveries.
The 3% rent growth assumption already represents a haircut to Austin's 3-year CAGR of approximately 4%.

**Execution Risk on Value-Add Program**
*Risk:* Unit renovation costs or timelines could exceed budget, delaying rent premiums and compressing Year 1–2 cash flows.
*Mitigant:* The $120,000 CapEx budget is sized for a modest, targeted program (6–8 units). Renovation ROI of $150–200/month
premium on a $15,000 unit cost represents a 12–16% return on renovation capital.

**Concentration Risk**
*Risk:* Single asset, single market exposure concentrates investor risk.
*Mitigant:* Austin's economic diversification (technology, government, education, healthcare) provides stability relative
to single-industry markets. The deal is sized for a well-capitalized sponsor with portfolio diversification.""",
        exit_strategy="""The primary exit strategy is an outright sale to a private equity real estate fund, family office,
or high-net-worth individual investor seeking stabilized multifamily cash flow in a high-growth Sun Belt market. The
24-unit scale targets a buyer segment with substantial capital to deploy but below the minimum check size requirements
of institutional buyers ($10M+), creating a more liquid buyer pool with less competition from institutional sellers.

The 5-year hold period is designed to capture the full benefit of the rent growth program and allow Austin's near-term
supply overhang to be absorbed by the market. By Year 5, the projected NOI of approximately $300,000 at a 5.5% exit
cap rate implies a gross exit value of $5.45M — a 13.5% premium over the purchase price before accounting for
operating cash flows distributed over the hold.

A secondary exit option is a 1031 exchange to an investor seeking to defer capital gains, which broadens the buyer
pool and often supports pricing. Additionally, the property could be refinanced into permanent agency debt at Year 5
and held as a long-term income vehicle if market conditions favor continued ownership over disposition.""",
    )

    html = _render_memo_html(demo_memo_obj, result, deal, None)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memo_to_dict(memo: InvestmentMemo) -> dict:
    """Serialize InvestmentMemo to JSON-safe dict."""
    return {
        "deal_name": memo.deal_name,
        "prepared_date": memo.prepared_date,
        "prepared_by": memo.prepared_by,
        "model_used": memo.model_used,
        "generation_time_seconds": memo.generation_time_seconds,
        "sections": {
            "executive_summary": memo.executive_summary,
            "investment_highlights": memo.investment_highlights,
            "market_analysis": memo.market_analysis,
            "investment_thesis": memo.investment_thesis,
            "financial_summary": memo.financial_summary,
            "risk_factors": memo.risk_factors,
            "exit_strategy": memo.exit_strategy,
        },
        "key_metrics": memo.key_metrics,
        "pro_forma_table": memo.pro_forma_table,
        "warnings": memo.warnings,
    }


def _render_memo_html(memo, result, deal, market) -> str:
    """Render the Jinja2 memo template to HTML string."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        import markdown

        templates_dir = str(
            TEMPLATES_DIR
            if "TEMPLATES_DIR" in dir()
            else __file__.replace("api/ai.py", "templates")
        )

        # Find templates dir relative to this file
        import os as _os

        templates_dir = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "templates"
        )

        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html"]),
        )

        # Add markdown filter
        def markdown_to_html(text: str) -> str:
            if not text:
                return ""
            html = markdown.markdown(text, extensions=["extra"])
            return html

        env.filters["markdown_to_html"] = markdown_to_html

        # Add enumerate as a global
        env.globals["enumerate"] = enumerate
        env.globals["abs"] = abs

        template = env.get_template("memo.html")
        return template.render(memo=memo, result=result, deal=deal, market=market)

    except ImportError as e:
        # Jinja2 or markdown not installed — return minimal HTML
        return f"""<html><body>
        <h1>{memo.deal_name}</h1>
        <h2>Executive Summary</h2><p>{memo.executive_summary}</p>
        <p><em>Install jinja2 and markdown packages for full rendering.</em></p>
        <p><em>Error: {e}</em></p>
        </body></html>"""
    except Exception as e:
        return f"<html><body><p>Render error: {e}</p></body></html>"


from pathlib import Path  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
