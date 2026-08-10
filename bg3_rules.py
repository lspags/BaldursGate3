"""Structured BG3 rules shared by the UI, validation, and tests.

Tooltip prose is deliberately not authoritative here. Calculations should use
these explicit fields so a wording change in scraped wiki text cannot alter a
character's statistics.
"""

from __future__ import annotations

from dataclasses import dataclass


POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
PROFICIENCY_THRESHOLDS = ((9, 4), (5, 3), (1, 2))


@dataclass(frozen=True)
class CasterRule:
    mode: str
    ability: str
    progression: str
    prepared_formula: str | None = None


CASTER_RULES = {
    "Bard": CasterRule("known", "Charisma", "full"),
    "Cleric": CasterRule("prepared", "Wisdom", "full", "class_level + ability_modifier"),
    "Druid": CasterRule("prepared", "Wisdom", "full", "class_level + ability_modifier"),
    "Paladin": CasterRule("prepared", "Charisma", "half", "class_level + ability_modifier"),
    "Ranger": CasterRule("known", "Wisdom", "half"),
    "Sorcerer": CasterRule("known", "Charisma", "full"),
    "Warlock": CasterRule("known", "Charisma", "pact"),
    "Wizard": CasterRule("spellbook", "Intelligence", "full", "class_level + ability_modifier"),
}


PALADIN_SPELL_TIERS = ((9, 3), (5, 2), (2, 1))

# Explicit item rules for effects whose behaviour depends on the wielder's
# race. These must not be inferred from tooltip wording.
EQUIPMENT_RACIAL_RULES = {
    "Nimblefinger Gloves": {
        "gnome": {"ability": "Dexterity", "kind": "add", "value": 2, "cap": 30},
        "halfling": {"ability": "Dexterity", "kind": "add", "value": 1, "cap": 30},
        "dwarf": {"ability": "Dexterity", "kind": "add", "value": 1, "cap": 30},
        "duergar": {"ability": "Dexterity", "kind": "add", "value": 1, "cap": 30},
    },
    "Circlet of Psionic Revenge": {
        "githyanki": {"saving_throw_bonus": {"Intelligence": 1, "Wisdom": 1, "Charisma": 1}},
    },
    "Aberration Hunters' Amulet": {
        "githyanki": {"saving_throw_advantage": ["Intelligence"]},
    },
    "Silver Sword of the Astral Plane": {
        "githyanki": {"saving_throw_advantage": ["Intelligence", "Wisdom", "Charisma"]},
    },
}

RECURRING_CHOICE_SCHEDULES = {
    ("Warlock", "Eldritch Invocations"): {2: 2, 5: 1, 7: 1, 9: 1, 12: 1},
    ("Sorcerer", "Metamagic"): {2: 2, 3: 1, 10: 1},
    ("Rogue", "Expertise"): {1: 2, 6: 2},
    ("Bard", "Expertise"): {3: 2, 10: 2},
    ("Fighter", "Battle Manoeuvres"): {3: 3, 7: 2, 10: 2},
    ("Fighter", "Arcane Shots"): {3: 3, 7: 1, 10: 1},
    ("Monk", "Elemental Disciplines"): {3: 3, 6: 1, 9: 1, 11: 1},
    ("Barbarian", "Animal Aspect"): {6: 1, 10: 1},
}


def ability_modifier(score: int) -> int:
    return (int(score) - 10) // 2


def proficiency_bonus(character_level: int) -> int:
    level = max(1, int(character_level or 1))
    return next(bonus for threshold, bonus in PROFICIENCY_THRESHOLDS if level >= threshold)


def point_buy_spent(scores: dict[str, int]) -> int:
    return sum(POINT_BUY_COSTS[int(score)] for score in scores.values())


def prepared_spell_limit(class_name: str, class_level: int, spellcasting_score: int) -> int:
    rule = CASTER_RULES.get(class_name)
    if not rule or not rule.prepared_formula or class_level < (2 if class_name == "Paladin" else 1):
        return 0
    return max(1, int(class_level) + ability_modifier(spellcasting_score))


def paladin_max_spell_level(class_level: int) -> int:
    return next((spell_level for threshold, spell_level in PALADIN_SPELL_TIERS if class_level >= threshold), 0)


def weapon_attack_ability(*, ranged: bool, finesse: bool, monk_weapon: bool,
                          strength_modifier: int, dexterity_modifier: int,
                          pact_weapon: bool = False) -> str:
    if pact_weapon:
        return "Charisma"
    if ranged:
        return "Dexterity"
    if finesse or monk_weapon:
        return "Dexterity" if dexterity_modifier > strength_modifier else "Strength"
    return "Strength"
