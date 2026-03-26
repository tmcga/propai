import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

interface Props {
  warnings: string[];
}

export default function WarningBanner({ warnings }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!warnings || warnings.length === 0) return null;

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-3"
      >
        <div className="flex items-center gap-2 text-amber-400 font-medium text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {warnings.length} underwriting assumption{warnings.length > 1 ? "s" : ""} flagged
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-amber-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-amber-400" />
        )}
      </button>

      {expanded && (
        <ul className="mt-3 space-y-1.5 border-t border-amber-500/20 pt-3">
          {warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-amber-300">
              <span className="mt-0.5 shrink-0 text-amber-500">•</span>
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
