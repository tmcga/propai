import axios from "axios";
import type {
  DealInput,
  InvestmentMemo,
  MarketReport,
  ParseResult,
  UnderwritingResult,
} from "@/types";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "/api",
  headers: { "Content-Type": "application/json" },
  timeout: 60_000,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.detail ?? err.message ?? "An unexpected error occurred";
    return Promise.reject(new Error(message));
  },
);

// ── Underwriting ───────────────────────────────────────────────────────────

export const underwrite = (deal: DealInput): Promise<UnderwritingResult> =>
  api.post<UnderwritingResult>("/underwrite", deal).then((r) => r.data);

export const underwriteQuick = (deal: DealInput): Promise<UnderwritingResult> =>
  api.post<UnderwritingResult>("/underwrite/quick", deal).then((r) => r.data);

export const getSampleResult = (): Promise<UnderwritingResult> =>
  api.get<UnderwritingResult>("/underwrite/sample/result").then((r) => r.data);

// ── Market Intelligence ────────────────────────────────────────────────────

export const getMetroMarket = (
  metro: string,
  params?: { state_fips?: string; county_fips?: string },
): Promise<MarketReport> =>
  api
    .get<MarketReport>(`/market/metro/${encodeURIComponent(metro)}`, { params })
    .then((r) => r.data);

export const getZipMarket = (zipcode: string): Promise<MarketReport> =>
  api.get<MarketReport>(`/market/zip/${zipcode}`).then((r) => r.data);

export const getMacroSnapshot = (): Promise<MarketReport> =>
  api.get<MarketReport>("/market/macro").then((r) => r.data);

export const getSampleMarket = (): Promise<MarketReport> =>
  api.get<MarketReport>("/market/sample").then((r) => r.data);

// ── AI ─────────────────────────────────────────────────────────────────────

export const analyzeDeal = (
  text: string,
): Promise<{
  deal_input: DealInput;
  underwriting: UnderwritingResult;
  memo: InvestmentMemo;
}> => api.post("/ai/analyze", { text }).then((r) => r.data);

export const parseDeal = (text: string): Promise<ParseResult> =>
  api.post<ParseResult>("/ai/parse", { text }).then((r) => r.data);

export const generateMemo = (deal: DealInput): Promise<InvestmentMemo> =>
  api.post<InvestmentMemo>("/ai/memo", deal).then((r) => r.data);

export const getDemoMemo = (): Promise<InvestmentMemo> =>
  api.get<InvestmentMemo>("/ai/memo/demo").then((r) => r.data);
