import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

const STATUS_STYLE = {
  customer: "bg-statusgreen-bg text-statusgreen-text",
  active: "bg-statusblue-bg text-statusblue-text",
  lead: "bg-statusamber-bg text-statusamber-text",
  inactive: "bg-sand-200 text-ink-muted",
};

function ContactForm({ initial, onSubmit, onClose }) {
  const [f, setF] = useState({
    name: "", email: "", phone: "", title: "", company: "",
    status: "lead", tags: [], notes: "", ...initial,
  });
  const upd = (k) => (e) => setF(s => ({ ...s, [k]: e.target.value }));
  return (
    <div className="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose} data-testid="contact-form-modal">
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={async (e) => { e.preventDefault(); await onSubmit(f); }}
        className="bg-white rounded-lg border border-sand-300 w-full max-w-lg p-6 space-y-4"
      >
        <h3 className="font-heading text-xl font-semibold">{initial?.id ? "Edit contact" : "New contact"}</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Full name</label>
            <input required value={f.name} onChange={upd("name")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-name-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Email</label>
            <input value={f.email || ""} onChange={upd("email")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-email-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Phone</label>
            <input value={f.phone || ""} onChange={upd("phone")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-phone-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Title</label>
            <input value={f.title || ""} onChange={upd("title")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-title-input" />
          </div>
          <div>
            <label className="text-xs text-ink-muted">Company</label>
            <input value={f.company || ""} onChange={upd("company")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-company-input" />
          </div>
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Status</label>
            <select value={f.status} onChange={upd("status")} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta bg-white" data-testid="contact-status-select">
              <option value="lead">Lead</option>
              <option value="active">Active</option>
              <option value="customer">Customer</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className="text-xs text-ink-muted">Notes</label>
            <textarea value={f.notes || ""} onChange={upd("notes")} rows={3} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="contact-notes-input" />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium rounded-md text-ink-muted hover:text-ink hover:bg-sand-100" data-testid="contact-cancel-btn">Cancel</button>
          <button type="submit" className="px-4 py-2 text-sm font-medium rounded-md bg-terracotta hover:bg-terracotta-hover text-white" data-testid="contact-save-btn">Save</button>
        </div>
      </form>
    </div>
  );
}

export default function Contacts() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    const { data } = await api.get("/contacts");
    setItems(data);
  };
  useEffect(() => { load(); }, []);

  const create = async (payload) => {
    try {
      await api.post("/contacts", payload);
      toast.success("Contact added");
      setShowForm(false);
      load();
    } catch (e) {
      toast.error("Failed to save");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this contact?")) return;
    await api.delete(`/contacts/${id}`);
    toast.success("Contact deleted");
    load();
  };

  const filtered = items.filter(c => {
    const s = q.toLowerCase();
    return !s || c.name?.toLowerCase().includes(s) || c.email?.toLowerCase().includes(s) || c.company?.toLowerCase().includes(s);
  });

  return (
    <div className="space-y-8" data-testid="contacts-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">People</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-heading font-bold tracking-tight">Contacts</h1>
          <p className="text-ink-muted mt-1">{items.length} contacts in your workspace</p>
        </div>
        <button onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2 text-sm" data-testid="add-contact-btn">
          <Plus className="w-4 h-4" /> New contact
        </button>
      </div>

      <div className="surface-card p-2">
        <div className="px-4 py-3 flex items-center gap-3 border-b border-sand-300">
          <Search className="w-4 h-4 text-ink-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, email, company…"
            className="flex-1 bg-transparent outline-none text-sm placeholder-ink-muted/70"
            data-testid="contacts-search-input"
          />
        </div>
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-ink-muted">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Title · Company</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Score</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sand-300">
              {filtered.map((c) => (
                <tr key={c.id} className="hover:bg-sand-100/60 transition-colors" data-testid={`contact-row-${c.id}`}>
                  <td className="px-4 py-3">
                    <Link to={`/contacts/${c.id}`} className="flex items-center gap-3 group">
                      <div className="w-8 h-8 rounded-full bg-sand-200 text-ink flex items-center justify-center text-xs font-semibold">
                        {(c.name || "?").split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase()}
                      </div>
                      <span className="font-medium group-hover:text-terracotta transition-colors">{c.name}</span>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-ink-muted">{c.title || "—"}{c.company ? ` · ${c.company}` : ""}</td>
                  <td className="px-4 py-3 text-ink-muted">{c.email || "—"}</td>
                  <td className="px-4 py-3"><span className={`pill ${STATUS_STYLE[c.status]}`}>{c.status}</span></td>
                  <td className="px-4 py-3">
                    {c.lead_score != null ? (
                      <span className="pill bg-sand-100 text-ink">{c.lead_score}</span>
                    ) : <span className="text-ink-muted">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => remove(c.id)} className="p-1.5 text-ink-muted hover:text-statusred-text rounded-md hover:bg-statusred-bg/50 transition-colors" data-testid={`delete-contact-${c.id}`}>
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">No contacts found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && <ContactForm onSubmit={create} onClose={() => setShowForm(false)} />}
    </div>
  );
}
