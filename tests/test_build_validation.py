import unittest

from build_validation import validate_abilities, validate_identity, validate_level_chain, validate_required_controls


class BuildValidationTests(unittest.TestCase):
    def test_identity_requires_real_subrace_only_when_applicable(self):
        self.assertTrue(validate_identity("Drow", None, "Soldier", {"Drow"}))
        self.assertFalse(validate_identity("Human", None, "Soldier", {"Drow"}))

    def test_complete_point_buy_and_bonuses(self):
        data = {"scores": {"STR": 15, "DEX": 15, "CON": 15, "INT": 8, "WIS": 8, "CHA": 8},
                "plus_two": "STR", "plus_one": "DEX"}
        self.assertEqual(validate_abilities(data), [])

    def test_level_gaps_are_errors(self):
        issues = validate_level_chain(["Fighter", None, "Wizard"])
        self.assertEqual(issues[0].severity, "error")

    def test_optional_replacement_is_not_required(self):
        issues = validate_required_controls(
            [None, ["Fire Bolt"]],
            [{"kind": "replace_from|2|known", "limit": 1}, {"kind": "cantrips|1|class", "limit": 2}],
            "Spells", {"replace_from"},
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("1/2", issues[0].message)

    def test_feat_multiselect_uses_structured_required_count(self):
        issues = validate_required_controls(
            [["Athletics"]], [{"field": "skills", "level": 4}], "Leveling",
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("1/3", issues[0].message)


if __name__ == "__main__":
    unittest.main()
