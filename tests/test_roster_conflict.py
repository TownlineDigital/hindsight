"""
Regression tests for analyze_matches.py's roster-conflict detection
(detect_roster_conflict_species / flag_roster_conflicts).

Grounded in a real finding from a human accuracy-review session against
actual video-job footage (jobs/303d13ba0940/human_grade_session.csv):
build_event_prompt's roster-substitution fallback ("Read 'X' on screen, but
that's not in the known roster - reporting closest match, Y") was firing for
BOTH genuine misreads/nicknames (fine to just flag as generically low-
confidence) AND cases where the raw read ("Kingambit", "Kommo-o") was
independently confirmed correct by a human against the on-screen text, but
still got silently swapped for a different real Pokemon because the match's
roster read had missed it. This distinct, much rarer, much higher-value case
needs its own flag rather than being lost in the generic <90%-confidence
"worth checking" bucket (1,433 of 3,584 events in that one job alone).

Run: py -m unittest tests.test_roster_conflict -v   (from poc-starter/)
"""

import unittest

import analyze_matches as am


class TestDetectRosterConflictSpecies(unittest.TestCase):

    def test_real_case_kingambit_bisharp(self):
        """The exact detail text from the human-confirmed Kingambit case
        (match 4, jobs/303d13ba0940) - on-screen text literally read
        'The opposing Kingambit fainted!', independently confirmed by a
        human, yet the system swapped it for Bisharp."""
        detail = ("Read 'Kingambit' on screen, but that's not in the known "
                  "roster - reporting closest match, Bisharp.")
        self.assertEqual(am.detect_roster_conflict_species(detail), ["Kingambit"])

    def test_real_case_basculegion_garchomp(self):
        """The exact detail text from the Basculegion case (match 30) -
        Basculegion is a real, legal M-B species, so this must flag too."""
        detail = ("Read 'Basculegion' on screen, but that's not in the known "
                  "roster - reporting closest match, Garchomp.")
        self.assertEqual(am.detect_roster_conflict_species(detail), ["Basculegion"])

    def test_real_case_multi_pokemon_field_state(self):
        """The exact detail text from the Whimsicott/Kommo-o case (match 2) -
        a field_state event's DIFFERENT phrasing (plural 'matches', both raw
        reads AND substitutes quoted, no 'but that's not in the known roster'
        clause) must still be caught, and must return BOTH names in order."""
        detail = ("Read 'Whimsicott' and 'Kommo-o' on screen, reporting "
                  "closest matches 'Amoonguss' and 'Dragonite'.")
        self.assertEqual(am.detect_roster_conflict_species(detail),
                         ["Whimsicott", "Kommo-o"])

    def test_nickname_case_does_not_flag(self):
        """The whole point of this being a SEPARATE flag from generic low
        confidence: a genuine nickname (not a real species at all) must NOT
        be flagged as a roster conflict - that's the ordinary ambiguous-read
        case the existing <90%-confidence badge already covers."""
        detail = ("Read 'Steve' on screen, but that's not in the known "
                  "roster - reporting closest match, Corviknight.")
        self.assertEqual(am.detect_roster_conflict_species(detail), [])

    def test_garbled_gibberish_does_not_flag(self):
        detail = ("Read 'Xyzzyplorp' on screen, but that's not in the known "
                  "roster - reporting closest match, Garchomp.")
        self.assertEqual(am.detect_roster_conflict_species(detail), [])

    def test_normal_detail_with_no_pattern_returns_empty(self):
        self.assertEqual(am.detect_roster_conflict_species("Altaria used Tailwind!"), [])

    def test_none_or_empty_detail_returns_empty(self):
        self.assertEqual(am.detect_roster_conflict_species(None), [])
        self.assertEqual(am.detect_roster_conflict_species(""), [])

    def test_illegal_species_in_this_regulation_does_not_flag(self):
        """A raw read that's a real Pokemon name but NOT legal under whatever
        regulation is currently configured must not flag either - flag_banned_
        species (which this reuses) is itself regulation-aware, so switching
        to M-A would correctly stop flagging an M-B-only species like this."""
        from tests.test_regulation_switching import ADAPTERS
        orig_species, orig_norm = am.ALLOWED_SPECIES, am._ALLOWED_NORM
        try:
            am.configure_regulation(ADAPTERS, "m-a")
            detail = ("Read 'Metagross' on screen, but that's not in the known "
                      "roster - reporting closest match, Steelix.")
            self.assertEqual(am.detect_roster_conflict_species(detail), [])
        finally:
            am.ALLOWED_SPECIES, am._ALLOWED_NORM = orig_species, orig_norm


class TestFlagRosterConflicts(unittest.TestCase):

    def test_tags_matching_events_in_place(self):
        events = [
            {"event": "pokemon_fainted", "detail": "Read 'Kingambit' on screen, "
             "but that's not in the known roster - reporting closest match, Bisharp."},
            {"event": "move_used", "detail": "Altaria used Tailwind!"},
        ]
        am.flag_roster_conflicts(events)
        self.assertTrue(events[0]["roster_conflict"])
        self.assertEqual(events[0]["roster_conflict_species"], ["Kingambit"])
        self.assertNotIn("roster_conflict", events[1])

    def test_empty_list_is_safe(self):
        self.assertEqual(am.flag_roster_conflicts([]), [])

    def test_missing_detail_key_is_safe(self):
        events = [{"event": "turn_start"}]
        am.flag_roster_conflicts(events)   # should not raise
        self.assertNotIn("roster_conflict", events[0])


if __name__ == "__main__":
    unittest.main()
