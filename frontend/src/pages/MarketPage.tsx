import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Loader2, Search, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import MacroSnapshot from "@/components/Dashboard/MacroSnapshot";
import { getMetroMarket, getZipMarket } from "@/lib/api";
import { fmt, gradeColor } from "@/lib/utils";

export default function MarketPage() {
  const [query, setQuery] = useState("");
  const [queryType, setQueryType] = useState<"metro" | "zip">("metro");

  const mutation = useMutation({
    mutationFn: () =>
      queryType === "zip" ? getZipMarket(query.trim()) : getMetroMarket(query.trim()),
  });

  const report = mutation.data;

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in">
      {/* Search */}
      <div className="card space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100 mb-1">Market Intelligence</h2>
          <p className="text-sm text-slate-400">
            Pull demographics, macroeconomic data, HUD fair market rents, and Zillow trends for any
            US market.
          </p>
        </div>

        <div className="flex gap-3">
          <div className="flex rounded-lg border border-navy-700 overflow-hidden text-sm shrink-0">
            {(["metro", "zip"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setQueryType(t)}
                className={`px-3 py-2 font-medium transition-colors capitalize ${
                  queryType === t
                    ? "bg-navy-700 text-slate-200"
                    : "text-slate-500 hover:text-slate-300 hover:bg-navy-800"
                }`}
              >
                {t === "zip" ? "ZIP Code" : "Metro"}
              </button>
            ))}
          </div>

          <div className="flex gap-2 flex-1">
            <input
              className="input flex-1"
              placeholder={queryType === "zip" ? "78701" : "Austin, TX"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && query.trim() && mutation.mutate()}
            />
            <button
              className="btn-primary shrink-0"
              disabled={!query.trim() || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              Search
            </button>
          </div>
        </div>

        {mutation.isError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            {(mutation.error as Error).message}
          </div>
        )}
      </div>

      {report && (
        <div className="space-y-6 animate-slide-up">
          {/* Market Score */}
          <div className="card">
            <div className="flex items-start justify-between mb-6">
              <div>
                <h3 className="text-lg font-bold text-slate-100">
                  {report.metro ?? report.zipcode}
                </h3>
                <p className="text-sm text-slate-400 mt-1 max-w-2xl leading-relaxed">
                  {report.market_thesis}
                </p>
              </div>
              <div className="text-right shrink-0 ml-6">
                <div className={`text-5xl font-bold ${gradeColor(report.market_grade)}`}>
                  {report.market_grade}
                </div>
                <div className="text-xs text-slate-500 mt-1">Market Grade</div>
                <div className="text-2xl font-semibold text-slate-300 mt-1">
                  {report.market_score}/100
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h4 className="text-xs font-semibold text-emerald-500 uppercase tracking-wider mb-2">
                  Tailwinds
                </h4>
                <ul className="space-y-1.5">
                  {report.tailwinds?.map((t, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                      <TrendingUp className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">
                  Headwinds
                </h4>
                <ul className="space-y-1.5">
                  {report.headwinds?.map((h, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                      <TrendingDown className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
                      {h}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-4 pt-4 border-t border-navy-800 grid grid-cols-2 gap-4">
              <div>
                <span className="metric-label">Suggested Rent Growth</span>
                <p className="text-xl font-bold text-slate-100 mt-1">
                  {fmt(report.suggested_rent_growth, "percent", 1)}/yr
                </p>
              </div>
              <div>
                <span className="metric-label">Suggested Exit Cap Range</span>
                <p className="text-xl font-bold text-slate-100 mt-1">
                  {report.suggested_exit_cap_range
                    ? `${fmt(report.suggested_exit_cap_range[0], "percent", 2)} – ${fmt(report.suggested_exit_cap_range[1], "percent", 2)}`
                    : "—"}
                </p>
              </div>
            </div>
          </div>

          {/* Demographics */}
          {report.demographics && (
            <div className="card">
              <h3 className="section-header">Demographics</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {[
                  {
                    label: "Population",
                    value: report.demographics.total_population?.toLocaleString(),
                  },
                  {
                    label: "Median HH Income",
                    value: fmt(report.demographics.median_household_income, "currency"),
                  },
                  {
                    label: "Median Gross Rent",
                    value: fmt(report.demographics.median_gross_rent, "currency"),
                  },
                  {
                    label: "Vacancy Rate",
                    value: fmt(report.demographics.vacancy_rate, "percent"),
                  },
                  {
                    label: "Homeownership Rate",
                    value: fmt(report.demographics.homeownership_rate, "percent"),
                  },
                  {
                    label: "Rent-to-Income Ratio",
                    value: fmt(report.demographics.rent_to_income_ratio, "percent"),
                  },
                ].map(({ label, value }) => (
                  <div key={label} className="card-sm">
                    <span className="metric-label">{label}</span>
                    <p className="text-lg font-semibold text-slate-200 mt-1">{value ?? "—"}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Rent Benchmarks */}
          {report.rent_benchmarks && (
            <div className="card">
              <h3 className="section-header">Rent Benchmarks</h3>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {[
                  ["Studio", report.rent_benchmarks.studio_fmr],
                  ["1BR", report.rent_benchmarks.one_br_fmr],
                  ["2BR", report.rent_benchmarks.two_br_fmr],
                  ["3BR", report.rent_benchmarks.three_br_fmr],
                  ["4BR", report.rent_benchmarks.four_br_fmr],
                ].map(([label, val]) => (
                  <div key={label as string} className="card-sm text-center">
                    <span className="metric-label">{label as string}</span>
                    <p className="text-xl font-bold text-slate-100 mt-1">
                      {val ? fmt(val as number, "currency") : "—"}
                    </p>
                    <p className="text-xs text-slate-500">FMR/mo</p>
                  </div>
                ))}
              </div>
              {report.rent_benchmarks.rent_yoy_pct != null && (
                <p className="text-xs text-slate-500 mt-3">
                  Zillow median asking rent:{" "}
                  <span className="text-slate-300 font-medium">
                    {fmt(report.rent_benchmarks.median_asking_rent ?? 0, "currency")}/mo
                  </span>{" "}
                  · YoY:{" "}
                  <span className="text-emerald-400 font-medium">
                    {fmt(report.rent_benchmarks.rent_yoy_pct, "percent", 1)}
                  </span>
                </p>
              )}
            </div>
          )}

          {/* Macro */}
          {report.macro && <MacroSnapshot macro={report.macro} />}
        </div>
      )}
    </div>
  );
}
