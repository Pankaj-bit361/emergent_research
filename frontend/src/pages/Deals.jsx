import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Plus, Trash2, DollarSign } from "lucide-react";
import { toast } from "sonner";

const STAGES = [
  { key: "lead", label: "Lead", bg: "bg-statusblue-bg", text: "text-statusblue-text" },
  { key: "qualified", label: "Qualified", bg: "bg-statusgreen-bg", text: "text-statusgreen-text" },
  { key: "proposal", label: "Proposal", bg: "bg-statusamber-bg", text: "text-statusamber-text" },
  { key: "negotiation", label: "Negotiation", bg: "bg-[#F3E8FF]", text: "text-nightblue" },
  { key: "won", label: "Won", bg: "bg-statusgreen-bg", text: "text-statusgreen-text" },
  { key: "lost", label: "Lost", bg: "bg-statusred-bg", text: "text-statusred-text" },
];

function fmtMoney(n = 0) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function DealForm({ contacts, onSubmit, onClose }) {
  const [f, setF] = useState({
    title: "", value: 0, stage: "lead", contact_id: "", company: "", probability: 20, notes: "",
  });
  const upd = (k) => (e) => setF(s => ({ ...s, [k]: e.target.value }));
  return (
    <div className="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose} data-testid="deal-form-modal">
      <form onClick={(e) => e.stopPropagation()} onSubmit={async (e) => {
        e.preventDefault();
        const c = contacts.find(c => c.id === f.contact_id);
        await onSubmit({
          ...f,
          value: Number(f.value) || 0,
          probability: Number(f.probability) || 0,
          contact_name: c?.name || null,
          company: c?.company || f.company || null,
        });
      }} className="bg-white rounded-lg border border-sand-300 w-full max-w-lg p-6 space-y-4">
        <h3 className="font-heading text-xl font-semibold">New deal</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Title</label>
            <input required value={f.title} onChange={upd("title")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="deal-title-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Value (USD)</label>
            <input type="number" value={f.value} onChange={upd("value")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="deal-value-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Probability %</label>
            <input type="number" value={f.probability} onChange={upd("probability")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="deal-prob-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Stage</label>
            <select value={f.stage} onChange={upd("stage")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta bg-white" data-testid="deal-stage-select">
              {STAGES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-ink-muted">Contact</label>
            <select value={f.contact_id} onChange={upd("contact_id")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta bg-white" data-testid="deal-contact-select">
              <option value="">— None —</option>
              {contacts.map(c => <option key={c.id} value={c.id}>{c.name}{c.company ? ` · ${c.company}` : ""}</option>)}
            </select>
          </div>
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Notes</label>
            <textarea value={f.notes} onChange={upd("notes")} rows={3} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="deal-notes-input" />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium rounded-md text-ink-muted hover:text-ink hover:bg-sand-100" data-testid="deal-cancel-btn">Cancel</button>
          <button type="submit" className="px-4 py-2 text-sm font-medium rounded-md bg-terracotta hover:bg-terracotta-hover text-white" data-testid="deal-save-btn">Save</button>
        </div>
      </form>
    </div>
  );
}

export default function Deals() {
  const [deals, setDeals] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [dragId, setDragId] = useState(null);
  const [overStage, setOverStage] = useState(null);

  const load = async () => {
    const [d, c] = await Promise.all([api.get("/deals"), api.get("/contacts")]);
    setDeals(d.data);
    setContacts(c.data);
  };
  useEffect(() => { load(); }, []);

  const create = async (payload) => {
    try {
      await api.post("/deals", payload);
      toast.success("Deal added");
      setShowForm(false);
      load();
    } catch { toast.error("Failed to save"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this deal?")) return;
    await api.delete(`/deals/${id}`);
    load();
  };

  const onDrop = async (stage) => {
    if (!dragId) return;
    const deal = deals.find(d => d.id === dragId);
    if (!deal || deal.stage === stage) { setDragId(null); setOverStage(null); return; }
    setDeals(ds => ds.map(d => d.id === dragId ? { ...d, stage } : d));
    setDragId(null);
    setOverStage(null);
    try {
      await api.patch(`/deals/${deal.id}/stage`, { stage });
      toast.success(`Moved to ${stage}`);
    } catch {
      toast.error("Move failed");
      load();
    }
  };

  const grouped = useMemo(() => {
    const g = {};
    for (const s of STAGES) g[s.key] = [];
    for (const d of deals) (g[d.stage] || g.lead).push(d);
    return g;
  }, [deals]);

  return (
    <div className="space-y-6" data-testid="deals-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">Pipeline</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-heading font-bold tracking-tight">Deals</h1>
          <p className="text-ink-muted mt-1">Drag cards between columns to move stages.</p>
        </div>
        <button onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2 text-sm" data-testid="add-deal-btn">
          <Plus className="w-4 h-4" /> New deal
        </button>
      </div>

      <div className="overflow-x-auto scrollbar-thin -mx-2 px-2">
        <div className="flex gap-4 min-w-max pb-4">
          {STAGES.map((s) => {
            const list = grouped[s.key];
            const total = list.reduce((a, d) => a + (d.value || 0), 0);
            const isOver = overStage === s.key;
            return (
              <div
                key={s.key}
                className={`w-72 shrink-0 rounded-lg p-3 transition-colors ${isOver ? "bg-sand-200/80" : "bg-sand-100"}`}
                onDragOver={(e) => { e.preventDefault(); setOverStage(s.key); }}
                onDragLeave={() => setOverStage(null)}
                onDrop={() => onDrop(s.key)}
                data-testid={`column-${s.key}`}
              >
                <div className="flex items-center justify-between px-2 mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`pill ${s.bg} ${s.text}`}>{s.label}</span>
                    <span className="text-xs text-ink-muted">{list.length}</span>
                  </div>
                  <div className="text-xs font-medium text-ink-muted">{fmtMoney(total)}</div>
                </div>
                <div className="space-y-2">
                  {list.map((d) => (
                    <div
                      key={d.id}
                      draggable
                      onDragStart={() => setDragId(d.id)}
                      onDragEnd={() => { setDragId(null); setOverStage(null); }}
                      className={`group bg-white rounded-md p-3.5 border border-sand-300 cursor-grab active:cursor-grabbing transition-all hover:shadow-sm ${dragId === d.id ? "opacity-50 scale-[0.98]" : ""}`}
                      data-testid={`deal-card-${d.id}`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="text-sm font-medium text-ink line-clamp-2">{d.title}</div>
                        <button onClick={() => remove(d.id)} className="ml-2 opacity-0 group-hover:opacity-100 text-ink-muted hover:text-statusred-text transition-opacity" data-testid={`delete-deal-${d.id}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <span className="inline-flex items-center gap-1 text-ink-muted"><DollarSign className="w-3 h-3" />{fmtMoney(d.value || 0)}</span>
                        <span className="text-ink-muted">{d.probability || 0}%</span>
                      </div>
                      {(d.contact_name || d.company) && (
                        <div className="mt-2 pt-2 border-t border-sand-300 text-xs text-ink-muted truncate">
                          {d.contact_name}{d.company ? ` · ${d.company}` : ""}
                        </div>
                      )}
                    </div>
                  ))}
                  {list.length === 0 && (
                    <div className="text-xs text-ink-muted/70 px-2 py-6 text-center border border-dashed border-sand-300 rounded-md">
                      Drop deals here
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showForm && <DealForm contacts={contacts} onSubmit={create} onClose={() => setShowForm(false)} />}
    </div>
  );
}
