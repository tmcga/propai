"""
Underwriting API endpoints.

POST /api/underwrite        — Run a full deal underwriting
POST /api/underwrite/quick  — Quick metrics only (no sensitivity tables)
GET  /api/underwrite/sample — Return a sample deal for the UI demo
"""

from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from engine.financial import (
    DealInput,
    UnderwritingResult,
    ProFormaEngine,
    WaterfallEngine,
    AssetClass,
)
from engine.financial.models import (
    LoanInput,
    OperatingAssumptions,
    ExitAssumptions,
    EquityStructure,
    LoanType,
)

router = APIRouter(prefix="/api/underwrite", tags=["underwriting"])


@router.post("", response_model=UnderwritingResult, summary="Full deal underwriting")
async def underwrite_deal(deal: DealInput) -> UnderwritingResult:
    """
    Run a complete underwriting analysis on a property.

    Returns:
      - Year-by-year pro forma
      - Return metrics (Cap Rate, CoC, DSCR, GRM, IRR, NPV, Equity Multiple)
      - Sensitivity tables (5×5 IRR and CoC grids)
      - Equity waterfall (if equity_structure is provided)
      - Plain-English warnings for aggressive assumptions
    """
    try:
        start = time.perf_counter()

        engine = ProFormaEngine(deal)
        result = engine.underwrite(include_sensitivity=True)

        # Compute waterfall if equity structure provided
        if deal.equity_structure:
            waterfall_engine = WaterfallEngine(
                equity_structure=deal.equity_structure,
                total_equity=result.equity_invested,
                cash_flows=engine._equity_cfs,
            )
            result.waterfall = waterfall_engine.compute()

        elapsed = time.perf_counter() - start
        # Log timing for performance monitoring (would wire to logger in prod)
        print(f"Underwriting completed in {elapsed:.3f}s for '{deal.name}'")

        return result

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Underwriting failed: {str(e)}")


@router.post("/quick", response_model=dict, summary="Quick metrics (no sensitivity)")
async def underwrite_quick(deal: DealInput) -> dict:
    """
    Fast underwriting with key metrics only — no sensitivity tables.
    Useful for screening large numbers of deals.

    Returns the same metrics as /underwrite but ~5x faster.
    """
    try:
        engine = ProFormaEngine(deal)
        result = engine.underwrite(include_sensitivity=False)
        return {
            "deal_name": result.deal_name,
            "purchase_price": result.purchase_price,
            "equity_invested": result.equity_invested,
            "going_in_cap_rate": result.metrics.going_in_cap_rate,
            "cash_on_cash_yr1": result.metrics.cash_on_cash_yr1,
            "dscr_yr1": result.metrics.dscr_yr1,
            "levered_irr": result.metrics.levered_irr,
            "equity_multiple": result.metrics.equity_multiple,
            "npv": result.metrics.npv,
            "exit_price": result.metrics.exit_price,
            "warnings": result.warnings,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quick underwriting failed: {str(e)}")


@router.get("/sample", response_model=DealInput, summary="Sample deal for UI demo")
async def sample_deal() -> DealInput:
    """
    Returns a sample 24-unit multifamily deal in Austin, TX.
    Used to pre-populate the UI for first-time users.
    """
    return DealInput(
        name="The Austin Arms — 24-Unit Multifamily",
        asset_class=AssetClass.MULTIFAMILY,
        purchase_price=4_800_000,
        units=24,
        square_feet=22_000,
        year_built=1998,
        market="Austin, TX",
        closing_costs=0.01,
        immediate_capex=120_000,
        loan=LoanInput(
            ltv=0.70,
            interest_rate=0.0675,
            amortization_years=30,
            loan_type=LoanType.FIXED,
            origination_fee=0.01,
        ),
        operations=OperatingAssumptions(
            gross_scheduled_income=576_000,   # 24 units × $2,000/mo
            vacancy_rate=0.05,
            credit_loss_rate=0.01,
            other_income=14_400,              # laundry + parking
            property_taxes=72_000,
            insurance=18_000,
            management_fee_pct=0.05,
            maintenance_reserves=36_000,
            capex_reserves=24_000,
            utilities=12_000,
            other_expenses=8_400,
            rent_growth_rate=0.03,
            expense_growth_rate=0.02,
        ),
        exit=ExitAssumptions(
            hold_period_years=5,
            exit_cap_rate=0.055,
            selling_costs_pct=0.03,
            discount_rate=0.08,
        ),
        equity_structure=EquityStructure(
            lp_equity_pct=0.90,
            gp_equity_pct=0.10,
            preferred_return=0.08,
            promote_hurdles=[0.08, 0.12, 0.15],
            promote_splits=[0.20, 0.30, 0.40],
        ),
    )


@router.get("/sample/result", response_model=UnderwritingResult, summary="Sample underwriting result")
async def sample_result() -> UnderwritingResult:
    """
    Returns a fully computed underwriting result for the sample deal.
    Useful for UI development and demos without needing to POST a deal.
    """
    deal = await sample_deal()
    return await underwrite_deal(deal)
