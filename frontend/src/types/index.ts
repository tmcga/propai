// ── Enums ──────────────────────────────────────────────────────────────────

export type AssetClass =
  | "sfr"
  | "small_multifamily"
  | "multifamily"
  | "office"
  | "retail"
  | "mixed_use"
  | "industrial"
  | "self_storage"
  | "str"
  | "development";

export type LoanType = "fixed" | "interest_only" | "io_then_amortizing";

// ── Deal Input Models ──────────────────────────────────────────────────────

export interface LoanInput {
  ltv: number;
  interest_rate: number;
  amortization_years: number;
  loan_type: LoanType;
  io_period_years?: number;
  origination_fee: number;
}

export interface OperatingAssumptions {
  gross_scheduled_income: number;
  vacancy_rate: number;
  credit_loss_rate: number;
  other_income: number;
  property_taxes: number;
  insurance: number;
  management_fee_pct: number;
  maintenance_reserves: number;
  capex_reserves: number;
  utilities: number;
  other_expenses: number;
  rent_growth_rate: number;
  expense_growth_rate: number;
}

export interface ExitAssumptions {
  hold_period_years: number;
  exit_cap_rate: number;
  selling_costs_pct: number;
  discount_rate: number;
}

export interface EquityStructure {
  lp_equity_pct: number;
  gp_equity_pct: number;
  preferred_return: number;
  tiers: WaterfallTierInput[];
}

export interface WaterfallTierInput {
  lp_irr_hurdle: number;
  gp_promote: number;
}

export interface DealInput {
  name: string;
  asset_class: AssetClass;
  purchase_price: number;
  units?: number;
  square_feet?: number;
  market: string;
  closing_costs: number;
  immediate_capex: number;
  loan: LoanInput;
  operations: OperatingAssumptions;
  exit: ExitAssumptions;
  equity_structure?: EquityStructure;
}

// ── Results Models ────────────────────────────────────────────────────────

export interface ReturnMetrics {
  going_in_cap_rate: number;
  stabilized_cap_rate?: number;
  gross_rent_multiplier: number;
  price_per_unit?: number;
  price_per_sf?: number;
  dscr_yr1: number;
  levered_irr: number;
  unlevered_irr: number;
  levered_npv: number;
  equity_multiple: number;
  cash_on_cash_yr1: number;
  avg_cash_on_cash: number;
  total_profit: number;
  equity_required: number;
  loan_amount: number;
}

export interface ProFormaYear {
  year: number;
  gross_scheduled_income: number;
  vacancy_credit_loss: number;
  other_income: number;
  effective_gross_income: number;
  operating_expenses: number;
  net_operating_income: number;
  debt_service: number;
  before_tax_cash_flow: number;
  loan_balance: number;
  cumulative_cash_flow: number;
  noi_margin: number;
  coc_return: number;
}

export interface SensitivityTable {
  metric: string;
  row_label: string;
  col_label: string;
  row_values: number[];
  col_values: number[];
  data: number[][];
}

export interface UnderwritingResult {
  deal: DealInput;
  metrics: ReturnMetrics;
  pro_forma: ProFormaYear[];
  irr_sensitivity?: SensitivityTable;
  coc_sensitivity?: SensitivityTable;
  waterfall?: WaterfallResult;
  warnings: string[];
}

export interface WaterfallTier {
  tier_name: string;
  irr_hurdle: number;
  distributions: number;
  lp_share: number;
  gp_share: number;
}

export interface WaterfallResult {
  total_distributions: number;
  lp_total: number;
  gp_total: number;
  lp_irr: number;
  gp_irr: number;
  tiers: WaterfallTier[];
}

// ── Market Data Models ─────────────────────────────────────────────────────

export interface MarketReport {
  metro?: string;
  zipcode?: string;
  market_score: number;
  market_grade: string;
  tailwinds: string[];
  headwinds: string[];
  suggested_rent_growth: number;
  suggested_exit_cap_range: [number, number];
  market_thesis: string;
  demographics?: DemographicProfile;
  macro?: MacroSnapshot;
  rent_benchmarks?: RentBenchmarks;
  zillow_metro?: ZillowMetrics;
}

export interface DemographicProfile {
  total_population: number;
  median_household_income: number;
  median_gross_rent: number;
  vacancy_rate: number;
  homeownership_rate: number;
  rent_to_income_ratio: number;
  price_to_income_ratio?: number;
  pct_renter_occupied: number;
  population_growth_signal?: string;
  income_signal?: string;
}

export interface MacroSnapshot {
  mortgage_rate_30yr: number;
  fed_funds_rate: number;
  cpi_yoy: number;
  unemployment_rate: number;
  gdp_growth: number;
  treasury_10yr: number;
  housing_starts: number;
  rate_environment: string;
  cap_rate_pressure: string;
}

export interface RentBenchmarks {
  studio_fmr?: number;
  one_br_fmr?: number;
  two_br_fmr?: number;
  three_br_fmr?: number;
  four_br_fmr?: number;
  median_asking_rent?: number;
  rent_yoy_pct?: number;
  rent_3yr_cagr?: number;
}

export interface ZillowMetrics {
  median_home_value?: number;
  zhvi_yoy_pct?: number;
  zhvi_3yr_cagr?: number;
  zhvi_5yr_cagr?: number;
  median_asking_rent?: number;
  zori_yoy_pct?: number;
  price_to_rent_ratio?: number;
  rent_growth_trend?: string;
}

// ── AI Models ──────────────────────────────────────────────────────────────

export interface InvestmentMemo {
  deal_name: string;
  generated_at: string;
  sections: {
    executive_summary?: string;
    investment_highlights?: string;
    market_analysis?: string;
    financial_analysis?: string;
    risk_factors?: string;
    investment_thesis?: string;
    [key: string]: string | undefined;
  };
  html?: string;
}

export interface ParseResult {
  deal_input: DealInput;
  extracted_values: Record<string, unknown>;
  assumed_values: Record<string, unknown>;
  clarifications_needed: string[];
}

// ── UI Utility Types ───────────────────────────────────────────────────────

export type LoadingState = "idle" | "loading" | "success" | "error";

export interface ApiError {
  detail: string;
  status?: number;
}
