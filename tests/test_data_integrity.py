import csv
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class DataIntegrityTests(unittest.TestCase):
    def test_spells_have_unique_names_and_sources(self):
        spells = rows(ROOT / "spells.csv")
        names = [row["spell"] for row in spells]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(row["source_url"].startswith("https://bg3.wiki/") for row in spells))
        self.assertTrue(all(row["description"].strip() for row in spells))

    def test_class_progressions_cover_levels_one_to_twelve(self):
        for path in (ROOT / "classes").glob("*.csv"):
            if path.name == "classes.csv":
                continue
            progression = rows(path)
            self.assertEqual([int(row["level"]) for row in progression], list(range(1, 13)), path.name)

    def test_equipment_has_names_and_sources(self):
        for path in (ROOT / "equipment").glob("*.csv"):
            equipment = rows(path)
            self.assertTrue(all(row["item"].strip() for row in equipment), path.name)
            self.assertTrue(all(row["source_url"].startswith("https://bg3.wiki/") for row in equipment), path.name)


if __name__ == "__main__":
    unittest.main()
