// Side-by-side period comparison for the combined "All Gameplay" view (added
// 2026-07-09, per the user's explicit design choice: delta-arrow stat cards
// in the Overview tab, NOT a trend chart/slider - see ARCHITECTURE_HANDOFF.md's
// date-filter/comparison section for the full rationale). Shown whenever the
// user has the comparison toggle on in GameplayDateFilter.jsx and both
// periods' data has loaded.
//
// periodAData / periodBData are each { record, skillScores } - the same
// shapes analytics.compute_record / compute_skill_scores return (see
// RecordCards.jsx / SkillScores.jsx for how those fields are used
// elsewhere). "A" is always the CURRENTLY SELECTED range (App.jsx's
// dateRange); "B" is the comparison range (compareRange) - by default the
// equal-length window immediately before A (see lib/dateRange.js's
// previousPeriod), so reading each row as "B -> A" naturally reads as
// "before -> after."

function fmtPct(v) {
  return v == null ? "–" : `${v}%`;
}

function fmtScore(v) {
  return v == null ? "–" : v;
}

// delta === null means "don't color or arrow this row" (used for the purely
// informational "matches played" row, where more/fewer isn't good or bad).
function DeltaBadge({ delta, suffix }) {
  if (delta == null || Number.isNaN(delta)) return <span className="note">no change</span>;
  const rounded = Math.round(delta * 10) / 10;
  if (rounded === 0) return <span className="note">no change</span>;
  const up = rounded > 0;
  const cls = up ? "good" : "bad";
  const arrow = up ? "▲" : "▼";
  return (
    <span className={`comparison-delta ${cls}`}>
      {arrow} {Math.abs(rounded)}{suffix || ""}
    </span>
  );
}

function ComparisonRow({ label, aValue, bValue, format, delta, deltaSuffix, informational }) {
  return (
    <div className="comparison-row">
      <div className="comparison-row-label">{label}</div>
      <div className="comparison-row-values">
        <span className="comparison-value">{format(bValue)}</span>
        <span className="comparison-arrow">{"→"}</span>
        <span className="comparison-value comparison-value-current">{format(aValue)}</span>
      </div>
      {!informational && <DeltaBadge delta={delta} suffix={deltaSuffix} />}
    </div>
  );
}

export default function PeriodComparison({ periodALabel, periodBLabel, periodAData, periodBData }) {
  const a = periodAData || {};
  const b = periodBData || {};
  const aRecord = a.record || {};
  const bRecord = b.record || {};
  const aScores = a.skillScores?.scores || {};
  const bScores = b.skillScores?.scores || {};
  const aOverall = a.skillScores?.overall;
  const bOverall = b.skillScores?.overall;

  return (
    <div className="card comparison-card">
      <h3>Period comparison</h3>
      <div className="note" style={{ marginBottom: 12 }}>
        {periodBLabel || "Compared period"} {"→"} {periodALabel || "Selected period"}
      </div>

      <div className="comparison-grid">
        <ComparisonRow
          label="Win rate"
          aValue={aRecord.win_rate} bValue={bRecord.win_rate}
          format={fmtPct}
          delta={aRecord.win_rate != null && bRecord.win_rate != null ? aRecord.win_rate - bRecord.win_rate : null}
          deltaSuffix="pts"
        />
        <ComparisonRow
          label="Record (W-L)"
          aValue={aRecord} bValue={bRecord}
          format={(r) => (r && r.wins != null ? `${r.wins}-${r.losses}` : "–")}
          informational
        />
        <ComparisonRow
          label="Matches played"
          aValue={aRecord.matches} bValue={bRecord.matches}
          format={(v) => (v == null ? "–" : v)}
          informational
        />
        <ComparisonRow
          label="Overall skill score"
          aValue={aOverall} bValue={bOverall}
          format={fmtScore}
          delta={aOverall != null && bOverall != null ? aOverall - bOverall : null}
        />
        <ComparisonRow
          label="Tempo"
          aValue={aScores.tempo} bValue={bScores.tempo}
          format={fmtScore}
          delta={aScores.tempo != null && bScores.tempo != null ? aScores.tempo - bScores.tempo : null}
        />
        <ComparisonRow
          label="Adaptability"
          aValue={aScores.adaptability} bValue={bScores.adaptability}
          format={fmtScore}
          delta={aScores.adaptability != null && bScores.adaptability != null ? aScores.adaptability - bScores.adaptability : null}
        />
        <ComparisonRow
          label="Execution"
          aValue={aScores.execution} bValue={bScores.execution}
          format={fmtScore}
          delta={aScores.execution != null && bScores.execution != null ? aScores.execution - bScores.execution : null}
        />
        <ComparisonRow
          label="Closing"
          aValue={aScores.closing} bValue={bScores.closing}
          format={fmtScore}
          delta={aScores.closing != null && bScores.closing != null ? aScores.closing - bScores.closing : null}
        />
      </div>
    </div>
  );
}
