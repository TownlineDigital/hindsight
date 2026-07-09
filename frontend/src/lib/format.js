export function pctClass(p) {
  if (p == null) return "";
  if (p >= 60) return "good";
  if (p <= 40) return "bad";
  return "warn";
}

export function formatDuration(seconds) {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

// Score-tier color for the 0-100 skill scores (different thresholds than
// win-rate pctClass - a 50 is "developing", not "bad", on a skill score).
export function scoreClass(v) {
  if (v == null) return "";
  if (v >= 70) return "good";
  if (v <= 35) return "bad";
  return "warn";
}
