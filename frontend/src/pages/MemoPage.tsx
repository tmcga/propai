import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { ArrowLeft, Download, RefreshCw, Sparkles, Loader2 } from "lucide-react";
import { getDemoMemo, generateMemo } from "@/lib/api";
import type { InvestmentMemo, DealInput, UnderwritingResult } from "@/types";

export default function MemoPage() {
  const { dealId } = useParams();
  const [memo, setMemo] = useState<InvestmentMemo | null>(null);
  const [deal, setDeal] = useState<DealInput | null>(null);

  useEffect(() => {
    // Restore deal from sessionStorage
    const stored = sessionStorage.getItem("propai_result");
    if (stored) {
      try {
        const result: UnderwritingResult = JSON.parse(stored);
        setDeal(result.deal);
      } catch {
        // fallback to demo
      }
    }
  }, []);

  const demoQuery = useQuery({
    queryKey: ["demo-memo"],
    queryFn: getDemoMemo,
    enabled: dealId === "sample" || !deal,
  });

  const generateMutation = useMutation({
    mutationFn: generateMemo,
    onSuccess: (data) => setMemo(data),
  });

  useEffect(() => {
    if (demoQuery.data) setMemo(demoQuery.data);
  }, [demoQuery.data]);

  const isLoading = demoQuery.isLoading || generateMutation.isPending;

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to={`/results/${dealId}`} className="btn-ghost">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-slate-100">Investment Memo</h1>
            {memo && (
              <p className="text-sm text-slate-400">{memo.deal_name}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {deal && !memo && (
            <button
              className="btn-primary"
              disabled={generateMutation.isPending}
              onClick={() => generateMemo && generateMutation.mutate(deal)}
            >
              {generateMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Generate with AI
                </>
              )}
            </button>
          )}
          {memo?.html && (
            <a
              href={`/api/ai/memo/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
            >
              <Download className="w-4 h-4" />
              Download PDF
            </a>
          )}
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center h-64">
          <div className="space-y-3 text-center">
            <RefreshCw className="w-6 h-6 text-gold-500 animate-spin mx-auto" />
            <p className="text-sm text-slate-400">Generating investment memo…</p>
            <p className="text-xs text-slate-600">This takes 15–30 seconds</p>
          </div>
        </div>
      )}

      {memo && (
        <div className="space-y-6">
          {/* If HTML memo, render it in an iframe */}
          {memo.html ? (
            <div className="card p-0 overflow-hidden rounded-xl">
              <iframe
                srcDoc={memo.html}
                title="Investment Memo"
                className="w-full h-[800px] bg-white"
                sandbox="allow-same-origin"
              />
            </div>
          ) : (
            /* Fallback: render sections as cards */
            Object.entries(memo.sections)
              .filter(([, v]) => Boolean(v))
              .map(([key, content]) => (
                <div key={key} className="card">
                  <h3 className="section-header capitalize">
                    {key.replace(/_/g, " ")}
                  </h3>
                  <div className="prose prose-invert prose-sm max-w-none text-slate-300 leading-relaxed whitespace-pre-wrap">
                    {content}
                  </div>
                </div>
              ))
          )}
        </div>
      )}

      {!isLoading && !memo && (
        <div className="card text-center py-16">
          <Sparkles className="w-8 h-8 text-gold-500 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-slate-200 mb-2">
            Ready to generate your memo
          </h3>
          <p className="text-sm text-slate-400 mb-6 max-w-sm mx-auto">
            PropAI will write a 9-section institutional investment memo using your
            underwriting data and market intelligence.
          </p>
          <p className="text-xs text-slate-600">
            Requires <code className="text-slate-400">ANTHROPIC_API_KEY</code> to be set.
            <br />
            <Link to="/results/sample" className="text-gold-500 hover:text-gold-400 underline">
              View the demo memo instead
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
