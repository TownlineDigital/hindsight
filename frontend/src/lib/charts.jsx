// Small hand-rolled SVG chart primitives - deliberately no charting library
// dependency (recharts/chart.js etc.) for a project this size; these three
// components cover every visualization the dashboard needs.

/** Horizontal bar with a label, a value, and a colored fill proportional to
 * `value` out of `max` (defaults to a 0-100 percent bar). */
export function Bar({ label, value, max = 100, colorVar = "--accent", suffix = "%", sublabel }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="bar-row">
      <div className="bar-row-top">
        <span className="bar-label">{label}</span>
        <span className="bar-value">{value == null ? "–" : `${value}${suffix}`}</span>
      </div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: `var(${colorVar})` }} />
      </div>
      {sublabel && <div className="bar-sublabel">{sublabel}</div>}
    </div>
  );
}

/** A ring/donut showing a single 0-100 value (used for win rate + overall skill). */
export function Ring({ value, size = 96, stroke = 10, colorVar = "--accent", label, sublabel }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
  const offset = c - (pct / 100) * c;
  return (
    <div className="ring-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={`var(${colorVar})`} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset .6s ease" }}
        />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="ring-value">
          {value == null ? "–" : Math.round(value)}
        </text>
      </svg>
      {label && <div className="ring-label">{label}</div>}
      {sublabel && <div className="ring-sublabel">{sublabel}</div>}
    </div>
  );
}

/** A simple win/loss trend line across matches in order (cumulative win %). */
export function TrendLine({ points, width = 560, height = 90 }) {
  if (!points || points.length < 2) {
    return <div className="empty">Not enough decided matches yet for a trend line.</div>;
  }
  const max = 100, min = 0;
  const stepX = width / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = i * stepX;
    const y = height - ((p - min) / (max - min)) * height;
    return [x, y];
  });
  const path = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1];
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="trendline">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" strokeDasharray="4 4" />
      <path d={areaPath} fill="var(--accent-fade)" stroke="none" />
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="3.5" fill={last >= 50 ? "var(--good)" : "var(--bad)"} />
    </svg>
  );
}

/** Several 0-100 series plotted on one shared x-axis (session index) - used
 * for the career skill-score trend (tempo/adaptability/execution/closing/
 * overall across every upload session). Each series is
 * { label, colorVar, points: (number|null)[] } - a null point (a session
 * with too few decided matches to score, see skill_scores.py's confidence
 * tiers) breaks the line rather than plotting a false 0, the same
 * "don't fake a number, show the gap" principle used elsewhere in this
 * dashboard (e.g. Bar's "–" for a null value). Includes its own legend since
 * multiple series without one would just be unreadable colored spaghetti. */
export function MultiTrendLine({ series, width = 640, height = 180, xLabels }) {
  const withData = (series || []).filter((s) => (s.points || []).some((p) => p != null));
  const n = Math.max(0, ...withData.map((s) => s.points.length));
  if (!withData.length || n < 2) {
    return <div className="empty">Not enough sessions yet for a trend line - upload and finish at least two.</div>;
  }
  const stepX = width / (n - 1);
  const toY = (v) => height - (Math.max(0, Math.min(100, v)) / 100) * height;

  // Build one <path> per contiguous run of non-null points, per series -
  // this is what makes a gap (an early low-sample session) render as a
  // visible break instead of silently interpolating across it.
  const seriesSegments = withData.map((s) => {
    const segments = [];
    let current = [];
    s.points.forEach((v, i) => {
      if (v == null) {
        if (current.length) segments.push(current);
        current = [];
        return;
      }
      current.push([i * stepX, toY(v)]);
    });
    if (current.length) segments.push(current);
    return { ...s, segments };
  });

  return (
    <div className="multitrend">
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="trendline">
        {[0, 25, 50, 75, 100].map((v) => (
          <line key={v} x1="0" y1={toY(v)} x2={width} y2={toY(v)} stroke="var(--border)" strokeDasharray="4 4" />
        ))}
        {seriesSegments.map((s) => (
          <g key={s.label}>
            {s.segments.map((seg, si) => (
              <path
                key={si}
                d={seg.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
                fill="none" stroke={`var(${s.colorVar})`}
                strokeWidth={s.label === "Overall" ? 2.5 : 1.5}
                opacity={s.label === "Overall" ? 1 : 0.75}
              />
            ))}
            {s.segments.map((seg, si) =>
              seg.map(([x, y], i) => (
                <circle key={`${si}-${i}`} cx={x} cy={y} r={s.label === "Overall" ? 3 : 2} fill={`var(${s.colorVar})`} />
              ))
            )}
          </g>
        ))}
      </svg>
      <div className="multitrend-legend">
        {withData.map((s) => (
          <span key={s.label} className="legend-item">
            <span className="legend-swatch" style={{ background: `var(${s.colorVar})` }} />
            {s.label}
          </span>
        ))}
      </div>
      {xLabels && (
        <div className="multitrend-xlabels">
          {xLabels.map((l, i) => <span key={i}>{l}</span>)}
        </div>
      )}
    </div>
  );
}
