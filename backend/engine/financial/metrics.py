"""
Core real estate financial metrics.

All functions are pure — they take numbers and return numbers.
No side effects, fully testable, no dependencies on other engine modules.
"""

from __future__ import annotations

import math
from typing import Optional


# ---------------------------------------------------------------------------
# Income & Expense
# ---------------------------------------------------------------------------

def effective_gross_income(
    gross_scheduled_income: float,
    vacancy_rate: float,
    credit_loss_rate: float,
    other_income: float = 0.0,
) -> float:
    """
    EGI = GSI × (1 - vacancy) × (1 - credit_loss) + other_income

    Args:
        gross_scheduled_income: Annual rent at 100% occupancy
        vacancy_rate:           Physical vacancy as a decimal (e.g., 0.05)
        credit_loss_rate:       Bad debt / credit loss as a decimal
        other_income:           Non-rental income (parking, laundry, etc.)

    Returns:
        Effective Gross Income
    """
    collected = gross_scheduled_income * (1 - vacancy_rate) * (1 - credit_loss_rate)
    return collected + other_income


def net_operating_income(
    egi: float,
    property_taxes: float,
    insurance: float,
    management_fee_pct: float,
    maintenance_reserves: float,
    capex_reserves: float = 0.0,
    utilities: float = 0.0,
    other_expenses: float = 0.0,
) -> tuple[float, float]:
    """
    NOI = EGI - Total Operating Expenses

    Management fee is computed as a % of EGI (standard industry practice).
    CapEx reserves are included in NOI calculation per institutional convention.

    Returns:
        (noi, total_opex) tuple
    """
    management_fee = egi * management_fee_pct
    total_opex = (
        property_taxes
        + insurance
        + management_fee
        + maintenance_reserves
        + capex_reserves
        + utilities
        + other_expenses
    )
    noi = egi - total_opex
    return noi, total_opex


# ---------------------------------------------------------------------------
# Capitalization & Valuation
# ---------------------------------------------------------------------------

def cap_rate(noi: float, value: float) -> float:
    """
    Cap Rate = NOI / Value

    The most fundamental RE valuation metric — used to compare
    risk-adjusted returns across properties regardless of financing.
    """
    if value <= 0:
        raise ValueError("Property value must be positive")
    return noi / value


def value_from_cap_rate(noi: float, cap_rate_: float) -> float:
    """
    Implied Value = NOI / Cap Rate

    Useful for computing reversion (exit) value.
    """
    if cap_rate_ <= 0:
        raise ValueError("Cap rate must be positive")
    return noi / cap_rate_


def gross_rent_multiplier(purchase_price: float, gross_annual_rent: float) -> float:
    """
    GRM = Purchase Price / Gross Annual Rent

    Quick screening metric. Lower is generally better.
    Typical ranges: SFR 10–15x, multifamily 8–12x, some markets 15–20x+.
    """
    if gross_annual_rent <= 0:
        raise ValueError("Gross annual rent must be positive")
    return purchase_price / gross_annual_rent


def price_per_unit(purchase_price: float, units: int) -> float:
    """Price Per Unit — fundamental multifamily comparison metric."""
    if units <= 0:
        raise ValueError("Units must be positive")
    return purchase_price / units


def price_per_sf(purchase_price: float, square_feet: float) -> float:
    """Price Per Square Foot — fundamental commercial/SFR comparison metric."""
    if square_feet <= 0:
        raise ValueError("Square feet must be positive")
    return purchase_price / square_feet


# ---------------------------------------------------------------------------
# Debt & Coverage
# ---------------------------------------------------------------------------

def annual_debt_service(
    loan_amount: float,
    interest_rate: float,
    amortization_years: int,
    io_years: int = 0,
    current_year: int = 1,
) -> tuple[float, float, float]:
    """
    Compute annual debt service, split into principal and interest.

    Handles fixed-rate amortizing, interest-only, and IO-then-amortizing loans.

    Args:
        loan_amount:        Original loan balance
        interest_rate:      Annual interest rate (decimal)
        amortization_years: Amortization period in years
        io_years:           Number of interest-only years (0 = fully amortizing from day 1)
        current_year:       Which year of the hold period (1-indexed)

    Returns:
        (total_debt_service, principal, interest) for the given year
    """
    monthly_rate = interest_rate / 12

    if current_year <= io_years:
        # Interest-only period
        annual_interest = loan_amount * interest_rate
        return annual_interest, 0.0, annual_interest

    # Amortizing period — compute remaining balance at start of amortizing period
    # then calculate P&I payment
    if io_years > 0:
        # After IO period the balance is still the original loan amount
        # (no principal has been paid down during IO)
        remaining_balance = loan_amount
        years_remaining = amortization_years - 0  # IO doesn't reduce amort schedule
    else:
        # Fully amortizing from start — balance depends on years elapsed
        elapsed_amort_years = current_year - 1
        if monthly_rate > 0:
            remaining_balance = loan_amount * (
                (1 + monthly_rate) ** (amortization_years * 12)
                - (1 + monthly_rate) ** (elapsed_amort_years * 12)
            ) / (
                (1 + monthly_rate) ** (amortization_years * 12) - 1
            )
        else:
            remaining_balance = loan_amount * (
                1 - elapsed_amort_years / amortization_years
            )
        years_remaining = amortization_years - elapsed_amort_years

    # Monthly P&I payment on remaining balance over remaining amort schedule
    months_remaining = years_remaining * 12
    if monthly_rate > 0:
        monthly_payment = remaining_balance * (
            monthly_rate * (1 + monthly_rate) ** months_remaining
        ) / (
            (1 + monthly_rate) ** months_remaining - 1
        )
    else:
        monthly_payment = remaining_balance / months_remaining

    annual_payment = monthly_payment * 12
    annual_interest = remaining_balance * interest_rate
    annual_principal = annual_payment - annual_interest

    return annual_payment, annual_principal, annual_interest


def loan_balance(
    loan_amount: float,
    interest_rate: float,
    amortization_years: int,
    years_elapsed: int,
    io_years: int = 0,
) -> float:
    """
    Remaining loan balance after `years_elapsed` years.
    """
    monthly_rate = interest_rate / 12

    if years_elapsed <= io_years:
        return loan_amount  # No amortization during IO period

    # Amortizing elapsed years (after IO period)
    amort_years_elapsed = years_elapsed - io_years
    n_total = amortization_years * 12
    n_elapsed = amort_years_elapsed * 12

    if monthly_rate > 0:
        balance = loan_amount * (
            (1 + monthly_rate) ** n_total
            - (1 + monthly_rate) ** n_elapsed
        ) / (
            (1 + monthly_rate) ** n_total - 1
        )
    else:
        balance = loan_amount * (1 - amort_years_elapsed / amortization_years)

    return max(balance, 0.0)


def debt_service_coverage_ratio(noi: float, annual_debt_service_: float) -> float:
    """
    DSCR = NOI / Annual Debt Service

    Lenders typically require 1.20–1.25x minimum.
    Below 1.0x means the property doesn't cover its debt service.
    """
    if annual_debt_service_ <= 0:
        return float("inf")
    return noi / annual_debt_service_


# ---------------------------------------------------------------------------
# Cash Flow & Returns
# ---------------------------------------------------------------------------

def before_tax_cash_flow(noi: float, debt_service: float) -> float:
    """BTCF = NOI - Debt Service (levered operating cash flow)."""
    return noi - debt_service


def cash_on_cash_return(btcf: float, equity_invested: float) -> float:
    """
    Cash-on-Cash = BTCF / Total Equity Invested

    Measures current-year cash yield on equity. Does not account for
    appreciation or loan paydown — use IRR for total return.
    """
    if equity_invested <= 0:
        raise ValueError("Equity invested must be positive")
    return btcf / equity_invested


def operating_expense_ratio(total_opex: float, egi: float) -> float:
    """
    OER = Total Operating Expenses / EGI

    Healthy ranges: 35–45% for multifamily, 30–40% for industrial.
    """
    if egi <= 0:
        return 0.0
    return total_opex / egi


def break_even_occupancy(
    total_opex: float,
    debt_service: float,
    gross_potential_rent: float,
) -> float:
    """
    Break-Even Occupancy = (OpEx + Debt Service) / Gross Potential Rent

    The occupancy rate below which the property operates at a loss.
    """
    if gross_potential_rent <= 0:
        return 1.0
    return (total_opex + debt_service) / gross_potential_rent


# ---------------------------------------------------------------------------
# Exit / Disposition
# ---------------------------------------------------------------------------

def exit_price(exit_noi: float, exit_cap_rate_: float) -> float:
    """Reversion value = exit year NOI / exit cap rate."""
    return value_from_cap_rate(exit_noi, exit_cap_rate_)


def net_sale_proceeds(
    gross_sale_price: float,
    remaining_loan_balance: float,
    selling_costs_pct: float,
) -> float:
    """
    Net proceeds to equity after paying off loan and selling costs.

    NSP = Gross Sale Price × (1 - selling_costs) - Loan Balance
    """
    gross_after_costs = gross_sale_price * (1 - selling_costs_pct)
    return gross_after_costs - remaining_loan_balance


# ---------------------------------------------------------------------------
# Quick Sanity Checks / Flags
# ---------------------------------------------------------------------------

def generate_warnings(
    going_in_cap: float,
    dscr: float,
    ltv: float,
    vacancy_rate: float,
    rent_growth: float,
    exit_cap: float,
    going_in_cap_for_exit: float,
) -> list[str]:
    """
    Generate plain-English warnings when deal assumptions look aggressive.
    These are surfaced in the UI to flag potential underwriting issues.
    """
    warnings: list[str] = []

    if dscr < 1.0:
        warnings.append(
            f"⚠️  DSCR of {dscr:.2f}x is below 1.0 — property does not cover debt service at current assumptions."
        )
    elif dscr < 1.20:
        warnings.append(
            f"⚠️  DSCR of {dscr:.2f}x is below the typical lender minimum of 1.20x — financing may be difficult."
        )

    if ltv > 0.80:
        warnings.append(
            f"⚠️  LTV of {ltv:.0%} is above 80% — expect higher rates, PMI, or lender pushback."
        )

    if vacancy_rate < 0.03:
        warnings.append(
            f"⚠️  Vacancy rate of {vacancy_rate:.0%} is very aggressive — most markets underwrite 5–7%."
        )

    if rent_growth > 0.05:
        warnings.append(
            f"⚠️  Rent growth assumption of {rent_growth:.1%}/yr is above long-term historical averages (~3%)."
        )

    if exit_cap < going_in_cap_for_exit - 0.005:
        warnings.append(
            f"⚠️  Exit cap rate ({exit_cap:.2%}) is lower than going-in cap rate ({going_in_cap_for_exit:.2%}) — "
            f"this assumes cap rate compression, which is an aggressive bet."
        )

    if going_in_cap < 0.04:
        warnings.append(
            f"⚠️  Going-in cap rate of {going_in_cap:.2%} is very compressed — limited margin of safety."
        )

    return warnings
