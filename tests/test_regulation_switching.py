"""
Tests for analyze_matches.py's regulation-switching mechanism: load_regulation(),
configure_regulation(), and build_roster_prompt() - the pieces that make
--regulation actually DO something instead of just being an accepted-and-ignored
flag. See ARCHITECTURE_HANDOFF.md section 3a.

Runs against the REAL adapters/ directory (same pattern as
test_compose_schema_regulation.py and test_species_legality.py) - there's real
value in these tests failing if adapters/pokemon/regulations/m-a.json or
m-b.json ever get corrupted or drift out of sync with the hardcoded
ALLOWED_SPECIES default.

IMPORTANT: configure_regulation() mutates analyze_matches.ALLOWED_SPECIES /
_ALLOWED_NORM as module-level globals (by design - every legality-checking
function reads them directly). Every test that calls it must restore the
original values in tearDown, or it will bleed into unrelated tests that run
after it (including tests in OTHER files, since unittest discover shares one
process/one import of analyze_matches).

Run: py -m unittest tests.test_regulation_switching -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import analyze_matches as am  # noqa: E402

ADAPTERS = os.path.join(BASE_DIR, "adapters")


class RestoresGlobalsMixin(unittest.TestCase):
    """configure_regulation() reassigns am.ALLOWED_SPECIES/_ALLOWED_NORM in
    place - save + restore them around every test so this file's runs don't
    leak state into tests in other files (species-legality tests in
    particular assume the module's own default M-B roster is active)."""

    def setUp(self):
        self._orig_species = am.ALLOWED_SPECIES
        self._orig_norm = am._ALLOWED_NORM

    def tearDown(self):
        am.ALLOWED_SPECIES = self._orig_species
        am._ALLOWED_NORM = self._orig_norm


class TestLoadRegulation(unittest.TestCase):
    def test_loads_mb_data(self):
        data = am.load_regulation(ADAPTERS, "m-b")
        self.assertEqual(data["regulation"], "M-B")
        self.assertIn("species", data)
        self.assertGreater(len(data["species"]), 0)

    def test_loads_ma_data(self):
        data = am.load_regulation(ADAPTERS, "m-a")
        self.assertEqual(data["regulation"], "M-A")

    def test_missing_regulation_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            am.load_regulation(ADAPTERS, "z-9-doesnt-exist")


class TestConfigureRegulation(RestoresGlobalsMixin):
    def test_switching_to_ma_shrinks_the_allowlist(self):
        """M-A (186 species) is a strict subset of M-B (212) - switching to
        it must actually shrink what's considered legal, not just accept the
        flag and keep M-B's roster active."""
        am.configure_regulation(ADAPTERS, "m-b")
        mb_count = len(am.ALLOWED_SPECIES)
        am.configure_regulation(ADAPTERS, "m-a")
        ma_count = len(am.ALLOWED_SPECIES)
        self.assertEqual(mb_count, 212)
        self.assertEqual(ma_count, 186)
        self.assertLess(ma_count, mb_count)

    def test_ma_only_species_rejected_under_ma_but_legal_under_mb(self):
        """Metagross is a confirmed M-B addition (not in the M-A launch
        roster) - it must be rejected as illegal once M-A is configured, and
        legal again once M-B is configured. This is the actual end-to-end
        proof that flag_banned_species (which reads the module globals, not
        a parameter) respects whichever regulation was last configured."""
        am.configure_regulation(ADAPTERS, "m-a")
        rejected_under_ma = am.flag_banned_species(["Metagross"])
        self.assertEqual(rejected_under_ma, ["Metagross"])

        am.configure_regulation(ADAPTERS, "m-b")
        self.assertEqual(am.flag_banned_species(["Metagross"]), [])

    def test_configure_regulation_returns_the_loaded_data(self):
        data = am.configure_regulation(ADAPTERS, "m-b")
        self.assertEqual(data["regulation"], "M-B")

    def test_unknown_regulation_exits_with_a_clear_message(self):
        with self.assertRaises(SystemExit) as ctx:
            am.configure_regulation(ADAPTERS, "z-9-doesnt-exist")
        self.assertIn("No regulation data file", str(ctx.exception))

    def test_default_module_constant_matches_mb_species_exactly(self):
        """The hardcoded ALLOWED_SPECIES constant (the zero-file-IO default
        used when nothing ever calls configure_regulation) is documented as
        being identical to m-b.json's own species list - catch the two
        drifting apart silently."""
        mb_data = am.load_regulation(ADAPTERS, "m-b")
        mb_species_from_file = {s.strip().lower() for s in mb_data["species"]}
        self.assertEqual(self._orig_species, mb_species_from_file)


class TestBuildRosterPrompt(unittest.TestCase):
    def test_none_rules_defaults_to_doubles_shaped_prompt(self):
        """Backward compatibility: any existing caller that doesn't pass
        `rules` at all (rules=None) must get the original, only-ever-tested
        doubles-shaped prompt - not silently switch to singles-shaped
        wording."""
        prompt = am.build_roster_prompt(None)
        self.assertIn("DOUBLES", prompt)
        self.assertIn("player_brought", prompt)

    def test_doubles_rules_mention_bring_count(self):
        prompt = am.build_roster_prompt({"bring_count": 4, "team_size": 6})
        self.assertIn("DOUBLES", prompt)
        self.assertIn("4", prompt)

    def test_singles_rules_do_not_mention_a_pick_step(self):
        """Singles has no 'pick 4 of 6' team-preview step at all - the
        prompt must not ask the model to find one."""
        prompt = am.build_roster_prompt({"bring_count": None, "team_size_min": 3, "team_size_max": 6})
        self.assertIn("SINGLES", prompt)
        self.assertNotIn("DOUBLES", prompt)

    def test_singles_and_doubles_prompts_differ(self):
        doubles_prompt = am.build_roster_prompt({"bring_count": 4, "team_size": 6})
        singles_prompt = am.build_roster_prompt({"bring_count": None})
        self.assertNotEqual(doubles_prompt, singles_prompt)

    def test_empty_dict_rules_treated_as_singles_shaped(self):
        """rules={} has no bring_count key at all (falsy via .get default) -
        must take the same no-pick-step branch as an explicit bring_count=None,
        not crash or default back to doubles."""
        prompt = am.build_roster_prompt({})
        self.assertIn("SINGLES", prompt)


def _sent_out_events(player_species, opponent_species):
    """Builds a minimal list of pokemon_sent_out events (the shape
    derive_brought actually scans), one per species per side, in appearance
    order, at increasing timestamps - just enough for derive_brought to
    derive brought/lead from."""
    events = []
    ts = 0.0
    for nm in player_species:
        events.append({"timestamp": ts, "event": "pokemon_sent_out", "actor": "player", "pokemon": nm})
        ts += 1.0
    for nm in opponent_species:
        events.append({"timestamp": ts, "event": "pokemon_sent_out", "actor": "opponent", "pokemon": nm})
        ts += 1.0
    return events


class TestDeriveBrought(unittest.TestCase):
    """Tests for analyze_matches.derive_brought()'s `rules` parameter - the
    mode-aware brought/lead cap fix. Before this parameter existed, brought
    was always capped at 4 and lead at 2 regardless of mode, which silently
    mis-derived Singles matches (only 1 Pokemon is ever active, and a 5-6
    Pokemon Singles team could have its brought list wrongly truncated)."""

    PLAYER_TEAM = ["Charizard", "Venusaur", "Blastoise", "Pikachu", "Gengar", "Dragonite"]
    OPPONENT_TEAM = ["Tyranitar", "Garchomp", "Metagross", "Hydreigon", "Excadrill", "Scizor"]

    def setUp(self):
        # 5 distinct species appear on each side - enough to distinguish a 4-cap
        # (doubles) from an uncapped/6-max result (singles).
        self.player_appeared = self.PLAYER_TEAM[:5]
        self.opponent_appeared = self.OPPONENT_TEAM[:5]
        self.events = _sent_out_events(self.player_appeared, self.opponent_appeared)
        self.roster = {"player_team": self.PLAYER_TEAM, "opponent_team": self.OPPONENT_TEAM}

    def test_rules_none_defaults_to_doubles_shaped_caps(self):
        """Backward compatibility: no `rules` at all must still get the
        ORIGINAL doubles-shaped caps (4 brought, 2 lead) - exactly matching
        build_roster_prompt's own rules=None convention."""
        pbrought, obrought, plead, olead = am.derive_brought(self.events, self.roster, rules=None)
        self.assertEqual(len(pbrought), 4)
        self.assertEqual(len(obrought), 4)
        self.assertEqual(len(plead), 2)
        self.assertEqual(len(olead), 2)

    def test_explicit_doubles_rules_match_the_none_default(self):
        rules = {"bring_count": 4, "active_per_side": 2}
        pbrought, obrought, plead, olead = am.derive_brought(self.events, self.roster, rules=rules)
        none_result = am.derive_brought(self.events, self.roster, rules=None)
        self.assertEqual((pbrought, obrought, plead, olead), none_result)

    def test_singles_rules_uncap_brought_and_cap_lead_at_one(self):
        """Singles has no separate 'brought' concept at all - the whole
        registered team (up to team_size_max) is what's used, and only 1
        Pokemon is ever active per side (not 2)."""
        rules = {"bring_count": None, "active_per_side": 1, "team_size_max": 6}
        pbrought, obrought, plead, olead = am.derive_brought(self.events, self.roster, rules=rules)
        # All 5 that appeared should be kept (well under the 6-max cap) -
        # NOT truncated to 4 the way the old hardcoded cap would have done.
        self.assertEqual(len(pbrought), 5)
        self.assertEqual(len(obrought), 5)
        self.assertEqual(len(plead), 1)
        self.assertEqual(len(olead), 1)

    def test_singles_team_larger_than_five_still_capped_at_team_size_max(self):
        """A 6-Pokemon Singles team where all 6 appear must be capped at
        team_size_max (6), not left fully uncapped forever."""
        events = _sent_out_events(self.PLAYER_TEAM, self.OPPONENT_TEAM)
        rules = {"bring_count": None, "active_per_side": 1, "team_size_max": 6}
        pbrought, obrought, plead, olead = am.derive_brought(events, self.roster, rules=rules)
        self.assertEqual(len(pbrought), 6)
        self.assertEqual(len(obrought), 6)

    def test_empty_dict_rules_treated_as_singles_shaped(self):
        """rules={} has no bring_count/active_per_side keys at all - must
        take the same no-bring-count branch as explicit bring_count=None
        (falling back to a team-size-based cap), and default active_per_side
        to 2 per the documented fallback, not crash."""
        pbrought, obrought, plead, olead = am.derive_brought(self.events, self.roster, rules={})
        self.assertEqual(len(pbrought), 5)   # capped by team_size fallback (6), not bring_count
        self.assertEqual(len(plead), 2)      # active_per_side falls back to 2 when absent


if __name__ == "__main__":
    unittest.main()
