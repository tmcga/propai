"""
Test suite for the PropAI financial engine.

Tests cover:
  - Core metrics (cap rate, CoC, DSCR, GRM, etc.)
  - DCF engine (IRR, NPV, equity multiple)
  - Debt service calculations (fixed, IO, IO-then-amortizing)
  - Pro forma generator (year-by-year correctness)
  - Equity waterfall distributions
  - Edge cases and boundary conditions

Run with: pytest tests/ -v --cov=engine
"""

import math
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.financial.metrics import (
    effective_gross_income,
    net_operating_income,
    cap_rate,
    value_from_cap_rate,
    gross_rent_multiplier,
    annual_debt_service,
    loan_balance,
    debt_service_coverage_ratio,
    before_tax_cash_flow,
    cash_on_cash_return,
    operating_expense_ratio,
    break_even_occupancy,
    net_sale_proceeds,
    generate_warnings,
)
from engine.financial.dcf import (
    npv,
    irr,
    equity_multiple,
    total_profit,
    average_cash_on_cash,
    DCFEngine,
)
from engine.financial.models import (
    DealInput,
    AssetClass,
    LoanInput,
    LoanType,
    OperatingAssumptions,
    ExitAssumptions,
    EquityStructure,
)
from engine.financial.proforma import ProFormaEngine
from engine.financial.waterfall import WaterfallEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_multifamily_deal() -> DealInput:
    """Standard 24-unit Austin multifamily deal for testing."""
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


@pytest.fixture
def simple_cash_flows() -> list[float]:
    """Simple 5-year cash flows with known IRR for unit testing."""
    # -100k invested, 10k/yr for 4 years, then 130k in year 5
    # IRR ≈ 12.8%
    return [-100_000, 10_000, 10_000, 10_000, 10_000, 130_000]


# ---------------------------------------------------------------------------
# Core Metrics Tests
# ---------------------------------------------------------------------------

class TestEffectiveGrossIncome:
    def test_basic_egi(self):
        """EGI = GSI × (1 - vacancy) × (1 - credit_loss) + other"""
        egi = effective_gross_income(
            gross_scheduled_income=100_000,
            vacancy_rate=0.05,
            credit_loss_rate=0.02,
            other_income=5_000,
        )
        expected = 100_000 * 0.95 * 0.98 + 5_000
        assert abs(egi - expected) < 0.01

    def test_full_occupancy_no_loss(self):
        egi = effective_gross_income(120_000, 0.0, 0.0, 0.0)
        assert egi == 120_000

    def test_full_vacancy(self):
        egi = effective_gross_income(100_000, 1.0, 0.0, 1_000)
        assert egi == 1_000  # Only other income


class TestCapRate:
    def test_standard_cap_rate(self):
        cr = cap_rate(noi=200_000, value=4_000_000)
        assert abs(cr - 0.05) < 1e-10

    def test_cap_rate_zero_value_raises(self):
        with pytest.raises(ValueError):
            cap_rate(200_000, 0)

    def test_value_from_cap_rate(self):
        val = value_from_cap_rate(noi=200_000, cap_rate_=0.05)
        assert abs(val - 4_000_000) < 0.01


class TestGrossRentMultiplier:
    def test_grm(self):
        grm = gross_rent_multiplier(purchase_price=1_000_000, gross_annual_rent=100_000)
        assert abs(grm - 10.0) < 1e-10

    def test_grm_zero_rent_raises(self):
        with pytest.raises(ValueError):
            gross_rent_multiplier(1_000_000, 0)


class TestDebtService:
    def test_fully_amortizing_payment(self):
        """Monthly payment on $3.36M at 6.75% over 30 years."""
        loan_amt = 3_360_000
        rate = 0.0675
        amort = 30

        ds, principal, interest = annual_debt_service(loan_amt, rate, amort, current_year=1)

        # Verify: annual DS should be reasonable (~$260k range for these params)
        assert 200_000 < ds < 350_000
        # Interest in year 1 should be ~= loan × rate
        assert abs(interest - loan_amt * rate) < 5_000  # Allow for rounding
        # Principal should be positive
        assert principal > 0
        # P + I = total DS
        assert abs(principal + interest - ds) < 1.0

    def test_io_loan_year_1(self):
        """Interest-only loan: no principal in IO period."""
        ds, principal, interest = annual_debt_service(
            loan_amount=1_000_000,
            interest_rate=0.06,
            amortization_years=30,
            io_years=3,
            current_year=1,
        )
        assert principal == 0.0
        assert abs(interest - 60_000) < 0.01
        assert abs(ds - 60_000) < 0.01

    def test_io_loan_after_io_period(self):
        """After IO period, loan amortizes."""
        ds, principal, interest = annual_debt_service(
            loan_amount=1_000_000,
            interest_rate=0.06,
            amortization_years=30,
            io_years=3,
            current_year=4,
        )
        assert principal > 0
        assert interest > 0

    def test_loan_balance_decreases(self):
        """Loan balance should decrease over time for amortizing loan."""
        b5 = loan_balance(1_000_000, 0.06, 30, 5)
        b10 = loan_balance(1_000_000, 0.06, 30, 10)
        b30 = loan_balance(1_000_000, 0.06, 30, 30)
        assert b5 > b10 > b30
        assert b30 < 1_000  # Nearly paid off

    def test_io_loan_balance_unchanged_during_io(self):
        """IO loan balance stays flat during IO period."""
        b1 = loan_balance(1_000_000, 0.06, 30, 1, io_years=5)
        b5 = loan_balance(1_000_000, 0.06, 30, 5, io_years=5)
        assert abs(b1 - 1_000_000) < 0.01
        assert abs(b5 - 1_000_000) < 0.01


class TestDSCR:
    def test_healthy_dscr(self):
        dscr = debt_service_coverage_ratio(noi=300_000, annual_debt_service_=200_000)
        assert abs(dscr - 1.5) < 1e-10

    def test_below_1_dscr(self):
        dscr = debt_service_coverage_ratio(noi=150_000, annual_debt_service_=200_000)
        assert dscr == 0.75

    def test_zero_debt_service(self):
        dscr = debt_service_coverage_ratio(noi=100_000, annual_debt_service_=0)
        assert dscr == float("inf")


class TestCashOnCash:
    def test_coc_return(self):
        coc = cash_on_cash_return(btcf=50_000, equity_invested=1_000_000)
        assert abs(coc - 0.05) < 1e-10

    def test_negative_coc(self):
        coc = cash_on_cash_return(btcf=-10_000, equity_invested=500_000)
        assert coc == -0.02


class TestNetSaleProceeds:
    def test_proceeds(self):
        nsp = net_sale_proceeds(
            gross_sale_price=5_000_000,
            remaining_loan_balance=3_000_000,
            selling_costs_pct=0.03,
        )
        expected = 5_000_000 * 0.97 - 3_000_000
        assert abs(nsp - expected) < 0.01


# ---------------------------------------------------------------------------
# DCF Engine Tests
# ---------------------------------------------------------------------------

class TestNPV:
    def test_zero_rate_npv(self):
        """At 0% discount rate, NPV = sum of all cash flows."""
        cfs = [-100_000, 30_000, 30_000, 30_000, 30_000]
        result = npv(0.0, cfs)
        assert abs(result - 20_000) < 0.01

    def test_positive_npv(self):
        """Good deal at 8% discount rate."""
        cfs = [-1_000_000, 100_000, 100_000, 100_000, 100_000, 1_200_000]
        result = npv(0.08, cfs)
        assert result > 0

    def test_negative_npv_high_discount(self):
        """At very high discount rate, NPV turns negative."""
        cfs = [-1_000_000, 50_000, 50_000, 50_000, 50_000, 1_050_000]
        assert npv(0.50, cfs) < 0


class TestIRR:
    def test_known_irr(self, simple_cash_flows):
        """Verify IRR against a known result."""
        result = irr(simple_cash_flows)
        assert result is not None
        # Verify by checking NPV at computed IRR is near 0
        assert abs(npv(result, simple_cash_flows)) < 1.0

    def test_irr_at_zero_npv(self):
        """IRR should be the rate that makes NPV = 0."""
        cfs = [-1_000_000, 80_000, 80_000, 80_000, 80_000, 1_080_000]
        rate = irr(cfs)
        assert rate is not None
        assert abs(npv(rate, cfs)) < 1.0

    def test_no_sign_change_returns_none(self):
        """All positive cash flows → no IRR."""
        result = irr([100, 200, 300])
        assert result is None

    def test_simple_irr(self):
        """Simple 2-period: invest 100, get 110 back → IRR = 10%."""
        result = irr([-100, 110])
        assert result is not None
        assert abs(result - 0.10) < 1e-6


class TestEquityMultiple:
    def test_standard_em(self, simple_cash_flows):
        em = equity_multiple(simple_cash_flows)
        assert em is not None
        # Invested 100k, received 10k×4 + 130k = 170k → EM = 1.7
        assert abs(em - 1.70) < 0.01

    def test_em_below_1_means_loss(self):
        em = equity_multiple([-100_000, 80_000])
        assert em is not None
        assert em < 1.0

    def test_no_investment_returns_none(self):
        em = equity_multiple([100, 200, 300])
        assert em is None


class TestDCFEngine:
    def test_dcf_engine_summary(self, simple_cash_flows):
        engine = DCFEngine(
            equity_cash_flows=simple_cash_flows,
            asset_cash_flows=simple_cash_flows,
            discount_rate=0.08,
        )
        summary = engine.summary()
        assert "levered_irr" in summary
        assert "equity_multiple" in summary
        assert summary["equity_multiple"] is not None
        assert summary["equity_multiple"] > 1.0  # Made money

    def test_levered_vs_unlevered(self):
        """Levered IRR should differ from unlevered when debt is modeled."""
        asset_cfs = [-5_000_000, 300_000, 300_000, 300_000, 300_000, 5_500_000]
        equity_cfs = [-1_500_000, 80_000, 85_000, 90_000, 95_000, 2_200_000]
        engine = DCFEngine(asset_cfs, equity_cfs, discount_rate=0.08)
        # With leverage, equity IRR should differ from asset IRR
        assert engine.levered_irr != engine.unlevered_irr


# ---------------------------------------------------------------------------
# Pro Forma Generator Tests
# ---------------------------------------------------------------------------

class TestProFormaEngine:
    def test_pro_forma_length(self, sample_multifamily_deal):
        """Pro forma should have exactly hold_period_years rows."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert len(result.pro_forma) == 5

    def test_noi_is_positive(self, sample_multifamily_deal):
        """NOI should be positive for a viable deal."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        for year in result.pro_forma:
            assert year.net_operating_income > 0, f"NOI negative in year {year.year}"

    def test_rent_grows_each_year(self, sample_multifamily_deal):
        """GSI should grow at the specified rent growth rate."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        rate = sample_multifamily_deal.operations.rent_growth_rate

        for i in range(1, len(result.pro_forma)):
            prev = result.pro_forma[i - 1].gross_scheduled_income
            curr = result.pro_forma[i].gross_scheduled_income
            expected = prev * (1 + rate)
            assert abs(curr - expected) < 1.0, f"Rent not growing correctly in year {i + 1}"

    def test_going_in_cap_rate(self, sample_multifamily_deal):
        """Going-in cap rate should be in a reasonable range."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        cap = result.metrics.going_in_cap_rate
        assert 0.02 < cap < 0.15, f"Going-in cap rate {cap:.2%} seems unreasonable"

    def test_levered_irr_is_computed(self, sample_multifamily_deal):
        """Levered IRR should be computed and positive for a viable deal."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert result.metrics.levered_irr is not None
        assert result.metrics.levered_irr > 0

    def test_equity_multiple_above_1(self, sample_multifamily_deal):
        """Equity multiple should be > 1 for a deal that makes money."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert result.metrics.equity_multiple > 1.0

    def test_sensitivity_tables_shape(self, sample_multifamily_deal):
        """Sensitivity tables should be 5×5."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=True)
        assert result.irr_sensitivity is not None
        assert len(result.irr_sensitivity.data) == 5
        assert all(len(row) == 5 for row in result.irr_sensitivity.data)

    def test_dscr_yr1(self, sample_multifamily_deal):
        """DSCR should be above 1.0 for a lendable deal."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert result.metrics.dscr_yr1 > 1.0

    def test_noi_per_unit(self, sample_multifamily_deal):
        """NOI per unit should be computed when units are provided."""
        engine = ProFormaEngine(sample_multifamily_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert result.metrics.noi_per_unit is not None
        assert result.metrics.noi_per_unit > 0

    def test_warnings_generated_for_aggressive_deal(self):
        """Deals with aggressive assumptions should generate warnings."""
        aggressive_deal = DealInput(
            name="Aggressive Test Deal",
            asset_class=AssetClass.MULTIFAMILY,
            purchase_price=5_000_000,
            units=20,
            closing_costs=0.01,
            loan=LoanInput(
                ltv=0.85,          # High LTV
                interest_rate=0.07,
                amortization_years=30,
                origination_fee=0.01,
            ),
            operations=OperatingAssumptions(
                gross_scheduled_income=400_000,
                vacancy_rate=0.02,     # Very aggressive vacancy
                credit_loss_rate=0.00,
                other_income=0,
                property_taxes=50_000,
                insurance=10_000,
                management_fee_pct=0.05,
                maintenance_reserves=15_000,
                capex_reserves=5_000,
                utilities=0,
                other_expenses=0,
                rent_growth_rate=0.07,  # Very high rent growth
                expense_growth_rate=0.02,
            ),
            exit=ExitAssumptions(
                hold_period_years=5,
                exit_cap_rate=0.04,  # Cap rate compression
                selling_costs_pct=0.03,
                discount_rate=0.08,
            ),
        )
        engine = ProFormaEngine(aggressive_deal)
        result = engine.underwrite(include_sensitivity=False)
        assert len(result.warnings) > 0, "Should have generated warnings for aggressive assumptions"


# ---------------------------------------------------------------------------
# Waterfall Tests
# ---------------------------------------------------------------------------

class TestWaterfallEngine:
    @pytest.fixture
    def equity_structure(self):
        return EquityStructure(
            lp_equity_pct=0.90,
            gp_equity_pct=0.10,
            preferred_return=0.08,
            promote_hurdles=[0.08, 0.12, 0.15],
            promote_splits=[0.20, 0.30, 0.40],
        )

    def test_all_equity_returned(self, equity_structure):
        """Total LP + GP distributions should equal sum of positive cash flows."""
        cash_flows = [-1_000_000, 80_000, 85_000, 90_000, 95_000, 1_200_000]
        total_positive = sum(cf for cf in cash_flows if cf > 0)

        engine = WaterfallEngine(
            equity_structure=equity_structure,
            total_equity=1_000_000,
            cash_flows=cash_flows,
        )
        result = engine.compute()
        assert abs(result.lp_total_distributions + result.gp_total_distributions - total_positive) < 1.0

    def test_lp_gets_more_than_gp_in_normal_deal(self, equity_structure):
        """LP should receive majority of distributions (90% co-invest)."""
        cash_flows = [-1_000_000, 80_000, 85_000, 90_000, 95_000, 1_200_000]
        engine = WaterfallEngine(
            equity_structure=equity_structure,
            total_equity=1_000_000,
            cash_flows=cash_flows,
        )
        result = engine.compute()
        assert result.lp_total_distributions > result.gp_total_distributions

    def test_waterfall_tiers_exist(self, equity_structure):
        """Waterfall should have at least return-of-capital and pref tiers."""
        cash_flows = [-1_000_000, 80_000, 85_000, 90_000, 95_000, 1_500_000]
        engine = WaterfallEngine(
            equity_structure=equity_structure,
            total_equity=1_000_000,
            cash_flows=cash_flows,
        )
        result = engine.compute()
        assert len(result.tiers) >= 2
        tier_names = [t.tier_name for t in result.tiers]
        assert any("Return of Capital" in name for name in tier_names)

    def test_equity_split_validation(self):
        """EquityStructure should reject splits that don't sum to 1."""
        with pytest.raises(ValueError):
            EquityStructure(
                lp_equity_pct=0.85,
                gp_equity_pct=0.20,  # 0.85 + 0.20 ≠ 1.0
                preferred_return=0.08,
            )


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unleveraged_deal(self):
        """Deal with 0% LTV (all cash) should still compute correctly."""
        deal = DealInput(
            name="All Cash Deal",
            asset_class=AssetClass.SFR,
            purchase_price=500_000,
            closing_costs=0.01,
            loan=LoanInput(
                ltv=0.0,
                interest_rate=0.07,
                amortization_years=30,
                origination_fee=0.0,
            ),
            operations=OperatingAssumptions(
                gross_scheduled_income=36_000,
                vacancy_rate=0.05,
                credit_loss_rate=0.01,
                other_income=0,
                property_taxes=8_000,
                insurance=2_500,
                management_fee_pct=0.08,
                maintenance_reserves=3_600,
                capex_reserves=2_400,
                utilities=0,
                other_expenses=0,
                rent_growth_rate=0.03,
                expense_growth_rate=0.02,
            ),
            exit=ExitAssumptions(
                hold_period_years=10,
                exit_cap_rate=0.055,
                selling_costs_pct=0.06,
                discount_rate=0.07,
            ),
        )
        engine = ProFormaEngine(deal)
        result = engine.underwrite(include_sensitivity=False)
        # With no debt, BTCF = NOI, and DS = 0
        for year in result.pro_forma:
            assert year.debt_service == 0.0 or abs(year.debt_service) < 1.0
            assert abs(year.before_tax_cash_flow - year.net_operating_income) < 1.0

    def test_single_year_hold(self):
        """1-year hold period should produce 1-row pro forma."""
        deal = DealInput(
            name="Flip",
            asset_class=AssetClass.SFR,
            purchase_price=300_000,
            closing_costs=0.01,
            loan=LoanInput(ltv=0.70, interest_rate=0.08, amortization_years=30, origination_fee=0.01),
            operations=OperatingAssumptions(
                gross_scheduled_income=24_000,
                vacancy_rate=0.05,
                credit_loss_rate=0.01,
                other_income=0,
                property_taxes=5_000,
                insurance=1_800,
                management_fee_pct=0.10,
                maintenance_reserves=2_400,
                capex_reserves=0,
                utilities=0,
                other_expenses=0,
                rent_growth_rate=0.03,
                expense_growth_rate=0.02,
            ),
            exit=ExitAssumptions(hold_period_years=1, exit_cap_rate=0.06, selling_costs_pct=0.06, discount_rate=0.10),
        )
        engine = ProFormaEngine(deal)
        result = engine.underwrite(include_sensitivity=False)
        assert len(result.pro_forma) == 1
