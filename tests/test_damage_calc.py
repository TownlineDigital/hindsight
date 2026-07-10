"""
Tests for backend/damage_calc.py - Phase 2 of the live-coaching/optimal-play
roadmap (ARCHITECTURE_HANDOFF.md §19). Every non-trivial number in this file
is checked against a hand-worked calculation using the same public Gen 9
damage formula the module itself documents (Bulbapedia's "Damage" article),
not against an external tool - this sandbox can't run @smogon/calc or
Showdown's own calculator (npm install is 403-blocked here; see
damage_calc.py's own docstring for why this was ported to Python instead of
wrapped). Each hand-worked value is shown in a comment next to its assertion
so a future reader can re-derive it without re-running anything.

Run: py -m unittest tests.test_damage_calc -v   (from poc-starter/)
"""

import unittest

from backend import damage_calc as dc


GARCHOMP_BASE = {"hp": 108, "attack": 130, "defense": 95,
                  "special-attack": 80, "special-defense": 85, "speed": 102}


class TestNatureMultiplier(unittest.TestCase):
    def test_boosted_stat(self):
        self.assertEqual(dc.nature_multiplier("Adamant", "atk"), 1.1)

    def test_lowered_stat(self):
        self.assertEqual(dc.nature_multiplier("Adamant", "spa"), 0.9)

    def test_neutral_stat_under_boosting_nature(self):
        self.assertEqual(dc.nature_multiplier("Adamant", "def"), 1.0)

    def test_neutral_nature(self):
        self.assertEqual(dc.nature_multiplier("Hardy", "atk"), 1.0)

    def test_none_nature(self):
        self.assertEqual(dc.nature_multiplier(None, "atk"), 1.0)

    def test_unrecognized_nature_is_neutral_not_an_error(self):
        self.assertEqual(dc.nature_multiplier("NotARealNature", "atk"), 1.0)


class TestCalcStats(unittest.TestCase):
    """Against Garchomp @ level 50, 252 Atk EV, 31 IVs (default), Adamant -
    a real, commonly-run competitive spread, hand-checked below."""

    def setUp(self):
        self.stats = dc.calc_stats(GARCHOMP_BASE, level=50, evs={"attack": 252}, nature="Adamant")

    def test_hp(self):
        # ((2*108 + 31 + 0) * 50) // 100 + 50 + 10 = (247*50)//100 + 60 = 123 + 60 = 183
        self.assertEqual(self.stats["hp"], 183)

    def test_boosted_attack(self):
        # inner = ((2*130 + 31 + 252//4) * 50) // 100 + 5 = ((260+31+63)*50)//100 + 5
        #       = (354*50)//100 + 5 = 17700//100 + 5 = 177 + 5 = 182
        # nature: floor(182 * 1.1) = floor(200.2) = 200
        self.assertEqual(self.stats["attack"], 200)

    def test_neutral_stat_no_ev(self):
        # defense: base 95, 0 EV -> inner = ((2*95+31+0)*50)//100+5 = (221*50)//100+5 = 110+5=115
        # neutral nature (not boosted/lowered for Adamant) -> unchanged
        self.assertEqual(self.stats["defense"], 115)

    def test_lowered_special_attack(self):
        # base 80, 0 EV -> inner = ((160+31)*50)//100+5 = (191*50)//100+5 = 95+5=100
        # Adamant lowers spa: floor(100*0.9) = 90
        self.assertEqual(self.stats["special-attack"], 90)

    def test_defaults_31_iv_0_ev(self):
        # base 102, 31 IV (default), 0 EV (default), no nature ->
        # ((2*102+31+0)*50)//100+5 = (235*50)//100+5 = 117+5 = 122
        neutral = dc.calc_stats(GARCHOMP_BASE, level=50)
        self.assertEqual(neutral["speed"], 122)

    def test_zero_base_stat_yields_zero(self):
        stats = dc.calc_stats({"hp": 0, "attack": 100, "defense": 100,
                                "special-attack": 100, "special-defense": 100, "speed": 100}, level=50)
        self.assertEqual(stats["hp"], 0)


class TestTypeEffectiveness(unittest.TestCase):
    def test_super_effective(self):
        self.assertEqual(dc.type_effectiveness("water", ["fire"]), 2.0)

    def test_immune(self):
        self.assertEqual(dc.type_effectiveness("ground", ["flying"]), 0.0)

    def test_dual_type_quad_effective(self):
        # ice vs dragon/flying (e.g. Dragonite): 2 * 2 = 4
        self.assertEqual(dc.type_effectiveness("ice", ["dragon", "flying"]), 4.0)

    def test_neutral(self):
        self.assertEqual(dc.type_effectiveness("normal", ["normal"]), 1.0)


class TestCalculateDamage(unittest.TestCase):
    """Garchomp (200 Atk, from TestCalcStats above) using a 100-power
    Ground-type physical move against a 100-Defense Normal-type target -
    every number here is hand-derived in the comments, then confirmed by
    running the real code in this sandbox (see the session's own verification
    notes in ARCHITECTURE_HANDOFF.md §19c)."""

    def setUp(self):
        atk_stats = dc.calc_stats(GARCHOMP_BASE, level=50, evs={"attack": 252}, nature="Adamant")
        self.attacker = {"stats": atk_stats, "types": ["ground", "dragon"],
                          "ability": None, "item": None, "status": None, "level": 50}
        self.defender = {"stats": {"hp": 150, "defense": 100, "special-defense": 100},
                          "types": ["normal"]}
        self.move = {"power": 100, "type": "ground", "category": "physical"}

    def test_base_stab_only_min_max(self):
        # term1 = (2*50)//5+2 = 22; step = (22*100*200)//100 = 4400; base = 4400//50+2 = 90
        # modifier = STAB 1.5 (ground is one of Garchomp's types) * type 1.0 (neutral vs Normal) = 1.5
        # roll range: floor(90*1.5*0.85)=floor(114.75)=114 .. floor(90*1.5*1.00)=135
        result = dc.calculate_damage(self.attacker, self.defender, self.move, field={})
        self.assertEqual(result["min"], 114)
        self.assertEqual(result["max"], 135)
        self.assertEqual(len(result["rolls"]), 16)
        self.assertEqual(result["min_pct"], round(114 / 150 * 100, 1))
        self.assertEqual(result["max_pct"], round(135 / 150 * 100, 1))

    def test_immunity_is_all_zero(self):
        flying_defender = {"stats": {"hp": 150, "defense": 100, "special-defense": 100}, "types": ["flying"]}
        result = dc.calculate_damage(self.attacker, flying_defender, self.move, field={})
        self.assertEqual(result["rolls"], [0] * 16)
        self.assertEqual(result["min_pct"], 0.0)
        self.assertEqual(result["max_pct"], 0.0)

    def test_status_move_zero_power_is_all_zero(self):
        result = dc.calculate_damage(self.attacker, self.defender, {"power": 0, "type": "ground",
                                                                       "category": "physical"}, field={})
        self.assertEqual(result["rolls"], [0] * 16)

    def test_spread_move_reduction_only_applies_with_multiple_targets(self):
        spread_move = dict(self.move, is_spread=True)
        single_target = dc.calculate_damage(self.attacker, self.defender, spread_move, field={"targets_count": 1})
        two_targets = dc.calculate_damage(self.attacker, self.defender, spread_move, field={"targets_count": 2})
        self.assertEqual(single_target["max"], 135)   # unaffected - only one real target
        # 90 * 1.5 * 0.75 = 101.25 -> floor 101 at the 1.00 roll
        self.assertEqual(two_targets["max"], 101)

    def test_same_type_terastallization_stab_bonus(self):
        # Terastallizing into one of the Pokemon's OWN types (Ground) grants
        # 2.0x STAB instead of 1.5x: 90*2.0 = 180
        tera_attacker = dict(self.attacker, is_tera=True, tera_type="Ground")
        result = dc.calculate_damage(tera_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 180)

    def test_adaptability_with_same_type_tera_is_2point25x(self):
        # Real Gen 9 interaction: Adaptability + same-type Tera = 2.25x, not
        # 2.0*2.0. 90 * 2.25 = 202.5 -> floor 202
        tera_attacker = dict(self.attacker, is_tera=True, tera_type="Ground", ability="Adaptability")
        result = dc.calculate_damage(tera_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 202)

    def test_critical_hit_multiplies_by_1_5(self):
        # 90 * 1.5 (stab) * 1.5 (crit) = 202.5 -> floor 202
        crit_move = dict(self.move, is_crit=True)
        result = dc.calculate_damage(self.attacker, self.defender, crit_move, field={})
        self.assertEqual(result["max"], 202)

    def test_choice_band_multiplies_physical_by_1_5(self):
        band_attacker = dict(self.attacker, item="Choice Band")
        result = dc.calculate_damage(band_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 202)

    def test_choice_specs_does_not_boost_a_physical_move(self):
        specs_attacker = dict(self.attacker, item="Choice Specs")
        result = dc.calculate_damage(specs_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 135)   # unaffected - wrong category

    def test_life_orb_multiplies_by_1_3(self):
        # 90 * 1.5 * 1.3 = 175.5 -> floor 175
        lo_attacker = dict(self.attacker, item="Life Orb")
        result = dc.calculate_damage(lo_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 175)

    def test_burn_halves_physical_damage(self):
        # 90 * 1.5 * 0.5 = 67.5 -> floor 67
        burned_attacker = dict(self.attacker, status="brn")
        result = dc.calculate_damage(burned_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 67)

    def test_guts_negates_burn_halving(self):
        guts_attacker = dict(self.attacker, status="brn", ability="Guts")
        result = dc.calculate_damage(guts_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 135)   # same as the unburned baseline

    def test_sun_boosts_fire_move(self):
        fire_move = {"power": 100, "type": "fire", "category": "special"}
        fire_attacker = dict(self.attacker, stats=dict(self.attacker["stats"], **{"special-attack": 150}))
        no_weather = dc.calculate_damage(fire_attacker, self.defender, fire_move, field={})
        sun = dc.calculate_damage(fire_attacker, self.defender, fire_move, field={"weather": "sun"})
        self.assertGreater(sun["max"], no_weather["max"])

    def test_sun_halves_water_move(self):
        water_move = {"power": 100, "type": "water", "category": "special"}
        no_weather = dc.calculate_damage(self.attacker, self.defender, water_move, field={})
        sun = dc.calculate_damage(self.attacker, self.defender, water_move, field={"weather": "sun"})
        self.assertLess(sun["max"], no_weather["max"])

    def test_positive_stat_stage_boosts_damage(self):
        boosted_attacker = dict(self.attacker, atk_stage=2)   # +2 -> 2x multiplier
        no_boost = dc.calculate_damage(self.attacker, self.defender, self.move, field={})
        boosted = dc.calculate_damage(boosted_attacker, self.defender, self.move, field={})
        self.assertGreater(boosted["max"], no_boost["max"])

    def test_negative_defense_stage_boosts_damage_taken(self):
        weakened_defender = dict(self.defender, def_stage=-2)
        baseline = dc.calculate_damage(self.attacker, self.defender, self.move, field={})
        weakened = dc.calculate_damage(self.attacker, weakened_defender, self.move, field={})
        self.assertGreater(weakened["max"], baseline["max"])

    def test_rolls_are_monotonically_nondecreasing(self):
        """The 16-value spread must be sorted low-to-high (85% roll first,
        100% roll last) - a sanity check that the random-roll loop iterates
        in the right order."""
        result = dc.calculate_damage(self.attacker, self.defender, self.move, field={})
        self.assertEqual(result["rolls"], sorted(result["rolls"]))

    def test_unrecognized_ability_and_item_are_ignored_not_errors(self):
        odd_attacker = dict(self.attacker, ability="NotARealAbility", item="NotARealItem")
        result = dc.calculate_damage(odd_attacker, self.defender, self.move, field={})
        self.assertEqual(result["max"], 135)   # same as no ability/item at all


if __name__ == "__main__":
    unittest.main()
