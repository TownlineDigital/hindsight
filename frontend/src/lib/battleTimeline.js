// Reconstructs a step-by-step BATTLE STATE (who's active, their HP/status/
// Tera, a plain-English caption) directly from one match's events.json
// entries - the "native in-dashboard replay" accuracy-checking view (chosen
// over generating a Showdown-protocol-shaped export: a real Showdown replay
// is exact simulator output - precise HP fractions, every stat boost/damage
// roll/ability proc - and our video-derived events are an AI's approximate
// read of a stream, so forcing them into that exact format would mean either
// fabricating precision we don't have, or a log full of gaps Showdown's own
// viewer isn't built to render gracefully. This instead walks OUR OWN event
// shape directly and renders whatever we actually know, honestly - a null HP
// stays a null HP, not a guessed number).
//
// Pure functions, no React - BattleReplay.jsx renders the frames this builds.

/** Same tolerant parsing as analyze_matches.py's names_of()/coach_chat.py's
 * split() - a Pokemon-name-bearing field can be a comma string ("A, B"), an
 * array of strings, an array of {name|pokemon|species} dicts (richer
 * field_state formats), or a single dict. Keeping this tolerant here (rather
 * than assuming one shape) matters because field_state's player_active/
 * opponent_active is exactly the field analyze_matches.py's own docstring
 * says can come back in any of these shapes. */
// Exported so lib/clarifications.js can reuse this exact tolerant parsing
// for team_preview's player_brought/opponent_brought fields, rather than a
// second copy that could drift out of sync.
export function namesOf(value) {
  if (value == null) return [];
  if (typeof value === "string") return value.split(",").map((s) => s.trim()).filter(Boolean);
  if (Array.isArray(value)) {
    const out = [];
    for (const item of value) {
      if (typeof item === "string" && item.trim()) out.push(item.trim());
      else if (item && typeof item === "object") {
        const n = item.name || item.pokemon || item.species;
        if (n) out.push(String(n).trim());
      }
    }
    return out;
  }
  if (typeof value === "object") {
    const n = value.name || value.pokemon || value.species;
    return n ? [String(n).trim()] : [];
  }
  return [String(value).trim()];
}

function parseHp(value) {
  if (value == null || value === "") return null;
  const n = Number(String(value).replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) ? n : null;
}

function actorPrefix(actor) {
  return actor === "opponent" ? "Opposing " : "";
}

/** Builds the human-readable line shown under each step. Deliberately
 * per-event-type rather than one generic template, since "what happened"
 * reads very differently for a faint vs a Tera vs a status - falls back to
 * a generic "{actor} {pokemon} {event_type}" for any event type not
 * explicitly handled, so a future new event type still renders SOMETHING
 * instead of breaking. */
function captionFor(e, playerActive, opponentActive) {
  const prefix = actorPrefix(e.actor);
  const mon = e.pokemon || "";
  switch (e.event) {
    case "team_preview":
      return `Team preview - you lead with ${e.player_lead || "?"}; opponent leads with ${e.opponent_lead || "?"}.`;
    case "pokemon_sent_out":
      return `${prefix}${mon} sent out.`;
    case "move_used":
      return `${prefix}${mon} used ${e.detail || "a move"}.`;
    case "pokemon_fainted":
      return `${prefix}${mon} fainted!`;
    case "status_inflicted":
      return `${prefix}${mon} was affected by ${e.detail || "a status condition"}.`;
    case "terastallized":
      return `${prefix}${mon} Terastallized!`;
    case "hp_change":
      return `${prefix}${mon}'s HP is now ${e.hp_percent != null ? `${e.hp_percent}%` : "unknown"}.`;
    case "item_or_ability_activated":
      return `${prefix}${mon}: ${e.detail || ""}`.trim();
    case "battle_end":
      if (e.winner === "player") return "You won the match!";
      if (e.winner === "opponent") return "You lost the match.";
      return "Match ended (result unclear).";
    case "field_state": {
      const bits = [];
      if (e.weather) bits.push(`Weather: ${e.weather}`);
      if (e.terrain) bits.push(`Terrain: ${e.terrain}`);
      if (e.trick_room) bits.push("Trick Room active");
      if (e.tailwind) bits.push("Tailwind active");
      if (e.screens) bits.push(`Screens: ${e.screens}`);
      if (bits.length) return bits.join(" - ");
      return `Now active: ${playerActive.join(" + ") || "?"} vs ${opponentActive.join(" + ") || "?"}`;
    }
    default:
      return `${prefix}${mon} ${String(e.event || "").replace(/_/g, " ")}`.trim();
  }
}

/** The core reconstruction. Returns one frame per event (in timestamp
 * order) for the given match: { idx, timestamp, event, actor, confidence,
 * referenceFrame, caption, player: MonState[], opponent: MonState[] }, where
 * MonState = { species, hp: number|null, status: string|null, tera: bool,
 * fainted: bool }.
 *
 * State-tracking approach: keyed by species name (not a Showdown-style slot
 * ID - this project's event data doesn't carry one), because that's the same
 * join key analyze_matches.py's own derive_brought() already uses. field_state
 * events (video-sourced matches) are the authoritative "who's on the field
 * right now" signal when present; pokemon_sent_out events (present on BOTH
 * video- and Showdown-sourced matches - see analyze_matches.py's `single`
 * event-type set) are what drives that same tracking when no field_state
 * events exist at all (a Showdown-sourced job has none). Doubles caps active
 * mons at 2/side, best-effort (drops an already-fainted one if a 3rd
 * genuinely gets added) rather than crashing on a data shape that doesn't
 * perfectly fit. */
export function buildBattleTimeline(events, matchNumber) {
  const matchEvents = (events || [])
    .map((e, i) => ({ ...e, __idx: i }))
    .filter((e) => e.match === matchNumber)
    .sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));

  const sideState = { player: new Map(), opponent: new Map() };
  let playerActive = [];
  let opponentActive = [];
  // Forward-filled from each field_state event's own `turn` field onto every
  // frame that follows it - the SAME convention decision_windows.py/
  // strategic_analysis.py use server-side (a field_state's turn number
  // applies to every subsequent event until the next field_state). This is
  // what lets MatchSummary.jsx look up that turn's strategic-analysis report
  // (GET /jobs/{id}/strategic-analysis) for a given frame - added 2026-07-09
  // for the VGC Battle Intelligence Manual per-turn recap feature. null until
  // the match's first field_state event (no turn number known yet).
  let currentTurn = null;

  function ensureMon(side, species) {
    if (!species) return null;
    if (!sideState[side].has(species)) {
      sideState[side].set(species, { species, hp: 100, status: null, tera: false, fainted: false });
    }
    return sideState[side].get(species);
  }

  function pushActive(side, species) {
    const list = side === "player" ? playerActive : opponentActive;
    if (list.includes(species)) return;
    list.push(species);
    while (list.length > 2) {
      const dropIdx = list.findIndex((sp) => sideState[side].get(sp)?.fainted);
      list.splice(dropIdx === -1 ? 0 : dropIdx, 1);
    }
  }

  function snapshotSide(side, activeList) {
    return activeList.map((sp) => {
      const st = sideState[side].get(sp);
      return st ? { ...st } : { species: sp, hp: null, status: null, tera: false, fainted: false };
    });
  }

  const frames = [];

  for (const e of matchEvents) {
    const side = e.actor === "opponent" ? "opponent" : e.actor === "player" ? "player" : null;

    if (e.event === "team_preview") {
      playerActive = namesOf(e.player_lead);
      opponentActive = namesOf(e.opponent_lead);
      playerActive.forEach((sp) => ensureMon("player", sp));
      opponentActive.forEach((sp) => ensureMon("opponent", sp));
    } else if (e.event === "field_state") {
      const newPlayer = namesOf(e.player_active);
      const newOpponent = namesOf(e.opponent_active);
      if (newPlayer.length) playerActive = newPlayer;
      if (newOpponent.length) opponentActive = newOpponent;
      playerActive.forEach((sp) => ensureMon("player", sp));
      opponentActive.forEach((sp) => ensureMon("opponent", sp));
      if (e.turn != null) currentTurn = e.turn;
    } else if (e.event === "pokemon_sent_out" && side && e.pokemon) {
      ensureMon(side, e.pokemon);
      pushActive(side, e.pokemon);
    } else if (side && e.pokemon) {
      const mon = ensureMon(side, e.pokemon);
      if (e.event === "pokemon_fainted") {
        mon.hp = 0;
        mon.fainted = true;
      }
      if (e.event === "hp_change") {
        const hp = parseHp(e.hp_percent);
        if (hp != null) mon.hp = hp;
      }
      if (e.event === "status_inflicted" && e.detail) {
        mon.status = e.detail;
      }
      if (e.event === "terastallized") {
        mon.tera = true;
      }
      pushActive(side, e.pokemon);
    }

    frames.push({
      idx: e.__idx,
      timestamp: e.timestamp,
      event: e.event,
      actor: e.actor,
      confidence: e.confidence,
      referenceFrame: e.reference_frame,
      caption: captionFor(e, playerActive, opponentActive),
      player: snapshotSide("player", playerActive),
      opponent: snapshotSide("opponent", opponentActive),
      turn: currentTurn,
    });
  }

  return frames;
}
