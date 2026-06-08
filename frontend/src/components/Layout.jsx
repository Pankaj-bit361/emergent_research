import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Users, Building2, Workflow, ListChecks,
  LogOut, Sparkles, Search,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true, testid: "nav-dashboard" },
  { to: "/contacts", label: "Contacts", icon: Users, testid: "nav-contacts" },
  { to: "/companies", label: "Companies", icon: Building2, testid: "nav-companies" },
  { to: "/deals", label: "Deals", icon: Workflow, testid: "nav-deals" },
  { to: "/tasks", label: "Tasks", icon: ListChecks, testid: "nav-tasks" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const initials = (user?.name || user?.email || "?")
    .split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="min-h-screen bg-sand-50 text-ink flex">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 bg-sand-100 border-r border-sand-300 hidden md:flex flex-col" data-testid="sidebar">
        <div className="px-6 pt-8 pb-6">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-md bg-terracotta flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div className="font-heading text-xl font-bold tracking-tight">Bloom CRM</div>
          </div>
        </div>
        <nav className="px-3 flex-1 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end, testid }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={testid}
              className={({ isActive }) =>
                [
                  "group flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors",
                  isActive
                    ? "bg-white text-ink shadow-sm border-l-2 border-terracotta"
                    : "text-ink-muted hover:text-ink hover:bg-white/60",
                ].join(" ")
              }
            >
              <Icon className="w-4 h-4" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-sand-300">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-nightblue text-white flex items-center justify-center text-xs font-semibold">
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate" data-testid="user-name">{user?.name}</div>
              <div className="text-xs text-ink-muted truncate">{user?.email}</div>
            </div>
            <button
              onClick={async () => { await logout(); navigate("/login"); }}
              className="p-2 rounded-md text-ink-muted hover:text-ink hover:bg-white transition-colors"
              data-testid="logout-btn"
              aria-label="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-20 bg-white/70 backdrop-blur-md border-b border-sand-300">
          <div className="h-16 px-6 lg:px-10 flex items-center gap-6">
            <div className="relative flex-1 max-w-xl">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input
                type="text"
                placeholder="Search contacts, deals…"
                className="w-full pl-9 pr-3 py-2 rounded-md border border-sand-300 bg-white/80 text-sm placeholder-ink-muted/70 focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta transition-all"
                data-testid="global-search-input"
              />
            </div>
            <div className="hidden md:flex items-center gap-2 text-xs text-ink-muted">
              <span className="overline">Beta</span>
              <span className="text-sand-300">|</span>
              <span>Workspace</span>
            </div>
          </div>
        </header>
        <main className="flex-1 px-6 lg:px-10 py-8" data-testid="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
