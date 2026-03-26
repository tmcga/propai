"""
Pro Forma Generator — the main underwriting engine.

Takes a DealInput and produces a complete UnderwritingResult including:
  - Year-by-year pro forma
  - Key return metrics (Cap Rate, CoC, DSCR, GRM, IRR, NPV, EM)
  - Sensitivity tables (IRR vs. exit cap / rent growth)
  - Plain-English warnings
"""

from __future__ import annotations

from typing import Optional

from .models import (
    DealInput,
    LoanType,
    ProFormaYear,
    ReturnMetrics,
    SensitivityTable,
    UnderwritingResult,
)
from .metrics import (
    effective_gross_income,
    net_operating_income,
    annual_debt_service,
    loan_balance,
    cap_rate,
    value_from_cap_rate,
    gross_rent_multiplier,
    price_per_unit,
    price_per_sf,
    debt_service_coverage_ratio,
    before_tax_cash_flow,
    cash_on_cash_return,
    operating_expense_ratio,
    break_even_occupancy,
    exit_price,
    net_sale_proceeds,
    generate_warnings,
)
from .dcf import DCFEngine, irr_sensitivity_table


class ProFormaEngine:
    """
    Orchestrates a full underwriting analysis from a DealInput.

    Usage:
        engine = ProFormaEngine(deal)
        result = engine.underwrite()
    """

    def __init__(self, deal: DealInput):
        self.deal = deal
        self._pro_forma: list[ProFormaYear] = []
        self._equity_cfs: list[float] = []
        self._asset_cfs: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def underwrite(self, include_sensitivity: bool = True) -> UnderwritingResult:
        """
        Run the full underwriting and return a complete result object.

        Args:
            include_sensitivity: Whether to compute sensitivity tables
                                  (adds ~100ms for a 5x5 grid)
        """
        deal = self.deal
        ops = deal.operations
        loan = deal.loan
        exit_ = deal.exit

        # ── 1. Derived acquisition values ────────────────────────────
        loan_amount = deal.loan_amount
        equity_invested = deal.equity_required
        total_cost = deal.total_project_cost

        # ── 2. Build year-by-year pro forma ──────────────────────────
        pro_forma = self._build_pro_forma(loan_amount, equity_invested)
        self._pro_forma = pro_forma

        # ── 3. Build cash flow series ─────────────────────────────────
        # Equity (levered) cash flows: t=0 is negative equity invested
        equity_cfs = [-equity_invested]
        asset_cfs = [-total_cost]

        for year_data in pro_forma[:-1]:  # Exclude exit year (handled separately)
            equity_cfs.append(year_data.before_tax_cash_flow)
            asset_cfs.append(year_data.net_operating_income)

        # Final year: operating CF + reversion proceeds
        final_year = pro_forma[-1]
        exit_noi = final_year.net_operating_income
        gross_exit_price = exit_price(exit_noi, exit_.exit_cap_rate)
        final_loan_balance = loan_balance(
            loan_amount,
            loan.interest_rate,
            loan.amortization_years,
            exit_.hold_period_years,
            io_years=loan.io_period_years if loan.loan_type != LoanType.FIXED else 0,
        )
        net_proceeds = net_sale_proceeds(
            gross_exit_price, final_loan_balance, exit_.selling_costs_pct
        )

        equity_cfs.append(final_year.before_tax_cash_flow + net_proceeds)
        asset_cfs.append(final_year.net_operating_income + gross_exit_price * (1 - exit_.selling_costs_pct))

        self._equity_cfs = equity_cfs
        self._asset_cfs = asset_cfs

        # ── 4. DCF engine ─────────────────────────────────────────────
        dcf = DCFEngine(equity_cfs, asset_cfs, discount_rate=exit_.discount_rate)

        # ── 5. Year 1 snapshot metrics ────────────────────────────────
        yr1 = pro_forma[0]
        io_years = loan.io_period_years if loan.loan_type != LoanType.FIXED else 0
        yr1_ds, _, _ = annual_debt_service(
            loan_amount, loan.interest_rate, loan.amortization_years,
            io_years=io_years, current_year=1
        )

        going_in_cap = cap_rate(yr1.net_operating_income, deal.purchase_price)
        dscr_yr1 = debt_service_coverage_ratio(yr1.net_operating_income, yr1_ds)
        coc_yr1 = cash_on_cash_return(yr1.before_tax_cash_flow, equity_invested)
        grm = gross_rent_multiplier(deal.purchase_price, ops.gross_scheduled_income)
        oer = operating_expense_ratio(yr1.total_operating_expenses, yr1.effective_gross_income)
        beo = break_even_occupancy(
            yr1.total_operating_expenses, yr1_ds, ops.gross_scheduled_income
        )

        # ── 6. Per-unit / per-SF metrics ──────────────────────────────
        ppu = price_per_unit(deal.purchase_price, deal.units) if deal.units else None
        ppsf = price_per_sf(deal.purchase_price, deal.square_feet) if deal.square_feet else None
        noi_unit = yr1.net_operating_income / deal.units if deal.units else None

        # ── 7. Return metrics ─────────────────────────────────────────
        l_irr = dcf.levered_irr
        em = dcf.equity_multiple
        total_distributions = sum(cf for cf in equity_cfs if cf > 0)

        metrics = ReturnMetrics(
            going_in_cap_rate=going_in_cap,
            cash_on_cash_yr1=coc_yr1,
            gross_rent_multiplier=grm,
            dscr_yr1=dscr_yr1,
            operating_expense_ratio=oer,
            break_even_occupancy=beo,
            price_per_unit=ppu,
            price_per_sf=ppsf,
            noi_per_unit=noi_unit,
            irr=dcf.unlevered_irr or 0.0,
            levered_irr=l_irr or 0.0,
            equity_multiple=em or 0.0,
            npv=dcf.levered_npv,
            average_cash_on_cash=dcf.average_coc,
            total_profit=dcf.total_equity_profit,
            exit_price=gross_exit_price,
            exit_noi=exit_noi,
            net_sale_proceeds=net_proceeds,
            total_equity_distributions=total_distributions,
            total_equity_invested=equity_invested,
        )

        # ── 8. Warnings ───────────────────────────────────────────────
        warnings = generate_warnings(
            going_in_cap=going_in_cap,
            dscr=dscr_yr1,
            ltv=loan.ltv,
            vacancy_rate=ops.vacancy_rate,
            rent_growth=ops.rent_growth_rate,
            exit_cap=exit_.exit_cap_rate,
            going_in_cap_for_exit=going_in_cap,
        )

        # ── 9. Sensitivity tables ─────────────────────────────────────
        irr_table = None
        coc_table = None

        if include_sensitivity:
            irr_table = self._irr_sensitivity(loan_amount, equity_invested, total_cost)
            coc_table = self._coc_sensitivity(loan_amount, equity_invested)

        return UnderwritingResult(
            deal_name=deal.name,
            asset_class=deal.asset_class,
            purchase_price=deal.purchase_price,
            loan_amount=loan_amount,
            equity_invested=equity_invested,
            total_project_cost=total_cost,
            metrics=metrics,
            pro_forma=pro_forma,
            irr_sensitivity=irr_table,
            coc_sensitivity=coc_table,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Pro Forma Builder
    # ------------------------------------------------------------------

    def _build_pro_forma(
        self, loan_amount: float, equity_invested: float
    ) -> list[ProFormaYear]:
        """Build the year-by-year operating pro forma."""
        deal = self.deal
        ops = deal.operations
        loan = deal.loan
        io_years = loan.io_period_years if loan.loan_type != LoanType.FIXED else 0

        rows: list[ProFormaYear] = []
        current_gsi = ops.gross_scheduled_income

        # Expense base values (grow at expense_growth_rate)
        current_taxes = ops.property_taxes
        current_insurance = ops.insurance
        current_maintenance = ops.maintenance_reserves
        current_capex = ops.capex_reserves
        current_utilities = ops.utilities
        current_other_exp = ops.other_expenses

        current_loan_balance = loan_amount

        for year in range(1, deal.exit.hold_period_years + 1):
            # ── Revenue ───────────────────────────────────────────────
            egi = effective_gross_income(
                current_gsi,
                ops.vacancy_rate,
                ops.credit_loss_rate,
                ops.other_income * (1 + ops.rent_growth_rate) ** (year - 1),
            )
            vacancy_loss = current_gsi * ops.vacancy_rate
            credit_loss = current_gsi * (1 - ops.vacancy_rate) * ops.credit_loss_rate
            other_inc = ops.other_income * (1 + ops.rent_growth_rate) ** (year - 1)

            # ── Expenses ──────────────────────────────────────────────
            mgmt_fee = egi * ops.management_fee_pct
            total_opex = (
                current_taxes
                + current_insurance
                + mgmt_fee
                + current_maintenance
                + current_capex
                + current_utilities
                + current_other_exp
            )
            noi = egi - total_opex

            # ── Debt Service ──────────────────────────────────────────
            ds, principal, interest = annual_debt_service(
                loan_amount,
                loan.interest_rate,
                loan.amortization_years,
                io_years=io_years,
                current_year=year,
            )

            # ── Cash Flow ─────────────────────────────────────────────
            btcf = before_tax_cash_flow(noi, ds)

            # ── Loan Balance ──────────────────────────────────────────
            current_loan_balance = loan_balance(
                loan_amount,
                loan.interest_rate,
                loan.amortization_years,
                years_elapsed=year,
                io_years=io_years,
            )

            # ── Marked-to-Market Equity Value ─────────────────────────
            # Use going-in cap rate as current cap rate for simplicity
            # In a more advanced version, this could use a time-varying cap rate
            implied_value = value_from_cap_rate(
                noi, cap_rate(ops.gross_scheduled_income * (1 - ops.vacancy_rate) - total_opex, deal.purchase_price)
            ) if deal.purchase_price > 0 else deal.purchase_price
            equity_value = implied_value - current_loan_balance

            row = ProFormaYear(
                year=year,
                gross_scheduled_income=round(current_gsi, 2),
                vacancy_loss=round(vacancy_loss, 2),
                credit_loss=round(credit_loss, 2),
                other_income=round(other_inc, 2),
                effective_gross_income=round(egi, 2),
                property_taxes=round(current_taxes, 2),
                insurance=round(current_insurance, 2),
                management_fee=round(mgmt_fee, 2),
                maintenance_reserves=round(current_maintenance, 2),
                capex_reserves=round(current_capex, 2),
                utilities=round(current_utilities, 2),
                other_expenses=round(current_other_exp, 2),
                total_operating_expenses=round(total_opex, 2),
                net_operating_income=round(noi, 2),
                debt_service=round(ds, 2),
                principal_paydown=round(principal, 2),
                interest_expense=round(interest, 2),
                before_tax_cash_flow=round(btcf, 2),
                loan_balance=round(current_loan_balance, 2),
                equity_value=round(equity_value, 2),
                noi_per_unit=round(noi / deal.units, 2) if deal.units else None,
                noi_per_sf=round(noi / deal.square_feet, 2) if deal.square_feet else None,
            )
            rows.append(row)

            # ── Grow inputs for next year ─────────────────────────────
            current_gsi *= (1 + ops.rent_growth_rate)
            current_taxes *= (1 + ops.expense_growth_rate)
            current_insurance *= (1 + ops.expense_growth_rate)
            current_maintenance *= (1 + ops.expense_growth_rate)
            current_capex *= (1 + ops.expense_growth_rate)
            current_utilities *= (1 + ops.expense_growth_rate)
            current_other_exp *= (1 + ops.expense_growth_rate)

        return rows

    # ------------------------------------------------------------------
    # Sensitivity Tables
    # ------------------------------------------------------------------

    def _irr_sensitivity(
        self,
        loan_amount: float,
        equity_invested: float,
        total_cost: float,
    ) -> SensitivityTable:
        """
        5×5 IRR sensitivity: rows = exit cap rates, cols = rent growth rates.
        """
        deal = self.deal
        ops = deal.operations
        loan = deal.loan
        exit_ = deal.exit
        io_years = loan.io_period_years if loan.loan_type != LoanType.FIXED else 0

        rent_growth_range = [
            max(0.0, ops.rent_growth_rate + delta)
            for delta in [-0.02, -0.01, 0.0, 0.01, 0.02]
        ]
        exit_cap_range = [
            max(0.01, exit_.exit_cap_rate + delta)
            for delta in [-0.01, -0.005, 0.0, 0.005, 0.01]
        ]

        def cash_flow_fn(rent_growth: float, exit_cap: float) -> list[float]:
            """Build equity cash flows for a given rent_growth and exit_cap."""
            from .models import OperatingAssumptions, ExitAssumptions
            import copy

            # Temporarily override growth and exit cap
            modified_deal = deal.model_copy(deep=True)
            modified_deal.operations.rent_growth_rate = rent_growth
            modified_deal.exit.exit_cap_rate = exit_cap

            engine = ProFormaEngine(modified_deal)
            pf = engine._build_pro_forma(loan_amount, equity_invested)

            cfs = [-equity_invested]
            for yr in pf[:-1]:
                cfs.append(yr.before_tax_cash_flow)

            # Final year
            final_noi = pf[-1].net_operating_income
            gross_price = value_from_cap_rate(final_noi, exit_cap)
            final_balance = loan_balance(
                loan_amount, loan.interest_rate, loan.amortization_years,
                years_elapsed=exit_.hold_period_years, io_years=io_years,
            )
            net_proc = net_sale_proceeds(gross_price, final_balance, exit_.selling_costs_pct)
            cfs.append(pf[-1].before_tax_cash_flow + net_proc)
            return cfs

        data = irr_sensitivity_table(cash_flow_fn, rent_growth_range, exit_cap_range)

        return SensitivityTable(
            row_label="Exit Cap Rate",
            col_label="Rent Growth",
            row_values=[round(v, 4) for v in exit_cap_range],
            col_values=[round(v, 4) for v in rent_growth_range],
            metric="levered_irr",
            data=data,
        )

    def _coc_sensitivity(
        self,
        loan_amount: float,
        equity_invested: float,
    ) -> SensitivityTable:
        """
        5×5 CoC sensitivity: rows = interest rates, cols = vacancy rates.
        """
        deal = self.deal
        ops = deal.operations
        loan = deal.loan
        io_years = loan.io_period_years if loan.loan_type != LoanType.FIXED else 0

        vacancy_range = [
            max(0.0, min(0.30, ops.vacancy_rate + delta))
            for delta in [-0.02, -0.01, 0.0, 0.01, 0.02]
        ]
        interest_range = [
            max(0.01, loan.interest_rate + delta)
            for delta in [-0.01, -0.005, 0.0, 0.005, 0.01]
        ]

        data = []
        for interest_rate in interest_range:
            row = []
            for vacancy in vacancy_range:
                try:
                    egi = effective_gross_income(
                        ops.gross_scheduled_income,
                        vacancy,
                        ops.credit_loss_rate,
                        ops.other_income,
                    )
                    mgmt = egi * ops.management_fee_pct
                    total_opex = (
                        ops.property_taxes + ops.insurance + mgmt
                        + ops.maintenance_reserves + ops.capex_reserves
                        + ops.utilities + ops.other_expenses
                    )
                    noi = egi - total_opex
                    ds, _, _ = annual_debt_service(
                        loan_amount, interest_rate, loan.amortization_years,
                        io_years=io_years, current_year=1
                    )
                    btcf = before_tax_cash_flow(noi, ds)
                    coc = btcf / equity_invested if equity_invested > 0 else 0.0
                    row.append(round(coc, 4))
                except Exception:
                    row.append(float("nan"))
            data.append(row)

        return SensitivityTable(
            row_label="Interest Rate",
            col_label="Vacancy Rate",
            row_values=[round(v, 4) for v in interest_range],
            col_values=[round(v, 4) for v in vacancy_range],
            metric="cash_on_cash_yr1",
            data=data,
        )
