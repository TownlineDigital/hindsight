import { useState } from "react";
import { supabase } from "../lib/supabase.js";

export default function Auth() {
  const [mode, setMode] = useState("signin"); // "signin" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        const { error: err } = await supabase.auth.signUp({ email, password });
        if (err) throw err;
        setMessage("Account created. Check your email to confirm, then sign in.");
        setMode("signin");
      } else {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
        // No further action needed here - App.jsx listens for the auth
        // state change (onAuthStateChange) and re-renders the dashboard.
      }
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <form className="card auth-card" onSubmit={submit}>
        <h1 className="auth-title">VGC Coach</h1>
        <p className="note">{mode === "signup" ? "Create an account" : "Sign in to see your dashboard"}</p>

        {error && <div className="banner">{error}</div>}
        {message && <div className="banner info">{message}</div>}

        <label className="auth-field">
          <span>Email</span>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label className="auth-field">
          <span>Password</span>
          <input
            type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signup" ? "new-password" : "current-password"} minLength={6}
          />
        </label>

        <button type="submit" disabled={busy}>
          {busy ? "…" : mode === "signup" ? "Sign up" : "Sign in"}
        </button>

        <button
          type="button" className="auth-switch"
          onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setError(null); setMessage(null); }}
        >
          {mode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"}
        </button>
      </form>
    </div>
  );
}
