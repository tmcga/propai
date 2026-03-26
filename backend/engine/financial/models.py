"""
Pydantic models for the PropAI financial engine.

All monetary values are in USD. Rates are expressed as decimals (e.g., 0.05 = 5%).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AssetClass(str, Enum):
    SFR = "sfr"  # Single-Family Residential
    SMALL_MULTIFAMILY = "small_multifamily"  # 2–20 units
    MULTIFAMILY = "multifamily"  # 20+ units
    OFFICE = "office"
    RETAIL = "retail"
    MIXED_USE = "mixed_use"
    INDUSTRIAL = "industrial"
    SELF_STORAGE = "self_storage"
    STR = "str"  # Short-Term Rental
    GROUND_UP = "ground_up"  # New construction / development


class LoanType(str, Enum):
    FIXED = "fixed"
    INTEREST_ONLY = "interest_only"
    IO_THEN_AMORTIZING = "io_then_amortizing"


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------


class LoanInput(BaseModel):
    """Debt financing assumptions."""

    ltv: float = Field(
        0.70, ge=0.0, le=0.95, description="Loan-to-Value ratio (e.g., 0.70 = 70%)"
    )
    interest_rate: float = Field(
        0.065, ge=0.0, le=0.30, description="Annual interest rate"
    )
    amortization_years: int = Field(
        30, ge=1, le=40, description="Amortization period in years"
    )
    loan_type: LoanType = Field(LoanType.FIXED, description="Loan structure")
    io_period_years: int = Field(
        0, ge=0, le=10, description="Interest-only period (for IO_THEN_AMORTIZING)"
    )
    origination_fee: float = Field(
        0.01, ge=0.0, le=0.05, description="Loan origination fee as % of loan amount"
    )

    @model_validator(mode="after")
    def validate_io_period(self) -> "LoanInput":
        if self.loan_type == LoanType.IO_THEN_AMORTIZING and self.io_period_years == 0:
            raise ValueError("io_period_years must be > 0 for IO_THEN_AMORTIZING loans")
        return self


class OperatingAssumptions(BaseModel):
    """Revenue and expense assumptions for stabilized operations."""

    # Revenue
    gross_scheduled_income: float = Field(
        ..., gt=0, description="Annual gross scheduled rental income (Year 1)"
    )
    vacancy_rate: float = Field(
        0.05, ge=0.0, le=0.50, description="Physical vacancy rate"
    )
    credit_loss_rate: float = Field(
        0.01, ge=0.0, le=0.20, description="Credit loss / bad debt rate"
    )
    other_income: float = Field(
        0.0, ge=0.0, description="Other annual income (parking, laundry, fees)"
    )

    # Expenses (annual, Year 1)
    property_taxes: float = Field(..., ge=0.0, description="Annual property taxes")
    insurance: float = Field(..., ge=0.0, description="Annual property insurance")
    management_fee_pct: float = Field(
        0.05, ge=0.0, le=0.20, description="Management fee as % of EGI"
    )
    maintenance_reserves: float = Field(
        ..., ge=0.0, description="Annual maintenance & repairs"
    )
    capex_reserves: float = Field(
        0.0, ge=0.0, description="Annual CapEx / replacement reserves"
    )
    utilities: float = Field(0.0, ge=0.0, description="Annual utilities paid by owner")
    other_expenses: float = Field(
        0.0, ge=0.0, description="Other annual operating expenses"
    )

    # Growth rates
    rent_growth_rate: float = Field(
        0.03, ge=-0.10, le=0.20, description="Annual rent growth rate"
    )
    expense_growth_rate: float = Field(
        0.02, ge=-0.05, le=0.15, description="Annual expense growth rate"
    )


class ExitAssumptions(BaseModel):
    """Hold period and disposition assumptions."""

    hold_period_years: int = Field(
        5, ge=1, le=30, description="Investment hold period in years"
    )
    exit_cap_rate: float = Field(
        ..., gt=0.0, le=0.30, description="Cap rate applied to exit NOI"
    )
    selling_costs_pct: float = Field(
        0.03,
        ge=0.0,
        le=0.10,
        description="Selling costs as % of sale price (broker, transfer tax, etc.)",
    )
    discount_rate: float = Field(
        0.08, ge=0.01, le=0.50, description="Discount rate for NPV calculation"
    )


class EquityStructure(BaseModel):
    """LP/GP equity split and waterfall parameters."""

    lp_equity_pct: float = Field(
        0.90, ge=0.0, le=1.0, description="LP share of total equity (e.g., 0.90 = 90%)"
    )
    gp_equity_pct: float = Field(
        0.10, ge=0.0, le=1.0, description="GP co-invest share of total equity"
    )
    preferred_return: float = Field(
        0.08, ge=0.0, le=0.30, description="LP preferred return (annual)"
    )
    promote_hurdles: list[float] = Field(
        default=[0.08, 0.12, 0.15],
        description="IRR hurdles at which GP promote increases",
    )
    promote_splits: list[float] = Field(
        default=[0.20, 0.30, 0.40],
        description="GP promote % above each IRR hurdle (same length as hurdles)",
    )

    @model_validator(mode="after")
    def validate_equity_splits(self) -> "EquityStructure":
        if abs(self.lp_equity_pct + self.gp_equity_pct - 1.0) > 0.001:
            raise ValueError("lp_equity_pct + gp_equity_pct must equal 1.0")
        if len(self.promote_hurdles) != len(self.promote_splits):
            raise ValueError(
                "promote_hurdles and promote_splits must have the same length"
            )
        return self


class DealInput(BaseModel):
    """Top-level deal input — the main entry point for underwriting."""

    # Property info
    name: str = Field(..., description="Deal name / property address")
    asset_class: AssetClass = Field(..., description="Property type")
    purchase_price: float = Field(..., gt=0, description="Purchase price")
    square_feet: Optional[float] = Field(
        None, ge=0, description="Total rentable square footage"
    )
    units: Optional[int] = Field(
        None, ge=1, description="Number of units (multifamily/STR)"
    )
    year_built: Optional[int] = Field(None, description="Year property was built")
    market: Optional[str] = Field(None, description="City/MSA (e.g., 'Austin, TX')")

    # Closing costs & immediate CapEx
    closing_costs: float = Field(
        0.01, ge=0.0, le=0.10, description="Closing costs as % of purchase price"
    )
    immediate_capex: float = Field(
        0.0, ge=0.0, description="Immediate CapEx / renovation budget at acquisition"
    )

    # Sub-models
    loan: LoanInput = Field(default_factory=LoanInput)  # type: ignore[arg-type]
    operations: OperatingAssumptions
    exit: ExitAssumptions
    equity_structure: Optional[EquityStructure] = Field(
        None, description="LP/GP structure (optional)"
    )

    @property
    def loan_amount(self) -> float:
        return self.purchase_price * self.loan.ltv

    @property
    def equity_required(self) -> float:
        down_payment = self.purchase_price * (1 - self.loan.ltv)
        closing = self.purchase_price * self.closing_costs
        origination = self.loan_amount * self.loan.origination_fee
        return down_payment + closing + self.immediate_capex + origination

    @property
    def total_project_cost(self) -> float:
        return (
            self.purchase_price
            + (self.purchase_price * self.closing_costs)
            + self.immediate_capex
            + (self.loan_amount * self.loan.origination_fee)
        )


# ---------------------------------------------------------------------------
# Output Models
# ---------------------------------------------------------------------------


class ProFormaYear(BaseModel):
    """Financial results for a single year in the pro forma."""

    year: int
    gross_scheduled_income: float
    vacancy_loss: float
    credit_loss: float
    other_income: float
    effective_gross_income: float

    property_taxes: float
    insurance: float
    management_fee: float
    maintenance_reserves: float
    capex_reserves: float
    utilities: float
    other_expenses: float
    total_operating_expenses: float

    net_operating_income: float
    debt_service: float
    principal_paydown: float
    interest_expense: float
    before_tax_cash_flow: float

    # Cumulative / balance sheet items
    loan_balance: float
    equity_value: float  # NOI / current_year_cap_rate (marked-to-market)

    # Per-unit / per-SF
    noi_per_unit: Optional[float] = None
    noi_per_sf: Optional[float] = None


class ReturnMetrics(BaseModel):
    """Stabilized (Year 1) and total-hold return metrics."""

    # Stabilized metrics (Year 1)
    going_in_cap_rate: float = Field(description="Year 1 NOI / Purchase Price")
    cash_on_cash_yr1: float = Field(description="Year 1 BTCF / Total Equity")
    gross_rent_multiplier: float = Field(
        description="Purchase Price / Gross Annual Rent"
    )
    dscr_yr1: float = Field(description="Year 1 NOI / Annual Debt Service")
    operating_expense_ratio: float = Field(description="Total OpEx / EGI")
    break_even_occupancy: float = Field(
        description="Occupancy needed to cover all cash obligations"
    )

    # Price per unit / per SF
    price_per_unit: Optional[float] = None
    price_per_sf: Optional[float] = None
    noi_per_unit: Optional[float] = None

    # Total hold period returns
    irr: float = Field(
        description="Project-level IRR (unleveraged if no debt, levered otherwise)"
    )
    levered_irr: float = Field(description="Equity / levered IRR")
    equity_multiple: float = Field(
        description="Total distributions / total equity invested"
    )
    npv: float = Field(description="Net Present Value at given discount rate")
    average_cash_on_cash: float = Field(
        description="Average annual cash-on-cash over hold period"
    )
    total_profit: float = Field(
        description="Total profit (distributions minus equity invested)"
    )

    # Exit
    exit_price: float
    exit_noi: float
    net_sale_proceeds: float
    total_equity_distributions: float
    total_equity_invested: float


class SensitivityTable(BaseModel):
    """2D sensitivity analysis table (e.g., rent growth vs. exit cap rate)."""

    row_label: str  # e.g., "Exit Cap Rate"
    col_label: str  # e.g., "Rent Growth"
    row_values: list[float]
    col_values: list[float]
    metric: str  # e.g., "levered_irr"
    data: list[list[float]]  # [row][col] → metric value


class WaterfallTier(BaseModel):
    """Results for a single waterfall distribution tier."""

    tier_name: str
    irr_hurdle: Optional[float]
    lp_distributions: float
    gp_distributions: float
    lp_split: float
    gp_split: float


class WaterfallResult(BaseModel):
    """Full equity waterfall distribution breakdown."""

    total_distributions: float
    equity_invested: float
    lp_equity_invested: float
    gp_equity_invested: float
    lp_total_distributions: float
    gp_total_distributions: float
    lp_irr: float
    gp_irr: float
    lp_equity_multiple: float
    gp_equity_multiple: float
    tiers: list[WaterfallTier]


class UnderwritingResult(BaseModel):
    """Complete underwriting output — the full package."""

    deal_name: str
    asset_class: AssetClass
    purchase_price: float
    loan_amount: float
    equity_invested: float
    total_project_cost: float

    metrics: ReturnMetrics
    pro_forma: list[ProFormaYear]
    waterfall: Optional[WaterfallResult] = None

    # Sensitivity tables
    irr_sensitivity: Optional[SensitivityTable] = None
    coc_sensitivity: Optional[SensitivityTable] = None

    # Flags / warnings
    warnings: list[str] = Field(default_factory=list)
