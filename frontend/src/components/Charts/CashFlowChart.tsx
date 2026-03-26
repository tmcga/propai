import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { ProFormaYear } from "@/types";
import { fmt } from "@/lib/utils";

interface Props {
  data: ProFormaYear[];
}

const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; color: string; value: number }>; label?: string }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-navy-800 border border-navy-700 rounded-lg p-3 text-xs space-y-1 shadow-xl">
      <p className="font-semibold text-slate-200 mb-2">Year {label}</p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-6">
          <span style={{ color: p.color }} className="text-slate-300">{p.name}</span>
          <span className="font-mono font-semibold" style={{ color: p.color }}>
            {fmt(p.value, "currency")}
          </span>
        </div>
      ))}
    </div>
  );
};

export default function CashFlowChart({ data }: Props) {
  const chartData = data.map((yr) => ({
    year: yr.year,
    NOI: yr.net_operating_income,
    "Debt Service": yr.debt_service,
    "Cash Flow": yr.before_tax_cash_flow,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={chartData} margin={{ top: 4, right: 16, bottom: 4, left: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#243b53" />
        <XAxis
          dataKey="year"
          tick={{ fill: "#627d98", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => `Yr ${v}`}
        />
        <YAxis
          tick={{ fill: "#627d98", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => fmt(v, "currency")}
          width={70}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: "#829ab1" }}
          iconSize={8}
        />
        <Bar dataKey="NOI" fill="#10b981" fillOpacity={0.6} radius={[3, 3, 0, 0]} />
        <Bar dataKey="Debt Service" fill="#334e68" fillOpacity={0.8} radius={[3, 3, 0, 0]} />
        <Line
          type="monotone"
          dataKey="Cash Flow"
          stroke="#e6b800"
          strokeWidth={2}
          dot={{ fill: "#e6b800", r: 3 }}
          activeDot={{ r: 5 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
