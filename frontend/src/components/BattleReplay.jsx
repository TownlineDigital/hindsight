import { useEffect, useMemo, useRef, useState } from "react";
import { buildBattleTimeline } from "../lib/battleTimeline.js";
import { Bar } from "../lib/charts.jsx";
import { EventThumb, ImageLightbox } from "./MatchEvents.jsx";

const AUTOPLAY_MS = 1400;

// Classic HP-bar color thresholds (green/yellow/red) - deliberately different
// thresholds than format.js's pctClass (win rate: 60/40) or scoreClass (skill
// score: 70/35), since "is this Pokemon in danger" is its own judgment call,
// not a win-rate or skill-tier one.
function hpColorVar(hp) {
  if (hp == null) return "--muted";
  if (hp <= 20) return "--bad";
  if (hp <= 50) return "--warn";
  return "--good";
}

function confidenceBadgeClass(confidence) {
  if (confidence < 0.7) return "bad";
  if (confidence < 0.9) return "warn";
  return "good";
}

function MonCard({ mon }) {
  return (
    <div className={`replay-mon-card ${mon.fainted ? "fainted" : ""}`}>
      <div className="replay-mon-name">
        <span>{mon.species}</span>
        {mon.tera && <span className="badge accent" title="Terastallized">TERA</span>}
        {mon.status && <span className="badge warn" title="Status condition">{mon.status}</span>}
        {mon.fainted && <span className="badge bad" title="Fainted">fainted</span>}
      </div>
      <Bar value={mon.hp} colorVar={hpColorVar(mon.hp)} suffix={mon.hp == null ? "" : "%"} />
    </div>
  );
}

/** The "native in-dashboard replay" accuracy-check view - steps through one
 * match's events.json entries in order, showing a reconstructed battle state
 * (active Pokemon, HP, status, Tera) alongside the exact reference frame the
 * AI read for that step, so a wrong extraction is visible at a glance rather
 * than needing to cross-reference a flat event list against raw footage by
 * hand. See lib/battleTimeline.js for the reconstruction logic and its
 * honesty caveats (a null HP stays null - never a guessed number). */
export default function BattleReplay({ jobId, events, matchNumber }) {
  const frames = useMemo(() => buildBattleTimeline(events, matchNumber), [events, matchNumber]);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [enlargedSrc, setEnlargedSrc] = useState(null);
  const timerRef = useRef(null);

  // Reset to the start whenever a different match is opened.
  useEffect(() => {
    setI(0);
    setPlaying(false);
  }, [matchNumber]);

  useEffect(() => {
    if (!playing) {
      if (timerRef.current) clearInterval(timerRef.current);
      return undefined;
    }
    timerRef.current = setInterval(() => {
      setI((cur) => {
        if (cur >= frames.length - 1) {
          setPlaying(false);
          return cur;
        }
        return cur + 1;
      });
    }, AUTOPLAY_MS);
    return () => clearInterval(timerRef.current);
  }, [playing, frames.length]);

  if (!frames.length) {
    return <div className="empty">No events recorded for this match.</div>;
  }

  const frame = frames[Math.min(i, frames.length - 1)];

  return (
    <div className="battle-replay">
      <div className="replay-sides">
        <div className="replay-side">
          <div className="replay-side-label">You</div>
          {frame.player.length
            ? frame.player.map((m) => <MonCard key={m.species} mon={m} />)
            : <div className="empty">No active Pokémon known yet.</div>}
        </div>
        <div className="replay-vs">vs</div>
        <div className="replay-side">
          <div className="replay-side-label">Opponent</div>
          {frame.opponent.length
            ? frame.opponent.map((m) => <MonCard key={m.species} mon={m} />)
            : <div className="empty">No active Pokémon known yet.</div>}
        </div>
      </div>

      <div className="replay-caption-row">
        <div className="replay-caption">
          {typeof frame.timestamp === "number" && <span className="replay-timestamp">{frame.timestamp.toFixed(1)}s </span>}
          {frame.caption}
        </div>
        {typeof frame.confidence === "number" && (
          <span className={`badge ${confidenceBadgeClass(frame.confidence)}`} title="How confident the AI was in this specific read">
            {Math.round(frame.confidence * 100)}% confidence
          </span>
        )}
      </div>

      {frame.referenceFrame ? (
        <div className="replay-frame">
          <EventThumb jobId={jobId} framePath={frame.referenceFrame} onEnlarge={setEnlargedSrc} />
          <div className="note">Source frame the AI read for this step - compare it against the reconstruction above.</div>
        </div>
      ) : (
        <div className="note">No source frame stored for this step (Showdown-sourced matches, or an inter-match summary event, have none).</div>
      )}

      <div className="replay-controls">
        <button type="button" onClick={() => { setPlaying(false); setI((x) => Math.max(0, x - 1)); }} disabled={i === 0}>
          ◂ Prev
        </button>
        <button type="button" onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "▸ Play"}</button>
        <button
          type="button"
          onClick={() => { setPlaying(false); setI((x) => Math.min(frames.length - 1, x + 1)); }}
          disabled={i === frames.length - 1}
        >
          Next ▸
        </button>
        <span className="replay-progress">Step {i + 1} of {frames.length}</span>
      </div>

      {enlargedSrc && <ImageLightbox src={enlargedSrc} onClose={() => setEnlargedSrc(null)} />}
    </div>
  );
}
