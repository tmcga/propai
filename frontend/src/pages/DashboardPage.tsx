import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Calculator, FileText, Github, Map as MapIcon } from "lucide-react";
import { Link } from "react-router-dom";
import MetricsBar from "@/components/Dashboard/MetricsBar";
import { getSampleResult } from "@/lib/api";

export default function DashboardPage() {
  const { data: sample } = useQuery({
    queryKey: ["sample-result"],
    queryFn: getSampleResult,
  });

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-fade-in">
      {/* Hero */}
      <div className="card bg-gradient-to-br from-navy-900 to-navy-800 border-gold-500/20">
        <div className="flex items-start justify-between">
          <div className="space-y-2 max-w-2xl">
            <h2 className="text-2xl font-bold text-slate-100">
              Real estate underwriting, <span className="text-gold-500">reimagined.</span>
            </h2>
            <p className="text-slate-400 leading-relaxed">
              PropAI replaces spreadsheets and $5k/year SaaS tools with an open-source, AI-native
              workflow. Describe a deal in plain English. Get a full pro forma, IRR analysis, market
              intelligence, and institutional memo — in under 60 seconds.
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <Link to="/underwrite" className="btn-primary">
                <Calculator className="w-4 h-4" />
                Underwrite a Deal
              </Link>
              <Link to="/market" className="btn-secondary">
                <MapIcon className="w-4 h-4" />
                Market Research
              </Link>
              <Link to="/memo/sample" className="btn-secondary">
                <FileText className="w-4 h-4" />
                View Sample Memo
              </Link>
            </div>
          </div>
          <a
            href="https://github.com/your-org/propai"
            target="_blank"
            rel="noopener noreferrer"
            className="btn-ghost hidden lg:flex"
          >
            <Github className="w-4 h-4" />
            Star on GitHub
          </a>
        </div>
      </div>

      {/* Features grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          {
            icon: "📊",
            title: "Financial Engine",
            desc: "Pure Python DCF — IRR, NPV, equity multiple, waterfall, sensitivity tables. Zero numpy.",
            link: "/underwrite",
          },
          {
            icon: "🗺️",
            title: "Market Intelligence",
            desc: "Census, FRED, HUD, Zillow data stitched together into a composite market score.",
            link: "/market",
          },
          {
            icon: "🤖",
            title: "AI Memo Generator",
            desc: "Claude writes a 9-section institutional investment memo from your underwriting data.",
            link: "/memo/sample",
          },
        ].map(({ icon, title, desc, link }) => (
          <Link
            key={title}
            to={link}
            className="card hover:border-navy-700 transition-colors group"
          >
            <div className="text-2xl mb-3">{icon}</div>
            <h3 className="font-semibold text-slate-200 mb-1 group-hover:text-gold-500 transition-colors">
              {title}
            </h3>
            <p className="text-xs text-slate-500 leading-relaxed">{desc}</p>
            <div className="flex items-center gap-1 mt-3 text-xs text-slate-600 group-hover:text-gold-500 transition-colors">
              Try it <ArrowRight className="w-3 h-3" />
            </div>
          </Link>
        ))}
      </div>

      {/* Sample deal preview */}
      {sample && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="section-header mb-0">Sample Deal — {sample.deal.name}</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {sample.deal.market} · {sample.deal.units} units · $
                {(sample.deal.purchase_price / 1_000_000).toFixed(1)}M
              </p>
            </div>
            <Link to="/results/sample" className="btn-ghost text-xs">
              View Full Analysis <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <MetricsBar metrics={sample.metrics} />
        </div>
      )}

      {/* Tech stack */}
      <div className="card">
        <h3 className="section-header">Built with</h3>
        <div className="flex flex-wrap gap-2">
          {[
            "Python 3.11",
            "FastAPI",
            "Pydantic v2",
            "React 18",
            "TypeScript",
            "Vite",
            "Tailwind CSS",
            "Claude (Anthropic)",
            "US Census Bureau API",
            "FRED API",
            "HUD API",
            "Zillow Research",
            "Docker",
            "MIT License",
          ].map((tech) => (
            <span
              key={tech}
              className="px-2.5 py-1 rounded-md bg-navy-800 text-xs text-slate-400 border border-navy-700"
            >
              {tech}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
