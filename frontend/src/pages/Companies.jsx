import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Plus, Trash2, Building2 } from "lucide-react";
import { toast } from "sonner";

function CompanyForm({ onSubmit, onClose }) {
  const [f, setF] = useState({ name: "", industry: "", website: "", size: "", notes: "" });
  const upd = (k) => (e) => setF(s => ({ ...s, [k]: e.target.value }));
  return (
    <div className="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose} data-testid="company-form-modal">
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={async (e) => { e.preventDefault(); await onSubmit(f); }}
        className="bg-white rounded-lg border border-sand-300 w-full max-w-lg p-6 space-y-4"
      >
        <h3 className="font-heading text-xl font-semibold">New company</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Name</label>
            <input required value={f.name} onChange={upd("name")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="company-name-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Industry</label>
            <input value={f.industry} onChange={upd("industry")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="company-industry-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Website</label>
            <input value={f.website} onChange={upd("website")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="company-website-input" />
          </div>
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Size</label>
            <input value={f.size} onChange={upd("size")} placeholder="e.g. 11-50" className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="company-size-input" />
          </div>
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Notes</label>
            <textarea value={f.notes} onChange={upd("notes")} rows={3} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="company-notes-input" />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium rounded-md text-ink-muted hover:text-ink hover:bg-sand-100" data-testid="company-cancel-btn">Cancel</button>
          <button type="submit" className="px-4 py-2 text-sm font-medium rounded-md bg-terracotta hover:bg-terracotta-hover text-white" data-testid="company-save-btn">Save</button>
        </div>
      </form>
    </div>
  );
}

export default function Companies() {
  const [items, setItems] = useState([]);
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    const { data } = await api.get("/companies");
    setItems(data);
  };
  useEffect(() => { load(); }, []);

  const create = async (payload) => {
    try {
      await api.post("/companies", payload);
      toast.success("Company added");
      setShowForm(false);
      load();
    } catch { toast.error("Failed to save"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this company?")) return;
    await api.delete(`/companies/${id}`);
    toast.success("Deleted");
    load();
  };

  return (
    <div className="space-y-8" data-testid="companies-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">Accounts</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-heading font-bold tracking-tight">Companies</h1>
          <p className="text-ink-muted mt-1">{items.length} companies tracked</p>
        </div>
        <button onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2 text-sm" data-testid="add-company-btn">
          <Plus className="w-4 h-4" /> New company
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {items.map((c) => (
          <div key={c.id} className="surface-card p-6 flex flex-col gap-3 hover:-translate-y-0.5 transition-transform" data-testid={`company-card-${c.id}`}>
            <div className="flex items-start justify-between">
              <div className="w-10 h-10 rounded-md bg-sand-100 flex items-center justify-center"><Building2 className="w-5 h-5 text-nightblue" /></div>
              <button onClick={() => remove(c.id)} className="p-1.5 text-ink-muted hover:text-statusred-text rounded-md hover:bg-statusred-bg/50 transition-colors" data-testid={`delete-company-${c.id}`}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <div>
              <h3 className="font-heading text-lg font-semibold">{c.name}</h3>
              <div className="text-xs text-ink-muted mt-0.5">{c.industry || "—"}{c.size ? ` · ${c.size}` : ""}</div>
            </div>
            {c.website && <div className="text-xs text-terracotta">{c.website}</div>}
            {c.notes && <p className="text-sm text-ink-muted leading-relaxed line-clamp-3">{c.notes}</p>}
          </div>
        ))}
        {items.length === 0 && (
          <div className="text-sm text-ink-muted">No companies yet.</div>
        )}
      </div>

      {showForm && <CompanyForm onSubmit={create} onClose={() => setShowForm(false)} />}
    </div>
  );
}
