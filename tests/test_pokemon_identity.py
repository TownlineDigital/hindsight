"""
Tests for pokemon_identity.py - the nickname/species resolution layer that
sits between OCR/text reading and the rest of the pipeline (see the
module's own docstring and ARCHITECTURE_HANDOFF.md's nickname discussion
for the full reasoning: a nickname isn't in any database, so the only real
fix is a single vision call per Pokemon, cached for the rest of the match).

Pure logic, no OCR/video/network/vision calls involved - `learn()` is
exactly the seam a real vision-call result would be plugged into.

Run: py -m unittest tests.test_pokemon_identity -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pokemon_identity as pid  # noqa: E402


class TestFreeFuzzyMatchAgainstKnownRoster(unittest.TestCase):
    """The common case - most Pokemon aren't nicknamed, so a display name
    that's exactly (or almost exactly) a real roster species should
    resolve for free, no vision call needed."""

    def test_exact_species_name_resolves_without_a_vision_call(self):
        resolver = pid.IdentityResolver(known_species=["Charizard", "Staraptor"])
        species, needs_vision = resolver.resolve_or_flag("Charizard")
        self.assertEqual(species, "Charizard")
        self.assertFalse(needs_vision)

    def test_case_and_punctuation_insensitive(self):
        resolver = pid.IdentityResolver(known_species=["Mr. Mime"])
        species, needs_vision = resolver.resolve_or_flag("mr mime")
        self.assertEqual(species, "Mr. Mime")
        self.assertFalse(needs_vision)

    def test_partial_ocr_read_still_resolves(self):
        """A real observed OCR failure mode - a truncated/partial read of
        a real species name - should still resolve cheaply rather than
        being treated as a nickname."""
        resolver = pid.IdentityResolver(known_species=["Incineroar"])
        species, needs_vision = resolver.resolve_or_flag("Incineroa")
        self.assertEqual(species, "Incineroar")
        self.assertFalse(needs_vision)

    def test_empty_roster_means_nothing_resolves_for_free(self):
        resolver = pid.IdentityResolver(known_species=[])
        species, needs_vision = resolver.resolve_or_flag("Charizard")
        self.assertIsNone(species)
        self.assertTrue(needs_vision)


class TestGenuineNicknamesAreFlaggedNotGuessed(unittest.TestCase):
    """The whole point of this module: a display name that shares nothing
    with any known roster species must be flagged for a real vision call,
    never silently guessed at or forced to match something wrong."""

    def test_unrelated_nickname_is_flagged(self):
        resolver = pid.IdentityResolver(known_species=["Charizard", "Staraptor"])
        species, needs_vision = resolver.resolve_or_flag("Big Red")
        self.assertIsNone(species)
        self.assertTrue(needs_vision)

    def test_nickname_is_never_coincidentally_matched_to_the_wrong_species(self):
        """A short nickname shouldn't accidentally overlap a real species
        name and get "resolved" to the wrong Pokemon entirely."""
        resolver = pid.IdentityResolver(known_species=["Charizard"])
        species, needs_vision = resolver.resolve_or_flag("Ash")
        self.assertIsNone(species)
        self.assertTrue(needs_vision)

    def test_blank_display_name_is_not_flagged(self):
        """Nothing to resolve and nothing worth a vision call for."""
        resolver = pid.IdentityResolver(known_species=["Charizard"])
        species, needs_vision = resolver.resolve_or_flag("")
        self.assertIsNone(species)
        self.assertFalse(needs_vision)

    def test_none_display_name_is_not_flagged(self):
        resolver = pid.IdentityResolver(known_species=["Charizard"])
        species, needs_vision = resolver.resolve_or_flag(None)
        self.assertIsNone(species)
        self.assertFalse(needs_vision)


class TestLearnCachesAVisionResult(unittest.TestCase):
    """learn() is the seam a real vision-call result plugs into - once
    called, that same display name must never be flagged again this
    match, and the ONE vision call actually gets reused, not repeated."""

    def test_learned_nickname_resolves_on_next_lookup_without_a_vision_call(self):
        resolver = pid.IdentityResolver(known_species=["Charizard", "Staraptor"])
        # First encounter: flagged, caller does a real vision call.
        species, needs_vision = resolver.resolve_or_flag("Big Red")
        self.assertTrue(needs_vision)
        resolver.learn("Big Red", "Charizard")

        # Every subsequent encounter this match: free.
        species, needs_vision = resolver.resolve_or_flag("Big Red")
        self.assertEqual(species, "Charizard")
        self.assertFalse(needs_vision)

    def test_learn_is_case_insensitive_on_lookup(self):
        resolver = pid.IdentityResolver()
        resolver.learn("Big Red", "Charizard")
        species, needs_vision = resolver.resolve_or_flag("BIG RED")
        self.assertEqual(species, "Charizard")
        self.assertFalse(needs_vision)

    def test_learn_ignores_blank_display_name_or_species(self):
        resolver = pid.IdentityResolver()
        resolver.learn("", "Charizard")
        resolver.learn("Big Red", "")
        resolver.learn(None, None)
        self.assertEqual(resolver.known_display_names(), set())

    def test_learn_widens_known_species_for_future_fuzzy_matches(self):
        """Once a nickname is learned, its species becomes part of the
        match's known roster too - so e.g. a differently-cased or slightly
        different-looking repeat OCR read of the SAME nickname text still
        resolves via the free path, not a second vision call."""
        resolver = pid.IdentityResolver()
        resolver.learn("Big Red", "Charizard")
        # A fresh, previously-unseen display name that happens to exactly
        # match the now-known species should also resolve for free.
        species, needs_vision = resolver.resolve_or_flag("Charizard")
        self.assertEqual(species, "Charizard")
        self.assertFalse(needs_vision)


class TestKnownDisplayNames(unittest.TestCase):
    def test_tracks_every_resolved_display_name(self):
        resolver = pid.IdentityResolver(known_species=["Charizard"])
        resolver.resolve_or_flag("Charizard")
        resolver.learn("Big Red", "Charizard")
        self.assertEqual(resolver.known_display_names(), {"charizard", "bigred"})


class TestScopingIsPerMatch(unittest.TestCase):
    def test_two_resolvers_do_not_share_state(self):
        """A nickname is only consistent within the match it was set in -
        a fresh IdentityResolver per match must not leak learned mappings
        from a previous match."""
        resolver_a = pid.IdentityResolver()
        resolver_a.learn("Big Red", "Charizard")

        resolver_b = pid.IdentityResolver()
        species, needs_vision = resolver_b.resolve_or_flag("Big Red")
        self.assertIsNone(species)
        self.assertTrue(needs_vision)


if __name__ == "__main__":
    unittest.main()
