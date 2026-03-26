import type { SensitivityTable } from "@/types";
import { fmt, irrHeatClass, cocHeatClass } from "@/lib/utils";

interface Props {
  table: SensitivityTable;
  formatAs: "percent" | "multiple";
}

export default function SensitivityGrid({ table, formatAs }: Props) {
  const { row_values, col_values, data } = table;
  const isIRR = table.metric === "irr";

  function heatClass(val: number): string {
    return isIRR ? irrHeatClass(val) : cocHeatClass(val);
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs min-w-[480px]">
        <thead>
          <tr>
            <th className="text-left py-1.5 pr-3 text-slate-500 font-medium">
              Exit Cap ↓ / Rent Growth →
            </th>
            {col_values.map((cv) => (
              <th key={cv} className="text-right py-1.5 px-2 text-slate-400 font-medium">
                {fmt(cv, "percent", 1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {row_values.map((rv, ri) => (
            <tr key={rv}>
              <td className="py-1.5 pr-3 text-slate-400 font-medium">
                {fmt(rv, "percent", 2)}
              </td>
              {col_values.map((cv, ci) => {
                const val = data[ri][ci];
                return (
                  <td
                    key={ci}
                    className={`text-right py-1.5 px-2 rounded font-mono font-semibold ${heatClass(val)}`}
                  >
                    {fmt(val, "percent", 1)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-4 pt-3 border-t border-navy-800">
        <span className="text-xs text-slate-600">Return quality:</span>
        {[
          { cls: "heat-hot", label: "≥20%" },
          { cls: "heat-warm", label: "15–20%" },
          { cls: "heat-neutral", label: "10–15%" },
          { cls: "heat-cool", label: "5–10%" },
          { cls: "heat-cold", label: "<5%" },
        ].map(({ cls, label }) => (
          <span key={cls} className={`text-xs px-2 py-0.5 rounded ${cls}`}>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
