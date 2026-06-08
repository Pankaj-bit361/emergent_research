import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { ArrowLeft, Mail, Phone, Building2, Sparkles, Send, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

const STATUS_STYLE = {
  customer: "bg-statusgreen-bg text-statusgreen-text",
  active: "bg-statusblue-bg text-statusblue-text",
  lead: "bg-statusamber-bg text-statusamber-text",
  inactive: "bg-sand-200 text-ink-muted",
};

export default function ContactDetail() {
  const { id } = useParams();
  const [contact, setContact] = useState(null);
  const [notes, setNotes] = useState([]);
  const [newNote, setNewNote] = useState("");
  const [noteType, setNoteType] = useState("note");
  const [scoring, setScoring] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState(null);

  const load = async () => {
    const { data } = await api.get(`/contacts/${id}`);
    setContact(data);
    const r = await api.get(`/notes/${id}`);
    setNotes(r.data);
  };

  useEffect(() => { load(); }, [id]);

  const addNote = async (e) => {
    e.preventDefault();
    if (!newNote.trim()) return;
    await api.post("/notes", { contact_id: id, content: newNote, type: noteType });
    setNewNote("");
    toast.success("Note saved");
    load();
  };

  const delNote = async (nid) => {
    await api.delete(`/notes/${nid}`);
    load();
  };

  const runScore = async () => {
    setScoring(true);
    try {
      const { data } = await api.post("/ai/lead-score", { contact_id: id });
      toast.success(`Lead scored: ${data.score}`);
      load();
    } catch (e) {
      toast.error("AI scoring failed");
    } finally {
      setScoring(false);
    }
  };

  const draftEmail = async () => {
    setDrafting(true);
    try {
      const { data } = await api.post("/ai/email-draft", { contact_id: id, purpose: "follow-up" });
      setDraft(data);
    } catch (e) {
      toast.error("Draft failed");
    } finally {
      setDrafting(false);
    }
  };

  if (!contact) return <div className="text-ink-muted text-sm">Loading…</div>;

  return (
    <div className="space-y-8" data-testid="contact-detail-page">
      <div>
        <Link to="/contacts" className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink" data-testid="back-to-contacts"><ArrowLeft className="w-4 h-4" /> All contacts</Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Header card */}
        <div className="surface-card p-6 lg:col-span-2">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-full bg-sand-200 text-ink flex items-center justify-center font-heading font-bold">
              {(contact.name || "?").split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-heading text-2xl font-bold tracking-tight">{contact.name}</h1>
                <span className={`pill ${STATUS_STYLE[contact.status]}`}>{contact.status}</span>
              </div>
              <div className="mt-1 text-sm text-ink-muted">{contact.title || ""}{contact.company ? ` · ${contact.company}` : ""}</div>
              <div className="mt-4 flex flex-wrap gap-4 text-sm text-ink-muted">
                {contact.email && <span className="inline-flex items-center gap-1.5"><Mail className="w-4 h-4" /> {contact.email}</span>}
                {contact.phone && <span className="inline-flex items-center gap-1.5"><Phone className="w-4 h-4" /> {contact.phone}</span>}
                {contact.company && <span className="inline-flex items-center gap-1.5"><Building2 className="w-4 h-4" /> {contact.company}</span>}
              </div>
            </div>
          </div>
          {contact.notes && (
            <div className="mt-6 p-4 bg-sand-50 border border-sand-300 rounded-md text-sm text-ink leading-relaxed">
              {contact.notes}
            </div>
          )}
        </div>

        {/* AI Panel */}
        <div className="rounded-lg p-6 border border-sand-300 bg-gradient-to-br from-sand-100 to-statusblue-bg/60" data-testid="ai-panel">
          <div className="flex items-center gap-2 overline"><Sparkles className="w-3.5 h-3.5" /> AI assistant</div>
          <h3 className="font-heading text-lg font-semibold mt-2">Get smarter on this contact</h3>

          <div className="mt-4 space-y-3">
            <button onClick={runScore} disabled={scoring} className="w-full inline-flex items-center justify-center gap-2 bg-nightblue hover:bg-nightblue-hover text-white text-sm font-medium px-4 py-2 rounded-md transition-colors disabled:opacity-60" data-testid="ai-score-btn">
              {scoring ? "Scoring…" : <>Score this lead <Sparkles className="w-4 h-4" /></>}
            </button>
            <button onClick={draftEmail} disabled={drafting} className="w-full inline-flex items-center justify-center gap-2 bg-white border border-sand-300 hover:bg-sand-100 text-ink text-sm font-medium px-4 py-2 rounded-md transition-colors disabled:opacity-60" data-testid="ai-draft-btn">
              {drafting ? "Drafting…" : <>Draft follow-up email <Send className="w-4 h-4" /></>}
            </button>
          </div>

          {contact.lead_score != null && (
            <div className="mt-5 p-3 bg-white border border-sand-300 rounded-md" data-testid="ai-score-result">
              <div className="flex items-center justify-between">
                <span className="overline">Lead score</span>
                <span className="font-heading text-2xl font-bold text-terracotta">{contact.lead_score}</span>
              </div>
              {contact.score_reasoning && (
                <p className="mt-1 text-xs text-ink-muted leading-relaxed">{contact.score_reasoning}</p>
              )}
            </div>
          )}

          {draft && (
            <div className="mt-5 p-3 bg-white border border-sand-300 rounded-md text-sm" data-testid="ai-draft-result">
              <div className="overline">Draft</div>
              <div className="mt-1 font-medium text-ink">{draft.subject}</div>
              <pre className="mt-2 whitespace-pre-wrap text-ink-muted font-sans text-[13px] leading-relaxed">{draft.body}</pre>
            </div>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="surface-card p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="overline">Activity</div>
            <h3 className="font-heading text-xl font-semibold mt-1">Notes & interactions</h3>
          </div>
        </div>

        <form onSubmit={addNote} className="mt-4 flex flex-col sm:flex-row gap-2">
          <select value={noteType} onChange={(e) => setNoteType(e.target.value)} className="rounded-md border border-sand-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta" data-testid="note-type-select">
            <option value="note">Note</option>
            <option value="call">Call</option>
            <option value="email">Email</option>
            <option value="meeting">Meeting</option>
          </select>
          <input
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            placeholder="Add a note or log an interaction…"
            className="flex-1 rounded-md border border-sand-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta"
            data-testid="note-input"
          />
          <button type="submit" className="inline-flex items-center gap-2 bg-terracotta hover:bg-terracotta-hover text-white text-sm font-medium rounded-md px-4 py-2" data-testid="add-note-btn">
            <Plus className="w-4 h-4" /> Log
          </button>
        </form>

        <div className="mt-6 space-y-4" data-testid="notes-list">
          {notes.length === 0 && <div className="text-sm text-ink-muted">No notes yet.</div>}
          {notes.map((n) => (
            <div key={n.id} className="flex gap-3 items-start" data-testid={`note-${n.id}`}>
              <div className="mt-1.5 w-2 h-2 rounded-full bg-terracotta shrink-0" />
              <div className="flex-1">
                <div className="flex items-center gap-2 text-xs text-ink-muted">
                  <span className="uppercase tracking-wider font-semibold text-ink">{n.type}</span>
                  <span>·</span>
                  <span>{new Date(n.created_at).toLocaleString()}</span>
                  {n.author && <><span>·</span><span>{n.author}</span></>}
                </div>
                <div className="mt-1 text-sm text-ink leading-relaxed">{n.content}</div>
              </div>
              <button onClick={() => delNote(n.id)} className="p-1.5 text-ink-muted hover:text-statusred-text rounded-md hover:bg-statusred-bg/50" data-testid={`del-note-${n.id}`}><Trash2 className="w-4 h-4" /></button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
