import type { MacroSnapshot as MacroSnapshotType } from "@/types";
import { fmt } from "@/lib/utils";

interface Props {
  macro: MacroSnapshotType;
}

export default function MacroSnapshot({ macro: m }: Props) {
  return (
    <div className="card">
      <div className="flex items-start justify-between mb-4">
        <h3 className="section-header mb-0">Macroeconomic Snapshot</h3>
        <div className="text-right">
          <p className="text-xs text-slate-500">{m.rate_environment}</p>
          <p className="text-xs text-slate-500 mt-0.5">{m.cap_rate_pressure}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "30yr Mortgage", value: fmt(m.mortgage_rate_30yr, "percent", 2) },
          { label: "Fed Funds Rate", value: fmt(m.fed_funds_rate, "percent", 2) },
          { label: "CPI (YoY)", value: fmt(m.cpi_yoy, "percent", 1) },
          { label: "Unemployment", value: fmt(m.unemployment_rate, "percent", 1) },
          { label: "GDP Growth", value: fmt(m.gdp_growth, "percent", 1) },
          { label: "10yr Treasury", value: fmt(m.treasury_10yr, "percent", 2) },
          { label: "Housing Starts", value: `${(m.housing_starts / 1000).toFixed(0)}K` },
        ].map(({ label, value }) => (
          <div key={label} className="card-sm">
            <span className="metric-label">{label}</span>
            <p className="text-lg font-semibold text-slate-200 mt-1">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
