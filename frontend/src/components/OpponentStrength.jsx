import { pctClass } from "../lib/format.js";

export default function OpponentStrength({ data }) {
  const c = data.correlation;
  return (
    <div className="opponent-strength">
      <p className="note">
        How much their brought 4 overlap on shared type weaknesses — a real doubles liability
        (one spread move or a well-picked attacker threatens multiple of their Pokémon at once).
        Lower risk score = tighter-built team. Correlated against your actual results below.
      </p>
      {c ? (
        <div className="overview-grid">
          <div className="card">
            <h3>Median risk score</h3>
            <div className="big">{c.median_risk_score}</div>
            <div className="note">{c.sample_size} matches scored</div>
          </div>
          <div className="card">
            <h3>Win rate vs weaker-built teams</h3>
            <div className={`big ${pctClass(c.win_rate_vs_weaker_built_teams)}`}>{c.win_rate_vs_weaker_built_teams}%</div>
            <div className="note">{c.vs_weaker_built_n} matches (above-median overlap)</div>
          </div>
          <div className="card">
            <h3>Win rate vs tighter-built teams</h3>
            <div className={`big ${pctClass(c.win_rate_vs_tighter_built_teams)}`}>{c.win_rate_vs_tighter_built_teams}%</div>
            <div className="note">{c.vs_tighter_built_n} matches (at/below-median overlap)</div>
          </div>
          <div className="card empty" style={{ gridColumn: "1 / -1" }}>{c.note}</div>
        </div>
      ) : (
        <div className="card empty">Not enough scored matches yet for a meaningful split.</div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr><th>#</th><th>Opponent brought</th><th>Risk score</th><th>Shared weaknesses</th><th>Result</th></tr>
          </thead>
          <tbody>
            {!data.matches.length && <tr><td colSpan={5} className="empty">No data</td></tr>}
            {data.matches.map((m) => {
              const shared = Object.entries(m.shared_weaknesses || {}).map(([t, n]) => `${t} (${n})`).join(", ") || "none";
              const coverageFull = m.coverage === `${(m.opponent_brought || []).length}/${(m.opponent_brought || []).length}`;
              return (
                <tr key={m.match}>
                  <td>{m.match}</td>
                  <td>
                    {(m.opponent_brought || []).join(", ")}
                    {!coverageFull && <span className="note"> ({m.coverage} typed)</span>}
                  </td>
                  <td>{m.risk_score}</td>
                  <td>{shared}</td>
                  <td className={m.player_won ? "good" : "bad"}>{m.player_won ? "You won" : "You lost"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
