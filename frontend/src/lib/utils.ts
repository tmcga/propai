import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmt(
  value: number,
  style: "currency" | "percent" | "number" | "multiple",
  decimals = 2,
): string {
  if (!Number.isFinite(value)) return "—";

  switch (style) {
    case "currency":
      if (Math.abs(value) >= 1_000_000) {
        return `$${(value / 1_000_000).toFixed(2)}M`;
      }
      if (Math.abs(value) >= 1_000) {
        return `$${(value / 1_000).toFixed(0)}K`;
      }
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(value);

    case "percent":
      return `${(value * 100).toFixed(decimals)}%`;

    case "multiple":
      return `${value.toFixed(2)}x`;

    case "number":
      return new Intl.NumberFormat("en-US", {
        maximumFractionDigits: decimals,
      }).format(value);
  }
}

export function irrHeatClass(irr: number): string {
  if (irr >= 0.2) return "heat-hot";
  if (irr >= 0.15) return "heat-warm";
  if (irr >= 0.1) return "heat-neutral";
  if (irr >= 0.05) return "heat-cool";
  return "heat-cold";
}

export function cocHeatClass(coc: number): string {
  if (coc >= 0.1) return "heat-hot";
  if (coc >= 0.07) return "heat-warm";
  if (coc >= 0.05) return "heat-neutral";
  if (coc >= 0.03) return "heat-cool";
  return "heat-cold";
}

export function gradeColor(grade: string): string {
  if (grade.startsWith("A")) return "text-emerald-400";
  if (grade.startsWith("B")) return "text-blue-400";
  if (grade.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

export const ASSET_CLASS_LABELS: Record<string, string> = {
  sfr: "Single-Family Rental",
  small_multifamily: "Small Multifamily (2–4)",
  multifamily: "Multifamily",
  office: "Office",
  retail: "Retail",
  mixed_use: "Mixed Use",
  industrial: "Industrial",
  self_storage: "Self-Storage",
  str: "Short-Term Rental",
  development: "Ground-Up Development",
};

export const LOAN_TYPE_LABELS: Record<string, string> = {
  fixed: "Fixed Rate (Amortizing)",
  interest_only: "Interest Only",
  io_then_amortizing: "IO → Amortizing",
};
