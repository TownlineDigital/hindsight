import { Ring, TrendLine } from "../lib/charts.jsx";
import { pctClass } from "../lib/format.js";

export default function RecordCards({ record, report, trend }) {
  const winRateClass = pctClass(record.win_rate);
  return (
    <div className="overview-grid">
      <div className="card hero-card">
        <Ring value={record.win_rate} colorVar={`--${winRateClass || "accent"}`} label="Win rate" />
        <div className="hero-side">
          <div className="hero-big">{record.wins}-{record.losses}</div>
          <div className="note">
            {record.undetermined
              ? `${record.matches} decided (${record.undetermined} of ${record.total_games} games had no result captured)`
              : `${record.matches} matches recorded`}
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Win rate trend</h3>
        <TrendLine points={trend} />
        <div className="note">Cumulative win % across decided matches, in order.</div>
      </div>

      <div className="stat-cards">
        <div className="card">
          <h3>KO differential / match</h3>
          <div className="big">{report.combat.ko_differential_avg >= 0 ? "+" : ""}{report.combat.ko_differential_avg}</div>
          <div className="note">{report.combat.kos_landed} landed / {report.combat.pokemon_lost} lost</div>
        </div>
        <div className="card">
          <h3>Avg winning margin</h3>
          <div className="big">{report.combat.avg_winning_margin}</div>
          <div className="note">Pokémon left when you win</div>
        </div>
        <div className="card">
          <h3>Most common lead</h3>
          <div className="big small-text">{report.leads.most_common}</div>
          <div className="note">{report.leads.predictability_pct}% of games</div>
        </div>
        {report.tera && (
          <div className="card">
            <h3>Win rate with Tera</h3>
            <div className={`big ${pctClass(report.tera.win_rate_with)}`}>{report.tera.win_rate_with}%</div>
            <div className="note">vs {report.tera.win_rate_without}% without ({report.tera.matches_with} matches)</div>
          </div>
        )}
      </div>
    </div>
  );
}
