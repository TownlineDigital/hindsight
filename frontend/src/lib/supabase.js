import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// LOCAL DEV MODE: when these aren't set (no frontend/.env yet), `supabase` is
// null instead of throwing - createClient() itself throws immediately if
// either argument is missing, which would crash the whole app before it even
// renders. Every caller (api.js, App.jsx) checks for null and skips auth
// entirely in that case, matching the backend's own local-mode fallback (see
// backend/auth.py) - this is what lets you run the app with zero cloud setup.
export const supabase = (url && anonKey) ? createClient(url, anonKey) : null;

if (!supabase) {
  console.warn(
    "VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not set - running in local dev mode " +
    "(no sign-in required, single local user). Copy frontend/.env.example to frontend/.env " +
    "and fill in your Supabase project's values to enable real accounts."
  );
}

// The anon key is safe to ship in the browser bundle by design - Supabase's
// access control is enforced server-side (this app's FastAPI backend checks
// every request's token via backend/auth.py, and the DB has Row Level
// Security policies too - see supabase_schema.sql). Never put the
// service_role key here.
