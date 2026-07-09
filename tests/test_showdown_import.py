"""
Tests for showdown_import.py, grounded in a REAL replay fetched from
replay.pokemonshowdown.com while building this ([Gen 9 Champions] VGC 2026
Reg M-A: Geordivgc vs. JarlomenVGC - a real, public, verifiable match). The
raw log below is copied verbatim from that replay's own .json API response,
not synthesized - every assertion here can be checked against the actual
battle if you want to re-verify it yourself.

Unlike the video pipeline, this parser is 100% deterministic (no AI, no
video) - these tests can assert EXACT values throughout, not just invariants.

Run: py -m unittest tests.test_showdown_import -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import showdown_import as si  # noqa: E402

# Verbatim from https://replay.pokemonshowdown.com/gen9championsvgc2026regma-2639736732.json
# (fetched 2026-07-02). Geordivgc (p1) beat JarlomenVGC (p2) in 12 turns.
REAL_REPLAY_JSON = r'''
{"id":"gen9championsvgc2026regma-2639736732","format":"[Gen 9 Champions] VGC 2026 Reg M-A","players":["Geordivgc","JarlomenVGC"],"log":"|j|☆Geordivgc\n|j|☆JarlomenVGC\n|t:|1782512570\n|gametype|doubles\n|player|p1|Geordivgc|worker|\n|player|p2|JarlomenVGC|hiker-gen4|\n|gen|9\n|tier|[Gen 9 Champions] VGC 2026 Reg M-A\n|rule|Species Clause: Limit one of each Pokémon\n|rule|Item Clause: Limit 1 of each item\n|clearpoke\n|poke|p1|Farigiraf, L50, M|\n|poke|p1|Rotom-Mow, L50|\n|poke|p1|Kangaskhan, L50, F|\n|poke|p1|Salazzle, L50, F|\n|poke|p1|Clefable, L50, M|\n|poke|p1|Gyarados, L50, M|\n|poke|p2|Charizard, L50, F|\n|poke|p2|Venusaur, L50, M|\n|poke|p2|Lucario, L50, F|\n|poke|p2|Rotom-Wash, L50|\n|poke|p2|Kangaskhan, L50, F|\n|poke|p2|Krookodile, L50, F|\n|teampreview|4\n|inactive|Battle timer is ON: inactive players will automatically lose when time's up. (requested by JarlomenVGC)\n|inactive|JarlomenVGC has 60 seconds left.\n|\n|t:|1782512616\n|teamsize|p1|4\n|teamsize|p2|4\n|start\n|switch|p1a: Salazzle|Salazzle, L50, F|100\/100\n|switch|p1b: Gyarados|Gyarados, L50, M|100\/100\n|switch|p2a: Charizard|Charizard, L50, F|100\/100\n|switch|p2b: Venusaur|Venusaur, L50, M|100\/100\n|-ability|p1b: Gyarados|Intimidate|boost\n|-unboost|p2a: Charizard|atk|1\n|-unboost|p2b: Venusaur|atk|1\n|turn|1\n|inactive|JarlomenVGC has 30 seconds left.\n|\n|t:|1782512659\n|switch|p2b: Krookodile|Krookodile, L50, F|100\/100\n|-ability|p2b: Krookodile|Intimidate|boost\n|detailschange|p2a: Charizard|Charizard-Mega-Y, L50, F\n|-mega|p2a: Charizard|Charizard|Charizardite Y\n|move|p1a: Salazzle|Fake Out|p2b: Krookodile\n|-damage|p2b: Krookodile|93\/100\n|move|p2a: Charizard|Solar Beam||[still]\n|move|p1b: Gyarados|Dragon Dance|p1b: Gyarados\n|-boost|p1b: Gyarados|atk|1\n|\n|upkeep\n|turn|2\n|\n|t:|1782512695\n|switch|p1a: Rotom|Rotom-Mow, L50|100\/100\n|move|p1b: Gyarados|Stone Edge|p2a: Charizard\n|-supereffective|p2a: Charizard|2\n|-damage|p2a: Charizard|0 fnt\n|faint|p2a: Charizard\n|move|p2b: Krookodile|Rock Slide|p1a: Rotom|[spread] p1a,p1b\n|-damage|p1a: Rotom|72\/100\n|-damage|p1b: Gyarados|23\/100\n|\n|upkeep\n|\n|t:|1782512709\n|switch|p2a: Kangaskhan|Kangaskhan, L50, F|100\/100\n|turn|3\n|\n|t:|1782512725\n|switch|p1a: Kangaskhan|Kangaskhan, L50, F|100\/100\n|move|p1b: Gyarados|Protect|p1b: Gyarados\n|move|p2a: Kangaskhan|Fake Out|p1a: Kangaskhan\n|-damage|p1a: Kangaskhan|77\/100\n|move|p2b: Krookodile|Crunch|p1a: Kangaskhan\n|-damage|p1a: Kangaskhan|22\/100\n|\n|upkeep\n|turn|4\n|\n|t:|1782512752\n|detailschange|p1a: Kangaskhan|Kangaskhan-Mega, L50, F\n|-mega|p1a: Kangaskhan|Kangaskhan|Kangaskhanite\n|move|p1a: Kangaskhan|Fake Out|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|76\/100\n|move|p1b: Gyarados|Waterfall|p2b: Krookodile\n|-damage|p2b: Krookodile|70\/100\n|move|p2b: Krookodile|Rock Slide|p1a: Kangaskhan|[spread] p1a,p1b\n|-damage|p1a: Kangaskhan|6\/100\n|-damage|p1b: Gyarados|0 fnt\n|faint|p1b: Gyarados\n|\n|upkeep\n|\n|t:|1782512772\n|switch|p1b: Rotom|Rotom-Mow, L50|72\/100\n|turn|5\n|\n|t:|1782512784\n|switch|p1a: Salazzle|Salazzle, L50, F|100\/100\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1b: Rotom|Leaf Storm|p2b: Krookodile\n|move|p2a: Kangaskhan|Last Resort|p1b: Rotom\n|-damage|p1b: Rotom|0 fnt\n|faint|p1b: Rotom\n|\n|upkeep\n|\n|t:|1782512794\n|switch|p1b: Kangaskhan|Kangaskhan-Mega, L50, F|6\/100\n|turn|6\n|\n|t:|1782512806\n|move|p1b: Kangaskhan|Fake Out|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|49\/100\n|move|p1a: Salazzle|Encore|p2b: Krookodile\n|move|p2b: Krookodile|Protect||[still]\n|\n|upkeep\n|turn|7\n|\n|t:|1782512843\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1a: Salazzle|Sludge Bomb|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|0 fnt\n|faint|p2a: Kangaskhan\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|\n|upkeep\n|\n|t:|1782512850\n|switch|p2a: Venusaur|Venusaur, L50, M|100\/100\n|turn|8\n|\n|t:|1782512870\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1b: Kangaskhan|Protect|p1b: Kangaskhan\n|move|p1a: Salazzle|Heat Wave|p2b: Krookodile|[spread] p2a\n|-damage|p2a: Venusaur|26\/100\n|move|p2a: Venusaur|Earth Power|p1a: Salazzle\n|-damage|p1a: Salazzle|1\/100\n|\n|upkeep\n|turn|9\n|\n|t:|1782512906\n|move|p2a: Venusaur|Protect|p2a: Venusaur\n|move|p1a: Salazzle|Encore|p2b: Krookodile\n|move|p1b: Kangaskhan|Hammer Arm|p2a: Venusaur\n|\n|upkeep\n|turn|10\n|\n|t:|1782512919\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1a: Salazzle|Encore|p2a: Venusaur\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|\n|upkeep\n|turn|11\n|\n|t:|1782512929\n|move|p2b: Krookodile|Protect||[still]\n|move|p2a: Venusaur|Protect|p2a: Venusaur\n|move|p1a: Salazzle|Heat Wave|p2a: Venusaur|[spread] p2b\n|-damage|p2b: Krookodile|21\/100\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|-damage|p2b: Krookodile|0 fnt\n|faint|p2b: Krookodile\n|\n|upkeep\n|turn|12\n|\n|t:|1782512941\n|move|p2a: Venusaur|Protect||[still]\n|move|p1a: Salazzle|Heat Wave|p2a: Venusaur\n|-damage|p2a: Venusaur|0 fnt\n|faint|p2a: Venusaur\n|\n|win|Geordivgc\n","uploadtime":1782512948,"views":33,"formatid":"gen9championsvgc2026regma","rating":null,"private":0,"password":null}
'''.strip()


class TestExtractLogText(unittest.TestCase):
    def test_direct_json_response(self):
        log = si.extract_log_text(REAL_REPLAY_JSON)
        self.assertTrue(log.startswith("|j|"))
        self.assertIn("|win|Geordivgc", log)

    def test_json_embedded_in_html_page(self):
        """Simulates a saved .html replay page with the same JSON blob
        embedded in a <script> tag - the parser shouldn't need to know
        Showdown's exact surrounding markup."""
        html = f'<html><body><script type="application/json" id="x">{REAL_REPLAY_JSON}</script></body></html>'
        log = si.extract_log_text(html)
        self.assertIn("|win|Geordivgc", log)

    def test_raw_protocol_text_fallback(self):
        """Plain pasted log text (no JSON wrapper at all)."""
        raw_lines = "|player|p1|Ash|1|\n|player|p2|Gary|2|\n|turn|1\n|win|Ash"
        log = si.extract_log_text(raw_lines)
        self.assertIn("|win|Ash", log)

    def test_no_log_found_exits(self):
        with self.assertRaises(SystemExit):
            si.extract_log_text("<html><body>nothing here</body></html>")


class TestSpeciesFromDetails(unittest.TestCase):
    def test_strips_level_and_gender(self):
        self.assertEqual(si.species_from_details("Farigiraf, L50, M"), "Farigiraf")

    def test_no_level_shown_for_l100(self):
        self.assertEqual(si.species_from_details("Rotom-Mow, L50"), "Rotom-Mow")

    def test_mega_suffix_preserved_for_later_normalization(self):
        """species_from_details itself does NOT strip Mega - that's
        analyze_matches._species_base_norm's job (already tested in
        test_species_legality.py), so the raw form must survive here."""
        self.assertEqual(si.species_from_details("Charizard-Mega-Y, L50, F"), "Charizard-Mega-Y")


class TestParseReplayAgainstRealMatch(unittest.TestCase):
    """Every value here is checkable against the real, public replay at
    https://replay.pokemonshowdown.com/gen9championsvgc2026regma-2639736732"""

    def setUp(self):
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.tp = self.events[0]
        self.be = self.events[-1]

    def test_full_six_pokemon_rosters(self):
        self.assertEqual(self.tp["player_team"],
                          "Farigiraf, Rotom-Mow, Kangaskhan, Salazzle, Clefable, Gyarados")
        self.assertEqual(self.tp["opponent_team"],
                          "Charizard, Venusaur, Lucario, Rotom-Wash, Kangaskhan, Krookodile")

    def test_brought_four_matches_what_actually_appeared(self):
        """Player switched in Salazzle, Gyarados, then Rotom, then Kangaskhan
        over the course of the match - exactly 4 unique species."""
        self.assertEqual(self.tp["player_brought"], "Salazzle, Gyarados, Rotom-Mow, Kangaskhan")
        self.assertEqual(self.tp["opponent_brought"], "Charizard, Venusaur, Krookodile, Kangaskhan")

    def test_leads_are_the_first_two_switched_in(self):
        self.assertEqual(self.tp["player_lead"], "Salazzle, Gyarados")
        self.assertEqual(self.tp["opponent_lead"], "Charizard, Venusaur")

    def test_no_illegal_species_in_a_real_legal_battle(self):
        """Showdown enforces format legality server-side - a real ladder
        battle in this tier can never contain a banned species. If this
        ever fails, it means OUR allowlist is missing a real, legal Pokemon
        (exactly the Dragalge/Qwilfish bug class), not that the data's wrong."""
        self.assertEqual(self.tp["illegal_species_detected"], [])

    def test_winner_resolves_correctly_for_the_named_player(self):
        self.assertEqual(self.be["winner"], "player")
        self.assertIn("Geordivgc", self.be["detail"])

    def test_winner_flips_for_the_other_side(self):
        events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="JarlomenVGC")
        self.assertEqual(events[-1]["winner"], "opponent")
        # and the roster/brought fields should also flip perspective
        self.assertEqual(events[0]["player_team"],
                          "Charizard, Venusaur, Lucario, Rotom-Wash, Kangaskhan, Krookodile")

    def test_second_username_does_not_get_stuck_on_wrong_default(self):
        """Regression test for a real bug: resolving --player against a
        username was done line-by-line as |player| lines streamed in, so if
        --player named whichever username printed SECOND in the log, the
        resolver locked onto the wrong default (p1) before that username had
        even been seen, and never corrected itself. Covered generically by
        test_winner_flips_for_the_other_side above, asserted explicitly here."""
        events_p2_username = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="JarlomenVGC")
        events_p2_id = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="p2")
        self.assertEqual(events_p2_username[0]["player_team"], events_p2_id[0]["player_team"])

    def test_case_insensitive_username_match(self):
        events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="geordivgc")
        self.assertEqual(events[-1]["winner"], "player")

    def test_real_unix_timestamps_produce_accurate_relative_duration(self):
        """First |t:| is 1782512570, last is 1782512941 - a real elapsed
        duration of 371 seconds, computed from Showdown's own clock (more
        accurate than the video pipeline's estimated timestamps)."""
        self.assertEqual(self.be["timestamp"], 371.0)

    def test_event_type_counts(self):
        from collections import Counter
        counts = Counter(e["event"] for e in self.events)
        self.assertEqual(counts["team_preview"], 1)
        self.assertEqual(counts["battle_end"], 1)
        self.assertEqual(counts["pokemon_fainted"], 6)   # Charizard, Gyarados, Rotom, p2 Kangaskhan, Krookodile, Venusaur
        self.assertGreater(counts["move_used"], 0)

    def test_all_events_have_match_number(self):
        for e in self.events:
            self.assertEqual(e["match"], 1)

    def test_confidence_is_maximal_not_an_ai_guess(self):
        """Unlike the video pipeline's confidence scores (0.8/0.85, an AI's
        self-reported certainty), Showdown data is ground truth - every event
        should carry full confidence."""
        for e in self.events:
            self.assertEqual(e["confidence"], 1.0)


class TestTurnTrackingAndFieldState(unittest.TestCase):
    """Regression tests for the 2026-07-04 turn-tracking fix: |turn|N| lines
    now emit a real field_state event (turn + both sides' active Pokemon),
    the same shape analyze_matches.py's video pipeline produces - this is
    what makes decision_windows.build_decision_windows() work on a
    Showdown-imported match at all (previously an honest, documented gap:
    "currently true of EVERY Showdown-imported match" that nothing keys
    turns off). Uses the same real, public replay as the class above."""

    def setUp(self):
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.field_states = [e for e in self.events if e["event"] == "field_state"]

    def test_one_field_state_per_real_turn(self):
        """The real replay is 12 turns (see the module docstring's own
        "12 turns" note) - one field_state per |turn|N| line."""
        self.assertEqual(len(self.field_states), 12)
        self.assertEqual([fs["turn"] for fs in self.field_states], list(range(1, 13)))

    def test_turn_1_field_state_shows_the_real_leads(self):
        """Turn 1's field_state must reflect the leads that were ALREADY
        switched in before the |turn|1| line (real protocol order: 2x
        |switch| per side, THEN |turn|1|) - Salazzle+Gyarados vs.
        Charizard+Venusaur, per the real replay."""
        turn1 = self.field_states[0]
        self.assertEqual(turn1["player_active"], "Salazzle, Gyarados")  # p1a, p1b in slot order
        self.assertEqual(turn1["opponent_active"], "Charizard, Venusaur")  # p2a, p2b in slot order

    def test_field_state_updates_after_a_switch(self):
        """Turn 2's field_state must show Krookodile (switched in for
        Venusaur during turn 1) instead of Venusaur."""
        turn2 = next(fs for fs in self.field_states if fs["turn"] == 2)
        self.assertIn("Krookodile", turn2["opponent_active"])
        self.assertNotIn("Venusaur", turn2["opponent_active"])

    def test_field_state_drops_a_fainted_pokemon_and_reflects_its_replacement(self):
        """Charizard faints during turn 2 (Gyarados's Stone Edge) and
        Kangaskhan switches in for it before |turn|3| appears - turn 3's
        field_state must show Kangaskhan, never the stale fainted
        Charizard."""
        turn3 = next(fs for fs in self.field_states if fs["turn"] == 3)
        self.assertNotIn("Charizard", turn3["opponent_active"])
        self.assertIn("Kangaskhan", turn3["opponent_active"])

    def test_field_state_events_have_full_confidence_like_every_other_showdown_event(self):
        for fs in self.field_states:
            self.assertEqual(fs["confidence"], 1.0)

    def test_decision_windows_now_works_on_a_showdown_imported_match(self):
        """The actual payoff: decision_windows.build_decision_windows()
        (previously always []  for a Showdown-sourced match, since it keys
        turns off field_state events that didn't exist) now returns a real,
        populated result."""
        sys.path.insert(0, BASE_DIR)
        import decision_windows as dw
        windows = dw.build_decision_windows(self.events, 1)
        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[0]["player"]["board"], ["Salazzle", "Gyarados"])


class TestPositionTrackingFix(unittest.TestCase):
    """Regression tests for the real doubles-tracking bug fixed alongside
    turn tracking: `self.active` used to be keyed by SIDE only (the old
    _position_side() sliced "p1a"/"p1b" down to 2 chars, dropping the slot
    letter), so the two active Pokemon on one side in doubles silently
    overwrote each other's tracked species - a move/status/ability read for
    slot "b" could report whichever of the side's two Pokemon most recently
    switched in, not the one that actually acted. Fixed by tracking the
    FULL position id (see _position_id/_side_of_position)."""

    def setUp(self):
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.moves = [e for e in self.events if e["event"] == "move_used"]

    def test_moves_attributed_to_the_correct_slot_not_whichever_switched_in_last(self):
        """Turn 1 of the real replay: p1a (Salazzle) uses Fake Out, p1b
        (Gyarados) uses Dragon Dance, IN THAT ORDER - since Salazzle is in
        slot 'a' and Gyarados in slot 'b', a slot-conflation bug would have
        misattributed one of these to the wrong species. Both must resolve
        to their OWN real species."""
        fake_out = next(m for m in self.moves if m["detail"] == "Fake Out")
        dragon_dance = next(m for m in self.moves if m["detail"] == "Dragon Dance")
        self.assertEqual(fake_out["pokemon"], "Salazzle")
        self.assertEqual(dragon_dance["pokemon"], "Gyarados")

    def test_p2_slot_b_switch_does_not_corrupt_p2_slot_a_tracking(self):
        """Turn 1: p2b switches from Venusaur to Krookodile, then p2a
        Mega-evolves (Charizard -> Charizard-Mega-Y) - a subsequent move
        from p2a must resolve to Charizard-Mega-Y (its own real, current
        form), never to Krookodile (the bug: both slots used to share one
        "p2" tracked species, so p2a's move could have picked up whatever
        p2b's switch last wrote)."""
        solar_beam = next(m for m in self.moves if m["detail"] == "Solar Beam")
        self.assertEqual(solar_beam["pokemon"], "Charizard-Mega-Y")
        self.assertNotEqual(solar_beam["pokemon"], "Krookodile")


class TestStatChangeParsing(unittest.TestCase):
    """Regression tests for the 2026-07-04 |-boost|/|-unboost| fix: this
    project never parsed these real protocol lines at all, so a Showdown-
    imported match never produced a single stat_change event - a real gap
    found while building strategic_analysis.py's win-condition inference
    (a stat-boost-driven "sweep" could never be detected on Showdown data).
    Uses the same real replay - Gyarados's own Intimidate lowers both
    opposing actives' Attack right after the turn-0 switches, and Gyarados's
    later Dragon Dance raises its own Attack by 1 stage."""

    def setUp(self):
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.stat_changes = [e for e in self.events if e["event"] == "stat_change"]

    def test_unboost_from_intimidate_on_both_opposing_actives(self):
        charizard = next(e for e in self.stat_changes if e["pokemon"] == "Charizard")
        venusaur = next(e for e in self.stat_changes if e["pokemon"] == "Venusaur")
        for e in (charizard, venusaur):
            self.assertEqual(e["detail"], "Attack fell")
            self.assertEqual(e["stat"], "Attack")
            self.assertEqual(e["stages"], -1)
            self.assertEqual(e["actor"], "opponent")

    def test_boost_from_dragon_dance(self):
        gyarados_boosts = [e for e in self.stat_changes if e["pokemon"] == "Gyarados"]
        self.assertEqual(len(gyarados_boosts), 1)
        e = gyarados_boosts[0]
        self.assertEqual(e["detail"], "Attack rose")
        self.assertEqual(e["stat"], "Attack")
        self.assertEqual(e["stages"], 1)
        self.assertEqual(e["actor"], "player")

    def test_detail_format_matches_ocr_tier_convention(self):
        """The whole point of matching battle_text_parser.py's own "STAT
        STAGE-WORD" wording exactly: one shared parser
        (strategic_analysis._parse_stat_change) can read stat_change
        events from either source without a source-specific branch."""
        for e in self.stat_changes:
            self.assertRegex(e["detail"], r"^(Attack|Defense|Sp\. Atk|Sp\. Def|Speed) (rose|fell)$")


class TestTerastallizeParsing(unittest.TestCase):
    """Regression tests for the 2026-07-08 |-terastallize| fix: found while
    reviewing a third-party Showdown-log-parsing script for ideas (its own
    example line: "|-terastallize|p1b: Amoonguss|Dark"). This project
    already has a full "terastallized" event type wired through
    player_report.py, coach_report.py, coach_chat.py, and backend/
    analytics.py (all built against the video pipeline's Gemini-derived
    events), but showdown_import.py never actually parsed the real protocol
    line that produces one - so no Showdown-imported match had ever emitted
    a single terastallized event, even for a real, tera'd replay.

    The real replay used elsewhere in this file (Reg M-A) doesn't contain a
    real |-terastallize| line (Champions doesn't implement Terastallization
    at all in this project's current regulations - see
    format_rules_validator.py), so these use small, self-contained synthetic
    logs fed directly through BattleParser.feed_line(), the same style
    TestExtractLogText already uses for isolated protocol-line checks."""

    def setUp(self):
        self.parser = si.BattleParser(match_number=1, player_id="p1")
        for line in [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|switch|p1a: Amoonguss|Amoonguss, L50, F|100/100",
            "|-terastallize|p1a: Amoonguss|Dark",
        ]:
            self.parser.feed_line(line)
        self.tera_events = [e for e in self.parser.events if e["event"] == "terastallized"]

    def test_emits_exactly_one_terastallized_event(self):
        self.assertEqual(len(self.tera_events), 1)

    def test_correct_pokemon_and_actor(self):
        e = self.tera_events[0]
        self.assertEqual(e["pokemon"], "Amoonguss")
        self.assertEqual(e["actor"], "player")

    def test_detail_and_structured_tera_type_field(self):
        """detail mirrors adapters/pokemon/game.json's own documented
        on-screen-text convention ("Terastallized into the [type] type");
        tera_type is a structured extra (same pattern as stat_change's
        stat/stages) for anything that wants the exact type without parsing
        detail text."""
        e = self.tera_events[0]
        self.assertEqual(e["detail"], "Terastallized into the Dark type")
        self.assertEqual(e["tera_type"], "Dark")

    def test_opponent_side_resolves_correctly(self):
        parser = si.BattleParser(match_number=1, player_id="p1")
        for line in [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|switch|p2a: Corviknight|Corviknight, L50|100/100",
            "|-terastallize|p2a: Corviknight|Flying",
        ]:
            parser.feed_line(line)
        e = next(x for x in parser.events if x["event"] == "terastallized")
        self.assertEqual(e["actor"], "opponent")
        self.assertEqual(e["pokemon"], "Corviknight")
        self.assertEqual(e["tera_type"], "Flying")


class TestIllusionReplaceCorrection(unittest.TestCase):
    """Regression tests for the 2026-07-08 |replace| retroactive-fix: found
    while reviewing a third-party Showdown-log-parsing script for ideas
    (that script backtracks its own log to fix which species a decoy really
    was once Illusion breaks). Before this fix, showdown_import.py treated
    |replace| exactly like an ordinary switch - so a decoy species that had
    already produced move_used/hp_change/etc events before the Illusion
    broke stayed mislabeled under the wrong (decoy) species forever. Since
    Zoroark is legal and actually played in Reg Champions VGC, any real
    Showdown-imported match containing an Illusion reveal had genuinely
    wrong event data until now.

    Simulates a real Illusion sequence per sim/SIM-PROTOCOL.md's own
    |replace| doc ("POKEMON will be the NEW Pokemon ID - i.e. it will have
    the nickname of the Zoroark"): Zoroark switches in disguised as
    "Incineroar", acts under that fake identity, takes damage, then the
    Illusion breaks and the real species is revealed in the same slot."""

    def setUp(self):
        self.parser = si.BattleParser(match_number=1, player_id="p1")
        for line in [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            # Illusion is up: the log reports the decoy's identity.
            "|switch|p2a: Incineroar|Incineroar, L50, M|100/100",
            "|move|p2a: Incineroar|Flamethrower|p1a: Farigiraf",
            "|-damage|p2a: Incineroar|90/100",
            # Illusion breaks - real species revealed, same slot.
            "|replace|p2a: Zoroark|Zoroark, L50, M|90/100",
            "|move|p2a: Zoroark|Night Daze|p1a: Farigiraf",
        ]:
            self.parser.feed_line(line)

    def test_events_before_the_reveal_are_retroactively_relabeled(self):
        """The move_used event emitted BEFORE |replace| was attributed to
        the decoy ("Incineroar") at the time - it must now read "Zoroark",
        the real species, not the decoy."""
        move_events = [e for e in self.parser.events if e["event"] == "move_used"]
        self.assertEqual(move_events[0]["pokemon"], "Zoroark")
        self.assertNotEqual(move_events[0]["pokemon"], "Incineroar")

    def test_hp_change_before_reveal_is_also_relabeled(self):
        hp_events = [e for e in self.parser.events if e["event"] == "hp_change"]
        self.assertEqual(hp_events[0]["pokemon"], "Zoroark")

    def test_event_after_the_reveal_already_uses_the_real_species(self):
        move_events = [e for e in self.parser.events if e["event"] == "move_used"]
        self.assertEqual(move_events[1]["pokemon"], "Zoroark")

    def test_no_decoy_pokemon_field_remains_anywhere_for_this_actor(self):
        """The decoy name should not survive anywhere in the opponent's
        event stream once the reveal has been processed."""
        opponent_events = [e for e in self.parser.events if e.get("actor") == "opponent"]
        self.assertFalse(any(e.get("pokemon") == "Incineroar" for e in opponent_events))

    def test_reveal_itself_emits_an_informative_pokemon_sent_out_event(self):
        sent_out = [e for e in self.parser.events if e["event"] == "pokemon_sent_out"]
        reveal_event = sent_out[-1]
        self.assertEqual(reveal_event["pokemon"], "Zoroark")
        self.assertIn("Illusion revealed", reveal_event["detail"])
        self.assertIn("Incineroar", reveal_event["detail"])

    def test_does_not_bleed_into_an_earlier_unrelated_instance_of_the_same_species_name(self):
        """Safety property: if the SAME species name the decoy used had
        ALSO legitimately appeared earlier in the match in a DIFFERENT slot
        (a real teammate, not the illusion), those earlier events must be
        left alone - the retroactive fix is scoped by this exact slot's own
        recorded switch-in event index (slot_last_switch_index), not by
        species-name matching alone, so it can never bleed backward into an
        unrelated earlier instance."""
        parser = si.BattleParser(match_number=2, player_id="p1")
        for line in [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            # An earlier, real, unrelated Incineroar appears and faints.
            "|switch|p2b: Incineroar|Incineroar, L50, M|100/100",
            "|move|p2b: Incineroar|Flamethrower|p1a: Farigiraf",
            "|-damage|p2b: Incineroar|0 fnt",
            "|faint|p2b: Incineroar",
            # Separately, in a DIFFERENT slot, Zoroark disguises as
            # "Incineroar" too.
            "|switch|p2a: Incineroar|Incineroar, L50, M|100/100",
            "|move|p2a: Incineroar|Dark Pulse|p1a: Farigiraf",
            "|replace|p2a: Zoroark|Zoroark, L50, M|100/100",
        ]:
            parser.feed_line(line)
        moves = [e for e in parser.events if e["event"] == "move_used"]
        # The first, real Incineroar's move must be untouched.
        self.assertEqual(moves[0]["pokemon"], "Incineroar")
        # The second slot's move (the actual illusion) must be corrected.
        self.assertEqual(moves[1]["pokemon"], "Zoroark")

    def test_identical_real_species_reveal_is_a_no_op(self):
        """If DETAILS happens to name the same species already tracked for
        this slot (shouldn't happen for a genuine Illusion reveal, but a
        defensive case), nothing should be relabeled and no confusing
        "disguised as X" wording should claim a disguise that didn't
        happen."""
        parser = si.BattleParser(match_number=3, player_id="p1")
        for line in [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|switch|p2a: Ditto|Ditto, L50|100/100",
            "|replace|p2a: Ditto|Ditto, L50|100/100",
        ]:
            parser.feed_line(line)
        sent_out = [e for e in parser.events if e["event"] == "pokemon_sent_out"]
        reveal_event = sent_out[-1]
        self.assertEqual(reveal_event["detail"], "Illusion revealed")
        self.assertNotIn("disguised", reveal_event["detail"])


class TestParseHpFraction(unittest.TestCase):
    """Unit tests for _parse_hp_fraction - the "CURRENT/MAX" (always out of
    100 in VGC replays) -> float percent conversion, plus its "skip, don't
    guess" behavior on anything unrecognized."""

    def test_normal_fraction(self):
        self.assertEqual(si._parse_hp_fraction("93/100"), 93.0)

    def test_fainted_bare_integer(self):
        """A lethal hit is reported as "0 fnt" - no slash at all - right
        before the separate |faint| line."""
        self.assertEqual(si._parse_hp_fraction("0 fnt"), 0.0)

    def test_fraction_with_status_suffix(self):
        self.assertEqual(si._parse_hp_fraction("82/100 par"), 82.0)

    def test_full_health(self):
        self.assertEqual(si._parse_hp_fraction("100/100"), 100.0)

    def test_unparseable_input_returns_none_not_a_guess(self):
        self.assertIsNone(si._parse_hp_fraction("???"))
        self.assertIsNone(si._parse_hp_fraction(""))
        self.assertIsNone(si._parse_hp_fraction(None))

    def test_zero_denominator_returns_none(self):
        self.assertIsNone(si._parse_hp_fraction("0/0"))


class TestHpChangeParsing(unittest.TestCase):
    """Regression tests for the 2026-07-05 |-damage|/|-heal| fix: this
    project never parsed these real protocol lines, so a Showdown-imported
    match never produced a single hp_change event - a real gap found while
    building strategic_analysis.py's HP-percent-based scoring (HP-based
    scoring had zero data to work with on Showdown replays, even though the
    replay carries an EXACT HP fraction on every hit). Every value below is
    hand-verified against the real replay's own log lines."""

    def setUp(self):
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.hp_changes = [e for e in self.events if e["event"] == "hp_change"]

    def test_total_hp_change_count_matches_the_replays_damage_and_faint_lines(self):
        """18 |-damage| lines in the real log (no |-heal| lines occur in
        this particular replay) - hand-counted directly against the raw
        log text above."""
        self.assertEqual(len(self.hp_changes), 18)

    def test_first_damage_is_krookodiles_fake_out_chip(self):
        first = self.hp_changes[0]
        self.assertEqual(first["pokemon"], "Krookodile")
        self.assertEqual(first["actor"], "opponent")
        self.assertEqual(first["hp_percent"], 93.0)
        self.assertEqual(first["detail"], "HP: 93/100")

    def test_fainting_blow_reports_zero_hp_percent(self):
        """Charizard-Mega-Y's fatal Stone Edge hit ("0 fnt") must resolve to
        an exact 0.0, matching the separate pokemon_fainted event's own
        hp_percent=0."""
        charizard_ko = next(e for e in self.hp_changes if e["pokemon"] == "Charizard-Mega-Y")
        self.assertEqual(charizard_ko["hp_percent"], 0.0)
        self.assertEqual(charizard_ko["actor"], "opponent")

    def test_spread_move_produces_one_hp_change_per_target(self):
        """Krookodile's turn-2 Rock Slide hits BOTH of the player's actives
        ([spread] p1a,p1b) - Rotom-Mow down to 72/100 and Gyarados down to
        23/100, as two separate hp_change events."""
        rotom = next(e for e in self.hp_changes if e["pokemon"] == "Rotom-Mow" and e["hp_percent"] == 72.0)
        gyarados = next(e for e in self.hp_changes if e["pokemon"] == "Gyarados" and e["hp_percent"] == 23.0)
        self.assertEqual(rotom["actor"], "player")
        self.assertEqual(gyarados["actor"], "player")

    def test_hp_change_events_have_full_confidence(self):
        """Showdown data is ground truth, same as every other event type
        this parser emits."""
        for e in self.hp_changes:
            self.assertEqual(e["confidence"], 1.0)

    def test_all_hp_percents_are_within_0_to_100(self):
        for e in self.hp_changes:
            self.assertGreaterEqual(e["hp_percent"], 0.0)
            self.assertLessEqual(e["hp_percent"], 100.0)


class TestIntegrationWithExistingAnalytics(unittest.TestCase):
    """The entire point of writing the same events.json shape: everything
    downstream should work with ZERO changes. This is the real payoff test."""

    def test_feeds_directly_into_backend_analytics_with_no_errors(self):
        sys.path.insert(0, BASE_DIR)
        from backend import analytics

        events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        record = analytics.compute_record(events)
        self.assertEqual(record["wins"], 1)
        self.assertEqual(record["losses"], 0)

        report = analytics.compute_report(events, rules={"terastallization": False})
        self.assertEqual(report["record"]["wins"], 1)

        skills = analytics.compute_skill_scores(events)
        self.assertIsNotNone(skills["scores"])


class _FakeArgs:
    """Minimal stand-in for argparse.Namespace - only the 4 mutually-exclusive
    source attributes build_sources() actually reads."""
    def __init__(self, file=None, url=None, files=None, urls=None):
        self.file = file
        self.url = url
        self.files = files
        self.urls = urls


class TestBuildSources(unittest.TestCase):
    """build_sources() is the bit of main() that decides which of --file/
    --url/--files/--urls was given and normalizes it to a uniform list of
    (kind, source) tuples - pulled out specifically so this branching logic
    is testable without real files or network access. Used by both the CLI
    and (once the backend wires --urls in) the web app's Showdown job path."""

    def test_single_file(self):
        self.assertEqual(si.build_sources(_FakeArgs(file="replay.html")),
                          [("file", "replay.html")])

    def test_single_url(self):
        self.assertEqual(si.build_sources(_FakeArgs(url="https://replay.pokemonshowdown.com/x")),
                          [("url", "https://replay.pokemonshowdown.com/x")])

    def test_multiple_files(self):
        self.assertEqual(
            si.build_sources(_FakeArgs(files=["a.html", "b.json"])),
            [("file", "a.html"), ("file", "b.json")])

    def test_multiple_urls(self):
        """The new --urls option, added so the backend can combine several
        Showdown replay links into one job the same way --files already
        combines several local files."""
        urls = ["https://replay.pokemonshowdown.com/a", "https://replay.pokemonshowdown.com/b"]
        self.assertEqual(si.build_sources(_FakeArgs(urls=urls)),
                          [("url", urls[0]), ("url", urls[1])])

    def test_files_takes_precedence_if_somehow_multiple_are_set(self):
        """Shouldn't happen in practice (argparse's mutually-exclusive group
        enforces only one is set), but if this function is called directly
        (as the backend will) with more than one populated, --files wins -
        matching the order it's checked in."""
        args = _FakeArgs(file="solo.html", files=["a.html", "b.html"])
        self.assertEqual(si.build_sources(args), [("file", "a.html"), ("file", "b.html")])


class TestFieldConditionParsing(unittest.TestCase):
    """Regression tests for the 2026-07-09 weather/terrain/trick_room/
    tailwind/screens fix, built for this project's VGC Battle Intelligence
    Manual reports: showdown_import.py never parsed |-weather|/|-fieldstart|/
    |-fieldend|/|-sidestart|/|-sideend| at all before this, so field_state's
    own weather/terrain/trick_room/tailwind/screens fields (already used by
    the video pipeline - see adapters/pokemon/game.json's fields spec) were
    always None/absent on every Showdown-imported match. Small, self-
    contained synthetic logs, same style TestTerastallizeParsing uses."""

    def _field_state_after(self, lines):
        parser = si.BattleParser(match_number=1, player_id="p1")
        for line in lines:
            parser.feed_line(line)
        field_states = [e for e in parser.events if e["event"] == "field_state"]
        return field_states[-1]

    def test_weather_reflected_in_next_field_state(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|switch|p1a: Pelipper|Pelipper, L50, M|100/100",
            "|-weather|RainDance",
            "|turn|1",
        ])
        self.assertEqual(fs["weather"], "rain")

    def test_weather_upkeep_argument_does_not_break_parsing(self):
        """Showdown resends |-weather| once per turn as a reminder while it's
        still active, with an extra |[upkeep]| argument - this must parse
        identically to the original set, not be dropped or misread."""
        fs = self._field_state_after([
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|-weather|Sandstorm",
            "|turn|1",
            "|-weather|Sandstorm|[upkeep]",
            "|turn|2",
        ])
        self.assertEqual(fs["weather"], "sand")

    def test_weather_cleared_back_to_none(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|-weather|SunnyDay",
            "|turn|1",
            "|-weather|none",
            "|turn|2",
        ])
        self.assertEqual(fs["weather"], "none")

    def test_default_weather_is_none_when_never_reported(self):
        fs = self._field_state_after(["|player|p1|Ash|1|", "|player|p2|Gary|2|", "|turn|1"])
        self.assertEqual(fs["weather"], "none")

    def test_trick_room_fieldstart_and_fieldend(self):
        fs_during = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Trick Room", "|turn|1",
        ])
        self.assertTrue(fs_during["trick_room"])

        fs_after = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Trick Room", "|turn|1",
            "|-fieldend|move: Trick Room", "|turn|2",
        ])
        self.assertFalse(fs_after["trick_room"])

    def test_terrain_fieldstart_and_fieldend(self):
        fs_during = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Electric Terrain", "|turn|1",
        ])
        self.assertEqual(fs_during["terrain"], "electric")

        fs_after = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Electric Terrain", "|turn|1",
            "|-fieldend|move: Electric Terrain", "|turn|2",
        ])
        self.assertEqual(fs_after["terrain"], "none")

    def test_all_four_terrains_map_correctly(self):
        for showdown_name, expected in [
            ("move: Electric Terrain", "electric"), ("move: Grassy Terrain", "grassy"),
            ("move: Misty Terrain", "misty"), ("move: Psychic Terrain", "psychic"),
        ]:
            fs = self._field_state_after([
                "|player|p1|Ash|1|", "|player|p2|Gary|2|",
                f"|-fieldstart|{showdown_name}", "|turn|1",
            ])
            self.assertEqual(fs["terrain"], expected)

    def test_unrelated_fieldstart_is_ignored(self):
        """Gravity, Magic Room, Wonder Room, etc. aren't in this project's
        tracked field_state vocabulary - must not be mistaken for a terrain
        or Trick Room, and must not crash."""
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Gravity", "|turn|1",
        ])
        self.assertEqual(fs["terrain"], "none")
        self.assertFalse(fs["trick_room"])

    def test_fieldend_for_a_different_terrain_does_not_clear_the_active_one(self):
        """A real (if rare) sequence: Grassy Terrain is up, then something
        else's fieldend line arrives (e.g. from a move that failed to
        overwrite it) - must not blank out the terrain that's still active."""
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-fieldstart|move: Grassy Terrain", "|turn|1",
            "|-fieldend|move: Electric Terrain", "|turn|2",
        ])
        self.assertEqual(fs["terrain"], "grassy")

    def test_tailwind_sidestart_for_player_only(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Tailwind", "|turn|1",
        ])
        self.assertEqual(fs["tailwind"], "player")

    def test_tailwind_sidestart_for_opponent_only(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p2: Gary|move: Tailwind", "|turn|1",
        ])
        self.assertEqual(fs["tailwind"], "opponent")

    def test_tailwind_both_sides_reports_both(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Tailwind",
            "|-sidestart|p2: Gary|move: Tailwind",
            "|turn|1",
        ])
        self.assertEqual(fs["tailwind"], "both")

    def test_tailwind_sideend_clears_it(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Tailwind", "|turn|1",
            "|-sideend|p1: Ash|move: Tailwind", "|turn|2",
        ])
        self.assertEqual(fs["tailwind"], "none")

    def test_bare_side_id_without_username_suffix_also_works(self):
        """Some replay logs report the side as a bare "p1" rather than
        "p1: Username" - _strip must handle both."""
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1|move: Tailwind", "|turn|1",
        ])
        self.assertEqual(fs["tailwind"], "player")

    def test_single_screen_reported_for_the_correct_side(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Reflect", "|turn|1",
        ])
        self.assertEqual(fs["screens"], "player Reflect")

    def test_multiple_screens_both_sides_comma_joined(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Reflect",
            "|-sidestart|p1: Ash|move: Light Screen",
            "|-sidestart|p2: Gary|move: Aurora Veil",
            "|turn|1",
        ])
        self.assertEqual(fs["screens"], "player Light Screen, player Reflect, opponent Aurora Veil")

    def test_screens_sideend_removes_just_that_one(self):
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Reflect",
            "|-sidestart|p1: Ash|move: Light Screen",
            "|turn|1",
            "|-sideend|p1: Ash|move: Reflect",
            "|turn|2",
        ])
        self.assertEqual(fs["screens"], "player Light Screen")

    def test_no_screens_reports_none(self):
        fs = self._field_state_after(["|player|p1|Ash|1|", "|player|p2|Gary|2|", "|turn|1"])
        self.assertEqual(fs["screens"], "none")

    def test_entry_hazard_sidestart_is_ignored_not_mistaken_for_a_screen(self):
        """Spikes/Stealth Rock/Toxic Spikes/Sticky Web aren't in this
        project's tracked screens vocabulary - must not appear in the
        screens field or crash."""
        fs = self._field_state_after([
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|Spikes", "|turn|1",
        ])
        self.assertEqual(fs["screens"], "none")

    def test_conditions_persist_across_multiple_turns_until_explicitly_ended(self):
        """Tailwind/screens/terrain/weather must carry FORWARD onto every
        subsequent turn's field_state until an explicit -end line, not reset
        each turn - a real multi-turn Tailwind window must show up on every
        turn's field_state it actually covers."""
        parser = si.BattleParser(match_number=1, player_id="p1")
        for line in [
            "|player|p1|Ash|1|", "|player|p2|Gary|2|",
            "|-sidestart|p1: Ash|move: Tailwind", "|turn|1",
            "|turn|2",
            "|turn|3",
        ]:
            parser.feed_line(line)
        field_states = [e for e in parser.events if e["event"] == "field_state"]
        self.assertEqual(len(field_states), 3)
        self.assertTrue(all(fs["tailwind"] == "player" for fs in field_states))


if __name__ == "__main__":
    unittest.main()
