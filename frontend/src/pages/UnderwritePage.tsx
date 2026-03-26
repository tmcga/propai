import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ArrowRight, Loader2, AlertCircle } from "lucide-react";
import { analyzeDeal, underwrite } from "@/lib/api";
import type { DealInput } from "@/types";
import DealForm from "@/components/Underwriting/DealForm";
import { cn } from "@/lib/utils";

export default function UnderwritePage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"ai" | "manual">("ai");
  const [nlText, setNlText] = useState("");
  const aiMutation = useMutation({
    mutationFn: analyzeDeal,
    onSuccess: (data) => {
      // Store result in sessionStorage so ResultsPage can read it
      sessionStorage.setItem("propai_result", JSON.stringify(data.underwriting));
      navigate("/results/latest");
    },
  });

  const manualMutation = useMutation({
    mutationFn: underwrite,
    onSuccess: (data) => {
      sessionStorage.setItem("propai_result", JSON.stringify(data));
      navigate("/results/latest");
    },
  });

  const examplePrompts = [
    "24-unit apartment in Austin TX at $4.8M. Rents average $2,000/mo. 70% LTV at 6.75%, 5-year hold, exit at 5.5 cap.",
    "12-unit multifamily in Nashville TN. Purchase $2.1M, avg rent $1,400. 65% LTV at 7.0%, 7-year hold.",
    "Industrial warehouse 40,000 SF in Phoenix AZ. $6M purchase, triple net leases at $8/SF. 60% LTV at 6.5%.",
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      {/* Mode toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setMode("ai")}
          className={cn(
            "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
            mode === "ai"
              ? "bg-gold-500/10 text-gold-500 border border-gold-500/30"
              : "text-slate-400 hover:text-slate-200 hover:bg-navy-800"
          )}
        >
          <span className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            AI Natural Language
          </span>
        </button>
        <button
          onClick={() => setMode("manual")}
          className={cn(
            "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
            mode === "manual"
              ? "bg-gold-500/10 text-gold-500 border border-gold-500/30"
              : "text-slate-400 hover:text-slate-200 hover:bg-navy-800"
          )}
        >
          Manual Entry
        </button>
      </div>

      {mode === "ai" ? (
        <div className="card space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100 mb-1">
              Describe your deal
            </h2>
            <p className="text-sm text-slate-400">
              Describe the property in plain English. PropAI will extract the deal
              structure and run a full underwriting.
            </p>
          </div>

          <textarea
            className="input resize-none h-28 font-mono text-sm"
            placeholder="e.g. 24-unit apartment in Austin TX at $4.8M. Rents average $2,000/mo. 70% LTV at 6.75%, 5-year hold, exit at 5.5 cap."
            value={nlText}
            onChange={(e) => setNlText(e.target.value)}
          />

          {aiMutation.isError && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              {(aiMutation.error as Error).message}
            </div>
          )}

          <div className="flex items-center justify-between">
            <div className="flex flex-wrap gap-2">
              {examplePrompts.map((p, i) => (
                <button
                  key={i}
                  onClick={() => setNlText(p)}
                  className="text-xs text-slate-500 hover:text-slate-300 underline transition-colors"
                >
                  Example {i + 1}
                </button>
              ))}
            </div>

            <button
              className="btn-primary"
              disabled={!nlText.trim() || aiMutation.isPending}
              onClick={() => aiMutation.mutate(nlText)}
            >
              {aiMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analyzing…
                </>
              ) : (
                <>
                  Analyze Deal
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>

          {/* Progress indicator during AI analysis */}
          {aiMutation.isPending && (
            <div className="space-y-2 pt-2">
              {[
                "Parsing deal structure…",
                "Running financial engine…",
                "Fetching market data…",
                "Generating investment memo…",
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-3 h-3 animate-spin shrink-0" />
                  {step}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <DealForm
          onSubmit={(deal: DealInput) => manualMutation.mutate(deal)}
          isLoading={manualMutation.isPending}
          error={manualMutation.isError ? (manualMutation.error as Error).message : undefined}
        />
      )}

      {/* Quick start tip */}
      {!aiMutation.isPending && !manualMutation.isPending && (
        <div className="text-center text-xs text-slate-600">
          No API key?{" "}
          <a
            href="/results/sample"
            className="text-slate-400 hover:text-slate-200 underline transition-colors"
            onClick={(e) => {
              e.preventDefault();
              navigate("/results/sample");
            }}
          >
            View a sample underwriting
          </a>
        </div>
      )}
    </div>
  );
}
