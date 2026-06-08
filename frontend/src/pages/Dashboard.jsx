import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
  BarChart, Bar, Cell,
} from "recharts";
import { ArrowUpRight, TrendingUp, Users, Workflow, ListChecks, DollarSign } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { Link } from "react-router-dom";

function fmtMoney(n = 0) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

const STAGE_COLORS = {
  lead: "#3D5A80",
  qualified: "#4A6B56",
  proposal: "#B37422",
  negotiation: "#3D405B",
  won: "#4A6B56",
  lost: "#9E4747",
};

const KpiCard = ({ label, value, sub, icon: Icon, testid }) => (
  <div className="surface-card p-6 flex flex-col gap-4 hover:-translate-y-0.5 transition-transform duration-200" data-testid={testid}>
    <div className="flex items-center justify-between">
      <div className="overline">{label}</div>
      <Icon className="w-4 h-4 text-ink-muted" />
    </div>
    <div className="font-heading text-3xl font-bold tracking-tight text-ink">{value}</div>
    {sub && <div className="text-xs text-ink-muted inline-flex items-center gap-1"><ArrowUpRight className="w-3 h-3" />{sub}</div>}
  </div>
);

export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/dashboard/stats").then(r => setData(r.data)).catch(() => {});
  }, []);

  if (!data) {
    return <div className="text-ink-muted text-sm">Loading dashboard…</div>;
  }

  const stageData = Object.entries(data.stage_breakdown).map(([k, v]) => ({
    stage: k, count: v.count, value: v.value, fill: STAGE_COLORS[k],
  }));

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">Overview</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-heading font-bold tracking-tight text-ink">
            Good to see you{user?.name ? `, ${user.name.split(" ")[0]}` : ""}.
          </h1>
          <p className="text-ink-muted mt-1">Here's how your pipeline looks today.</p>
        </div>
        <Link
          to="/contacts"
          className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2 text-sm transition-colors"
          data-testid="cta-add-contact"
        >
          Manage Contacts <ArrowUpRight className="w-4 h-4" />
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard testid="kpi-revenue" label="Revenue (won)" value={fmtMoney(data.kpis.revenue)} sub="All time" icon={DollarSign} />
        <KpiCard testid="kpi-pipeline" label="Pipeline value" value={fmtMoney(data.kpis.pipeline_value)} sub={`${data.kpis.deals_won} deals won`} icon={TrendingUp} />
        <KpiCard testid="kpi-contacts" label="Contacts" value={data.kpis.contacts} sub="In workspace" icon={Users} />
        <KpiCard testid="kpi-tasks" label="Open tasks" value={data.kpis.tasks_open} sub="Awaiting you" icon={ListChecks} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="surface-card p-6 lg:col-span-2">
          <div className="flex items-baseline justify-between">
            <div>
              <div className="overline">Revenue trend</div>
              <h3 className="font-heading text-xl font-semibold mt-1">Last 6 months</h3>
            </div>
          </div>
          <div className="mt-6 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.revenue_trend} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#E5E2DC" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" stroke="#75716C" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#75716C" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => v >= 1000 ? `${v / 1000}k` : v} />
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid #E5E2DC", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => fmtMoney(v)}
                />
                <Line type="monotone" dataKey="value" stroke="#D96C4A" strokeWidth={2.5} dot={{ r: 4, fill: "#D96C4A" }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="surface-card p-6">
          <div className="overline">Pipeline</div>
          <h3 className="font-heading text-xl font-semibold mt-1">By stage</h3>
          <div className="mt-6 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stageData} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#E5E2DC" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" stroke="#75716C" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="stage" stroke="#75716C" fontSize={11} tickLine={false} axisLine={false} width={80} />
                <Tooltip contentStyle={{ background: "#fff", border: "1px solid #E5E2DC", borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {stageData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="surface-card p-6 lg:col-span-2">
          <div className="flex items-baseline justify-between">
            <div>
              <div className="overline">Recent contacts</div>
              <h3 className="font-heading text-xl font-semibold mt-1">Latest additions</h3>
            </div>
            <Link to="/contacts" className="text-sm text-terracotta hover:underline" data-testid="see-all-contacts">See all</Link>
          </div>
          <div className="mt-4 divide-y divide-sand-300" data-testid="recent-contacts-list">
            {data.recent_contacts.length === 0 && (
              <div className="text-sm text-ink-muted py-6">No contacts yet.</div>
            )}
            {data.recent_contacts.map((c) => (
              <Link to={`/contacts/${c.id}`} key={c.id} className="flex items-center justify-between py-3 hover:bg-sand-100 px-2 rounded-md transition-colors" data-testid={`recent-contact-${c.id}`}>
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full bg-sand-200 text-ink flex items-center justify-center text-xs font-semibold">
                    {(c.name || "?").split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-ink">{c.name}</div>
                    <div className="text-xs text-ink-muted">{c.title || ""}{c.company ? ` · ${c.company}` : ""}</div>
                  </div>
                </div>
                <span className={`pill ${
                  c.status === "customer" ? "bg-statusgreen-bg text-statusgreen-text" :
                  c.status === "active" ? "bg-statusblue-bg text-statusblue-text" :
                  c.status === "lead" ? "bg-statusamber-bg text-statusamber-text" :
                  "bg-sand-200 text-ink-muted"
                }`}>{c.status}</span>
              </Link>
            ))}
          </div>
        </div>

        <div className="rounded-lg p-6 border border-sand-300 bg-gradient-to-br from-sand-100 to-statusblue-bg/60" data-testid="ai-suggest-card">
          <div className="flex items-center gap-2 overline">
            <Workflow className="w-3.5 h-3.5" /> AI assistant
          </div>
          <h3 className="font-heading text-xl font-semibold mt-2 leading-tight">Score a lead. Draft a follow-up. In seconds.</h3>
          <p className="mt-2 text-sm text-ink-muted">
            Open any contact to generate an AI lead score with reasoning, or draft a follow-up email tailored to your last interaction.
          </p>
          <Link
            to="/contacts"
            className="mt-4 inline-flex items-center gap-2 bg-nightblue hover:bg-nightblue-hover text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
            data-testid="try-ai-link"
          >
            Try it now <ArrowUpRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
