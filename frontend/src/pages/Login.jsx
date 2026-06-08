import React, { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Sparkles, ArrowRight } from "lucide-react";

export default function Login() {
  const { user, login, error } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@crm.com");
  const [password, setPassword] = useState("admin123");
  const [submitting, setSubmitting] = useState(false);

  if (user && user !== false && user !== null) return <Navigate to="/" replace />;

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    const ok = await login(email, password);
    setSubmitting(false);
    if (ok) navigate("/");
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-sand-50">
      {/* Visual */}
      <div className="hidden lg:flex relative overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1501619438411-47314d5a0580?crop=entropy&cs=srgb&fm=jpg&q=85"
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-br from-nightblue/70 via-nightblue/30 to-transparent" />
        <div className="relative z-10 p-12 flex flex-col justify-between text-white">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-md bg-terracotta flex items-center justify-center">
              <Sparkles className="w-5 h-5" />
            </div>
            <div className="font-heading text-2xl font-bold tracking-tight">Bloom CRM</div>
          </div>
          <div>
            <p className="overline text-white/70">A calmer way to sell</p>
            <h1 className="mt-3 text-4xl xl:text-5xl font-heading font-black tracking-tighter leading-tight">
              Relationships, <br /> not row counts.
            </h1>
            <p className="mt-4 text-white/80 max-w-md leading-relaxed">
              Track every conversation, pipeline, and signal — without the bloat. AI helps you draft, score, and stay close.
            </p>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center p-8 lg:p-16">
        <form onSubmit={onSubmit} className="w-full max-w-md space-y-6" data-testid="login-form">
          <div>
            <div className="overline">Welcome back</div>
            <h2 className="mt-2 text-3xl font-heading font-bold text-ink">Sign in to Bloom</h2>
            <p className="mt-2 text-sm text-ink-muted">Use your work email to continue.</p>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-ink">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1.5 w-full rounded-md border border-sand-300 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta"
                data-testid="login-email-input"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-ink">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1.5 w-full rounded-md border border-sand-300 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/20 focus:border-terracotta"
                data-testid="login-password-input"
              />
            </div>
          </div>

          {error && (
            <div className="text-sm bg-statusred-bg text-statusred-text px-3 py-2 rounded-md" data-testid="login-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-terracotta hover:bg-terracotta-hover text-white font-medium rounded-md px-4 py-2.5 inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
            data-testid="login-submit-btn"
          >
            {submitting ? "Signing in…" : <>Sign in <ArrowRight className="w-4 h-4" /></>}
          </button>

          <div className="text-sm text-ink-muted text-center">
            New here?{" "}
            <Link to="/register" className="text-terracotta hover:underline font-medium" data-testid="go-register-link">
              Create an account
            </Link>
          </div>

          <div className="mt-6 rounded-md border border-sand-300 bg-white/60 p-3 text-xs text-ink-muted">
            <span className="font-medium text-ink">Demo:</span> admin@crm.com / admin123
          </div>
        </form>
      </div>
    </div>
  );
}
