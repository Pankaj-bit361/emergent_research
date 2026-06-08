import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

const PRIORITY_STYLE = {
  high: "bg-statusred-bg text-statusred-text",
  medium: "bg-statusamber-bg text-statusamber-text",
  low: "bg-sand-200 text-ink-muted",
};

export default function Tasks() {
  const [items, setItems] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [f, setF] = useState({ title: "", description: "", priority: "medium", contact_id: "" });

  const load = async () => {
    const [t, c] = await Promise.all([api.get("/tasks"), api.get("/contacts")]);
    setItems(t.data);
    setContacts(c.data);
  };
  useEffect(() => { load(); }, []);

  const toggle = async (t) => {
    setItems(its => its.map(i => i.id === t.id ? { ...i, completed: !i.completed } : i));
    await api.put(`/tasks/${t.id}`, { ...t, completed: !t.completed });
  };

  const create = async (e) => {
    e.preventDefault();
    try {
      await api.post("/tasks", { ...f, completed: false });
      toast.success("Task added");
      setF({ title: "", description: "", priority: "medium", contact_id: "" });
      setShowForm(false);
      load();
    } catch { toast.error("Failed to save"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this task?")) return;
    await api.delete(`/tasks/${id}`);
    load();
  };

  const open = items.filter(i => !i.completed);
  const done = items.filter(i => i.completed);

  return (
    <div className="space-y-8" data-testid="tasks-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">Today</div>
          <h1 className="mt-1 text-3xl sm:text-4xl font-heading font-bold tracking-tight">Tasks</h1>
          <p className="text-ink-muted mt-1">{open.length} open · {done.length} done</p>
        </div>
        <button onClick={() => setShowForm(true)} className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2 text-sm" data-testid="add-task-btn">
          <Plus className="w-4 h-4" /> New task
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface-card p-6">
          <h3 className="font-heading text-lg font-semibold mb-4">Open</h3>
          <div className="space-y-2" data-testid="open-tasks-list">
            {open.length === 0 && <div className="text-sm text-ink-muted">All clear.</div>}
            {open.map((t) => (
              <div key={t.id} className="flex items-start gap-3 p-3 border border-sand-300 rounded-md hover:bg-sand-100 transition-colors" data-testid={`task-${t.id}`}>
                <input type="checkbox" checked={t.completed} onChange={() => toggle(t)} className="mt-1 accent-terracotta" data-testid={`task-check-${t.id}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{t.title}</div>
                  {t.description && <div className="text-xs text-ink-muted mt-0.5">{t.description}</div>}
                  <div className="mt-1.5 flex gap-2 items-center">
                    <span className={`pill ${PRIORITY_STYLE[t.priority]}`}>{t.priority}</span>
                  </div>
                </div>
                <button onClick={() => remove(t.id)} className="p-1 text-ink-muted hover:text-statusred-text" data-testid={`delete-task-${t.id}`}><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-heading text-lg font-semibold mb-4">Completed</h3>
          <div className="space-y-2" data-testid="done-tasks-list">
            {done.length === 0 && <div className="text-sm text-ink-muted">Nothing finished yet.</div>}
            {done.map((t) => (
              <div key={t.id} className="flex items-start gap-3 p-3 border border-sand-300 rounded-md opacity-60" data-testid={`task-${t.id}`}>
                <input type="checkbox" checked={t.completed} onChange={() => toggle(t)} className="mt-1 accent-terracotta" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium line-through">{t.title}</div>
                  {t.description && <div className="text-xs text-ink-muted mt-0.5">{t.description}</div>}
                </div>
                <button onClick={() => remove(t.id)} className="p-1 text-ink-muted hover:text-statusred-text" data-testid={`delete-task-${t.id}`}><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showForm && (
        <div className="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowForm(false)} data-testid="task-form-modal">
          <form onClick={(e) => e.stopPropagation()} onSubmit={create} className="bg-white rounded-lg border border-sand-300 w-full max-w-lg p-6 space-y-4">
            <h3 className="font-heading text-xl font-semibold">New task</h3>
            <div>
              <label className="text-xs text-ink-muted">Title</label>
              <input required value={f.title} onChange={(e) => setF(s => ({ ...s, title: e.target.value }))} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="task-title-input" />
            </div>
            <div>
              <label className="text-xs text-ink-muted">Description</label>
              <textarea value={f.description} onChange={(e) => setF(s => ({ ...s, description: e.target.value }))} rows={3} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="task-desc-input" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-ink-muted">Priority</label>
                <select value={f.priority} onChange={(e) => setF(s => ({ ...s, priority: e.target.value }))} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="task-priority-select">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-ink-muted">Linked contact</label>
                <select value={f.contact_id} onChange={(e) => setF(s => ({ ...s, contact_id: e.target.value }))} className="mt-1 w-full rounded-md border border-sand-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="task-contact-select">
                  <option value="">— None —</option>
                  {contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-sm font-medium rounded-md text-ink-muted hover:text-ink hover:bg-sand-100" data-testid="task-cancel-btn">Cancel</button>
              <button type="submit" className="px-4 py-2 text-sm font-medium rounded-md bg-terracotta hover:bg-terracotta-hover text-white" data-testid="task-save-btn">Save</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
