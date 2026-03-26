import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText, RefreshCw, AlertTriangle, ArrowLeft } from "lucide-react";
import { getSampleResult } from "@/lib/api";
import type { UnderwritingResult } from "@/types";
import MetricsBar from "@/components/Dashboard/MetricsBar";
import ProFormaTable from "@/components/Reports/ProFormaTable";
import SensitivityGrid from "@/components/Reports/SensitivityGrid";
import WarningBanner from "@/components/Dashboard/WarningBanner";
import CashFlowChart from "@/components/Charts/CashFlowChart";

export default function ResultsPage() {
  const { dealId } = useParams();
  const navigate = useNavigate();
  const [result, setResult] = useState<UnderwritingResult | null>(null);

  // Load from sessionStorage for "latest" or fetch sample
  const { data: sampleData, isLoading } = useQuery({
    queryKey: ["sample-result"],
    queryFn: getSampleResult,
    enabled: dealId === "sample" && !result,
  });

  useEffect(() => {
    if (dealId === "latest") {
      const stored = sessionStorage.getItem("propai_result");
      if (stored) {
        try {
          setResult(JSON.parse(stored));
        } catch {
          navigate("/underwrite");
        }
      } else {
        navigate("/underwrite");
      }
    }
  }, [dealId, navigate]);

  useEffect(() => {
    if (sampleData) setResult(sampleData);
  }, [sampleData]);

  if (isLoading || !result) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-slate-500 animate-spin" />
      </div>
    );
  }

  const { deal, metrics, pro_forma, irr_sensitivity, coc_sensitivity, warnings } = result;

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/underwrite" className="btn-ghost">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-slate-100">{deal.name}</h1>
            <p className="text-sm text-slate-400">
              {deal.market} · {deal.asset_class.replace("_", " ")} ·{" "}
              {deal.units ? `${deal.units} units` : deal.square_feet ? `${deal.square_feet.toLocaleString()} SF` : ""}
            </p>
          </div>
        </div>
        <Link to={`/memo/${dealId}`} className="btn-primary">
          <FileText className="w-4 h-4" />
          Generate Memo
        </Link>
      </div>

      {/* Warnings */}
      {warnings && warnings.length > 0 && (
        <WarningBanner warnings={warnings} />
      )}

      {/* Key Metrics */}
      <MetricsBar metrics={metrics} />

      {/* Cash Flow Chart */}
      {pro_forma && pro_forma.length > 0 && (
        <div className="card">
          <h3 className="section-header">Cash Flow Projections</h3>
          <CashFlowChart data={pro_forma} />
        </div>
      )}

      {/* Pro Forma Table */}
      {pro_forma && pro_forma.length > 0 && (
        <div className="card overflow-x-auto">
          <h3 className="section-header">5-Year Pro Forma</h3>
          <ProFormaTable data={pro_forma} />
        </div>
      )}

      {/* Sensitivity Tables */}
      {(irr_sensitivity || coc_sensitivity) && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {irr_sensitivity && (
            <div className="card overflow-x-auto">
              <h3 className="section-header">IRR Sensitivity</h3>
              <p className="text-xs text-slate-500 mb-4">Exit Cap Rate × Rent Growth</p>
              <SensitivityGrid table={irr_sensitivity} formatAs="percent" />
            </div>
          )}
          {coc_sensitivity && (
            <div className="card overflow-x-auto">
              <h3 className="section-header">Cash-on-Cash Sensitivity</h3>
              <p className="text-xs text-slate-500 mb-4">Exit Cap Rate × Rent Growth</p>
              <SensitivityGrid table={coc_sensitivity} formatAs="percent" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
