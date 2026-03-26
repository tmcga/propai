"""
Shared test fixtures for PropAI backend tests.
"""

import sys
import os

import pytest

# Add backend to path so imports work without install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.financial.models import (
    DealInput,
    AssetClass,
    LoanInput,
    LoanType,
    OperatingAssumptions,
    ExitAssumptions,
)


@pytest.fixture
def sample_deal() -> DealInput:
    """Standard 24-unit Austin multifamily deal — shared across test modules."""
    return DealInput(
        name="Test Multifamily",
        asset_class=AssetClass.MULTIFAMILY,
        purchase_price=4_800_000,
        units=24,
        square_feet=22_000,
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
            gross_scheduled_income=576_000,
            vacancy_rate=0.05,
            credit_loss_rate=0.01,
            other_income=14_400,
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
    )
