import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, AlertCircle } from "lucide-react";
import type { DealInput } from "@/types";
import { ASSET_CLASS_LABELS, LOAN_TYPE_LABELS } from "@/lib/utils";

const schema = z.object({
  name: z.string().min(1, "Deal name required"),
  asset_class: z.string(),
  purchase_price: z.coerce.number().positive(),
  units: z.coerce.number().positive().optional(),
  square_feet: z.coerce.number().positive().optional(),
  market: z.string().min(1, "Market required"),
  closing_costs: z.coerce.number().min(0).max(0.1).default(0.01),
  immediate_capex: z.coerce.number().min(0).default(0),
  // Loan
  loan_ltv: z.coerce.number().min(0).max(0.95).default(0.70),
  loan_interest_rate: z.coerce.number().min(0).max(0.20).default(0.0675),
  loan_amortization_years: z.coerce.number().default(30),
  loan_type: z.string().default("fixed"),
  loan_origination_fee: z.coerce.number().min(0).max(0.05).default(0.01),
  // Operations
  gross_scheduled_income: z.coerce.number().positive(),
  vacancy_rate: z.coerce.number().min(0).max(0.5).default(0.05),
  other_income: z.coerce.number().min(0).default(0),
  property_taxes: z.coerce.number().min(0),
  insurance: z.coerce.number().min(0),
  management_fee_pct: z.coerce.number().min(0).max(0.20).default(0.05),
  maintenance_reserves: z.coerce.number().min(0).default(0),
  capex_reserves: z.coerce.number().min(0).default(0),
  utilities: z.coerce.number().min(0).default(0),
  other_expenses: z.coerce.number().min(0).default(0),
  rent_growth_rate: z.coerce.number().min(-0.1).max(0.2).default(0.03),
  expense_growth_rate: z.coerce.number().min(-0.1).max(0.2).default(0.02),
  // Exit
  hold_period_years: z.coerce.number().int().min(1).max(30).default(5),
  exit_cap_rate: z.coerce.number().min(0.01).max(0.20).default(0.055),
  selling_costs_pct: z.coerce.number().min(0).max(0.10).default(0.03),
  discount_rate: z.coerce.number().min(0.01).max(0.30).default(0.08),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  onSubmit: (deal: DealInput) => void;
  isLoading: boolean;
  error?: string;
  defaultValues?: Partial<FormValues>;
}

export default function DealForm({ onSubmit, isLoading, error, defaultValues }: Props) {
  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      asset_class: "multifamily",
      closing_costs: 0.01,
      immediate_capex: 0,
      loan_ltv: 0.70,
      loan_interest_rate: 0.0675,
      loan_amortization_years: 30,
      loan_type: "fixed",
      loan_origination_fee: 0.01,
      vacancy_rate: 0.05,
      other_income: 0,
      management_fee_pct: 0.05,
      rent_growth_rate: 0.03,
      expense_growth_rate: 0.02,
      hold_period_years: 5,
      exit_cap_rate: 0.055,
      selling_costs_pct: 0.03,
      discount_rate: 0.08,
      ...defaultValues,
    },
  });

  function transform(values: FormValues): DealInput {
    return {
      name: values.name,
      asset_class: values.asset_class as DealInput["asset_class"],
      purchase_price: values.purchase_price,
      units: values.units,
      square_feet: values.square_feet,
      market: values.market,
      closing_costs: values.closing_costs,
      immediate_capex: values.immediate_capex,
      loan: {
        ltv: values.loan_ltv,
        interest_rate: values.loan_interest_rate,
        amortization_years: values.loan_amortization_years,
        loan_type: values.loan_type as DealInput["loan"]["loan_type"],
        origination_fee: values.loan_origination_fee,
      },
      operations: {
        gross_scheduled_income: values.gross_scheduled_income,
        vacancy_rate: values.vacancy_rate,
        credit_loss_rate: 0.005,
        other_income: values.other_income,
        property_taxes: values.property_taxes,
        insurance: values.insurance,
        management_fee_pct: values.management_fee_pct,
        maintenance_reserves: values.maintenance_reserves,
        capex_reserves: values.capex_reserves,
        utilities: values.utilities,
        other_expenses: values.other_expenses,
        rent_growth_rate: values.rent_growth_rate,
        expense_growth_rate: values.expense_growth_rate,
      },
      exit: {
        hold_period_years: values.hold_period_years,
        exit_cap_rate: values.exit_cap_rate,
        selling_costs_pct: values.selling_costs_pct,
        discount_rate: values.discount_rate,
      },
    };
  }

  return (
    <form onSubmit={handleSubmit((v) => onSubmit(transform(v)))} className="space-y-6">
      {/* Property */}
      <div className="card space-y-4">
        <h3 className="section-header">Property</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="label">Deal Name</label>
            <input className="input" placeholder="The Austin Arms" {...register("name")} />
            {errors.name && <p className="text-xs text-red-400 mt-1">{errors.name.message}</p>}
          </div>
          <div>
            <label className="label">Asset Class</label>
            <select className="input" {...register("asset_class")}>
              {Object.entries(ASSET_CLASS_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Market</label>
            <input className="input" placeholder="Austin, TX" {...register("market")} />
          </div>
          <div>
            <label className="label">Purchase Price ($)</label>
            <input className="input" type="number" placeholder="4800000" {...register("purchase_price")} />
          </div>
          <div>
            <label className="label">Units (multifamily)</label>
            <input className="input" type="number" placeholder="24" {...register("units")} />
          </div>
          <div>
            <label className="label">Closing Costs (%)</label>
            <input className="input" type="number" step="0.001" placeholder="0.01" {...register("closing_costs")} />
          </div>
          <div>
            <label className="label">Immediate CapEx ($)</label>
            <input className="input" type="number" placeholder="0" {...register("immediate_capex")} />
          </div>
        </div>
      </div>

      {/* Financing */}
      <div className="card space-y-4">
        <h3 className="section-header">Financing</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">LTV (%)</label>
            <input className="input" type="number" step="0.01" placeholder="0.70" {...register("loan_ltv")} />
          </div>
          <div>
            <label className="label">Interest Rate (%)</label>
            <input className="input" type="number" step="0.0001" placeholder="0.0675" {...register("loan_interest_rate")} />
          </div>
          <div>
            <label className="label">Amortization (years)</label>
            <input className="input" type="number" placeholder="30" {...register("loan_amortization_years")} />
          </div>
          <div>
            <label className="label">Loan Type</label>
            <select className="input" {...register("loan_type")}>
              {Object.entries(LOAN_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Origination Fee (%)</label>
            <input className="input" type="number" step="0.001" placeholder="0.01" {...register("loan_origination_fee")} />
          </div>
        </div>
      </div>

      {/* Operations */}
      <div className="card space-y-4">
        <h3 className="section-header">Operations (Year 1)</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Gross Scheduled Income ($/yr)</label>
            <input className="input" type="number" placeholder="576000" {...register("gross_scheduled_income")} />
          </div>
          <div>
            <label className="label">Vacancy Rate (%)</label>
            <input className="input" type="number" step="0.01" placeholder="0.05" {...register("vacancy_rate")} />
          </div>
          <div>
            <label className="label">Other Income ($/yr)</label>
            <input className="input" type="number" placeholder="0" {...register("other_income")} />
          </div>
          <div>
            <label className="label">Property Taxes ($/yr)</label>
            <input className="input" type="number" placeholder="72000" {...register("property_taxes")} />
          </div>
          <div>
            <label className="label">Insurance ($/yr)</label>
            <input className="input" type="number" placeholder="18000" {...register("insurance")} />
          </div>
          <div>
            <label className="label">Management Fee (%)</label>
            <input className="input" type="number" step="0.01" placeholder="0.05" {...register("management_fee_pct")} />
          </div>
          <div>
            <label className="label">Maintenance Reserves ($/yr)</label>
            <input className="input" type="number" placeholder="36000" {...register("maintenance_reserves")} />
          </div>
          <div>
            <label className="label">CapEx Reserves ($/yr)</label>
            <input className="input" type="number" placeholder="24000" {...register("capex_reserves")} />
          </div>
          <div>
            <label className="label">Rent Growth Rate (%/yr)</label>
            <input className="input" type="number" step="0.001" placeholder="0.03" {...register("rent_growth_rate")} />
          </div>
          <div>
            <label className="label">Expense Growth Rate (%/yr)</label>
            <input className="input" type="number" step="0.001" placeholder="0.02" {...register("expense_growth_rate")} />
          </div>
        </div>
      </div>

      {/* Exit */}
      <div className="card space-y-4">
        <h3 className="section-header">Exit Assumptions</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Hold Period (years)</label>
            <input className="input" type="number" placeholder="5" {...register("hold_period_years")} />
          </div>
          <div>
            <label className="label">Exit Cap Rate (%)</label>
            <input className="input" type="number" step="0.001" placeholder="0.055" {...register("exit_cap_rate")} />
          </div>
          <div>
            <label className="label">Selling Costs (%)</label>
            <input className="input" type="number" step="0.001" placeholder="0.03" {...register("selling_costs_pct")} />
          </div>
          <div>
            <label className="label">Discount Rate (%)</label>
            <input className="input" type="number" step="0.001" placeholder="0.08" {...register("discount_rate")} />
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      <button type="submit" className="btn-primary w-full justify-center py-3" disabled={isLoading}>
        {isLoading ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Running Underwriting…
          </>
        ) : (
          "Run Full Underwriting"
        )}
      </button>
    </form>
  );
}
