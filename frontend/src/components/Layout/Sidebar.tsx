import { NavLink } from "react-router-dom";
import {
  Calculator,
  BarChart3,
  Map,
  FileText,
  LayoutDashboard,
  Building2,
} from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { to: "/underwrite", icon: Calculator, label: "Underwrite" },
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/market", icon: Map, label: "Market Intel" },
];

export default function Sidebar() {
  return (
    <aside className="w-16 lg:w-56 flex flex-col bg-navy-900 border-r border-navy-800 shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-navy-800">
        <div className="w-8 h-8 bg-gold-500 rounded-lg flex items-center justify-center shrink-0">
          <Building2 className="w-4 h-4 text-navy-950" />
        </div>
        <span className="hidden lg:block text-sm font-bold text-slate-100 tracking-tight">
          PropAI
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                isActive
                  ? "bg-gold-500/10 text-gold-500"
                  : "text-slate-400 hover:bg-navy-800 hover:text-slate-200"
              )
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            <span className="hidden lg:block">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-navy-800">
        <a
          href="https://github.com/your-org/propai"
          target="_blank"
          rel="noopener noreferrer"
          className="hidden lg:flex items-center gap-2 text-xs text-slate-500 hover:text-slate-300 transition-colors"
        >
          <BarChart3 className="w-3 h-3" />
          Open Source · MIT
        </a>
      </div>
    </aside>
  );
}
