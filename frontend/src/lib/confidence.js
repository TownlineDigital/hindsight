// Shared confidence threshold - pulled out of MatchEvents.jsx into its own
// plain .js module (rather than exporting it from the .jsx file directly)
// so pure-logic files like clarifications.js can import it too: Node's
// built-in test runner (used by clarifications.test.mjs/battleTimeline.test.mjs)
// can't load a .jsx file directly (no JSX transform outside Vite/Babel), so
// anything meant to be both React-usable AND plain-Node-testable has to live
// in a .js file with no JSX in it.
//
// Below this, an event gets a visible "worth checking" flag - not because
// anything's necessarily wrong, but because it's the AI's own signal that
// this particular read is less certain than most. 0.9 was picked by looking
// at real extracted data: routine field_state reads come back at a full
// 1.0, while reads that involved some inference or a fuzzy species match
// (team_preview, pokemon_fainted) commonly land around 0.8 - including a
// real misread this threshold was tuned to actually catch (an opponent's
// Pokemon reported as "Charizard" while the event's own detail text said
// "Staraptor fainted", a genuine name-canonicalization mismatch).
export const LOW_CONFIDENCE_THRESHOLD = 0.9;
