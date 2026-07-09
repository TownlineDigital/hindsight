import { supabase } from "./lib/supabase.js";

// Same-origin in production (this app is served by the FastAPI app itself at
// /dashboard/); in dev, vite.config.js proxies these paths to :8000.
const API = "";

async function authHeader() {
  if (!supabase) return {};   // local dev mode - see lib/supabase.js
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJSON(url, opts = {}) {
  const headers = { ...(opts.headers || {}), ...(await authHeader()) };
  const res = await fetch(API + url, { ...opts, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : res.statusText;
    throw new Error(detail);
  }
  return body;
}

// Fetches one stored reference frame (GET /jobs/{id}/frame/{path}) as a
// blob: URL instead of a plain JSON response - <img src="..."> can't carry
// an Authorization header, so this is what lets a private (Supabase-auth'd)
// job's frames still render: fetch the bytes ourselves (with the header),
// then hand the browser a local object URL pointing at those same bytes.
// Callers are responsible for URL.revokeObjectURL() when done with it (see
// MatchEvents.jsx's cleanup effect) - otherwise each one leaks until reload.
async function frameBlobUrl(jobId, framePath) {
  // reference_frame paths were built with the HOST OS's path separator
  // (os.path.join, in analyze_matches.py) - normalize backslashes to
  // forward slashes first so this works the same whether the backend ran
  // on Windows or not, then percent-encode each segment individually so a
  // literal "/" in the path is preserved as a path separator, not escaped.
  const encodedPath = framePath.replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/");
  const headers = await authHeader();
  const res = await fetch(`${API}/jobs/${jobId}/frame/${encodedPath}`, { headers });
  if (!res.ok) throw new Error(`Could not load reference frame (${res.status})`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export const api = {
  authStatus: () => getJSON("/auth/status"),
  listJobs: () => getJSON("/jobs"),
  jobStatus: (jobId) => getJSON(`/jobs/${jobId}`),
  record: (jobId) => getJSON(`/jobs/${jobId}/record`),
  report: (jobId) => getJSON(`/jobs/${jobId}/report`),
  matchesSummary: (jobId) => getJSON(`/jobs/${jobId}/matches/summary`),
  opponentStrength: (jobId) => getJSON(`/jobs/${jobId}/opponent-strength`),
  skillScores: (jobId) => getJSON(`/jobs/${jobId}/skill-scores`),
  events: (jobId) => getJSON(`/jobs/${jobId}/events`),

  // Per-turn strategic analysis (backend/main.py's GET /jobs/{id}/
  // strategic-analysis, wrapping strategic_analysis.compute_strategic_analysis)
  // - one entry per match, each with a momentum_timeline of per-turn reports
  // (score/delta/win_probability/reasons plus the VGC Battle Intelligence
  // Manual's 6 reports: speed_control/threat_pressure/resource_advantage/
  // momentum/position_score/risk_management - see strategic_analysis.py's
  // build_momentum_timeline docstring). This endpoint already existed before
  // 2026-07-09 but was never called from the frontend until MatchSummary.jsx
  // wired it in for the per-turn recap.
  strategicAnalysis: (jobId) => getJSON(`/jobs/${jobId}/strategic-analysis`),

  // Job-wide "overall skill set" rollup (backend/main.py's GET /jobs/{id}/
  // battle-profile, wrapping analytics.compute_job_battle_profile, added
  // 2026-07-09, tasks #234-237) - aggregates every match's per-turn six
  // reports (speed_control/threat_pressure/resource_advantage/momentum/
  // position_score/risk_management) into one job-wide profile, plus
  // recurring mistake/win-condition/loss patterns. Returns null (not a
  // 404/409) if no match in the job has any turns analyzed yet - see
  // BattleProfile.jsx's own empty-state handling.
  battleProfile: (jobId) => getJSON(`/jobs/${jobId}/battle-profile`),
  askCoach: (jobId, question) =>
    getJSON(`/jobs/${jobId}/coach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),

  // Starts a new job (video URL/upload, or Showdown replay file(s)/URL(s)) -
  // formData is built by NewJobPanel.jsx. No Content-Type header set here on
  // purpose: the browser fills in the multipart boundary itself for FormData,
  // and would get it wrong if we tried to set it manually.
  createJob: (formData) => getJSON("/jobs", { method: "POST", body: formData }),

  // Corrects one field (or several) on one event by hand, e.g.
  // correctEvent(jobId, 12, { pokemon: "Charizard" }) to fix a misread
  // species - see MatchEvents.jsx.
  correctEvent: (jobId, index, fields) =>
    getJSON(`/jobs/${jobId}/events/${index}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields }),
    }),

  frameBlobUrl,

  // "Career" endpoints - aggregate across EVERY completed job this account
  // has ever uploaded, not just the currently-selected job (see
  // backend/career.py). No jobId argument: the scope is implicitly "this
  // whole account's match history."
  careerRecord: () => getJSON("/career/record"),
  careerReport: () => getJSON("/career/report"),
  careerMatches: () => getJSON("/career/matches"),
  careerSkillScores: () => getJSON("/career/skill-scores"),
  careerSkillScoresTrend: () => getJSON("/career/skill-scores/trend"),
  askCareerCoach: (question) =>
    getJSON("/career/coach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),

  // Coach sharing (backend/coaching.py) - player-generated links, a
  // persistent coach/student roster, and notes. See that module's docstring
  // for the privacy model: nothing here is visible without a valid token the
  // PLAYER themselves generated. coachView() is the one PUBLIC call (no
  // signed-in session required) - getJSON still attaches a Bearer header if
  // the visitor happens to be signed in, which is harmless since the
  // endpoint itself never requires one.
  createShareLink: (label, expiresInDays) =>
    getJSON("/account/share-links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label || null, expires_in_days: expiresInDays || null }),
    }),
  listShareLinks: () => getJSON("/account/share-links"),
  revokeShareLink: (token) => getJSON(`/account/share-links/${token}`, { method: "DELETE" }),
  myCoachingNotes: () => getJSON("/account/coaching-notes"),
  coachView: (token) => getJSON(`/coach-view/${token}`),

  addStudent: (token) =>
    getJSON("/coach/students", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  listStudents: () => getJSON("/coach/students"),
  renameStudent: (playerUserId, label) =>
    getJSON(`/coach/students/${playerUserId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    }),
  removeStudent: (playerUserId) => getJSON(`/coach/students/${playerUserId}`, { method: "DELETE" }),
  studentProfile: (playerUserId) => getJSON(`/coach/students/${playerUserId}/profile`),
  studentNotes: (playerUserId) => getJSON(`/coach/students/${playerUserId}/notes`),
  addStudentNote: (playerUserId, text, category) =>
    getJSON(`/coach/students/${playerUserId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, category: category || null }),
    }),
  updateNote: (noteId, fields) =>
    getJSON(`/coach/notes/${noteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),
  deleteNote: (noteId) => getJSON(`/coach/notes/${noteId}`, { method: "DELETE" }),

  // Lightweight usage tracking (tab views, UI interactions) - see backend/
  // audit.py + POST /telemetry/event. Fire-and-forget by design: callers
  // never await this and it swallows its own errors, since a tracking call
  // failing must never affect the actual feature the user is using.
  track: (eventType, payload) => {
    getJSON("/telemetry/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_type: eventType, payload: payload || {} }),
    }).catch(() => {});
  },
};
