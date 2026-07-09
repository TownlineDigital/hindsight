"""
Tests for analyze_matches.py's build_event_prompt() - specifically the
roster-constraint wording, which was rewritten after a real bug found during
end-to-end testing: an event's own "detail" text said "The opposing Staraptor
fainted!" while its "pokemon" field said "Charizard", because the OLD prompt
told Gemini to "pick the closest from known teams" and "NEVER output
'unknown'" with no distinction between a minor misread of a real roster name
and a completely different species that isn't in the roster at all. The
fix keeps the same hard requirement (a species name, never "unknown") but
tells the model to drop its confidence sharply and explain the mismatch in
"detail" when what it read doesn't match anything in the known roster - so
a case like the Staraptor/Charizard one shows up with low confidence (which
the dashboard now auto-flags as "worth checking" - see MatchEvents.jsx)
instead of blending in with normal, reliable reads.

Pure string-building logic, no video/Gemini/network involved.

Run: py -m unittest tests.test_build_event_prompt -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import analyze_matches as am  # noqa: E402

_SCHEMA = {
    "event_types": ["move_used", "pokemon_fainted"],
    "fields_to_capture": {"pokemon": "string", "detail": "string"},
    "notes_for_the_ai": "",
}


class TestBuildEventPromptRosterWording(unittest.TestCase):
    def test_includes_known_teams_when_roster_present(self):
        roster = {"player_team": ["Greninja", "Meowscarada"], "opponent_team": ["Charizard", "Primarina"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("Greninja, Meowscarada", prompt)
        self.assertIn("Charizard, Primarina", prompt)

    def test_still_forbids_outputting_unknown(self):
        """The hard requirement downstream code depends on (pokemon is always
        populated, never a literal "unknown" string) must still hold - only
        the confidence/explanation guidance around IT changed."""
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("never output 'unknown'", prompt)

    def test_distinguishes_fuzzy_match_from_no_match_at_all(self):
        """The actual fix: the prompt must tell the model to treat a genuine
        misspelling differently from a totally different species name, since
        conflating the two was the root cause of the Staraptor/Charizard bug."""
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("close/plausible match", prompt)
        self.assertIn("does NOT match any of these names at all", prompt)

    def test_instructs_lowering_confidence_on_a_true_mismatch(self):
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("confidence to 0.3 or", prompt)

    def test_instructs_explaining_the_mismatch_in_detail(self):
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("say plainly in 'detail'", prompt)

    def test_no_roster_text_when_both_teams_empty(self):
        """Unchanged behavior: an empty roster (e.g. roster read totally
        failed) means no KNOWN TEAMS constraint gets added at all - the
        surrounding fallback logic elsewhere already handles that case."""
        prompt = am.build_event_prompt(_SCHEMA, {}, [0.0])
        self.assertNotIn("KNOWN TEAMS", prompt)

    def test_includes_timestamps_and_schema_fields_regardless_of_roster(self):
        prompt = am.build_event_prompt(_SCHEMA, {}, [1.0, 2.5])
        self.assertIn("1s", prompt)
        self.assertIn("Image 1", prompt)
        self.assertIn("Image 2", prompt)
        self.assertIn("pokemon_fainted", prompt)


class TestBuildEventPromptClosedSetNarrowing(unittest.TestCase):
    """Covers the team-preview "brought" (pick-4) closed-set narrowing added
    on top of the roster-wording fix above: battle-frame identification
    should check the narrower brought list FIRST, before falling back to the
    full 6-per-side team, and the prompt should frame the whole thing as a
    closed-set task rather than open recognition - see build_event_prompt's
    own docstring for why (this was a direct response to a user request to
    use team-preview's known roster to narrow identification instead of
    analyzing every Pokemon from scratch each frame)."""

    def test_brought_list_surfaced_and_checked_first_when_present(self):
        roster = {
            "player_team": ["Greninja", "Meowscarada", "Amoonguss", "Rillaboom", "Flutter Mane", "Urshifu"],
            "opponent_team": ["Charizard", "Primarina", "Landorus", "Tornadus", "Gholdengo", "Iron Hands"],
            "player_brought": ["Greninja", "Amoonguss", "Flutter Mane", "Urshifu"],
            "opponent_brought": ["Charizard", "Landorus", "Gholdengo", "Iron Hands"],
        }
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("BROUGHT to battle", prompt)
        self.assertIn("Greninja, Amoonguss, Flutter Mane, Urshifu", prompt)
        self.assertIn("Charizard, Landorus, Gholdengo, Iron Hands", prompt)
        self.assertIn("check there FIRST", prompt)

    def test_no_brought_text_when_brought_missing_falls_back_to_full_team(self):
        """When the brought (pick-4) read didn't succeed, there's no narrower
        list to surface - the prompt should fall back to full-team-only
        wording with no BROUGHT block at all, rather than claiming an empty
        brought list is meaningful."""
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertNotIn("BROUGHT to battle", prompt)

    def test_closed_set_framing_language_present_when_roster_known(self):
        roster = {"player_team": ["Greninja"], "opponent_team": ["Charizard"]}
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("CLOSED-SET identification task", prompt)
        self.assertIn("not open recognition", prompt)

    def test_partial_brought_read_still_surfaces_the_side_that_succeeded(self):
        """A brought read can succeed for one side and fail for the other -
        the prompt should still surface whichever side DID come back, and
        say plainly that the other wasn't confidently read, rather than
        silently dropping the whole brought_txt block."""
        roster = {
            "player_team": ["Greninja", "Meowscarada"],
            "opponent_team": ["Charizard", "Primarina"],
            "player_brought": ["Greninja"],
            "opponent_brought": [],
        }
        prompt = am.build_event_prompt(_SCHEMA, roster, [0.0])
        self.assertIn("BROUGHT to battle", prompt)
        self.assertIn("Player: [Greninja]", prompt)
        self.assertIn("Opponent: [not confidently read]", prompt)


if __name__ == "__main__":
    unittest.main()
