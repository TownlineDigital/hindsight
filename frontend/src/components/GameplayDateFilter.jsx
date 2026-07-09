import { useState } from "react";
import { PRESETS, rangeForPreset, previousPeriod, formatRangeLabel } from "../lib/dateRange.js";

// Which preset button is "active" for a given range - reverse-lookups
// rangeForPreset's own output rather than tracking a separate id in state,
// so a range set any other way (e.g. typed directly into the custom date
// inputs) still highlights the right button when it happens to match one.
function presetIdForRange(range) {
  if (!range?.since && !range?.until) return "all";
  for (const p of PRESETS) {
    if (p.id === "all" || p.id === "custom") continue;
    const preset = rangeForPreset(p.id);
    if (preset.since === range?.since && preset.until === range?.until) return p.id;
  }
  return "custom";
}

// One row of preset buttons + (when "custom" is active) a pair of raw date
// inputs - reused for both Period A (always shown) and Period B (only shown
// once comparison mode is toggled on, see below).
function RangeRow({ range, onChange }) {
  const activePreset = presetIdForRange(range);
  return (
    <>
      <div className="tabs-inline small">
        {PRESETS.map((p) => (
          <button
            type="button" key={p.id}
            className={`tab-inline ${activePreset === p.id ? "active" : ""}`}
            onClick={() => onChange(p.id === "custom" ? range : rangeForPreset(p.id))}
          >
            {p.label}
          </button>
        ))}
      </div>
      {activePreset === "custom" && (
        <div className="two-col" style={{ marginTop: 8 }}>
          <label className="field small">
            <span>From</span>
            <input
              type="date" value={range?.since || ""}
              onChange={(e) => onChange({ ...range, since: e.target.value || null })}
            />
          </label>
          <label className="field small">
            <span>To</span>
            <input
              type="date" value={range?.until || ""}
              onChange={(e) => onChange({ ...range, until: e.target.value || null })}
            />
          </label>
        </div>
      )}
    </>
  );
}

// Shown above the tabs whenever the header's Gameplay dropdown is on "All
// Gameplay (Combined)" (see App.jsx's isCombined) - lets the combined view
// be narrowed to a date window (range) and, optionally, compared against a
// second window (compareRange). Both props are {since, until} objects (or
// compareRange is null when comparison isn't active) - see lib/dateRange.js
// for the exact shape and helpers.
export default function GameplayDateFilter({ range, onRangeChange, compareRange, onCompareRangeChange }) {
  const [compareEnabled, setCompareEnabled] = useState(!!compareRange);

  function toggleCompare(checked) {
    setCompareEnabled(checked);
    if (!checked) {
      onCompareRangeChange(null);
      return;
    }
    // Default Period B to the equal-length window immediately before Period
    // A - the obvious "compare to the period right before this one" case.
    // An "All time" Period A has no natural "period before all time," so
    // that falls back to a blank custom range instead (previousPeriod's own
    // contract - see its docstring).
    onCompareRangeChange(previousPeriod(range));
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="matches-note-row" style={{ marginBottom: 10 }}>
        <div className="note-banner">
          Showing <strong>{formatRangeLabel(range)}</strong>
          {compareRange && <> compared to <strong>{formatRangeLabel(compareRange)}</strong></>}
          . This narrows every combined tab (Overview, Matches, Opponent intel, Progression) down to the
          selected window.
        </div>
      </div>

      <RangeRow range={range} onChange={onRangeChange} />

      <label className="field small" style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12 }}>
        <input
          type="checkbox" checked={compareEnabled}
          onChange={(e) => toggleCompare(e.target.checked)}
        />
        <span>Compare to another period</span>
      </label>

      {compareEnabled && (
        <div style={{ marginTop: 8 }}>
          <div style={{ marginBottom: 6, fontSize: 12.5, color: "var(--muted)", fontWeight: 600 }}>Compared to:</div>
          <RangeRow range={compareRange || { since: null, until: null }} onChange={onCompareRangeChange} />
        </div>
      )}
    </div>
  );
}
