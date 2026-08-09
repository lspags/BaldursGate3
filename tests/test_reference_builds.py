import unittest

from bg3_rules import ability_modifier, prepared_spell_limit, proficiency_bonus, weapon_attack_ability


class ReferenceBuildTests(unittest.TestCase):
    """Small golden builds that guard several rules at once."""

    def test_level_12_strength_paladin(self):
        level, paladin_level, charisma, strength = 12, 12, 18, 20
        self.assertEqual(proficiency_bonus(level), 4)
        self.assertEqual(prepared_spell_limit("Paladin", paladin_level, charisma), 16)
        self.assertEqual(ability_modifier(strength) + proficiency_bonus(level), 9)
        self.assertEqual(weapon_attack_ability(
            ranged=False, finesse=False, monk_weapon=False,
            strength_modifier=ability_modifier(strength), dexterity_modifier=1,
        ), "Strength")

    def test_level_5_dexterity_finesse_character(self):
        self.assertEqual(proficiency_bonus(5), 3)
        self.assertEqual(weapon_attack_ability(
            ranged=False, finesse=True, monk_weapon=False,
            strength_modifier=0, dexterity_modifier=4,
        ), "Dexterity")

    def test_level_5_pact_weapon_character(self):
        self.assertEqual(weapon_attack_ability(
            ranged=False, finesse=False, monk_weapon=False,
            strength_modifier=3, dexterity_modifier=2, pact_weapon=True,
        ), "Charisma")


if __name__ == "__main__":
    unittest.main()
