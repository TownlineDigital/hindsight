import { Bar } from "../lib/charts.jsx";
import { CountTable } from "./StatTable.jsx";

// Same 7 bands strategic_analysis.py's POSITION_SCORE_BANDS defines, in the
// same order (Dominating -> Losing) - kept here as a display order only, not
// a re-derivation of the thresholds themselves (those live entirely
// server-side).
const POSITION_BAND_ORDER = [
  "Dominating", "Strong Advantage", "Slight Advantage", "Even",
  "Slight Disadvantage", "Major Disadvantage", "Losing",
];

const RISK_POSTURE_LABELS = {
  safe: "Safe",
  cautiously_safe: "Cautiously safe",
  balanced: "Balanced",
  cautiously_aggressive: "Cautiously aggressive",
  aggressive: "Aggressive",
};

function signed(n) {
  if (n == null) return "–";
  return n >= 0 ? `+${n}` : `${n}`;
}

function toCountRows(counts) {
  return Object.entries(counts || {})
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count);
}

/** Job-wide "overall skill set" view (task #236) - a straightforward rollup
 * of every match's per-turn six battle-intelligence reports (see
 * strategic_analysis.compute_job_battle_profile's own docstring for exactly
 * what's counted/averaged here, and how it deliberately does NOT re-derive
 * SkillScores' separate tempo/adaptability/execution/closing heuristic or
 * the win/loss record shown elsewhere on this tab - this is additional
 * signal, not a restatement). Renders nothing misleading when there's no
 * turn-by-turn data yet (e.g. a job made entirely of pre-2026-07-04
 * Showdown imports) - same "gap, not a fake zero" handling used throughout
 * this dashboard. */
export default function BattleProfile({ data }) {
  if (!data) {
    return (
      <div className="card empty">
        Not enough turn-by-turn data yet for an overall battle profile. This
        needs at least one match with per-turn field-state tracking (see the
        per-turn battle intelligence line in Matches) - Showdown imports from
        before the turn-tracking fix won't have this yet.
      </div>
    );
  }

  const {
    position_score, speed_control, threat_pressure, resource_advantage,
    momentum, risk_management, mistake_patterns, win_condition_patterns, loss_patterns,
  } = data;

  return (
    <div className="battle-profile">
      <div className="card">
        <h3>Overall battle profile</h3>
        <div className="note">
          {data.matches_analyzed} match{data.matches_analyzed === 1 ? "" : "es"} analyzed, {data.turns_analyzed} turns total
          {data.matches_errored > 0 &&
            ` — ${data.matches_errored} match${data.matches_errored === 1 ? "" : "es"} couldn't be analyzed and ${data.matches_errored === 1 ? "is" : "are"} excluded below`}
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Position score</h3>
          <div className={`big ${position_score.average >= 0 ? "good" : "bad"}`}>{signed(position_score.average)}</div>
          <div className="note">
            Best turn {signed(position_score.best)} · Worst turn {signed(position_score.worst)}
            {position_score.final_turn_average != null && ` · Final-turn avg ${signed(position_score.final_turn_average)}`}
          </div>
        </div>
        <div className="card">
          <h3>Position score band distribution</h3>
          {POSITION_BAND_ORDER.map((band) => (
            <Bar key={band} label={band} value={position_score.band_distribution[band] ?? 0} colorVar="--accent" />
          ))}
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Speed control</h3>
          <Bar label="Favorable to you" value={speed_control.player_favorable_pct} colorVar="--good" />
          <Bar label="Favorable to opponent" value={speed_control.opponent_favorable_pct} colorVar="--bad" />
          <Bar label="Contested" value={speed_control.contested_pct} colorVar="--warn" />
          <Bar label="Neither side" value={speed_control.none_pct} colorVar="--muted" />
        </div>
        <div className="card">
          <h3>Threat pressure</h3>
          <Bar label="Favorable to you" value={threat_pressure.player_favorable_pct} colorVar="--good" />
          <Bar label="Favorable to opponent" value={threat_pressure.opponent_favorable_pct} colorVar="--bad" />
          <Bar label="Even" value={threat_pressure.even_pct} colorVar="--warn" />
        </div>
      </div>

      <div className="two-col">
        <CountTable title="Your danger tools" rows={toCountRows(threat_pressure.player_tool_counts)} emptyText="No danger tools tallied yet." />
        <CountTable title="Opponent's danger tools" rows={toCountRows(threat_pressure.opponent_tool_counts)} emptyText="No danger tools tallied yet." />
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Screens</h3>
          <Bar label="Your screen uptime" value={resource_advantage.player_screen_uptime_pct} colorVar="--good" />
          <Bar label="Opponent's screen uptime" value={resource_advantage.opponent_screen_uptime_pct} colorVar="--bad" />
          <div className="note">Average screen score: {resource_advantage.average_screen_score}</div>
        </div>
        <div className="card">
          <h3>Momentum</h3>
          <Bar label="Gained" value={momentum.gained_pct} colorVar="--good" />
          <Bar label="Lost" value={momentum.lost_pct} colorVar="--bad" />
          <Bar label="Neutral" value={momentum.neutral_pct} colorVar="--muted" />
        </div>
      </div>

      <div className="two-col">
        <CountTable title="Momentum events" rows={toCountRows(momentum.event_counts)} emptyText="No momentum events tallied yet." />
        <div className="card">
          <h3>Risk posture</h3>
          {Object.entries(RISK_POSTURE_LABELS).map(([key, label]) => (
            <Bar key={key} label={label} value={risk_management[key] ?? 0} colorVar="--accent" />
          ))}
        </div>
      </div>

      <div className="two-col">
        <CountTable title="Mistake patterns" rows={toCountRows(mistake_patterns.counts_by_type)} emptyText="No mistake candidates flagged yet." />
        <div className="card">
          <h3>Loss patterns</h3>
          {loss_patterns.losses_analyzed === 0 ? (
            <div className="empty">No losses analyzed yet.</div>
          ) : (
            <>
              <div className="note">
                {loss_patterns.losses_analyzed} loss{loss_patterns.losses_analyzed === 1 ? "" : "es"} analyzed
                {loss_patterns.average_decisive_turn != null && ` · average decisive turn ${loss_patterns.average_decisive_turn}`}
              </div>
              {loss_patterns.common_final_blow_pokemon.length > 0 && (
                <div className="mini-table" style={{ marginTop: 10 }}>
                  {loss_patterns.common_final_blow_pokemon.map((p) => (
                    <div className="mini-row" key={p.pokemon}>
                      <span className="mini-label" title={p.pokemon}>{p.pokemon}</span>
                      <span className="mini-pct">{p.count}x final blow</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="two-col">
        <CountTable
          title="Top designated sweepers"
          rows={win_condition_patterns.top_designated_sweepers.map((s) => ({ label: s.pokemon, count: s.times_established }))}
          emptyText="No designated sweepers established yet."
        />
        <CountTable
          title="Top primary closers"
          rows={win_condition_patterns.top_primary_closers.map((s) => ({ label: s.pokemon, count: s.times_established }))}
          emptyText="No primary closers established yet."
        />
      </div>
    </div>
  );
}
