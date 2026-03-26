import type { ProFormaYear } from "@/types";
import { fmt } from "@/lib/utils";

interface Props {
  data: ProFormaYear[];
}

const rows: Array<{ key: keyof ProFormaYear; label: string; style?: string }> = [
  { key: "gross_scheduled_income", label: "Gross Scheduled Income" },
  { key: "vacancy_credit_loss", label: "  (–) Vacancy & Credit Loss" },
  { key: "other_income", label: "  (+) Other Income" },
  { key: "effective_gross_income", label: "Effective Gross Income", style: "font-semibold border-t border-navy-700" },
  { key: "operating_expenses", label: "  (–) Operating Expenses" },
  { key: "net_operating_income", label: "Net Operating Income", style: "font-semibold text-emerald-400 border-t border-navy-700" },
  { key: "debt_service", label: "  (–) Debt Service" },
  { key: "before_tax_cash_flow", label: "Before-Tax Cash Flow", style: "font-semibold text-blue-400 border-t border-navy-700" },
  { key: "coc_return", label: "  Cash-on-Cash Return" },
  { key: "loan_balance", label: "Remaining Loan Balance" },
];

export default function ProFormaTable({ data }: Props) {
  return (
    <table className="w-full text-sm min-w-[640px]">
      <thead>
        <tr className="border-b border-navy-700">
          <th className="text-left py-2 pr-4 text-slate-400 font-medium text-xs uppercase tracking-wider w-56">
            Line Item
          </th>
          {data.map((yr) => (
            <th key={yr.year} className="text-right py-2 px-2 text-slate-400 font-medium text-xs uppercase tracking-wider">
              Year {yr.year}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ key, label, style }) => (
          <tr key={key} className={`border-b border-navy-800/60 hover:bg-navy-800/30 ${style ?? ""}`}>
            <td className="py-2 pr-4 text-slate-300 text-xs">{label}</td>
            {data.map((yr) => {
              const val = yr[key] as number;
              const isPercent = key === "coc_return" || key === "noi_margin";
              return (
                <td key={yr.year} className="text-right py-2 px-2 font-mono text-xs text-slate-200">
                  {isPercent ? fmt(val, "percent") : fmt(val, "currency")}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
