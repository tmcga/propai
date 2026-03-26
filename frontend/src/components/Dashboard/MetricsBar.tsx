import { cn, fmt } from "@/lib/utils";
import type { ReturnMetrics } from "@/types";

interface Props {
  metrics: ReturnMetrics;
}

interface MetricTile {
  label: string;
  value: string;
  sub?: string;
  good?: boolean | null; // null = neutral
}

function tile(label: string, value: string, sub?: string, good?: boolean | null): MetricTile {
  return { label, value, sub, good };
}

export default function MetricsBar({ metrics: m }: Props) {
  const tiles: MetricTile[] = [
    tile(
      "Going-in Cap",
      fmt(m.going_in_cap_rate, "percent"),
      undefined,
      m.going_in_cap_rate >= 0.055 ? true : m.going_in_cap_rate < 0.04 ? false : null,
    ),
    tile(
      "Levered IRR",
      fmt(m.levered_irr, "percent"),
      `Unlev: ${fmt(m.unlevered_irr, "percent")}`,
      m.levered_irr >= 0.15 ? true : m.levered_irr < 0.08 ? false : null,
    ),
    tile(
      "Equity Multiple",
      fmt(m.equity_multiple, "multiple"),
      undefined,
      m.equity_multiple >= 1.8 ? true : m.equity_multiple < 1.2 ? false : null,
    ),
    tile(
      "DSCR (Yr 1)",
      fmt(m.dscr_yr1, "number"),
      m.dscr_yr1 >= 1.25 ? "✓ Lender min met" : "⚠ Below 1.25x",
      m.dscr_yr1 >= 1.25 ? true : false,
    ),
    tile(
      "Cash-on-Cash",
      fmt(m.cash_on_cash_yr1, "percent"),
      `Avg: ${fmt(m.avg_cash_on_cash, "percent")}`,
      m.cash_on_cash_yr1 >= 0.07 ? true : m.cash_on_cash_yr1 < 0.04 ? false : null,
    ),
    tile("GRM", fmt(m.gross_rent_multiplier, "number"), undefined, null),
    tile("Equity Required", fmt(m.equity_required, "currency"), undefined, null),
    tile("Loan Amount", fmt(m.loan_amount, "currency"), undefined, null),
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
      {tiles.map((t) => (
        <div key={t.label} className="card-sm flex flex-col gap-1">
          <span className="metric-label">{t.label}</span>
          <span
            className={cn(
              "text-xl font-bold",
              t.good === true
                ? "text-emerald-400"
                : t.good === false
                  ? "text-red-400"
                  : "text-slate-100",
            )}
          >
            {t.value}
          </span>
          {t.sub && <span className="text-xs text-slate-500">{t.sub}</span>}
        </div>
      ))}
    </div>
  );
}
