"""
Discounted Cash Flow engine.

Computes IRR, NPV, equity multiple, and related return metrics from
a series of periodic cash flows. Uses Newton-Raphson for IRR so
there is no dependency on numpy-financial (keeping the engine portable).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional


# ---------------------------------------------------------------------------
# Core DCF Functions
# ---------------------------------------------------------------------------


def npv(discount_rate: float, cash_flows: list[float]) -> float:
    """
    Net Present Value.

    NPV = Σ  CF_t / (1 + r)^t   for t = 0, 1, 2, ..., n

    cash_flows[0] is the Year 0 cash flow (typically negative = equity invested).

    Args:
        discount_rate:  Annual discount rate (decimal, e.g., 0.08)
        cash_flows:     List of annual cash flows, starting at t=0

    Returns:
        Net present value in dollars
    """
    return sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows))


def irr(
    cash_flows: list[float],
    guess: float = 0.10,
    tolerance: float = 1e-8,
    max_iterations: int = 1000,
) -> Optional[float]:
    """
    Internal Rate of Return via Newton-Raphson iteration.

    IRR is the discount rate at which NPV = 0.

    Args:
        cash_flows:     List of annual cash flows (t=0 is typically negative)
        guess:          Initial IRR guess (default 10%)
        tolerance:      Convergence tolerance
        max_iterations: Maximum Newton-Raphson iterations

    Returns:
        IRR as a decimal, or None if no solution is found.

    Raises:
        ValueError: If cash flows don't have at least one sign change.
    """
    # Validate: need at least one sign change for IRR to exist
    has_negative = any(cf < 0 for cf in cash_flows)
    has_positive = any(cf > 0 for cf in cash_flows)
    if not (has_negative and has_positive):
        return None

    rate = guess

    for _ in range(max_iterations):
        # f(r) = NPV
        f = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))

        # f'(r) = dNPV/dr  = Σ -t × CF_t / (1 + r)^(t+1)
        f_prime = sum(
            -t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows) if t > 0
        )

        if abs(f_prime) < 1e-12:
            # Derivative too small — try a different starting point
            rate = guess * 1.5
            continue

        new_rate = rate - f / f_prime

        # Guard against divergence
        if new_rate < -0.999:
            new_rate = -0.999

        if abs(new_rate - rate) < tolerance:
            return new_rate

        rate = new_rate

    # Try alternate starting points if initial guess fails
    for alt_guess in [0.05, 0.15, 0.20, 0.25, 0.30, -0.05]:
        result = _irr_attempt(cash_flows, alt_guess, tolerance, max_iterations)
        if result is not None:
            return result

    return None


def _irr_attempt(
    cash_flows: list[float],
    guess: float,
    tolerance: float,
    max_iterations: int,
) -> Optional[float]:
    """Single Newton-Raphson attempt from a given starting guess."""
    rate = guess
    for _ in range(max_iterations):
        f = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))
        f_prime = sum(
            -t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows) if t > 0
        )
        if abs(f_prime) < 1e-12:
            return None
        new_rate = rate - f / f_prime
        if new_rate < -0.999:
            return None
        if abs(new_rate - rate) < tolerance:
            return new_rate
        rate = new_rate
    return None


def equity_multiple(cash_flows: list[float]) -> Optional[float]:
    """
    Equity Multiple (EM) = Total Distributions / Total Equity Invested

    EM > 1.0 means you got your money back and more.
    EM of 2.0 = doubled your money (regardless of time).

    Args:
        cash_flows: List of cash flows where negative values = capital invested
                    and positive values = distributions received.

    Returns:
        Equity multiple, or None if no capital was invested.
    """
    invested = sum(-cf for cf in cash_flows if cf < 0)
    received = sum(cf for cf in cash_flows if cf > 0)

    if invested <= 0:
        return None

    return received / invested


def total_profit(cash_flows: list[float]) -> float:
    """Total profit = sum of all cash flows (positive + negative)."""
    return sum(cash_flows)


def average_cash_on_cash(
    annual_btcf: list[float],
    equity_invested: float,
) -> float:
    """
    Average annual cash-on-cash return over the hold period.

    Excludes Year 0 (acquisition) and the final year reversion.
    Useful for understanding the ongoing income yield of the investment.
    """
    if not annual_btcf or equity_invested <= 0:
        return 0.0
    annual_coc = [btcf / equity_invested for btcf in annual_btcf]
    return sum(annual_coc) / len(annual_coc)


# ---------------------------------------------------------------------------
# Sensitivity Analysis
# ---------------------------------------------------------------------------


def irr_sensitivity_table(
    base_cash_flow_fn: Callable[[float, float], list[float]],
    rent_growth_range: list[float],
    exit_cap_range: list[float],
) -> list[list[float]]:
    """
    Generate a 2D IRR sensitivity table.

    Rows = exit cap rates, Columns = rent growth rates.

    Args:
        base_cash_flow_fn:  Function that takes (rent_growth, exit_cap) and
                            returns a list of cash flows for IRR calculation.
        rent_growth_range:  List of rent growth rates to test (e.g., [0.01, 0.02, 0.03, 0.04, 0.05])
        exit_cap_range:     List of exit cap rates to test (e.g., [0.05, 0.055, 0.06, 0.065, 0.07])

    Returns:
        2D list [row=exit_cap][col=rent_growth] of IRR values
    """
    table = []
    for exit_cap in exit_cap_range:
        row = []
        for rent_growth in rent_growth_range:
            try:
                cfs = base_cash_flow_fn(rent_growth, exit_cap)
                irr_val = irr(cfs)
                row.append(round(irr_val, 4) if irr_val is not None else float("nan"))
            except Exception:
                row.append(float("nan"))
        table.append(row)
    return table


def coc_sensitivity_table(
    base_cash_flow_fn: Callable[[float, float], tuple[float, float]],
    rent_growth_range: list[float],
    interest_rate_range: list[float],
) -> list[list[float]]:
    """
    Generate a 2D cash-on-cash sensitivity table.

    Rows = interest rates, Columns = rent growth rates.
    """
    table = []
    for interest_rate in interest_rate_range:
        row = []
        for rent_growth in rent_growth_range:
            try:
                btcf, equity = base_cash_flow_fn(rent_growth, interest_rate)
                coc = btcf / equity if equity > 0 else float("nan")
                row.append(round(coc, 4))
            except Exception:
                row.append(float("nan"))
        table.append(row)
    return table


# ---------------------------------------------------------------------------
# Unlevered (Asset-Level) vs Levered (Equity-Level) Returns
# ---------------------------------------------------------------------------


class DCFEngine:
    """
    Wraps cash flow lists with IRR/NPV/EM computation.
    Handles both levered (equity) and unlevered (asset) return analysis.
    """

    def __init__(
        self,
        equity_cash_flows: list[float],
        asset_cash_flows: list[float],
        discount_rate: float = 0.08,
    ):
        """
        Args:
            equity_cash_flows:  Levered cash flows (equity perspective).
                                t=0: -(equity invested)
                                t=1..N-1: BTCF (NOI - debt service)
                                t=N: BTCF + net sale proceeds

            asset_cash_flows:   Unlevered cash flows (asset perspective, no debt).
                                t=0: -(total project cost)
                                t=1..N-1: NOI
                                t=N: NOI + gross sale proceeds - selling costs

            discount_rate:      Discount rate for NPV (typically WACC or hurdle rate)
        """
        self.equity_cash_flows = equity_cash_flows
        self.asset_cash_flows = asset_cash_flows
        self.discount_rate = discount_rate

    @property
    def levered_irr(self) -> Optional[float]:
        """Equity-level (levered) IRR."""
        return irr(self.equity_cash_flows)

    @property
    def unlevered_irr(self) -> Optional[float]:
        """Asset-level (unlevered) IRR — measures property performance independent of financing."""
        return irr(self.asset_cash_flows)

    @property
    def levered_npv(self) -> float:
        """Equity NPV at the given discount rate."""
        return npv(self.discount_rate, self.equity_cash_flows)

    @property
    def unlevered_npv(self) -> float:
        """Asset NPV at the given discount rate."""
        return npv(self.discount_rate, self.asset_cash_flows)

    @property
    def equity_multiple(self) -> Optional[float]:
        """Equity multiple on invested capital."""
        return equity_multiple(self.equity_cash_flows)

    @property
    def total_equity_profit(self) -> float:
        """Net profit in dollars on the equity investment."""
        return total_profit(self.equity_cash_flows)

    @property
    def average_coc(self) -> float:
        """Average cash-on-cash excluding acquisition and reversion years."""
        if len(self.equity_cash_flows) < 3:
            return 0.0
        equity_invested = abs(self.equity_cash_flows[0])
        operating_cfs = self.equity_cash_flows[1:-1]  # Exclude t=0 and final year
        return average_cash_on_cash(operating_cfs, equity_invested)

    def summary(self) -> dict[str, object]:
        """Return all key DCF metrics as a dictionary."""
        l_irr = self.levered_irr
        ul_irr = self.unlevered_irr
        em = self.equity_multiple

        return {
            "levered_irr": round(l_irr, 4) if l_irr is not None else None,
            "unlevered_irr": round(ul_irr, 4) if ul_irr is not None else None,
            "levered_npv": round(self.levered_npv, 2),
            "unlevered_npv": round(self.unlevered_npv, 2),
            "equity_multiple": round(em, 3) if em is not None else None,
            "total_equity_profit": round(self.total_equity_profit, 2),
            "average_cash_on_cash": round(self.average_coc, 4),
        }
