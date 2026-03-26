import { useLocation } from "react-router-dom";
import { Github, ExternalLink } from "lucide-react";

const PAGE_TITLES: Record<string, string> = {
  "/underwrite": "Deal Underwriting",
  "/dashboard": "Portfolio Dashboard",
  "/market": "Market Intelligence",
};

export default function Topbar() {
  const { pathname } = useLocation();

  const title =
    PAGE_TITLES[pathname] ??
    (pathname.startsWith("/results") ? "Underwriting Results" : "") ??
    (pathname.startsWith("/memo") ? "Investment Memo" : "PropAI");

  return (
    <header className="h-14 flex items-center justify-between px-6 border-b border-navy-800 bg-navy-900 shrink-0">
      <h1 className="text-sm font-semibold text-slate-200">{title}</h1>

      <div className="flex items-center gap-2">
        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="btn-ghost text-xs"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          API Docs
        </a>
        <a
          href="https://github.com/your-org/propai"
          target="_blank"
          rel="noopener noreferrer"
          className="btn-ghost text-xs"
        >
          <Github className="w-3.5 h-3.5" />
          GitHub
        </a>
      </div>
    </header>
  );
}
