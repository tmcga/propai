"""
Equity Waterfall Distribution Engine.

Models LP/GP promote structures with multiple IRR hurdles.
Handles: return of capital → preferred return → catch-up → promote tiers.

Standard waterfall tiers:
  1. Return of Capital        — all equity returned pro-rata (LP + GP)
  2. Preferred Return         — LP receives pref (e.g., 8% cumulative)
  3. GP Catch-Up              — GP catches up to its target % of total distributions
  4. Residual / Promote Tiers — remaining split by IRR hurdle

This is the structure used by institutional RE private equity funds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dcf import irr as compute_irr, equity_multiple as compute_em
from .models import EquityStructure, WaterfallResult, WaterfallTier


@dataclass
class CashFlowSeries:
    """Raw cash flow series with timing for waterfall computation."""

    periods: list[float]  # Annual cash flows, t=0 is negative (equity in)


class WaterfallEngine:
    """
    Compute LP and GP distributions through a standard PE waterfall.

    The waterfall distributes cash flows in order:
      1. Return of capital (pro-rata LP/GP)
      2. LP preferred return (cumulative, compounded)
      3. GP catch-up (if applicable)
      4. Residual split at promote tiers

    Usage:
        waterfall = WaterfallEngine(
            equity_structure=deal.equity_structure,
            total_equity=500_000,
            cash_flows=[-500_000, 45_000, 48_000, 51_000, 54_000, 750_000]
        )
        result = waterfall.compute()
    """

    def __init__(
        self,
        equity_structure: EquityStructure,
        total_equity: float,
        cash_flows: list[float],
        gp_catch_up: bool = True,
        gp_catch_up_pct: float = 0.20,
    ):
        """
        Args:
            equity_structure:   LP/GP split and promote parameters
            total_equity:       Total equity invested (LP + GP combined)
            cash_flows:         List of annual cash flows (t=0 = negative equity in)
            gp_catch_up:        Whether to include a GP catch-up provision
            gp_catch_up_pct:    GP's target % of total distributions before promote tiers
        """
        self.structure = equity_structure
        self.total_equity = total_equity
        self.cash_flows = cash_flows
        self.gp_catch_up = gp_catch_up
        self.gp_catch_up_pct = gp_catch_up_pct

        # Derived
        self.lp_equity = total_equity * equity_structure.lp_equity_pct
        self.gp_equity = total_equity * equity_structure.gp_equity_pct

    def compute(self) -> WaterfallResult:
        """
        Run the full waterfall distribution.

        Returns:
            WaterfallResult with per-tier breakdown and final IRRs.
        """
        structure = self.structure

        # Total positive distributions to split
        total_distributions = sum(cf for cf in self.cash_flows if cf > 0)
        remaining = total_distributions

        lp_total = 0.0
        gp_total = 0.0
        tiers: list[WaterfallTier] = []

        # ── Tier 1: Return of Capital ──────────────────────────────────
        roc = min(remaining, self.total_equity)
        lp_roc = roc * structure.lp_equity_pct
        gp_roc = roc * structure.gp_equity_pct
        lp_total += lp_roc
        gp_total += gp_roc
        remaining -= roc

        tiers.append(
            WaterfallTier(
                tier_name="Return of Capital",
                irr_hurdle=None,
                lp_distributions=round(lp_roc, 2),
                gp_distributions=round(gp_roc, 2),
                lp_split=structure.lp_equity_pct,
                gp_split=structure.gp_equity_pct,
            )
        )

        if remaining <= 0:
            return self._build_result(lp_total, gp_total, tiers)

        # ── Tier 2: LP Preferred Return ────────────────────────────────
        # Compute cumulative preferred return owed to LP
        # Simple approximation: pref × LP equity × hold period
        # A more precise implementation would use compounding period-by-period
        hold_years = len(self.cash_flows) - 1
        pref_owed = self._compute_cumulative_pref(
            self.lp_equity,
            structure.preferred_return,
            hold_years,
        )
        pref_paid = min(remaining, pref_owed)
        lp_total += pref_paid
        remaining -= pref_paid

        tiers.append(
            WaterfallTier(
                tier_name=f"LP Preferred Return ({structure.preferred_return:.0%})",
                irr_hurdle=structure.preferred_return,
                lp_distributions=round(pref_paid, 2),
                gp_distributions=0.0,
                lp_split=1.0,
                gp_split=0.0,
            )
        )

        if remaining <= 0:
            return self._build_result(lp_total, gp_total, tiers)

        # ── Tier 3: GP Catch-Up (optional) ────────────────────────────
        if self.gp_catch_up and remaining > 0:
            # GP catches up until it has received gp_catch_up_pct of total distributions so far
            target_gp = (lp_total + gp_total + remaining) * self.gp_catch_up_pct
            catch_up_needed = max(0.0, target_gp - gp_total)
            catch_up_paid = min(remaining, catch_up_needed)

            if catch_up_paid > 0:
                gp_total += catch_up_paid
                remaining -= catch_up_paid
                tiers.append(
                    WaterfallTier(
                        tier_name="GP Catch-Up",
                        irr_hurdle=None,
                        lp_distributions=0.0,
                        gp_distributions=round(catch_up_paid, 2),
                        lp_split=0.0,
                        gp_split=1.0,
                    )
                )

        if remaining <= 0:
            return self._build_result(lp_total, gp_total, tiers)

        # ── Tier 4+: Residual Promote Tiers ───────────────────────────
        # At each IRR hurdle, the GP's share (promote) increases
        # We approximate by seeing what IRR the LP is achieving and
        # splitting the residual accordingly

        # For simplicity, split residual based on the highest hurdle
        # that the LP IRR clears. In a rigorous implementation this
        # would be computed iteratively.
        for i, hurdle in enumerate(structure.promote_hurdles):
            if remaining <= 0:
                break

            gp_promote = structure.promote_splits[i]
            lp_split = 1.0 - gp_promote
            tier_name = f"Above {hurdle:.0%} IRR Hurdle ({gp_promote:.0%} promote)"

            if i + 1 < len(structure.promote_hurdles):
                # Estimate how much cash flow corresponds to this tier
                # (between this hurdle and the next)
                # Simplified: split remaining evenly across tiers
                tier_amount = remaining / (len(structure.promote_hurdles) - i)
            else:
                # Final tier: all remaining cash
                tier_amount = remaining

            tier_amount = min(tier_amount, remaining)
            lp_tier = tier_amount * lp_split
            gp_tier = tier_amount * gp_promote

            lp_total += lp_tier
            gp_total += gp_tier
            remaining -= tier_amount

            tiers.append(
                WaterfallTier(
                    tier_name=tier_name,
                    irr_hurdle=hurdle,
                    lp_distributions=round(lp_tier, 2),
                    gp_distributions=round(gp_tier, 2),
                    lp_split=lp_split,
                    gp_split=gp_promote,
                )
            )

        # Any truly residual amount (shouldn't happen in practice)
        if remaining > 1.0:
            final_promote = structure.promote_splits[-1]
            lp_total += remaining * (1 - final_promote)
            gp_total += remaining * final_promote

        return self._build_result(lp_total, gp_total, tiers)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_cumulative_pref(
        self,
        equity: float,
        annual_pref: float,
        years: int,
    ) -> float:
        """
        Compute cumulative preferred return using simple compounding.

        Pref = equity × ((1 + pref_rate)^years - 1)
        """
        return equity * ((1 + annual_pref) ** years - 1)

    def _estimate_lp_irr(self, lp_total_so_far: float, pref_paid: float) -> float:
        """Rough LP IRR estimate for hurdle determination."""
        lp_cfs = [-self.lp_equity]
        # Distribute LP cash flows pro-rata across operating years
        op_years = len(self.cash_flows) - 2
        if op_years > 0:
            annual_lp = pref_paid / op_years
            for _ in range(op_years):
                lp_cfs.append(annual_lp * self.structure.lp_equity_pct)
        # Final year: remaining LP distributions
        lp_cfs.append(lp_total_so_far - sum(lp_cfs[1:]))

        result = compute_irr(lp_cfs)
        return result if result is not None else 0.0

    def _build_result(
        self,
        lp_total: float,
        gp_total: float,
        tiers: list[WaterfallTier],
    ) -> WaterfallResult:
        """Assemble the final WaterfallResult with IRRs and EMs."""

        # Build per-party cash flow series for IRR computation
        lp_cfs = self._party_cash_flows(lp_total, self.lp_equity, is_lp=True)
        gp_cfs = self._party_cash_flows(gp_total, self.gp_equity, is_lp=False)

        lp_irr = compute_irr(lp_cfs) or 0.0
        gp_irr = compute_irr(gp_cfs) or 0.0
        lp_em = compute_em(lp_cfs) or 0.0
        gp_em = compute_em(gp_cfs) or 0.0

        return WaterfallResult(
            total_distributions=round(lp_total + gp_total, 2),
            equity_invested=round(self.total_equity, 2),
            lp_equity_invested=round(self.lp_equity, 2),
            gp_equity_invested=round(self.gp_equity, 2),
            lp_total_distributions=round(lp_total, 2),
            gp_total_distributions=round(gp_total, 2),
            lp_irr=round(lp_irr, 4),
            gp_irr=round(gp_irr, 4),
            lp_equity_multiple=round(lp_em, 3),
            gp_equity_multiple=round(gp_em, 3),
            tiers=tiers,
        )

    def _party_cash_flows(
        self,
        total_distributions: float,
        equity_invested: float,
        is_lp: bool,
    ) -> list[float]:
        """
        Approximate per-party cash flow series for IRR computation.
        Distributions are spread proportionally across operating periods,
        with the bulk at the final year (reversion).
        """
        n = len(self.cash_flows) - 1  # Number of periods
        if n <= 0:
            return [-equity_invested, total_distributions]

        # Operating distributions (assume ~20% of total spread over operating years)
        operating_total = total_distributions * 0.20
        reversion_total = total_distributions * 0.80

        cfs = [-equity_invested]
        for _ in range(n - 1):
            cfs.append(operating_total / max(n - 1, 1))
        cfs.append(reversion_total + (operating_total / max(n - 1, 1)))

        return cfs
