"""
Analysis API — Deal Screener, Document Parser, Due Diligence, LP Comms
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from agents.deal_screener import DealScreener, ScreenInput
from agents.document_parser import DocumentParser
from agents.due_diligence import DueDiligenceAgent
from agents.lp_comms import LPCommsAgent, LPCommsInput, AssetSnapshot
from engine.financial.models import DealInput
from engine.financial.proforma import ProFormaEngine

router = APIRouter(prefix="/api", tags=["analysis"])


def _dc_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dc_to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_dc_to_dict(i) for i in obj]
    if isinstance(obj, tuple):
        return [_dc_to_dict(i) for i in obj]
    return obj


# ── Deal Screener ─────────────────────────────────────────────────────────

class ScreenRequest(BaseModel):
    asset_class: str = "multifamily"
    purchase_price: float
    market: str
    gross_scheduled_income: float = 0
    units: int | None = None
    avg_unit_rent: float | None = None
    square_feet: float | None = None
    asking_rent_per_sf: float | None = None
    vacancy_rate: float = 0.05
    expense_ratio: float | None = None
    noi_override: float | None = None
    ltv: float = 0.70
    interest_rate: float = 0.0675
    amortization_years: int = 30
    hold_period_years: int = 5
    exit_cap_rate: float | None = None
    additional_notes: str = ""


@router.post("/screen")
async def screen_deal(req: ScreenRequest):
    """
    Fast go/no-go deal screen. Returns verdict + quick metrics in ~5 seconds.
    No ANTHROPIC_API_KEY required for the math pass; AI verdict requires it.
    """
    try:
        inp = ScreenInput(**req.model_dump())
        screener = DealScreener()
        verdict = await screener.screen(inp)
        return _dc_to_dict(verdict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screen/sample")
async def screen_sample():
    """Sample deal screen — no API key required."""
    req = ScreenRequest(
        asset_class="multifamily",
        purchase_price=4_800_000,
        market="Austin, TX",
        units=24,
        avg_unit_rent=2_000,
        vacancy_rate=0.05,
        ltv=0.70,
        interest_rate=0.0675,
        hold_period_years=5,
        additional_notes="Value-add 1980s vintage. Rents 15% below market. New roofs 2022.",
    )
    screener = DealScreener()
    math = screener._math_pass(ScreenInput(**req.model_dump()))
    # Return math-only for sample (no AI call)
    return {
        "verdict": "SOFT_GO",
        "confidence": "MEDIUM",
        "headline": "Deal pencils at target metrics with rent growth execution — vacancy and rate sensitivity are key risks.",
        "estimated_cap_rate": math["cap_rate"],
        "estimated_dscr": math["dscr"],
        "estimated_coc": math["coc"],
        "estimated_irr_range": [math["irr_low"], math["irr_high"]],
        "price_per_unit": math["price_per_unit"],
        "grm": math["grm"],
        "strengths": [
            "Going-in cap of 5.4% meets minimum threshold",
            "15% below-market rents provide organic rent growth upside",
            "Recent capital improvements reduce near-term capex risk",
        ],
        "concerns": [
            "Rate sensitivity: DSCR drops to 1.18x at 7.5% interest rate",
            "Austin supply pipeline remains elevated through 2025",
        ],
        "suggested_max_price": math["max_price_at_target_cap"],
        "full_reasoning": (
            "The Austin Arms trades at a 5.4% going-in cap, just above the minimum threshold "
            "but below the 5.5% target. At 70% LTV and 6.75%, DSCR clears 1.25x comfortably. "
            "The real story is the rent growth upside — at 15% below market, the property has "
            "a clear path to a 6%+ cap rate on stabilized rents without any physical upgrades.\n\n"
            "The main risks are execution-dependent: rent growth requires lease turnover, which "
            "takes time and creates temporary vacancy drag. Austin's supply pipeline also keeps "
            "a ceiling on how aggressively rents can grow in the near term.\n\n"
            "Worth a full underwrite. Negotiate toward $4.6M to create a margin of safety."
        ),
    }


# ── Document Parser ───────────────────────────────────────────────────────

@router.post("/parse/document")
async def parse_document(
    file: UploadFile = File(...),
    doc_type: str = Form("auto"),
):
    """
    Parse an OM, T-12, or rent roll PDF/text file into structured data.
    Supports PDF (requires pdfminer.six) and plain text.
    """
    try:
        content = await file.read()
        # Try to decode as text; if it fails, treat as PDF bytes
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            # Write to temp file for PDF extraction (ignore user-supplied filename for safety)
            import tempfile, os
            suffix = ".pdf" if file.content_type == "application/pdf" else ".txt"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                parser = DocumentParser()
                result = await parser.parse_file(tmp_path, doc_type)
            finally:
                os.unlink(tmp_path)
            return _dc_to_dict(result)

        parser = DocumentParser()
        result = await parser.parse_text(text, doc_type)
        return _dc_to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parse/text")
async def parse_document_text(body: dict):
    """Parse raw document text (OM, T-12, rent roll) into structured data."""
    text = body.get("text", "")
    doc_type = body.get("doc_type", "auto")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        parser = DocumentParser()
        result = await parser.parse_text(text, doc_type)
        return _dc_to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Due Diligence ─────────────────────────────────────────────────────────

class DDRequest(BaseModel):
    deal: DealInput
    t12_text: str | None = None          # raw T-12 text (will be parsed)
    rent_roll_text: str | None = None    # raw rent roll text (will be parsed)
    additional_docs: str = ""


@router.post("/due-diligence")
async def run_due_diligence(req: DDRequest):
    """
    Full due diligence analysis. Provide the deal input + any available
    T-12 or rent roll text. Returns red flags with severity and financial impact.
    """
    try:
        doc_parser = DocumentParser()
        t12 = None
        rent_roll = None

        if req.t12_text:
            parsed = await doc_parser.parse_text(req.t12_text, "t12")
            t12 = parsed.t12

        if req.rent_roll_text:
            parsed = await doc_parser.parse_text(req.rent_roll_text, "rent_roll")
            rent_roll = parsed.rent_roll

        agent = DueDiligenceAgent()
        report = await agent.analyze(
            deal=req.deal,
            t12=t12,
            rent_roll=rent_roll,
            additional_docs=req.additional_docs,
        )
        return _dc_to_dict(report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── LP Communications ─────────────────────────────────────────────────────

class AssetSnapshotRequest(BaseModel):
    property_name: str
    market: str
    asset_class: str
    units_or_sf: str
    acquisition_date: str
    acquisition_price: float
    current_value_estimate: float | None = None
    period_noi: float = 0
    period_dscr: float = 0
    period_occupancy: float = 0
    period_coc_return: float = 0
    ytd_distributions: float = 0
    total_distributions_to_date: float = 0
    equity_multiple_to_date: float = 0
    noi_vs_proforma_pct: float = 0
    occupancy_vs_proforma_pct: float = 0
    capex_spend_period: float = 0
    notable_updates: list[str] = Field(default_factory=list)


class LPCommsRequest(BaseModel):
    comm_type: str = "monthly_update"
    fund_name: str
    gp_name: str
    gp_firm: str
    lp_name: str | None = None
    period: str = ""
    assets: list[AssetSnapshotRequest] = Field(default_factory=list)
    distribution_amount: float | None = None
    distribution_per_unit: float | None = None
    distribution_date: str | None = None
    distribution_type: str = "Preferred Return"
    capital_call_amount: float | None = None
    capital_call_due_date: str | None = None
    capital_call_purpose: str | None = None
    new_deal_summary: dict = Field(default_factory=dict)
    tone: str = "professional"
    include_disclaimer: bool = True
    additional_context: str = ""


@router.post("/lp-comms")
async def generate_lp_communication(req: LPCommsRequest):
    """
    Generate a professional LP communication.
    Supports: monthly_update, quarterly_report, distribution_announcement,
              capital_call, new_deal_announcement, annual_report.
    """
    try:
        assets = [AssetSnapshot(**a.model_dump()) for a in req.assets]
        inp = LPCommsInput(
            **{k: v for k, v in req.model_dump().items() if k != "assets"},
            assets=assets,
        )
        agent = LPCommsAgent()
        output = await agent.generate(inp)
        return _dc_to_dict(output)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lp-comms/sample")
async def sample_lp_communication():
    """Sample LP communication — no API key required."""
    return {
        "comm_type": "monthly_update",
        "subject_line": "The Austin Arms — October 2025 Investor Update",
        "body_markdown": """## October 2025 Investor Update — The Austin Arms

Dear Partners,

October delivered strong operational performance across the portfolio, with The Austin Arms posting its fourth consecutive month above pro forma NOI.

### Portfolio Highlights

| Metric | October | Pro Forma | YTD |
|---|---|---|---|
| Physical Occupancy | 95.8% | 93.0% | 94.2% |
| EGI | $47,200 | $45,800 | $554,100 |
| NOI | $26,800 | $25,400 | $312,400 |
| DSCR (trailing 3-mo) | 1.31x | 1.28x | 1.30x |

### Property Update

Leasing remained strong in October with three new leases signed at an average of $2,175/month, representing 8.8% growth over the expiring leases. We renewed six leases at an average increase of 4.2%.

The unit renovation program continues on pace — we completed three units in October with an average turn time of 5.2 days and are tracking toward our target of 18 renovated units by year-end. Renovated units are achieving an average premium of $215/month, producing an 18-month payback on the $4,800 average renovation cost.

### Distribution

We are pleased to distribute **$12,400** to investors for October operations, representing an **annualized 7.4% cash-on-cash return** on committed equity. Wires will process November 15.

### What's Next

November focus areas: lease renewal negotiations for the 4 leases expiring in December, final three unit renovations before the holiday slowdown, and HVAC preventive maintenance ahead of winter.

As always, please reach out directly with any questions.

Best regards,
Tom McGahan | Acme Capital""",
        "key_numbers": {
            "Occupancy": "95.8%",
            "NOI": "$26,800",
            "vs. Pro Forma": "+5.5%",
            "Distribution": "$12,400",
            "Annualized CoC": "7.4%",
        },
        "action_items": ["Watch for distribution wire on November 15"],
        "disclaimer": "This communication is intended solely for the addressee(s) and contains confidential information. Past performance is not indicative of future results.",
    }
