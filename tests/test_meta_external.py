"""
Tests for the "external_meta" feature (task #130): real, official Smogon
usage-stats ingestion in meta_build.py, and its surfacing in coach_chat.py's
load_meta_context(). See meta_build.py's fetch_external_meta() docstring for
the full "why Smogon, why it's ToS-safe, why it's the same format" writeup -
these tests don't re-litigate that, they verify the parsing/mapping/wiring
code is correct.

No live network calls here (this environment's sandbox blocks outbound
requests anyway, and a unit test shouldn't depend on smogon.com being up) -
_parse_smogon_usage_text is tested against a REAL captured excerpt (fetched
directly from https://www.smogon.com/stats/2026-06/gen9championsvgc2026regma-1760.txt
on 2026-07-05 while building this feature, not a synthetic fixture), and
fetch_external_meta's month/cutoff-walking logic is tested with urlopen
monkeypatched to a fake that mimics real HTTP 404s without touching the
network.

Run: py -m unittest tests.test_meta_external -v   (from poc-starter/)
"""

import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error

import meta_build as mb


def _ensure_stub(name, attrs):
    """coach_chat.py needs google.genai at import time - stub it if the real
    package isn't installed (same pattern as test_coach_chat_sessions.py)."""
    try:
        __import__(name)
        return False
    except ImportError:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        return True


_ensure_stub("google", {})
_ensure_stub("google.genai", {"Client": object})
_ensure_stub("google.genai.types", {"GenerateContentConfig": object})

import coach_chat as cc  # noqa: E402

# Real excerpt fetched directly from Smogon's own published stats page
# (https://www.smogon.com/stats/2026-06/gen9championsvgc2026regma-1760.txt) on
# 2026-07-05 - genuine data, not fabricated, just trimmed to a few rows.
_REAL_SMOGON_EXCERPT = """Total battles: 1479658
Avg. weight/team: 0.003
+ ---- + ------------------ + --------- + ------ + ------- + ------ + ------- +
| Rank | Pokemon            | Usage %   | Raw    | %       | Real   | %       |
+ ---- + ------------------ + --------- + ------ + ------- + ------ + ------- +
| 1    | Kingambit          | 46.34371% | 702513 | 23.739% | 0      |  0.000% |
| 2    | Basculegion        | 42.36626% | 687754 | 23.240% | 0      |  0.000% |
| 3    | Garchomp           | 41.54915% | 752790 | 25.438% | 0      |  0.000% |
| 4    | Incineroar         | 40.23116% | 918428 | 31.035% | 0      |  0.000% |
| 9    | Whimsicott         | 21.51303% | 474698 | 16.041% | 0      |  0.000% |
+ ---- + ------------------ + --------- + ------ + ------- + ------ + ------- +
"""


class TestSmogonTierSlug(unittest.TestCase):
    """Confirmed by directly fetching Smogon's own June-2026 stats directory
    listing on 2026-07-05: this exact game is tracked as
    gen9championsvgc<year>reg<code> - not a guess, not borrowed from a
    different game's tier naming."""

    def test_regulation_m_a(self):
        self.assertEqual(mb._smogon_tier_slug("M-A", 2026), "gen9championsvgc2026regma")

    def test_regulation_m_b(self):
        self.assertEqual(mb._smogon_tier_slug("M-B", 2026), "gen9championsvgc2026regmb")

    def test_case_and_dash_insensitive(self):
        self.assertEqual(mb._smogon_tier_slug("m-b", 2026), mb._smogon_tier_slug("M-B", 2026))

    def test_none_regulation_returns_none(self):
        self.assertIsNone(mb._smogon_tier_slug(None, 2026))

    def test_empty_string_regulation_returns_none(self):
        self.assertIsNone(mb._smogon_tier_slug("", 2026))


class TestParseSmogonUsageText(unittest.TestCase):
    """Against a REAL excerpt of Smogon's own published stats page (see
    _REAL_SMOGON_EXCERPT above) - not a synthetic fixture guessing at the
    format."""

    def test_parses_total_battles(self):
        total, _ = mb._parse_smogon_usage_text(_REAL_SMOGON_EXCERPT)
        self.assertEqual(total, 1479658)

    def test_parses_every_real_usage_row(self):
        _, usage = mb._parse_smogon_usage_text(_REAL_SMOGON_EXCERPT)
        self.assertEqual(usage, {
            "Kingambit": 46.34371,
            "Basculegion": 42.36626,
            "Garchomp": 41.54915,
            "Incineroar": 40.23116,
            "Whimsicott": 21.51303,
        })

    def test_html_404_page_returns_none_and_empty_dict(self):
        total, usage = mb._parse_smogon_usage_text("<html><body>404 Not Found</body></html>")
        self.assertIsNone(total)
        self.assertEqual(usage, {})

    def test_empty_string_returns_none_and_empty_dict(self):
        total, usage = mb._parse_smogon_usage_text("")
        self.assertIsNone(total)
        self.assertEqual(usage, {})


class _FakeResponse:
    def __init__(self, text):
        self._text = text.encode("utf-8")

    def read(self):
        return self._text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFetchExternalMeta(unittest.TestCase):
    """fetch_external_meta()'s month/rating-cutoff walking logic, with
    urllib.request.urlopen monkeypatched to a fake that mimics real HTTP
    behavior (404s via urllib.error.HTTPError) without touching the network -
    this environment's sandbox blocks outbound requests anyway, and a unit
    test shouldn't depend on smogon.com being reachable/unchanged."""

    def setUp(self):
        self._orig_urlopen = mb.urllib.request.urlopen
        self.addCleanup(setattr, mb.urllib.request, "urlopen", self._orig_urlopen)

    def _patch_urlopen(self, url_to_text):
        """`url_to_text`: {url: text_or_None}. None means "raise HTTPError
        (404)", matching a real month/tier/cutoff combo that doesn't exist
        yet."""
        def fake_urlopen(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else req
            if url not in url_to_text or url_to_text[url] is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return _FakeResponse(url_to_text[url])
        mb.urllib.request.urlopen = fake_urlopen

    def test_succeeds_on_first_url_tried(self):
        year = "2026"
        month = mb.time.strftime("%Y-%m")
        tier = mb._smogon_tier_slug("M-A", year)
        url = f"{mb.SMOGON_STATS_BASE}/{month}/{tier}-1760.txt"
        self._patch_urlopen({url: _REAL_SMOGON_EXCERPT})

        result = mb.fetch_external_meta("M-A", year=year)
        self.assertIsNotNone(result)
        self.assertEqual(result["tier"], tier)
        self.assertEqual(result["rating_cutoff"], 1760)
        self.assertEqual(result["total_battles"], 1479658)
        self.assertIn("Kingambit", result["pokemon_usage_pct"])

    def test_falls_back_through_rating_cutoffs_within_a_month(self):
        """1760/1630/1500 all 404 (not enough games at those skill bands
        yet), but "-0" (uncapped) exists - must still succeed, not give up
        after the first three misses."""
        year = "2026"
        month = mb.time.strftime("%Y-%m")
        tier = mb._smogon_tier_slug("M-A", year)
        only_zero_url = f"{mb.SMOGON_STATS_BASE}/{month}/{tier}-0.txt"
        self._patch_urlopen({only_zero_url: _REAL_SMOGON_EXCERPT})

        result = mb.fetch_external_meta("M-A", year=year)
        self.assertIsNotNone(result)
        self.assertEqual(result["rating_cutoff"], 0)

    def test_falls_back_to_a_prior_month_if_current_month_not_yet_published(self):
        """Smogon's dumps lag a few days into the new month - the walk must
        keep trying prior months, not just give up after month 0."""
        year = "2026"
        tier = mb._smogon_tier_slug("M-A", year)
        prior_month_t = mb.time.gmtime(mb.time.time() - 30 * 86400)
        prior_month = mb.time.strftime("%Y-%m", prior_month_t)
        url = f"{mb.SMOGON_STATS_BASE}/{prior_month}/{tier}-1760.txt"
        self._patch_urlopen({url: _REAL_SMOGON_EXCERPT})

        result = mb.fetch_external_meta("M-A", year=year)
        self.assertIsNotNone(result)
        self.assertEqual(result["month"], prior_month)

    def test_returns_none_when_every_attempt_fails(self):
        self._patch_urlopen({})   # every URL 404s
        result = mb.fetch_external_meta("M-A", year="2026")
        self.assertIsNone(result)

    def test_returns_none_for_unmapped_regulation(self):
        self._patch_urlopen({})
        result = mb.fetch_external_meta(None, year="2026")
        self.assertIsNone(result)


class TestLoadMetaContextSurfacesExternalMeta(unittest.TestCase):
    """coach_chat.py's load_meta_context() - confirms external_meta actually
    reaches the coach's prompt text (not just sits unused in the JSON file),
    and is clearly labeled as field-wide/other-players' data rather than
    blended in with this player's own own_meta stats."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.schema_path = os.path.join(self._tmp.name, "schema.json")
        self.meta_dir = os.path.join(self._tmp.name, "meta")
        os.makedirs(self.meta_dir)
        with open(self.schema_path, "w", encoding="utf-8") as f:
            json.dump({"rules": {"format_name": "Test Format", "regulation": "M-B"}}, f)

    def _write_meta(self, extra):
        payload = {"rules": {"format_name": "Test Format"}}
        payload.update(extra)
        with open(os.path.join(self.meta_dir, "test_format.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_external_meta_appears_in_context_with_real_numbers(self):
        self._write_meta({
            "external_meta": {
                "tier": "gen9championsvgc2026regmb",
                "month": "2026-06",
                "total_battles": 500000,
                "pokemon_usage_pct": {"Kingambit": 45.0, "Garchomp": 40.0},
            }
        })
        ctx = cc.load_meta_context(schema_path=self.schema_path, meta_dir=self.meta_dir)
        self.assertIn("FIELD-WIDE META", ctx)
        self.assertIn("Kingambit 45.0%", ctx)
        self.assertIn("gen9championsvgc2026regmb", ctx)
        self.assertIn("2026-06", ctx)

    def test_missing_external_meta_does_not_crash_or_add_a_field_wide_line(self):
        self._write_meta({})   # no external_meta key at all - an old meta.json predating this feature
        ctx = cc.load_meta_context(schema_path=self.schema_path, meta_dir=self.meta_dir)
        self.assertNotIn("FIELD-WIDE META", ctx)

    def test_external_meta_present_but_empty_usage_does_not_add_a_field_wide_line(self):
        self._write_meta({"external_meta": {"tier": "x", "pokemon_usage_pct": {}}})
        ctx = cc.load_meta_context(schema_path=self.schema_path, meta_dir=self.meta_dir)
        self.assertNotIn("FIELD-WIDE META", ctx)

    def test_field_wide_line_is_distinct_from_own_meta_line(self):
        """Both blocks can coexist without one clobbering the other - own_meta
        is THIS player's worst matchups, external_meta is the wider field's
        usage - a real coach needs both, not one replacing the other."""
        self._write_meta({
            "own_meta": {"opponent_threats": {"Garchomp": {"win_pct": 20.0}}},
            "external_meta": {
                "tier": "gen9championsvgc2026regmb", "month": "2026-06",
                "total_battles": 1, "pokemon_usage_pct": {"Kingambit": 45.0},
            },
        })
        ctx = cc.load_meta_context(schema_path=self.schema_path, meta_dir=self.meta_dir)
        self.assertIn("Your worst matchups", ctx)
        self.assertIn("FIELD-WIDE META", ctx)


if __name__ == "__main__":
    unittest.main()
