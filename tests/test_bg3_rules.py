import unittest

from bg3_rules import (
    EQUIPMENT_RACIAL_RULES, RECURRING_CHOICE_SCHEDULES, ability_modifier, paladin_max_spell_level, point_buy_spent,
    prepared_spell_limit, proficiency_bonus, weapon_attack_ability,
)


class AbilityRulesTests(unittest.TestCase):
    def test_modifier_boundaries(self):
        expected = {1: -5, 8: -1, 10: 0, 13: 1, 15: 2, 17: 3, 20: 5, 30: 10}
        for score, modifier in expected.items():
            self.assertEqual(ability_modifier(score), modifier)

    def test_point_buy_costs(self):
        scores = {"Strength": 15, "Dexterity": 15, "Constitution": 15,
                  "Intelligence": 8, "Wisdom": 8, "Charisma": 8}
        self.assertEqual(point_buy_spent(scores), 27)

    def test_proficiency_tiers(self):
        self.assertEqual([proficiency_bonus(level) for level in (1, 4, 5, 8, 9, 12)], [2, 2, 3, 3, 4, 4])


class SpellcastingRulesTests(unittest.TestCase):
    def test_paladin_prepared_limit_uses_full_class_level(self):
        self.assertEqual(prepared_spell_limit("Paladin", 2, 16), 5)
        self.assertEqual(prepared_spell_limit("Paladin", 9, 18), 13)

    def test_paladin_spell_tiers(self):
        expected = {1: 0, 2: 1, 4: 1, 5: 2, 8: 2, 9: 3, 12: 3}
        for level, spell_level in expected.items():
            self.assertEqual(paladin_max_spell_level(level), spell_level)


class RecurringChoiceTests(unittest.TestCase):
    def test_warlock_invocations_recur_at_every_required_level(self):
        self.assertEqual(
            RECURRING_CHOICE_SCHEDULES[("Warlock", "Eldritch Invocations")],
            {2: 2, 5: 1, 7: 1, 9: 1, 12: 1},
        )

    def test_other_repeated_class_choices_are_tracked(self):
        self.assertEqual(RECURRING_CHOICE_SCHEDULES[("Sorcerer", "Metamagic")][10], 1)
        self.assertEqual(RECURRING_CHOICE_SCHEDULES[("Fighter", "Battle Manoeuvres")][7], 2)
        self.assertEqual(RECURRING_CHOICE_SCHEDULES[("Barbarian", "Animal Aspect")][10], 1)


class WeaponRulesTests(unittest.TestCase):
    def test_attack_ability_selection(self):
        self.assertEqual(weapon_attack_ability(ranged=True, finesse=False, monk_weapon=False,
                                               strength_modifier=4, dexterity_modifier=2), "Dexterity")
        self.assertEqual(weapon_attack_ability(ranged=False, finesse=True, monk_weapon=False,
                                               strength_modifier=1, dexterity_modifier=3), "Dexterity")
        self.assertEqual(weapon_attack_ability(ranged=False, finesse=False, monk_weapon=True,
                                               strength_modifier=4, dexterity_modifier=2), "Strength")
        self.assertEqual(weapon_attack_ability(ranged=False, finesse=False, monk_weapon=False,
                                               strength_modifier=4, dexterity_modifier=2,
                                               pact_weapon=True), "Charisma")

    def test_race_specific_equipment_is_structured(self):
        gloves = EQUIPMENT_RACIAL_RULES["Nimblefinger Gloves"]
        self.assertEqual(gloves["gnome"]["value"], 2)
        self.assertEqual(gloves["dwarf"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
