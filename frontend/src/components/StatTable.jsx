import { pctClass } from "../lib/format.js";

/** rows: [{label, wins, total, winPct}], sorted by caller. Renders an inline
 * bar behind the win% so patterns pop out at a glance instead of requiring
 * you to read every number. */
export function WinRateTable({ title, rows, emptyText = "No data yet." }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      {!rows.length ? (
        <div className="empty">{emptyText}</div>
      ) : (
        <div className="mini-table">
          {rows.map((r) => (
            <div className="mini-row" key={r.label}>
              <span className="mini-label" title={r.label}>{r.label}</span>
              <span className="mini-record">{r.wins}-{r.total - r.wins}</span>
              <div className="mini-bar-track">
                <div className={`mini-bar-fill ${pctClass(r.winPct)}`} style={{ width: `${r.winPct}%` }} />
              </div>
              <span className={`mini-pct ${pctClass(r.winPct)}`}>{r.winPct}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** rows: [{label, count}] for plain-usage stats (no win-rate dimension). */
export function CountTable({ title, rows, emptyText = "No data yet." }) {
  const max = rows.length ? Math.max(...rows.map((r) => r.count)) : 1;
  return (
    <div className="card">
      <h3>{title}</h3>
      {!rows.length ? (
        <div className="empty">{emptyText}</div>
      ) : (
        <div className="mini-table">
          {rows.map((r) => (
            <div className="mini-row" key={r.label}>
              <span className="mini-label" title={r.label}>{r.label}</span>
              <div className="mini-bar-track">
                <div className="mini-bar-fill accent" style={{ width: `${(r.count / max) * 100}%` }} />
              </div>
              <span className="mini-pct">{r.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
