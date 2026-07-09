// Tests for battleTimeline.js's buildBattleTimeline() - the pure-JS battle-
// state reconstruction that drives BattleReplay.jsx (the "native in-dashboard
// replay" accuracy-check view, see that component's own docstring for why
// this was built instead of exporting to Showdown's exact replay format).
//
// Uses Node's built-in test runner (node:test) + node:assert/strict - no
// devDependency added (vitest/jest etc.), matching this project's existing
// "dependency-free unit tests for every piece of pure logic" convention on
// the Python side (see ARCHITECTURE_HANDOFF.md section 5a).
//
// Run (from frontend/):  node --test src/lib/battleTimeline.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildBattleTimeline } from "./battleTimeline.js";

function sampleEvents() {
  return [
    { event: "team_preview", match: 1, actor: "both", timestamp: 0,
      player_lead: "Rotom, Incineroar", opponent_lead: "Rillaboom, Whimsicott",
      confidence: 1.0 },
    { event: "move_used", match: 1, actor: "player", pokemon: "Incineroar", detail: "Fake Out",
      timestamp: 5, confidence: 0.95, reference_frame: "match_1/f1.jpg" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", hp_percent: 82,
      timestamp: 6, confidence: 0.9 },
    { event: "status_inflicted", match: 1, actor: "opponent", pokemon: "Whimsicott", detail: "burn",
      timestamp: 10, confidence: 0.6 },
    { event: "terastallized", match: 1, actor: "player", pokemon: "Rotom", timestamp: 12, confidence: 1.0 },
    { event: "pokemon_fainted", match: 1, actor: "opponent", pokemon: "Rillaboom", timestamp: 20, confidence: 1.0 },
    { event: "pokemon_sent_out", match: 1, actor: "opponent", pokemon: "Farigiraf", timestamp: 21, confidence: 0.9 },
    { event: "battle_end", match: 1, actor: "player", winner: "player", timestamp: 90, confidence: 1.0 },
  ];
}

test("one frame is produced per event, in timestamp order", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  assert.equal(frames.length, 8);
});

test("team_preview seeds active mons at full HP from the lead fields", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  assert.deepEqual(frames[0].player.map((m) => m.species), ["Rotom", "Incineroar"]);
  assert.deepEqual(frames[0].opponent.map((m) => m.species), ["Rillaboom", "Whimsicott"]);
  assert.equal(frames[0].player[0].hp, 100);
});

test("hp_change updates HP from that frame onward", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  const rillaboom = frames[2].opponent.find((m) => m.species === "Rillaboom");
  assert.equal(rillaboom.hp, 82);
});

test("status_inflicted sticks on the named mon", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  const whimsicott = frames[3].opponent.find((m) => m.species === "Whimsicott");
  assert.equal(whimsicott.status, "burn");
});

test("terastallized sets the tera flag", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  const rotom = frames[4].player.find((m) => m.species === "Rotom");
  assert.equal(rotom.tera, true);
});

test("pokemon_fainted marks fainted and zeroes HP", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  const fainted = frames[5].opponent.find((m) => m.species === "Rillaboom");
  assert.equal(fainted.fainted, true);
  assert.equal(fainted.hp, 0);
});

test("pokemon_sent_out adds the new mon and doubles caps active list at 2, dropping a fainted one first", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  const oppSpecies = frames[6].opponent.map((m) => m.species);
  assert.ok(oppSpecies.includes("Farigiraf"));
  assert.ok(oppSpecies.length <= 2);
});

test("captions are human-readable and name the right actor/species", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  assert.match(frames[1].caption, /Incineroar used Fake Out/);
  assert.match(frames[5].caption, /Opposing Rillaboom fainted/);
  assert.match(frames[4].caption, /Rotom Terastallized/);
  assert.match(frames[7].caption, /You won the match/);
});

test("confidence and reference_frame pass through unchanged, including when absent", () => {
  const frames = buildBattleTimeline(sampleEvents(), 1);
  assert.equal(frames[1].confidence, 0.95);
  assert.equal(frames[1].referenceFrame, "match_1/f1.jpg");
  assert.equal(frames[2].referenceFrame, undefined);
});

test("a match number with no matching events returns an empty array, not a crash", () => {
  assert.deepEqual(buildBattleTimeline(sampleEvents(), 999), []);
});

test("a null hp_percent does not clobber a known HP with a fake value", () => {
  const events = [
    { event: "team_preview", match: 2, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "hp_change", match: 2, actor: "player", pokemon: "Rotom", hp_percent: null, timestamp: 5 },
  ];
  const frames = buildBattleTimeline(events, 2);
  const rotom = frames[1].player.find((m) => m.species === "Rotom");
  assert.equal(rotom.hp, 100);
});

test("hp_percent given as a string like '82%' still parses correctly", () => {
  const events = [
    { event: "team_preview", match: 3, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "hp_change", match: 3, actor: "player", pokemon: "Rotom", hp_percent: "82%", timestamp: 5 },
  ];
  const frames = buildBattleTimeline(events, 3);
  assert.equal(frames[1].player.find((m) => m.species === "Rotom").hp, 82);
});

test("field_state's richer {name, hp_percent} dict shape for active mons is tolerated", () => {
  const events = [
    { event: "team_preview", match: 4, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "field_state", match: 4, timestamp: 5,
      player_active: [{ pokemon: "Rotom", hp_percent: 60 }],
      opponent_active: [{ name: "Rillaboom" }] },
  ];
  const frames = buildBattleTimeline(events, 4);
  assert.deepEqual(frames[1].player.map((m) => m.species), ["Rotom"]);
  assert.deepEqual(frames[1].opponent.map((m) => m.species), ["Rillaboom"]);
});

test("an event with no actor/pokemon (e.g. a bare field_state with no active lists) does not crash and just repeats prior state", () => {
  const events = [
    { event: "team_preview", match: 5, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "field_state", match: 5, timestamp: 5, weather: "Sun" },
  ];
  const frames = buildBattleTimeline(events, 5);
  assert.equal(frames.length, 2);
  assert.match(frames[1].caption, /Weather: Sun/);
  // active mons should still be whatever team_preview set, untouched by the empty field_state
  assert.deepEqual(frames[1].player.map((m) => m.species), ["Rotom"]);
});

// Turn stamping (added 2026-07-09 for the VGC Battle Intelligence Manual
// per-turn recap feature): each frame carries a `turn` field, forward-filled
// from the most recent field_state event's own `turn` - the same convention
// decision_windows.py/strategic_analysis.py already use server-side. This is
// what lets MatchSummary.jsx look up a given frame's per-turn strategic-
// analysis report.

test("frames before the first field_state have turn: null", () => {
  const events = [
    { event: "team_preview", match: 6, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
  ];
  const frames = buildBattleTimeline(events, 6);
  assert.equal(frames[0].turn, null);
});

test("turn is stamped from field_state and carries forward onto later events", () => {
  const events = [
    { event: "team_preview", match: 7, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "field_state", match: 7, timestamp: 5, turn: 1, player_active: ["Rotom"], opponent_active: ["Rillaboom"] },
    { event: "move_used", match: 7, actor: "player", pokemon: "Rotom", detail: "Thunderbolt", timestamp: 6 },
  ];
  const frames = buildBattleTimeline(events, 7);
  assert.equal(frames[1].turn, 1);
  // move_used has no turn field of its own - must inherit the last field_state's turn
  assert.equal(frames[2].turn, 1);
});

test("turn advances on the next field_state and does not reset to null", () => {
  const events = [
    { event: "team_preview", match: 8, timestamp: 0, player_lead: "Rotom", opponent_lead: "Rillaboom" },
    { event: "field_state", match: 8, timestamp: 5, turn: 1, player_active: ["Rotom"], opponent_active: ["Rillaboom"] },
    { event: "field_state", match: 8, timestamp: 10, turn: 2, player_active: ["Rotom"], opponent_active: ["Rillaboom"] },
    { event: "move_used", match: 8, actor: "player", pokemon: "Rotom", detail: "Thunderbolt", timestamp: 11 },
  ];
  const frames = buildBattleTimeline(events, 8);
  assert.equal(frames[1].turn, 1);
  assert.equal(frames[2].turn, 2);
  assert.equal(frames[3].turn, 2);
});
