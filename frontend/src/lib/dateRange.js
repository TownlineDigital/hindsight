// Date-range helpers for the combined "All Gameplay" view's date filter and
// period-comparison feature (added 2026-07-09). A "range" throughout this
// file (and GameplayDateFilter.jsx/App.jsx) is a plain {since, until} object,
// each side either a 'YYYY-MM-DD' string or null/undefined - the exact shape
// backend/career.filter_by_date and api.js's rangeQuery() expect. null on
// either side means "no bound there" (an omitted since = no lower bound /
// start of time; an omitted until = no upper bound / now).

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Deliberately NOT `date.toISOString().slice(0, 10)` - toISOString() converts
// to UTC first, which can silently shift the calendar date by one in a
// negative-UTC-offset browser timezone (e.g. 11pm local on the 9th becomes
// the 10th in UTC). Building the string from the LOCAL year/month/day is
// what keeps "today" meaning the same day the user's clock actually shows.
export function toDateStr(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function todayStr() {
  return toDateStr(new Date());
}

export function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toDateStr(d);
}

export function startOfMonthStr() {
  const d = new Date();
  d.setDate(1);
  return toDateStr(d);
}

// Presets shown as quick-pick buttons in GameplayDateFilter.jsx. "custom"
// isn't a real date computation - selecting it just reveals the two raw
// date inputs, letting the range stay whatever it already was (or blank).
export const PRESETS = [
  { id: "all", label: "All time" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "month", label: "This month" },
  { id: "custom", label: "Custom range" },
];

export function rangeForPreset(id) {
  switch (id) {
    case "7d":
      return { since: daysAgoStr(6), until: null };   // today + 6 days back = 7 days inclusive
    case "30d":
      return { since: daysAgoStr(29), until: null };
    case "month":
      return { since: startOfMonthStr(), until: null };
    case "all":
    case "custom":
    default:
      return { since: null, until: null };
  }
}

function parseLocalDateStr(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// 'YYYY-MM-DD' -> "Jul 9, 2026" - parsed via parseLocalDateStr rather than
// `new Date(dateStr)` (which parses as UTC midnight and can display as the
// PREVIOUS day in the user's own timezone).
export function formatDateLabel(dateStr) {
  return parseLocalDateStr(dateStr).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

export function formatRangeLabel(range) {
  const since = range?.since;
  const until = range?.until;
  if (!since && !until) return "All time";
  if (since && !until) return `${formatDateLabel(since)} – now`;
  if (!since && until) return `Through ${formatDateLabel(until)}`;
  return `${formatDateLabel(since)} – ${formatDateLabel(until)}`;
}

// Default "Period B" for the comparison toggle: the window of the SAME
// LENGTH as `range`, immediately preceding it (ending the day before
// `range.since` starts). Only meaningful when `range` has a real `since` -
// an "All time" primary range has no natural "period before all time", so
// callers (GameplayDateFilter.jsx) should fall back to a blank custom range
// in that case rather than calling this. When `range.until` is also unset
// (an open-ended "Last N days" preset with an implicit "now" upper bound),
// falls back to a 30-day-long comparison window - a reasonable default
// rather than refusing to suggest anything.
export function previousPeriod(range) {
  if (!range?.since) return { since: null, until: null };
  const sinceDate = parseLocalDateStr(range.since);
  const untilDate = new Date(sinceDate);
  untilDate.setDate(untilDate.getDate() - 1);   // the day before `range` starts

  let lengthDays = 30;
  if (range.until) {
    const untilA = parseLocalDateStr(range.until);
    lengthDays = Math.max(1, Math.round((untilA - sinceDate) / 86400000) + 1);
  }
  const prevSinceDate = new Date(untilDate);
  prevSinceDate.setDate(prevSinceDate.getDate() - (lengthDays - 1));

  return { since: toDateStr(prevSinceDate), until: toDateStr(untilDate) };
}
