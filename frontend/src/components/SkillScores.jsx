import { Bar, Ring } from "../lib/charts.jsx";
import { scoreClass } from "../lib/format.js";

const SCORE_META = {
  tempo: { label: "Tempo", desc: "Taking and keeping the initiative" },
  adaptability: { label: "Adaptability", desc: "Varying leads/brings vs different opponents" },
  execution: { label: "Execution", desc: "Trading cleanly, avoiding misplays" },
  closing: { label: "Closing", desc: "Finishing won positions" },
};

export default function SkillScores({ data }) {
  if (!data || data.overall == null) {
    return (
      <div className="card empty">
        {data?.note || "Not enough decided matches yet to compute skill scores."}
      </div>
    );
  }
  return (
    <div className="skill-grid">
      <div className="card hero-card">
        <Ring value={data.overall} colorVar={`--${scoreClass(data.overall) || "accent"}`} label="Overall" size={112} />
        <div className="hero-side">
          <div className="pill">{data.confidence.tier}</div>
          <div className="note">
            {data.matches_analyzed} matches analyzed
            {data.confidence.matches_to_next_tier
              ? ` — ${data.confidence.matches_to_next_tier} more to next tier`
              : ""}
          </div>
        </div>
      </div>
      <div className="card">
        <h3>Progression scores</h3>
        {Object.entries(SCORE_META).map(([key, meta]) => (
          <Bar
            key={key}
            label={meta.label}
            value={data.scores[key]}
            suffix=""
            colorVar={`--${scoreClass(data.scores[key]) || "accent"}`}
            sublabel={`${meta.desc} — ${data.drivers[key]}`}
          />
        ))}
      </div>
    </div>
  );
}
