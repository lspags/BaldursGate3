from __future__ import annotations

import csv
import re
import time
from datetime import datetime
from collections import Counter
from pathlib import Path
from typing import Any

from dash import ALL, Dash, Input, Output, State, callback, ctx, dcc, html, no_update
from flask import request

from persistence import (
    AUTH_ENABLED, create_build_share, delete_build, delete_team, init_persistence, list_builds, list_teams, load_build,
    revoke_build_share, save_build, save_team, user_identity,
)


ROOT = Path(__file__).resolve().parent


def read_csv(filename: str) -> list[dict[str, str]]:
    with (ROOT / filename).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


RACES = read_csv("races.csv")
BACKGROUNDS = read_csv("backgrounds.csv")
SKILL_GROUPS = read_csv("skills.csv")
CLASSES = read_csv("classes/classes.csv")
FEATS = read_csv("feats.csv")
MAGIC_INITIATE_SPELLS = read_csv("magic_initiate_spells.csv")
SPELLS = read_csv("spells.csv")
WEAPON_PROFICIENCIES = read_csv("weapon_proficiencies.csv")
FIGHTING_STYLES = read_csv("fighting_styles.csv")
RACIAL_TRAITS = read_csv("racial_traits.csv")
# Increment when the generated feature catalogue changes so the Dash reloader refreshes it.
CLASS_FEATURE_DATA_VERSION = 3
CLASS_FEATURES = read_csv("class_features.csv") if (ROOT / "class_features.csv").exists() else []
# Increment whenever generated equipment CSV columns change so the Dash reloader
# rebuilds its in-memory catalogue instead of retaining stale rows.
EQUIPMENT_DATA_VERSION = 2
EQUIPMENT_DIR = ROOT / "equipment"
RANGED_WEAPON_FILES = {"hand_crossbows", "heavy_crossbows", "light_crossbows", "longbows", "shortbows"}
NON_WEAPON_FILES = {"amulets", "armour", "cloaks", "clothing", "footwear", "handwear", "headwear", "light_sources", "rings", "shields"}


def load_equipment_catalogue() -> list[dict[str, str]]:
    records, seen = [], set()
    for path in sorted(EQUIPMENT_DIR.glob("*.csv")):
        file_key = path.stem
        if file_key == "light_sources":
            continue
        if file_key in {"amulets", "armour", "cloaks", "clothing", "footwear", "handwear", "headwear", "rings", "shields"}:
            category = "shield" if file_key == "shields" else file_key
        else:
            category = "ranged" if file_key in RANGED_WEAPON_FILES else "melee"
        item_type = file_key.replace("_", " ").title()
        for row in read_csv(f"equipment/{path.name}"):
            key = (category, item_type, row.get("item", ""))
            if not row.get("item") or key in seen:
                continue
            seen.add(key)
            records.append({**row, "category": category, "item_type": item_type, "equipment_id": "|".join(key)})
    return records


EQUIPMENT = load_equipment_catalogue()
EQUIPMENT_BY_ID = {row["equipment_id"]: row for row in EQUIPMENT}

ACT_ONE_LOCATION_TERMS = ("emerald grove", "the hollow", "sacred pool", "blighted village", "goblin camp", "shattered sanctum", "risen road", "waukeen", "zhentarim", "underdark", "grymforge", "adamantine forge", "crèche", "creche", "rosymorn", "mountain pass", "arcane tower", "myconid", "sunlit wetlands", "overgrown", "ravaged beach")
ACT_TWO_LOCATION_TERMS = ("last light", "moonrise", "gauntlet of shar", "shadow-cursed", "reithwin", "house of healing", "mason's guild", "waning moon", "mind flayer colony", "shadowfell", "sharran sanctuary")
ACT_THREE_LOCATION_TERMS = ("rivington", "jungle", "forge of the nine", "wyrm's", "lower city", "baldur's gate", "stormshore", "sorcerous sundries", "house of hope", "guildhall", "murder tribunal", "bhaal temple", "circus of the last days", "counting house", "steel watch", "iron throne", "house of grief", "cazador", "ramazith", "devil's fee", "danthelon", "facemaker", "highberry", "lora's house", "dragon's sanctum", "undercity")


def equipment_earliest_act(row):
    location = (row.get("where_to_find") or "").lower()
    candidate_acts = [
        act for act, patterns in {
            1: (r"\bact\s+(?:one|1)\b",),
            2: (r"\bact\s+(?:two|2)\b",),
            3: (r"\bact\s+(?:three|3)\b",),
        }.items() if any(re.search(pattern, location, re.IGNORECASE) for pattern in patterns)
    ]
    if any(term in location for term in ACT_ONE_LOCATION_TERMS):
        candidate_acts.append(1)
    if any(term in location for term in ACT_TWO_LOCATION_TERMS):
        candidate_acts.append(2)
    if any(term in location for term in ACT_THREE_LOCATION_TERMS):
        candidate_acts.append(3)
    return min(candidate_acts) if candidate_acts else 1
ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
DAMAGE_TYPES = ["Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison", "Psychic", "Radiant", "Slashing", "Thunder"]
WILD_SHAPE_FORMS = {
    "Badger": {"level": 2, "actions": [("Claws", "2d4+2", "Slashing"), ("Bite", "1d6+2", "Piercing")]},
    "Cat": {"level": 2, "actions": [("Claws", "1", "Slashing")]},
    "Spider": {"level": 2, "actions": [("Bite", "1d8+3;1d10", "Piercing, Poison")]},
    "Wolf": {"level": 2, "actions": [("Bite", "2d4+3", "Piercing"), ("Exposing Bite", "2d4+3", "Piercing")]},
    "Bear": {"level": 2, "moon": True, "actions": [("Claws", "2d4+4", "Slashing")]},
    "Deep Rothé": {"level": 4, "actions": [("Gore", "1d8+4", "Piercing"), ("Charge", "1d8+4", "Piercing")]},
    "Dire Raven": {"level": 4, "moon": True, "actions": [("Beak", "1d6+2", "Piercing"), ("Rend Vision", "1d6+2", "Piercing")]},
    "Panther": {"level": 6, "actions": [("Jugular Strike", "1d6+2", "Piercing")], "bonus": [("Pounce", "1d6+2", "Bludgeoning")]},
    "Owlbear": {"level": 6, "actions": [("Claws", "1d8+5", "Slashing"), ("Rupture", "1d8", "Bludgeoning")], "bonus": [("Crushing Flight", "1d8", "Bludgeoning")]},
    "Sabre-Toothed Tiger": {"level": 8, "moon": True, "actions": [("Bite", "2d6+4", "Piercing"), ("Jugular Strike", "2d6+4", "Piercing"), ("Shred Armour", "2d6+4", "Slashing")]},
    "Dilophosaurus": {"level": 10, "actions": [("Bite", "1d10+4", "Piercing"), ("Corrosive Spit", "2d8+4", "Acid")], "bonus": [("Pounce", "2d6+4", "Bludgeoning")]},
    "Air Myrmidon": {"level": 10, "moon": True, "myrmidon": True, "actions": [("Electrified Flail", "1d8+4;1d10", "Bludgeoning, Lightning"), ("Raging Vortex", "2d8", "Lightning")]},
    "Earth Myrmidon": {"level": 10, "moon": True, "myrmidon": True, "actions": [("Grounded Thunder Strike", "1d10+4;1d10", "Bludgeoning, Thunder")], "bonus": [("Muck to Metal", "1d8", "Acid")]},
    "Fire Myrmidon": {"level": 10, "moon": True, "myrmidon": True, "actions": [("Scorching Strike", "1d6+4;1d6", "Slashing, Fire"), ("Cinderous Swipe", "2d6", "Fire")]},
    "Water Myrmidon": {"level": 10, "moon": True, "myrmidon": True, "actions": [("Trident Strike", "1d8+4;1d6", "Piercing, Cold"), ("Explosive Icicle", "3d8", "Cold")]},
}
WILD_SHAPE_STRENGTH = {
    "Badger": 14, "Cat": 6, "Spider": 14, "Wolf": 17, "Bear": 19,
    "Deep Rothé": 18, "Dire Raven": 6, "Panther": 14, "Owlbear": 20,
    "Sabre-Toothed Tiger": 18, "Dilophosaurus": 19, "Air Myrmidon": 18,
    "Earth Myrmidon": 18, "Fire Myrmidon": 13, "Water Myrmidon": 18,
}
POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
FIXED_FEAT_ABILITIES = {
    "Actor": ("Charisma", 1), "Durable": ("Constitution", 1),
    "Heavily Armoured": ("Strength", 1), "Heavy Armour Master": ("Strength", 1),
    "Performer": ("Charisma", 1),
}
CHOICE_FEAT_ABILITIES = {
    "Athlete": ["Strength", "Dexterity"], "Lightly Armoured": ["Strength", "Dexterity"],
    "Moderately Armoured": ["Strength", "Dexterity"], "Tavern Brawler": ["Strength", "Constitution"],
    "Weapon Master": ["Strength", "Dexterity"], "Resilient": ABILITIES,
}
RITUAL_SPELLS = ["Speak with Dead", "Find Familiar", "Longstrider", "Enhance Leap", "Disguise Self", "Speak with Animals"]
SPELL_SNIPER_CANTRIPS = ["Bone Chill", "Eldritch Blast", "Fire Bolt", "Ray of Frost", "Shocking Grasp", "Thorn Whip"]
MANOEUVRES = ["Commander's Strike", "Disarming Attack", "Distracting Strike", "Evasive Footwork", "Feinting Attack", "Goading Attack", "Manoeuvring Attack", "Menacing Attack", "Precision Attack", "Pushing Attack", "Rally", "Riposte", "Sweeping Attack", "Trip Attack"]
ARCANE_SHOTS = ["Arcane Shot: Banishing Arrow", "Arcane Shot: Beguiling Arrow", "Arcane Shot: Bursting Arrow", "Arcane Shot: Enfeebling Arrow", "Arcane Shot: Grasping Arrow", "Arcane Shot: Piercing Arrow", "Arcane Shot: Seeking Arrow", "Arcane Shot: Shadow Arrow"]
METAMAGIC_BASIC = ["Careful Spell", "Distant Spell", "Extended Spell", "Twinned Spell"]
METAMAGIC_ADVANCED = ["Heightened Spell", "Quickened Spell", "Subtle Spell"]
SWORDS_BARD_ATTACKS = ["Defensive Flourish (Melee)", "Defensive Flourish (Ranged)", "Slashing Flourish (Melee)", "Slashing Flourish (Ranged)", "Mobile Flourish (Melee)", "Mobile Flourish (Ranged)"]
SUBCLASS_ATTACK_FEATURES = {
    "Frenzied Strike", "Enraged Throw",
    "Radiance of the Dawn", "Touch of Death", "Divine Strike: Thunder", "Divine Strike: Weapon",
    "Divine Strike: Poison", "Divine Strike: Elemental Fury", "Divine Strike: Necrotic", "Divine Strike: Radiant",
    "Halo of Spores", "Spreading Spores", "Curving Shot",
    "Chill of the Mountain", "Fangs of the Fire Snake", "Fist of Unbroken Air", "Sweeping Cinder Strike",
    "Touch of the Storm", "Intoxicating Strike", "Redirect Attack", "Ki Resonation: Punch",
    "Ki Resonation: Punch (bonus action)", "Ki Resonation: Blast", "Shadow Strike", "Shadow Strike: Unarmed",
    "Giant Killer", "Volley", "Whirlwind Attack", "Rakish Sneak Attack (Melee)", "Rakish Sneak Attack (Ranged)",
    "Storm's Fury",
} | set(SWORDS_BARD_ATTACKS)
NON_ATTACK_SUBCLASS_ACTIONS = {"Symbiotic Entity", "Elemental Cleaver", "Combat Inspiration", "Blade Flourish"}
CORE_COMBAT_ACTIONS = {
    "Reckless Attack", "Divine Smite", "Sneak Attack (Melee)", "Sneak Attack (Ranged)",
    "Martial Arts: Bonus Unarmed Strike", "Flurry of Blows", "Stunning Strike (Melee)", "Stunning Strike (Unarmed)",
    "Flurry of Blows: Topple", "Flurry of Blows: Stagger", "Flurry of Blows: Push", "Drunken Technique",
    "Turn Undead", "Destroy Undead",
    "Boot of the Giants", "Intimidating Presence", "Mighty Impel", "Mantle of Majesty: Command",
    "Radiance of the Dawn", "Charm Animals and Plants", "Water Whip", "Starry Form: Archer", "Starry Form: Chalice", "Starry Form: Dragon",
    "Abjure Enemy", "Dreadful Aspect", "Nature's Wrath", "Fey Presence", "Hexblade's Curse",
    "Hypnotic Gaze", "Dirty Trick: Flick o' the Wrist", "Dirty Trick: Sand Toss", "Panache",
}
NON_COMBAT_ACTION_FEATURES = NON_ATTACK_SUBCLASS_ACTIONS | {
    "Rage", "Frenzy", "Giant's Rage", "Rage: Wild Magic", "Magic Awareness", "Bolstering Magic: Boon",
    "Natural Recovery", "Combat Wild Shape", "Lunar Mend",
    "Weapon Bond", "Harmony of Fire and Water", "Wholeness of Body", "Shadow Step", "Mist Stance", "Ride the Wind",
    "Healing Radiance", "Inquisitor's Might", "Vow of Enmity", "Aura of Protection", "Aura of Warding",
    "Aura of Devotion", "Aura of Hate", "Aura of Courage", "Ranger's Companion", "Dread Ambusher: Hide",
    "Umbral Shroud", "Writhing Tide", "Infiltration Expertise", "Supreme Sneak", "Hound of Ill Omen", "Fly",
    "Shadow Walk", "Bind Hexed Weapon", "Benign Transposition", "Third Eye: Darkvision", "Third Eye: See Invisibility",
    "Shapechanger",
}
COMBAT_ACTION_DESCRIPTIONS = {
    "Sneak Attack (Melee)": "Deal additional Sneak Attack damage with a Finesse melee weapon when its requirements are met.",
    "Sneak Attack (Ranged)": "Deal additional Sneak Attack damage with a ranged weapon when its requirements are met.",
    "Martial Arts: Bonus Unarmed Strike": "After attacking with a Monk weapon or unarmed strike, make an unarmed strike as a Bonus Action.",
    "Flurry of Blows": "Spend a Ki Point and a Bonus Action to punch twice in quick succession.",
    "Stunning Strike (Melee)": "Spend a Ki Point after a melee weapon hit to deal weapon damage and potentially Stun the target.",
    "Stunning Strike (Unarmed)": "Spend a Ki Point to make an unarmed attack that can Stun the target.",
    "Divine Smite": "After a melee weapon hit, expend a spell slot to deal additional Radiant damage.",
    "Turn Undead": "Spend Channel Divinity to Turn nearby undead; affected creatures flee and cannot take actions or reactions.",
    "Starry Form: Archer": "Spend a Wild Shape Charge to enter Archer form. Luminous Arrow then deals 1d8 + Wisdom modifier Radiant damage as a Bonus Action, increasing to 2d8 at Druid level 10.",
    "Starry Form: Chalice": "Spend a Wild Shape Charge to enter Chalice form. After casting an eligible healing spell, heal another target for 1d8 + Wisdom modifier, increasing to 2d8 at Druid level 10.",
    "Starry Form: Dragon": "Spend a Wild Shape Charge to enter Dragon form. Dazzling Breath deals Radiant damage as a Bonus Action and the form improves Concentration saves.",
}
ARCANE_SHOT_DESCRIPTIONS = {
    "Arcane Shot: Banishing Arrow": "Deal normal weapon damage and potentially Banish the target.",
    "Arcane Shot: Beguiling Arrow": "Deal normal weapon damage plus 2d6 Psychic damage and potentially Charm the target.",
    "Arcane Shot: Bursting Arrow": "Deal normal weapon damage plus 2d6 Force damage in a 5 m radius.",
    "Arcane Shot: Enfeebling Arrow": "Deal normal weapon damage plus 2d6 Necrotic damage and potentially make the target Feeble.",
    "Arcane Shot: Grasping Arrow": "Deal normal weapon damage plus 2d6 Poison damage and entangle the target in damaging brambles.",
    "Arcane Shot: Piercing Arrow": "Fire through targets in a 10 m line for normal weapon damage plus 1d6 weapon damage.",
    "Arcane Shot: Seeking Arrow": "Deal normal weapon damage plus 1d6 Force damage and reveal the target with Faerie Fire.",
    "Arcane Shot: Shadow Arrow": "Deal normal weapon damage plus 2d6 Psychic damage and potentially Blind the target.",
}
WEAPON_TYPES = ["Battleaxes", "Clubs", "Daggers", "Flails", "Glaives", "Greataxes", "Greatclubs", "Greatswords", "Halberds", "Hand Crossbows", "Handaxes", "Heavy Crossbows", "Javelins", "Light Crossbows", "Light Hammers", "Longbows", "Longswords", "Maces", "Mauls", "Morningstars", "Pikes", "Quarterstaves", "Rapiers", "Scimitars", "Shortbows", "Shortswords", "Sickles", "Spears", "Tridents", "War Picks", "Warhammers"]
SKILL_TO_ABILITY = {
    skill: row["ability"]
    for row in SKILL_GROUPS
    for skill in row["skills"].split("; ")
    if skill and skill != "None"
}


def snake_case(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


CLASS_PROGRESSIONS = {
    row["class"]: read_csv(f"classes/{snake_case(row['class'])}.csv") for row in CLASSES
}


def meaningful(*values: str) -> list[str]:
    return [value.strip() for value in values if value and value.strip() not in {"-", "None"}]


def metric_movement(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*m\b", value or "")
    return f"{match.group(1)} m" if match else "—"


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def spellcasting_ability_name(value: str) -> str:
    matches = [(match.start(), ability) for ability in ABILITIES if (match := re.search(rf"\b{ability}\b", value or "", re.IGNORECASE))]
    return min(matches)[1] if matches else "None"


def proficiency_bonus(level: int) -> int:
    if level >= 9:
        return 4
    if level >= 5:
        return 3
    return 2


def feat_choice_dropdown(level: int, field: str, label: str, options, multi: bool = False):
    return html.Div(
        [html.Label(label), dcc.Dropdown(
            id={"type": "feat-choice", "level": level, "field": field},
            options=[{"label": option, "value": option} for option in options],
            multi=multi,
            placeholder=f"Choose {label.lower()}",
            className="rich-dropdown compact-dropdown",
        )],
        className="feat-choice-field",
    )


def skills_mentioned(*values: str) -> set[str]:
    combined = " ".join(value or "" for value in values).lower()
    return {skill for skill in SKILL_TO_ABILITY if re.search(rf"\b{re.escape(skill.lower())}\b", combined)}


def ability_rows() -> list[html.Div]:
    rows = []
    for ability in ABILITIES:
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(ability[:3].upper(), className="ability-icon"),
                            html.Span(ability, className="ability-name"),
                        ],
                        className="ability-heading",
                    ),
                    html.Button(
                        "−",
                        id={"type": "ability-step", "ability": ability, "direction": -1},
                        n_clicks=0,
                        className="ability-step ability-step--minus",
                    ),
                    html.Span("8", id={"type": "ability-score", "ability": ability}, className="ability-score"),
                    html.Button(
                        "+",
                        id={"type": "ability-step", "ability": ability, "direction": 1},
                        n_clicks=0,
                        className="ability-step ability-step--plus",
                    ),
                    html.Button(
                        "",
                        id={"type": "ability-bonus-select", "ability": ability, "bonus": 2},
                        n_clicks=0,
                        className="bonus-check",
                        **{"aria-label": f"Assign +2 bonus to {ability}"},
                    ),
                    html.Button(
                        "",
                        id={"type": "ability-bonus-select", "ability": ability, "bonus": 1},
                        n_clicks=0,
                        className="bonus-check",
                        **{"aria-label": f"Assign +1 bonus to {ability}"},
                    ),
                ],
                className="ability-row",
            )
        )
    return rows


def leveling_rows() -> list[html.Div]:
    rows = []
    for level in range(1, 13):
        rows.append(
            html.Article(
                [
                    html.Div(
                        [html.Span("CHARACTER LEVEL", className="level-row-kicker"), html.Strong(str(level))],
                        className="level-row-number",
                    ),
                    html.Div(
                        [
                            html.Label("Class"),
                            dcc.Dropdown(
                                id={"type": "level-class", "level": level},
                                options=class_options(),
                                placeholder="Choose class",
                                optionHeight=142,
                                maxHeight=430,
                                disabled=level != 1,
                                className="rich-dropdown",
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        className="field",
                    ),
                    html.Div(
                        [
                            html.Label("Subclass"),
                            dcc.Dropdown(
                                id={"type": "level-subclass", "level": level},
                                placeholder="Not available",
                                disabled=True,
                                className="rich-dropdown compact-dropdown",
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        id={"type": "level-subclass-field", "level": level},
                        className="field",
                    ),
                    html.Div(
                        [
                            html.Label("Feat"),
                            dcc.Dropdown(
                                id={"type": "level-feat", "level": level},
                                options=feat_options(),
                                placeholder="No feat at this level",
                                disabled=True,
                                optionHeight=112,
                                maxHeight=420,
                                className="rich-dropdown compact-dropdown",
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        id={"type": "level-feat-field", "level": level},
                        className="field",
                    ),
                    html.Div(id={"type": "level-details", "level": level}, className="level-row-details"),
                    html.Div(id={"type": "feat-choice-container", "level": level}, className="feat-choice-container"),
                    html.Div(id={"type": "class-choice-container", "level": level}, className="feat-choice-container"),
                ],
                id={"type": "level-row", "level": level},
                className="level-selection-row",
                style={} if level == 1 else {"display": "none"},
            )
        )
    return rows


def formula_base(value: str) -> int:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else 0


def option_label(title: str, details: list[str], title_class: str = "") -> html.Div:
    return html.Div(
        [
            html.Span(title, className=f"option-title {title_class}".strip()),
            html.Span(" • ".join(details), className="option-detail") if details else None,
        ],
        className="dropdown-option",
    )


def race_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for race in dict.fromkeys(row["race"] for row in RACES):
        row = next(item for item in RACES if item["race"] == race)
        details = meaningful(row["base_speed"], row["race_proficiencies"], row["race_features"])
        options.append({"label": option_label(race, details), "value": race, "search": f"{race} {' '.join(details)}"})
    return options


def background_options() -> list[dict[str, Any]]:
    return [
        {
            "label": option_label(row["background"], [f"Skills: {row['skill_proficiencies']}"]),
            "value": row["background"],
            "search": f"{row['background']} {row['skill_proficiencies']}",
        }
        for row in BACKGROUNDS
    ]


def class_options() -> list[dict[str, Any]]:
    options = []
    for row in CLASSES:
        details = meaningful(
            f"Key abilities: {row['key_abilities']}",
            f"Hit points: {row['hit_points_level_1']} at level 1",
            row["description"],
        )
        options.append(
            {
                "label": option_label(row["class"], details),
                "value": row["class"],
                "search": f"{row['class']} {' '.join(details)}",
            }
        )
    return options


def feat_options() -> list[dict[str, Any]]:
    return [
        {
            "label": option_label(row["feat"], [row["description"]]),
            "value": row["feat"],
            "search": f"{row['feat']} {row['description']}",
        }
        for row in FEATS
    ]


def equipment_rarity_class(row: dict[str, str]) -> str:
    rarity = (row.get("rarity") or "Common").strip().lower()
    if "story" in rarity:
        return "item-rarity--story"
    return {
        "uncommon": "item-rarity--uncommon",
        "rare": "item-rarity--rare",
        "very rare": "item-rarity--very-rare",
        "legendary": "item-rarity--legendary",
    }.get(rarity, "item-rarity--common")


def equipment_type_label(row: dict[str, str]) -> str:
    armour_type = (row.get("armour_type") or "").strip()
    if armour_type and armour_type.lower() != "non-armour":
        return f"{armour_type} Armour"
    return {
        "amulets": "Necklace", "rings": "Ring", "handwear": "Handwear",
        "footwear": "Footwear", "headwear": "Headwear", "cloaks": "Cape", "clothing": "Clothing",
        "armour": "Armour", "shield": "Shield",
    }.get(row["category"], row.get("item_type", ""))


def equipment_option(row: dict[str, str]) -> dict[str, Any]:
    details = meaningful(
        f"Available by Act {equipment_earliest_act(row)}",
        equipment_type_label(row),
        row.get("damage", ""),
        f"AC {row['armour_class']}" if row.get("armour_class") else "",
        row.get("shared_properties", ""),
        row.get("special", ""),
    )
    return {
        "label": option_label(row["item"], details, equipment_rarity_class(row)),
        "value": row["equipment_id"],
        "search": f"{row['item']} {' '.join(details)}",
    }


def equipment_field(label: str, component_id: str) -> html.Div:
    return html.Div(
        [html.Label(label, htmlFor=component_id), dcc.Dropdown(
            id=component_id, placeholder=f"Search or choose {label.lower()}", clearable=True, searchable=True,
            optionHeight=118, maxHeight=430, className="rich-dropdown equipment-dropdown",
            persistence=True, persistence_type="session",
        )],
        className="field equipment-field",
    )


def equipment_tooltip(row: dict[str, str]) -> str:
    parts = meaningful(
        equipment_type_label(row), row.get("rarity", "") or "Common",
        f"Damage: {row.get('damage')} {row.get('damage_type', '')}" if row.get("damage") else "",
        f"Armour Class: {row.get('armour_class')}" if row.get("armour_class") else "",
        f"Properties: {row.get('shared_properties')}" if row.get("shared_properties") else "",
        row.get("special", ""), row.get("description", ""),
    )
    return " · ".join(parts)[:900]


def item_has_property(row: dict[str, str] | None, name: str) -> bool:
    return bool(row and name.lower() in row.get("shared_properties", "").lower())


def defensive_effects(text: str, source: str) -> dict[str, list[tuple[str, str]]]:
    results = {"resistances": [], "immunities": [], "vulnerabilities": []}
    if not text:
        return results
    chunks = [chunk.strip() for chunk in re.split(r";|\.(?=\s+[A-Z])", text) if chunk.strip()]
    for chunk in chunks:
        lowered = chunk.lower()
        if any(phrase in lowered for phrase in ("ignore resistance", "bypass resistance", "enemies", "creatures hit", "target vulnerable", "make it vulnerable", "allied undead", "summoned creatures", "grant an ally")):
            continue
        conditional = any(word in lowered for word in ("while ", "if ", "when ", "short rest", "wild shape", "raging", "enter a rage"))
        suffix = " (conditional)" if conditional else ""
        damage_types = [damage for damage in DAMAGE_TYPES if re.search(rf"\b{damage.lower()}\b", lowered)]

        is_resistance = bool(re.search(r"\bresistan(?:ce|t)\b", lowered))
        if is_resistance:
            labels = damage_types
            if "physical damage" in lowered or "blade ward" in lowered:
                labels = ["Bludgeoning", "Piercing", "Slashing"]
            elif "falling damage" in lowered:
                labels = ["Falling damage"]
            elif "trap" in lowered:
                labels = ["Trap damage"]
            elif "all damage" in lowered and "except psychic" in lowered:
                labels = [f"All except Psychic"]
            elif "damage type" in lowered and not labels:
                labels = ["Chosen damage type"]
            for label in labels:
                results["resistances"].append((label + suffix, f"{source}: {chunk}"))

        is_immunity = "immun" in lowered or re.search(r"\b(?:can't|cannot) be\b", lowered)
        if is_immunity and "unless" not in lowered:
            immunity_starts = [position for needle in ("immunity", "immune", "can't be", "cannot be") if (position := lowered.find(needle)) >= 0]
            immunity_scope = lowered[min(immunity_starts):] if immunity_starts else lowered
            labels = [damage for damage in DAMAGE_TYPES if re.search(rf"\b{damage.lower()}\b", immunity_scope)]
            condition_names = {
                "charm": "Charmed", "sleep": "Magical Sleep", "fright": "Frightened",
                "poison": "Poisoned", "disease": "Disease", "blind": "Blinded",
                "stun": "Stunned", "burn": "Burning", "enweb": "Enwebbed",
                "electrocut": "Electrocuted", "falling": "Falling damage",
            }
            labels += [label for needle, label in condition_names.items() if needle in immunity_scope and label not in labels]
            for label in labels:
                results["immunities"].append((label + suffix, f"{source}: {chunk}"))

        if "vulnerab" in lowered and not any(word in lowered for word in ("enemy", "target", "creature")):
            for label in damage_types:
                results["vulnerabilities"].append((label + suffix, f"{source}: {chunk}"))
    return results


def defence_column(title: str, entries: list[tuple[str, str]], class_name: str) -> html.Div:
    unique = {}
    for label, tooltip in entries:
        unique.setdefault(label, []).append(tooltip)
    terms = []
    for label, tooltips in unique.items():
        terms.append(html.Span(label, className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": " | ".join(dict.fromkeys(tooltips))[:900]}))
    return html.Div([
        html.Span(title, className="summary-label"),
        html.Div([html.Span([term, ", " if index < len(terms) - 1 else ""]) for index, term in enumerate(terms)] if terms else "—", className="sheet-defence-values"),
    ], className=f"sheet-defence-column {class_name}")


def detail_block(label: str, value: str) -> html.Div:
    return html.Div([html.Span(label, className="summary-label"), html.Span(value or "—")], className="summary-row")


def proficiency_tooltip_text(value: str):
    """Turn known weapon category names into accessible hover/focus tooltips."""
    if not value:
        return "—"
    lookup = {row["proficiency"].lower(): row for row in WEAPON_PROFICIENCIES}
    parts = re.split(r"(Simple weapons|Martial weapons)", value, flags=re.IGNORECASE)
    rendered = []
    for part in parts:
        row = lookup.get(part.lower())
        if not row:
            rendered.append(part)
            continue
        tooltip = f"{row['description']} Includes: {row['included_weapon_types'].replace(';', ',')}."
        rendered.append(html.Span(part, className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": tooltip}))
    return rendered


def racial_trait_tooltips(value: str):
    if not value or value.strip() in {"", "-"}:
        return "—"
    found = []
    occupied = []
    for row in sorted(RACIAL_TRAITS, key=lambda item: len(item["trait"]), reverse=True):
        match = re.search(re.escape(row["trait"]), value, re.IGNORECASE)
        if match and not any(match.start() < end and match.end() > start for start, end in occupied):
            found.append((match.start(), row))
            occupied.append(match.span())
    if not found:
        return value
    rendered = []
    for index, (_, row) in enumerate(sorted(found)):
        if index:
            rendered.append(", ")
        rendered.append(html.Span(row["trait"], className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": row["description"]}))
    return rendered


def feat_tooltips(feat_values):
    rendered = []
    seen = set()
    for feat in feat_values or []:
        if not feat or feat in seen:
            continue
        seen.add(feat)
        row = next((item for item in FEATS if item["feat"] == feat), None)
        if rendered:
            rendered.append(", ")
        rendered.append(
            html.Span(
                feat,
                className="sheet-tooltip-term",
                tabIndex=0,
                **{"data-tooltip": row["description"] if row else "Feat selected during level up."},
            )
        )
    return rendered


PACT_BOONS = {
    "Pact of the Blade": "Summon or bind a magical pact weapon that uses your spellcasting ability modifier instead of Strength or Dexterity.",
    "Pact of the Chain": "Gain a familiar that can take an animal, imp, or quasit form.",
    "Pact of the Tome": "Gain the Book of Shadows and the Guidance, Vicious Mockery, and Thorn Whip cantrips.",
}
CLASS_FEATURE_OVERRIDES = {
    "Spellcasting": "Allows you to learn or prepare class spells and cast them using spell slots and your class's spellcasting ability. Cantrips can normally be cast without expending a spell slot.",
    "Arcane Recovery": "Once per day while out of combat, replenish expended spell slots using Arcane Recovery Charges equal to half your Wizard level, rounded up. Restoring a slot costs charges equal to its level, and slots above level 5 cannot be restored.",
    "Pact Magic": "Allows you to learn and cast Warlock spells using Charisma. Warlock spells are always prepared, Pact Magic slots are always cast at the highest spell level currently available to you, and all expended Pact Magic slots are restored after a short or long rest.",
    "Cunning Action: Dash": "Use a bonus action to double your movement speed for the current turn.",
    "Cunning Action: Disengage": "Use a bonus action to retreat safely; your movement does not provoke Opportunity Attacks for the rest of the turn.",
    "Cunning Action: Hide": "Use a bonus action to hide from enemies by succeeding on Stealth checks and staying outside their sight.",
    "Divine Smite": "When a melee weapon attack hits, expend a spell slot to deal additional Radiant damage. Higher-level spell slots deal more damage.",
    "Second Wind": "Use a bonus action once per short rest to regain hit points equal to 1d10 plus your Fighter level.",
    "Wild Shape": "Transform into a beast using a Wild Shape charge, gaining that form's physical statistics and abilities while retaining your mental ability scores.",
    "Jack of All Trades": "Add half your proficiency bonus, rounded down, to ability checks using skills in which you are not proficient.",
    "Deepened Pact": "Improves your chosen Pact Boon at Warlock level 5: Blade gains an extra pact-weapon attack, Chain familiars gain an extra attack, and Tome gains additional once-per-long-rest spells.",
    "Transcribing scrolls": "Copy eligible Wizard spells from scrolls into your spellbook by paying gold. The spell must be a level you can prepare.",
    "Create Sorcery Points": "Convert a spell slot into Sorcery Points. Higher-level slots create more points.",
    "Create Spell Slot": "Spend Sorcery Points to create a spell slot. Higher-level slots cost more Sorcery Points.",
    "Font of Inspiration": "Bardic Inspiration charges are restored on a short rest as well as a long rest.",
    "Lay on Hands": "Spend a Lay on Hands charge to heal a creature or cure it of diseases and poisons.",
    "Sneak Attack (Melee)": "Deal additional weapon damage with a finesse melee weapon when you have Advantage or an adjacent ally enables Sneak Attack.",
    "Sneak Attack (Ranged)": "Deal additional weapon damage with a ranged weapon when you have Advantage or an adjacent ally enables Sneak Attack.",
}


def class_feature_tooltips(features, inline_descriptions=None):
    inline_descriptions = inline_descriptions or {}
    rendered = []
    for feature in dict.fromkeys(features or []):
        row = next((item for item in CLASS_FEATURES if item["feature"].lower() == feature.lower()), None)
        style = next((item for item in FIGHTING_STYLES if item["fighting_style"].lower() == feature.lower()), None)
        if not row:
            row = next((item for item in CLASS_FEATURES if item["feature"].lower().split(" (")[0] == feature.lower().split(" (")[0]), None)
        wiki_description = row["description"] if row else ""
        inline_description = inline_descriptions.get(feature, "")
        description = CLASS_FEATURE_OVERRIDES.get(feature) or PACT_BOONS.get(feature) or (style or {}).get("description", "") or " ".join(dict.fromkeys(filter(None, [inline_description, wiki_description]))) or f"Class feature: {feature}."
        if rendered:
            rendered.append(", ")
        rendered.append(html.Span(feature, className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": description[:900]}))
    return rendered


def feature_names(value: str) -> list[str]:
    ignored = {"-", "Feat", "Choose a subclass", "Choose a Subclass", "Subclass feature", "Subclass Feature"}
    parts = re.split(r";|,\s*(?=[A-Z])", value or "")
    cleaned = [part.strip(" :*") for part in parts]
    return [
        part for part in cleaned
        if part and not part.endswith(".") and part not in ignored
        and not re.match(r"^(?:\+?\d+(?:d\d+)?|Gain|Choose|Select|Learn|New Spells|Spells? Known|Replacement Spell|Improved Warlock Spell Slots)\b", part, re.IGNORECASE)
        and part.lower() not in {"martial weapons", "medium armour", "shields"}
    ]


def inline_feature_descriptions(value: str) -> dict[str, str]:
    parts = [part.strip(" :*") for part in re.split(r";|,\s*(?=[A-Z])", value or "") if part.strip(" :*")]
    descriptions, current_title = {}, None
    for part in parts:
        if part.endswith("."):
            if current_title:
                descriptions[current_title] = " ".join(filter(None, [descriptions.get(current_title, ""), part]))
        elif part in feature_names(part):
            current_title = part
    return descriptions


def progression_features_by_class(class_values, subclass_values) -> dict[str, list[str]]:
    active_classes = []
    for class_name in class_values or []:
        if not class_name:
            break
        active_classes.append(class_name)
    subclass_by_class = {
        class_name: subclass
        for class_name, subclass in zip(class_values or [], subclass_values or [])
        if class_name and subclass
    }
    features = {}
    counts = Counter()
    for class_name in active_classes:
        counts[class_name] += 1
        row = CLASS_PROGRESSIONS[class_name][counts[class_name] - 1]
        features.setdefault(class_name, []).extend(feature_names(row.get("class_features", "")))
        subclass = subclass_by_class.get(class_name)
        if subclass:
            features[class_name].extend(feature_names(row.get(snake_case(subclass), "")))
    return {class_name: list(dict.fromkeys(values)) for class_name, values in features.items()}


def earned_subclass_attacks(class_values, subclass_values) -> dict[str, list[str]]:
    subclass_by_class = {
        class_name: subclass for class_name, subclass in zip(class_values or [], subclass_values or [])
        if class_name and subclass
    }
    attacks, counts = {}, Counter()
    for class_name in class_values or []:
        if not class_name:
            break
        counts[class_name] += 1
        subclass = subclass_by_class.get(class_name)
        if not subclass:
            continue
        row = CLASS_PROGRESSIONS[class_name][counts[class_name] - 1]
        values = feature_names(row.get(snake_case(subclass), ""))
        spell_names = {spell["spell"].lower() for spell in SPELLS}
        for feature in values:
            if feature.lower() in spell_names or feature in NON_ATTACK_SUBCLASS_ACTIONS:
                continue
            feature_row = next((item for item in CLASS_FEATURES if item["feature"].lower() == feature.lower()), None)
            description = (feature_row or {}).get("description", "").lower()
            action_like = bool(
                "weapon action" in description
                or re.search(r"\b(?:class|bonus|free) action\b", description)
                and re.search(r"\b(?:deals?|make|perform|launch|fire|hit|punch|strike|throw)[^.]{0,90}\b(?:damage|attack|target|enemy)", description)
                or "reaction" in description and re.search(r"\b(?:retaliate|redirect|deal extra|make an? .*attack)", description)
            )
            if feature in SUBCLASS_ATTACK_FEATURES or action_like:
                attacks.setdefault(class_name, []).append(feature)
    return {class_name: list(dict.fromkeys(values)) for class_name, values in attacks.items() if values}


def earned_combat_actions(class_values, subclass_values) -> dict[str, list[str]]:
    progression = progression_features_by_class(class_values, subclass_values)
    subclass_actions = earned_subclass_attacks(class_values, subclass_values)
    spell_names = {spell["spell"].lower() for spell in SPELLS}
    results = {}
    for class_name, features in progression.items():
        candidates = list(dict.fromkeys(features + subclass_actions.get(class_name, [])))
        for feature in candidates:
            if feature.lower() in spell_names or feature in NON_COMBAT_ACTION_FEATURES:
                continue
            feature_row = next((item for item in CLASS_FEATURES if item["feature"].lower() == feature.lower()), None)
            description = (feature_row or {}).get("description", "").lower()
            action_marker = bool(re.search(r"\b(?:weapon|class|bonus|free) action\b|\breaction\b", description))
            direct_effect = bool(re.search(
                r"\b(?:make|perform|redirect|retaliate|deal|deals|hit|strike|throw|kick|punch|inflict|knock|push|pull|frighten|charm|stun|intoxicate|command|curse|hypnoti)[^.]{0,110}\b(?:attack|damage|target|enemy|creature|prone|condition|frightened|charmed|stunned|blinded)",
                description,
            ))
            passive_only = "passive feature" in description and not ("reaction" in description or "weapon action" in description)
            if feature in CORE_COMBAT_ACTIONS or feature in SUBCLASS_ATTACK_FEATURES or action_marker and direct_effect and not passive_only:
                results.setdefault(class_name, []).append(feature)
    return {class_name: list(dict.fromkeys(values)) for class_name, values in results.items() if values}


def progression_feature_descriptions(class_values, subclass_values) -> dict[str, str]:
    subclass_by_class = {class_name: subclass for class_name, subclass in zip(class_values or [], subclass_values or []) if class_name and subclass}
    descriptions, counts = {}, Counter()
    for class_name in class_values or []:
        if not class_name:
            break
        counts[class_name] += 1
        row = CLASS_PROGRESSIONS[class_name][counts[class_name] - 1]
        descriptions.update(inline_feature_descriptions(row.get("class_features", "")))
        subclass = subclass_by_class.get(class_name)
        if subclass:
            descriptions.update(inline_feature_descriptions(row.get(snake_case(subclass), "")))
    return descriptions


def proficiency_items(*values) -> list[str]:
    items = []
    for value in values:
        chunks = list(value) if isinstance(value, (list, tuple, set)) else re.split(r"[;,]", value or "")
        for chunk in chunks:
            item = re.sub(r"^(Weapons?|Armou?r|Skills?)\s*:?\s*", "", str(chunk).strip(), flags=re.IGNORECASE).strip()
            if item and item not in {"-", "None"} and item.lower() != "one skill of choice" and item.lower() not in {existing.lower() for existing in items}:
                items.append(item)
    return items


def collapse_weapon_proficiencies(items: list[str]) -> list[str]:
    present = {item.lower() for item in items}
    covered = set()
    for row in WEAPON_PROFICIENCIES:
        if row["proficiency"].lower() in present:
            covered.update(weapon.strip().lower() for weapon in row["included_weapon_types"].split(";") if weapon.strip())
    return [item for item in items if item.lower() not in covered]


PREPARED_CASTERS = {"Cleric", "Druid", "Paladin", "Wizard"}
KNOWN_CASTERS = {"Bard", "Ranger", "Sorcerer", "Warlock"}
MULTICLASS_SPELL_SLOTS = {
    1: [2, 0, 0, 0, 0, 0],
    2: [3, 0, 0, 0, 0, 0],
    3: [4, 2, 0, 0, 0, 0],
    4: [4, 3, 0, 0, 0, 0],
    5: [4, 3, 2, 0, 0, 0],
    6: [4, 3, 3, 0, 0, 0],
    7: [4, 3, 3, 1, 0, 0],
    8: [4, 3, 3, 2, 0, 0],
    9: [4, 3, 3, 3, 1, 0],
    10: [4, 3, 3, 3, 2, 0],
    11: [4, 3, 3, 3, 2, 1],
    12: [4, 3, 3, 3, 2, 1],
}


def numeric_progression_value(row: dict[str, str], field: str) -> int:
    match = re.search(r"\d+", row.get(field, "") or "")
    return int(match.group()) if match else 0


def spell_option(row: dict[str, str]) -> dict[str, Any]:
    details = meaningful(
        f"Level: {'Cantrip' if row['level'] == 'C' else row['level']}",
        row["school"],
        row["cast_time"],
        row["damage_effect"],
    )
    return {"label": option_label(row["spell"], details), "value": row["spell"], "search": f"{row['spell']} {' '.join(details)}"}


def spell_profile(class_name: str, class_level: int, ability_data, feat_effects, equipment_effects=None) -> dict[str, Any] | None:
    if class_name not in PREPARED_CASTERS | KNOWN_CASTERS or class_level < 1:
        return None
    row = CLASS_PROGRESSIONS[class_name][class_level - 1]
    max_spell_level = max((level for level in range(1, 7) if numeric_progression_value(row, f"spell_slots_{level}")), default=0)
    cantrip_limit = numeric_progression_value(row, "cantrips_known")
    learned_field = "spells_learned" if class_name == "Wizard" else "spells_known"
    learned_limit = numeric_progression_value(row, learned_field)
    ability = spellcasting_ability_name(next(item for item in CLASSES if item["class"] == class_name)["spellcasting_ability"])
    score = final_ability_scores(ability_data, feat_effects, equipment_effects)[ability]
    prepared_limit = 0
    if class_name in {"Cleric", "Druid", "Wizard"}:
        prepared_limit = max(1, class_level + ability_modifier(score))
    elif class_name == "Paladin" and class_level >= 2:
        prepared_limit = max(1, class_level // 2 + ability_modifier(score))
    return {"level": class_level, "max_spell_level": max_spell_level, "cantrips": cantrip_limit, "learned": learned_limit, "prepared": prepared_limit, "ability": ability}


def spell_choice_field(class_name: str, kind: str, label: str, options, limit: int):
    return html.Div(
        [
            html.Label(label),
            dcc.Dropdown(
                id={"type": "spell-choice", "class": class_name, "kind": kind, "limit": limit},
                options=options,
                multi=True,
                placeholder=f"Choose up to {limit}",
                className="rich-dropdown spell-dropdown",
                optionHeight=112,
                maxHeight=430,
                persistence=True,
                persistence_type="session",
            ),
            html.P(f"0 / {limit} selected", id={"type": "spell-choice-status", "class": class_name, "kind": kind, "limit": limit}, className="spell-choice-status"),
        ],
        className="spell-choice-field",
    )


def spell_tooltip_list(names, spell_attack_bonus=None, spellcasting_ability=None):
    rendered = []
    for name in dict.fromkeys(names or []):
        row = next((item for item in SPELLS if item["spell"] == name), None)
        if rendered:
            rendered.append(", ")
        if row:
            details = "; ".join(meaningful(
                f"Description: {row.get('description', '')}" if row.get("description", "") else "",
                f"{'Cantrip' if row['level'] == 'C' else 'Level ' + row['level']} {row['school']}",
                f"Cast time: {row['cast_time']}",
                f"Duration: {row['duration']}" if row["duration"] != "-" else "",
                f"Range/area: {row['range_area']}" if row["range_area"] != "-" else "",
                f"Attack/save: {row['attack_save']}" if row["attack_save"] != "-" else "",
                f"Spell attack roll: +{spell_attack_bonus} ({spellcasting_ability} + proficiency)" if spell_attack_bonus is not None and "attack roll" in row.get("attack_save", "").lower() else "",
                f"Damage/effect: {row['damage_effect']}" if row["damage_effect"] != "-" else "Damage/effect: None",
            ))
            rendered.append(html.Span(name, className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": details}))
        else:
            rendered.append(name)
    return rendered


def spell_slot_group(title: str, slots: list[tuple[int, int]], kind: str):
    return html.Div(
        [
            html.Div([html.Strong(title), html.Span("Long rest" if kind == "standard" else "Short rest")], className="spell-slot-group-heading"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"L{level}", className="spell-slot-level"),
                            html.Div([html.Span(className=f"spell-slot-pip spell-slot-pip--{kind}") for _ in range(count)], className="spell-slot-pips"),
                            html.Span(str(count), className="spell-slot-count"),
                        ],
                        className="spell-slot-row",
                        title=f"{count} level {level} {'Pact Magic slots' if kind == 'pact' else 'spell slots'}",
                    )
                    for level, count in slots if count
                ],
                className="spell-slot-levels",
            ),
        ],
        className=f"spell-slot-group spell-slot-group--{kind}",
    )


def class_resource_group(resources: list[dict[str, Any]]):
    return html.Div([
        html.Div([html.Strong("Class Resources"), html.Span("Recharge shown per resource")], className="spell-slot-group-heading"),
        html.Div([
            html.Div([
                html.Div([html.Span(resource["name"], className="class-resource-name"), html.Span(resource["recharge"], className="class-resource-recharge")]),
                html.Div([html.Span(className="spell-slot-pip spell-slot-pip--resource") for _ in range(resource["count"])], className="spell-slot-pips"),
                html.Strong(str(resource["count"]), className="spell-slot-count"),
            ], className="class-resource-row", title=resource.get("description", ""))
            for resource in resources
        ], className="class-resource-list"),
    ], className="spell-slot-group spell-slot-group--resource")


app = Dash(__name__, title="BG3 Character Builder", suppress_callback_exceptions=True)
server = app.server
init_persistence(server)

app.layout = html.Div(
    [
        html.Header(
            [
                html.P("BALDUR'S GATE 3", className="eyebrow"),
                html.H1("Character Builder"),
                html.P("Build the foundation of your next adventurer.", className="subtitle"),
                dcc.ConfirmDialogProvider(
                    children=html.Button("Clear Character", id="clear-character", n_clicks=0, className="clear-character-button"),
                    id="confirm-clear-character",
                    message="Clear every selection in the current character? Saved builds and your account will not be deleted.",
                ),
            ],
            className="hero",
        ),
        dcc.Store(id="clear-character-sink", storage_type="memory"),
        html.Section([
            dcc.Interval(id="account-refresh", interval=3_600_000, n_intervals=0, max_intervals=1),
            html.Div(id="account-status", className="account-status"),
            html.Div([
                dcc.RadioItems(
                    id="workspace-mode", value="character",
                    options=[{"label": "Character Builder", "value": "character"}, {"label": "Team Builder", "value": "team"}],
                    inline=True, className="workspace-mode-toggle",
                ),
            ], id="workspace-mode-controls", style={"display": "none"}),
            html.Div([
                dcc.Input(id="build-name", placeholder="Build name", maxLength=120, className="build-name-input"),
                dcc.Dropdown(id="saved-build-dropdown", placeholder="Open a saved build", className="rich-dropdown build-dropdown"),
                html.Button("Save", id="save-build", n_clicks=0, className="build-action-button"),
                html.Button("Open", id="open-build", n_clicks=0, className="build-action-button"),
                html.Button("Delete", id="delete-build", n_clicks=0, className="build-action-button build-delete-button"),
            ], id="build-controls", className="build-controls", style={"display": "none"}),
            html.Div([
                html.Button("Share", id="share-build", n_clicks=0, className="build-action-button"),
                html.Button("Revoke", id="revoke-share", n_clicks=0, className="build-action-button build-delete-button"),
                dcc.Input(id="share-build-link", readOnly=True, placeholder="Create a share link", className="share-link-input"),
                dcc.Clipboard(target_id="share-build-link", title="Copy share link", className="share-link-copy"),
            ], id="share-build-controls", className="share-build-controls", style={"display": "none"}),
            html.Div(id="share-message", className="share-message"),
            html.Div(id="build-message", className="build-message", role="status", **{"aria-live": "polite"}),
            dcc.Interval(id="build-message-dismiss", interval=4500, n_intervals=0, disabled=True, max_intervals=1),
            dcc.ConfirmDialog(
                id="confirm-build-overwrite",
                message="A saved build already uses this name. Replace it with the current build?",
            ),
            dcc.Store(id="pending-build-overwrite", storage_type="memory"),
        ], className="account-panel", style={} if AUTH_ENABLED else {"display": "none"}),
        dcc.Store(id="character-store", storage_type="session"),
        dcc.Store(id="pending-build-load", storage_type="memory"),
        dcc.Store(
            id="abilities-store",
            data={"scores": {ability: 8 for ability in ABILITIES}, "plus_two": None, "plus_one": None},
            storage_type="session",
        ),
        dcc.Store(
            id="skill-state-store",
            data={"level": 1, "expertise": [], "item_bonuses": {}, "initiative_bonus": 0},
            storage_type="session",
        ),
        dcc.Store(id="feat-effects-store", data={"ability_bonuses": {}, "skills": [], "expertise": []}, storage_type="session"),
        dcc.Store(id="equipment-effects-store", data={"ability_adjustments": [], "lightning_items": [], "reverberation_items": [], "equipped_items": []}, storage_type="session"),
        dcc.Store(id="act-equipment-loadouts", data={"active_act": 1, "loadouts": {}}, storage_type="session"),
        html.Main(
            [
                dcc.Tabs(
                    id="builder-tabs",
                    value="background-tab",
                    className="builder-tabs",
                    children=[
                dcc.Tab(
                    label="Background",
                    value="background-tab",
                    className="builder-tab",
                    selected_className="builder-tab builder-tab--selected",
                    children=html.Div(
                        [
                            html.Section(
                                [
                                    html.Div(
                                        [
                                            html.Label("Name", htmlFor="character-name"),
                                            dcc.Input(
                                                id="character-name",
                                                type="text",
                                                placeholder="Enter a character name",
                                                debounce=True,
                                                className="text-input",
                                            ),
                                        ],
                                        className="field field--wide",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Race", htmlFor="race-dropdown"),
                                            dcc.Dropdown(
                                                id="race-dropdown",
                                                options=race_options(),
                                                placeholder="Choose a race",
                                                optionHeight=132,
                                                maxHeight=420,
                                                clearable=True,
                                                className="rich-dropdown",
                                            ),
                                        ],
                                        className="field field--wide",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Subrace", htmlFor="subrace-dropdown"),
                                            dcc.Dropdown(
                                                id="subrace-dropdown",
                                                placeholder="Choose a race first",
                                                optionHeight=132,
                                                maxHeight=420,
                                                disabled=True,
                                                clearable=True,
                                                className="rich-dropdown",
                                            ),
                                        ],
                                        id="subrace-field",
                                        className="field field--wide",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Background", htmlFor="background-dropdown"),
                                            dcc.Dropdown(
                                                id="background-dropdown",
                                                options=background_options(),
                                                placeholder="Choose a background",
                                                optionHeight=70,
                                                maxHeight=420,
                                                clearable=True,
                                                className="rich-dropdown",
                                            ),
                                        ],
                                        className="field field--wide",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Human Versatility skill", htmlFor="human-versatility-skill"),
                                            dcc.Dropdown(
                                                id="human-versatility-skill",
                                                options=[{"label": skill, "value": skill} for skill in sorted(SKILL_TO_ABILITY)],
                                                placeholder="Choose one additional skill proficiency",
                                                clearable=True,
                                                className="rich-dropdown",
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                        ],
                                        id="human-versatility-field",
                                        className="field field--wide",
                                        style={"display": "none"},
                                    ),
                                ],
                                className="form-card",
                            ),
                        ],
                        className="tab-content",
                    ),
                ),
                dcc.Tab(
                    label="Abilities",
                    value="abilities-tab",
                    className="builder-tab",
                    selected_className="builder-tab builder-tab--selected",
                    children=html.Div(
                        [
                            html.Section(
                                [
                                    html.Div(
                                        [
                                            html.Div(className="ability-heading-spacer"),
                                            html.Div(
                                                [html.Span("Ability Points", className="points-label"), html.Strong("27", id="points-remaining")],
                                                className="points-counter",
                                            ),
                                            html.Div(
                                                [
                                                    html.Span("Bonus", className="bonus-title"),
                                                    html.Div([html.Span("+2"), html.Span("+1")], className="bonus-columns"),
                                                ],
                                                className="bonus-heading",
                                            ),
                                        ],
                                        className="ability-table-head",
                                    ),
                                    html.Div(ability_rows(), className="ability-list"),
                                    html.P(
                                        "Scores 8–13 cost one point per increase. Raising a score to 14 or 15 costs two points.",
                                        className="ability-help",
                                    ),
                                ],
                                className="abilities-card",
                            )
                        ],
                        className="tab-content",
                    ),
                ),
                dcc.Tab(
                    label="Leveling",
                    value="leveling-tab",
                    className="builder-tab",
                    selected_className="builder-tab builder-tab--selected",
                    children=html.Div(
                        [
                            html.Div(
                                [
                                    html.P("LEVEL-BY-LEVEL BUILD", className="eyebrow"),
                                    html.Div([
                                        html.H2("Choose a class at each character level"),
                                        html.Div([
                                            html.Button("Clear All", id="clear-leveling", n_clicks=0, className="clear-leveling-button", title="Reset all class levels, subclasses, feats, and level choices"),
                                        ], className="leveling-header-actions"),
                                    ], className="leveling-title-row"),
                                    html.P(
                                        "Each new row unlocks after the previous level is assigned. Choosing a different class creates a multiclass build.",
                                        className="leveling-intro",
                                    ),
                                ],
                                className="leveling-header",
                            ),
                            html.Div(leveling_rows(), className="level-selection-list"),
                            html.Div([
                                html.Button("Level Up", id="level-up", n_clicks=0, disabled=True, className="level-up-button", title="Add another level in the previous class"),
                            ], className="level-up-footer"),
                        ],
                        className="tab-content leveling-content",
                    ),
                ),
                dcc.Tab(
                    label="Spells & Attacks",
                    value="spells-tab",
                    className="builder-tab",
                    selected_className="builder-tab builder-tab--selected",
                    children=html.Div(
                        [
                            html.Div(
                                [
                                    html.P("SPELLBOOK & COMBAT ACTIONS", className="eyebrow"),
                                    html.H2("Spells and attacks"),
                                    html.P("Available spells and class attacks update from the choices made on the Leveling tab.", className="leveling-intro"),
                                ],
                                className="leveling-header",
                            ),
                            html.Div(id="spell-builder", className="spell-builder"),
                            html.Div(id="attack-builder", className="spell-builder attack-builder"),
                            html.Section([
                                html.Div([
                                    html.P("TURN CONDITIONS", className="eyebrow"),
                                    html.H3("Optimization assumptions"),
                                ], className="condition-heading"),
                                html.Div([
                                    html.Div([html.Label("Visibility"), dcc.Dropdown(
                                        id="turn-visibility", value="No condition", clearable=False, searchable=False,
                                        options=["No condition", "Lightly Obscured", "Heavily Obscured"], className="rich-dropdown",
                                        persistence=True, persistence_type="session",
                                    )], className="field"),
                                    html.Div([html.Label("Elevation"), dcc.Dropdown(
                                        id="turn-elevation", value="No condition", clearable=False, searchable=False,
                                        options=["No condition", "High Ground", "Low Ground"], className="rich-dropdown",
                                        persistence=True, persistence_type="session",
                                    )], className="field"),
                                    html.Div([html.Label("Attacker conditions"), dcc.Dropdown(
                                        id="turn-attacker-conditions", multi=True, placeholder="Choose active conditions",
                                        options=["Advantage", "Hidden", "Invisible", "Raging", "Concentrating", "Below 50% HP", "Threatened"],
                                        className="rich-dropdown", persistence=True, persistence_type="session",
                                    )], className="field"),
                                    html.Div([
                                        html.Label("Wild Shape form"),
                                        dcc.Dropdown(
                                            id="optimizer-wild-shape", value=None, clearable=True,
                                            placeholder="No Wild Shape",
                                            className="rich-dropdown", persistence=True, persistence_type="session",
                                        ),
                                        html.P("Select a form to optimize using only that form's available attacks.", className="condition-help"),
                                    ], id="optimizer-wild-shape-field", className="field", style={"display": "none"}),
                                    html.Div([
                                        html.Label("Active features"),
                                        dcc.Checklist(id="optimizer-active-features", options=[], value=[],
                                                      className="optimizer-resource-toggle",
                                                      persistence=True, persistence_type="session"),
                                        dcc.Dropdown(
                                            id="optimizer-elemental-cleaver-type",
                                            options=["Acid", "Cold", "Fire", "Lightning", "Thunder"],
                                            placeholder="Choose Elemental Cleaver damage type",
                                            className="rich-dropdown", style={"display": "none"},
                                            persistence=True, persistence_type="session",
                                        ),
                                        dcc.Dropdown(
                                            id="optimizer-lightning-charges", value=0, clearable=False,
                                            options=[{"label": f"Starting Lightning Charges: {value}", "value": value} for value in range(6)],
                                            className="rich-dropdown", style={"display": "none"},
                                            persistence=True, persistence_type="session",
                                        ),
                                        html.P("Only features unlocked by the current build appear here.", className="condition-help"),
                                    ], className="field"),
                                html.Div([html.Label("Target conditions"), dcc.Dropdown(
                                        id="turn-target-conditions", multi=True, placeholder="Choose target conditions",
                                        options=["Below Maximum HP", "Large or Larger", "Fiend or Undead", "Hunter's Marked", "Bleeding", "Burning", "Charmed", "Frightened", "Poisoned", "Prone", "Restrained", "Threatened by Ally", "Wet", "Will Move"],
                                        className="rich-dropdown", persistence=True, persistence_type="session",
                                    )], className="field"),
                                    html.Div([
                                        html.Label("Resource usage"),
                                        dcc.Checklist(
                                            id="optimizer-use-limited-resources",
                                            options=[{
                                                "label": " Allow limited resources (spell slots, class charges, Ki, Sorcery Points, Superiority Dice, and rest-based actions)",
                                                "value": "limited",
                                            }],
                                            value=[], className="optimizer-resource-toggle",
                                            persistence=True, persistence_type="session",
                                        ),
                                        html.P("Unchecked: optimize using unlimited weapon attacks, unarmed attacks, and cantrips only.", className="condition-help"),
                                    ], className="field optimizer-resource-field"),
                                ], className="turn-condition-grid"),
                            ], className="turn-condition-card"),
                            html.Section([
                                html.Div([html.P("TURN PLAN", className="eyebrow"), html.H3("Optimized Turn")], className="condition-heading"),
                                html.Div(
                                    "The damage optimizer is not calculated yet. This area will show the recommended action sequence, damage range, mean damage, and resources spent.",
                                    id="optimized-turn", className="optimized-turn-empty",
                                ),
                            ], className="optimized-turn-card"),
                        ],
                        className="tab-content leveling-content",
                    ),
                ),
                dcc.Tab(
                    label="Weapons & Equipment",
                    value="weapons-tab",
                    className="builder-tab",
                    selected_className="builder-tab builder-tab--selected",
                    children=html.Div(
                        [
                            html.Div([
                                html.P("LOADOUT", className="eyebrow"),
                                html.H2("Weapons and equipment"),
                                dcc.Tabs(id="equipment-act-tab", value=1, children=[
                                    dcc.Tab(label=f"Act {act}", value=act, className="builder-tab", selected_className="builder-tab builder-tab--selected")
                                    for act in (1, 2, 3)
                                ], className="equipment-act-tabs"),
                                html.P("The open act loadout is applied to the character sheet and optimizer. Later acts include all equipment obtainable in earlier acts.", className="condition-help"),
                                dcc.Checklist(
                                    id="proficient-equipment-only",
                                    options=[{"label": " Only show items I am proficient with", "value": "proficient"}],
                                    value=[], className="equipment-filter",
                                ),
                            ], className="leveling-header"),
                            html.Section([
                                html.H3("Weapons"),
                                html.Div([
                                    equipment_field("Melee main hand", "equipment-melee-main"),
                                    equipment_field("Melee off hand", "equipment-melee-off"),
                                    equipment_field("Ranged main hand", "equipment-ranged-main"),
                                    equipment_field("Ranged off hand", "equipment-ranged-off"),
                                ], className="equipment-grid"),
                            ], className="equipment-card"),
                            html.Section([
                                html.H3("Armour and accessories"),
                                html.Div([
                                    equipment_field("Headwear", "equipment-headwear"),
                                    equipment_field("Armour", "equipment-armour"),
                                    equipment_field("Handwear", "equipment-handwear"),
                                    equipment_field("Footwear", "equipment-footwear"),
                                    equipment_field("Cape", "equipment-cape"),
                                    equipment_field("Necklace", "equipment-necklace"),
                                    equipment_field("Ring 1", "equipment-ring-1"),
                                    equipment_field("Ring 2", "equipment-ring-2"),
                                ], className="equipment-grid"),
                            ], className="equipment-card"),
                            html.Section([
                                html.H3("Item location checklist"),
                                html.P("Locations for the items in your current loadout. Check off each item after you obtain it.", className="item-location-intro"),
                                dcc.Checklist(
                                    id="item-location-checklist",
                                    options=[],
                                    value=[],
                                    className="item-location-checklist",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                html.P("Select equipment above to build your checklist.", id="item-location-empty", className="item-location-empty"),
                            ], className="equipment-card item-location-card"),
                        ], className="tab-content leveling-content",
                    ),
                ),
                    ],
                ),
                html.Aside(
                    [
                        html.Div(className="sheet-ornament"),
                        html.P("CHARACTER RECORD", className="sheet-kicker"),
                        html.H2(id="summary-name", children="Unnamed Adventurer"),
                        html.Section(
                            [
                                html.H3("Class & Level"),
                                html.Div(
                                    [
                                        detail_block("Class", "Not selected"),
                                        detail_block("Level", "1"),
                                        detail_block("Subclass", "Not selected"),
                                    ],
                                    id="sheet-class-level",
                                    className="sheet-identity sheet-class-identity",
                                ),
                                html.Div([
                                    html.Div([
                                        html.Span("Initiative", className="summary-label"),
                                        html.Span("+0", id="sheet-initiative", title="Dexterity modifier"),
                                    ], className="summary-row sheet-initiative-row"),
                                    html.Div([
                                        html.Span("Armour Class", className="summary-label"),
                                        html.Span("9", id="sheet-ac", title="10 + Dexterity modifier"),
                                    ], className="summary-row sheet-initiative-row sheet-ac-row"),
                                    html.Div([
                                        html.Span("Actions", className="summary-label"),
                                        html.Span("1", id="sheet-actions", title="1 Action per turn"),
                                    ], className="summary-row sheet-initiative-row sheet-action-row"),
                                    html.Div([
                                        html.Span("Bonus Actions", className="summary-label"),
                                        html.Span("1", id="sheet-bonus-actions", title="1 Bonus Action per turn"),
                                    ], className="summary-row sheet-initiative-row sheet-bonus-action-row"),
                                ], className="sheet-vitals-grid"),
                                html.Div(id="sheet-selected-feats", className="sheet-selected-feats"),
                            ],
                            className="sheet-panel sheet-class-panel",
                        ),
                        html.Section(
                            [html.H3("Class Features"), html.Div(id="sheet-class-features", className="sheet-class-feature-groups")],
                            className="sheet-panel sheet-class-features-panel",
                        ),
                        html.Section(
                            [
                                html.H3("Ability Scores"),
                                html.Div(id="sheet-abilities", className="sheet-ability-grid"),
                            ],
                            className="sheet-panel sheet-abilities-panel",
                        ),
                        html.Section(
                            [
                                html.Div(
                                    [
                                        html.H3("Skills"),
                                        html.Span("Proficiency +2", id="sheet-proficiency-bonus", className="sheet-section-note"),
                                    ],
                                    className="sheet-panel-heading",
                                ),
                                html.Div(id="sheet-skills", className="sheet-skills-grid"),
                            ],
                            className="sheet-panel sheet-skills-panel",
                        ),
                        html.Section(
                            [html.H3("Spell Slots & Resources"), html.Div(id="sheet-spell-slots", className="sheet-spell-slots"), html.Div(id="sheet-spells", className="sheet-spells")],
                            className="sheet-panel sheet-spells-panel",
                        ),
                        html.Section(
                            [html.H3("Defences"), html.Div(id="sheet-defences", className="sheet-defences-grid")],
                            className="sheet-panel sheet-defences-panel",
                        ),
                        html.Section(
                            [html.H3("Equipment"), html.Div(id="sheet-equipment", className="sheet-equipment-grid")],
                            className="sheet-panel sheet-equipment-panel",
                        ),
                        html.Div(id="character-summary", className="character-sheet-content"),
                    ],
                    className="character-sheet",
                ),
            ],
            id="character-builder-view", className="builder-workspace",
        ),
        html.Section([
            html.Div([
                html.P("SIGNED-IN WORKSPACE", className="eyebrow"),
                html.H2("Team Builder"),
                html.P("Choose exactly four saved characters and review their loadouts side by side.", className="leveling-intro"),
            ], className="leveling-header"),
            html.Div([
                dcc.Input(id="team-name", placeholder="Team name", maxLength=120, className="build-name-input"),
                dcc.Dropdown(id="saved-team-dropdown", placeholder="Open a saved team", className="rich-dropdown build-dropdown"),
                html.Button("Save Team", id="save-team", n_clicks=0, className="build-action-button"),
                html.Button("Open", id="open-team", n_clicks=0, className="build-action-button"),
                html.Button("Delete", id="delete-team", n_clicks=0, className="build-action-button build-delete-button"),
            ], className="build-controls team-controls"),
            html.Div([
                html.Div([html.Label(f"Team member {slot}"), dcc.Dropdown(id=f"team-member-{slot}", placeholder="Choose a saved character", className="rich-dropdown")], className="field")
                for slot in range(1, 5)
            ], className="team-member-selectors"),
            html.Div(id="team-equipment-warning", className="team-equipment-warning"),
            html.Div(id="team-member-summaries", className="team-member-summaries"),
            html.Div(id="team-message", className="team-message", role="status"),
            dcc.ConfirmDialog(id="confirm-team-overwrite", message="A saved team already uses this name. Replace it?"),
            dcc.Store(id="pending-team-overwrite", storage_type="memory"),
        ], id="team-builder-view", className="team-builder-view", style={"display": "none"}),
    ],
    className="app-shell",
)


app.clientside_callback(
    """
    function(confirmClicks) {
        if (!confirmClicks) return window.dash_clientside.no_update;
        window.sessionStorage.clear();
        for (let index = window.localStorage.length - 1; index >= 0; index--) {
            const key = window.localStorage.key(index);
            if (key && key.startsWith("_dash_persistence.")) {
                window.localStorage.removeItem(key);
            }
        }
        window.location.replace(window.location.pathname + window.location.search);
        return Date.now();
    }
    """,
    Output("clear-character-sink", "data"),
    Input("confirm-clear-character", "submit_n_clicks"),
    prevent_initial_call=True,
)


def packed_pattern_values(values, ids):
    return [{"id": item_id, "value": value} for value, item_id in zip(values or [], ids or [])]


def restored_pattern_values(records, ids):
    records = records or []
    return [next((record.get("value") for record in records if record.get("id") == item_id), None) for item_id in (ids or [])]


def build_notice(message: str):
    """Return a fresh toast node so repeated notices always animate."""
    nonce = str(time.time_ns())
    return html.Div(message, id=f"build-toast-{nonce}", key=nonce, className="build-toast-card")


@callback(
    Output("account-status", "children"), Output("build-controls", "style"),
    Input("account-refresh", "n_intervals"),
)
def render_account_status(_interval):
    user_id, email = user_identity()
    if not AUTH_ENABLED:
        return [], {"display": "none"}
    if not user_id:
        return html.Div([
            html.Span("Guest mode — sign in to save builds."),
            html.A("Sign in", href="login", className="account-link"),
            html.A("Create account", href="register", className="account-link"),
        ]), {"display": "none"}
    return html.Div([
        html.Span(f"Signed in as {email}"), html.A("Sign out", href="logout", className="account-link")
    ]), {}


@callback(Output("workspace-mode-controls", "style"), Input("account-refresh", "n_intervals"))
def show_workspace_mode(_interval):
    user_id, _ = user_identity()
    return {} if user_id else {"display": "none"}


@callback(Output("share-build-controls", "style"), Input("account-refresh", "n_intervals"))
def show_share_controls(_interval):
    user_id, _ = user_identity()
    return {} if user_id else {"display": "none"}


@callback(
    Output("share-build-link", "value"), Output("share-message", "children"),
    Input("share-build", "n_clicks"), Input("revoke-share", "n_clicks"),
    State("saved-build-dropdown", "value"),
    prevent_initial_call=True,
)
def manage_build_share(_share, _revoke, build_id):
    user_id, _ = user_identity()
    if not user_id:
        return no_update, "Sign in to share builds."
    if not build_id:
        return no_update, "Save or select a build before sharing it."
    if ctx.triggered_id == "revoke-share":
        revoked = revoke_build_share(user_id, int(build_id))
        return "", "Share link revoked." if revoked else "This build does not have an active share link."
    token = create_build_share(user_id, int(build_id))
    if not token:
        return no_update, "The selected build could not be found."
    link = request.host_url.rstrip("/") + f"/share/{token}"
    return link, "Read-only share link created. Copy it and send it to anyone."


@callback(
    Output("character-builder-view", "style"), Output("team-builder-view", "style"),
    Input("workspace-mode", "value"),
)
def switch_workspace(mode):
    user_id, _ = user_identity()
    if mode == "team" and user_id:
        return {"display": "none"}, {}
    return {}, {"display": "none"}


@callback(
    Output("team-member-1", "options"), Output("team-member-2", "options"),
    Output("team-member-3", "options"), Output("team-member-4", "options"),
    Output("saved-team-dropdown", "options"),
    Input("account-refresh", "n_intervals"), Input("team-message", "children"), Input("build-message", "children"),
)
def refresh_team_options(_interval, _team_message, _build_message):
    user_id, _ = user_identity()
    if not user_id:
        return [], [], [], [], []
    build_options = [{"label": row["name"], "value": row["id"]} for row in list_builds(user_id)]
    team_options = [{"label": row["name"], "value": row["id"]} for row in list_teams(user_id)]
    return build_options, build_options, build_options, build_options, team_options


def team_member_card(payload, slot):
    classes = [value for value in payload.get("classes", []) if value]
    class_counts = Counter(classes)
    class_line = " / ".join(f"{name} {level}" for name, level in class_counts.items()) or "No class"
    equipment_ids = [value for value in (payload.get("equipment") or {}).values() if value]
    equipment_names = [EQUIPMENT_BY_ID[value]["item"] for value in equipment_ids if value in EQUIPMENT_BY_ID]
    spells = []
    for record in payload.get("spell_choices") or []:
        value = record.get("value")
        spells.extend(value if isinstance(value, list) else ([value] if value else []))
    attacks = []
    for record in payload.get("class_choices") or []:
        value = record.get("value")
        attacks.extend(value if isinstance(value, list) else ([value] if value else []))
    feats = [value for value in payload.get("feats", []) if value]

    def summary(label, values):
        return html.Div([html.Strong(label), html.P(", ".join(dict.fromkeys(values)) if values else "None")], className="team-summary-section")

    return html.Article([
        html.Div([html.Span(f"Member {slot}"), html.H3(payload.get("character_name") or "Unnamed Adventurer"), html.P(class_line)], className="team-card-heading"),
        summary("Equipment", equipment_names), summary("Attacks & class choices", attacks),
        summary("Spells", spells), summary("Feats", feats),
    ], className="team-member-card")


@callback(
    Output("team-member-summaries", "children"), Output("team-equipment-warning", "children"),
    Input("team-member-1", "value"), Input("team-member-2", "value"),
    Input("team-member-3", "value"), Input("team-member-4", "value"),
)
def render_team_members(*build_ids):
    user_id, _ = user_identity()
    if not user_id:
        return [], []
    cards, item_members = [], {}
    for slot, build_id in enumerate(build_ids, 1):
        if not build_id:
            cards.append(html.Article([html.H3(f"Member {slot}"), html.P("Choose a saved character.")], className="team-member-card team-member-card--empty"))
            continue
        payload = load_build(user_id, int(build_id)) or {}
        cards.append(team_member_card(payload, slot))
        for equipment_id in set(value for value in (payload.get("equipment") or {}).values() if value):
            item_members.setdefault(equipment_id, []).append(slot)
    conflicts = [(equipment_id, slots) for equipment_id, slots in item_members.items() if len(slots) > 1]
    warning = [] if not conflicts else html.Div([
        html.Strong("Equipment overlap detected"),
        html.Ul([html.Li(f"{EQUIPMENT_BY_ID.get(item_id, {}).get('item', item_id)} — members {', '.join(map(str, slots))}") for item_id, slots in conflicts]),
    ])
    return cards, warning


@callback(
    Output("team-message", "children"), Output("saved-team-dropdown", "value"), Output("team-name", "value"),
    Output("team-member-1", "value"), Output("team-member-2", "value"),
    Output("team-member-3", "value"), Output("team-member-4", "value"),
    Output("confirm-team-overwrite", "displayed"), Output("pending-team-overwrite", "data"),
    Input("save-team", "n_clicks"), Input("open-team", "n_clicks"), Input("delete-team", "n_clicks"),
    Input("confirm-team-overwrite", "submit_n_clicks"),
    State("saved-team-dropdown", "value"), State("team-name", "value"),
    State("team-member-1", "value"), State("team-member-2", "value"),
    State("team-member-3", "value"), State("team-member-4", "value"), State("pending-team-overwrite", "data"),
    prevent_initial_call=True,
)
def manage_teams(_save, _open, _delete, _confirm, team_id, team_name, member_1, member_2, member_3, member_4, pending):
    user_id, _ = user_identity()
    unchanged = [no_update] * 6
    if not user_id:
        return "Sign in to manage teams.", *unchanged, False, None
    trigger = ctx.triggered_id
    if trigger == "confirm-team-overwrite":
        if not pending:
            return "No team is pending overwrite.", *unchanged, False, None
        saved_id = save_team(user_id, pending["name"], pending["payload"], int(pending["team_id"]))
        return f"Team overwritten successfully at {datetime.now().strftime('%I:%M:%S %p').lstrip('0')}.", saved_id, pending["name"], *pending["payload"]["members"], False, None
    teams = list_teams(user_id)
    if trigger == "open-team":
        row = next((row for row in teams if row["id"] == team_id), None)
        if not row:
            return "Choose a team to open.", *unchanged, False, None
        members = (row["team_data"].get("members") or [None] * 4)[:4]
        return "Team opened.", row["id"], row["name"], *members, False, None
    if trigger == "delete-team":
        if not team_id:
            return "Choose a team to delete.", *unchanged, False, None
        delete_team(user_id, int(team_id))
        return "Team deleted.", None, None, None, None, None, None, False, None
    members = [member_1, member_2, member_3, member_4]
    if any(member is None for member in members):
        return "A team must contain four saved characters.", *unchanged, False, None
    name = (team_name or "Unnamed Team").strip()[:120]
    payload = {"schema_version": 1, "members": members}
    match = next((row for row in teams if row["name"].strip().casefold() == name.casefold()), None)
    if match:
        return f'A team named "{name}" already exists. Confirm to overwrite it.', *unchanged, True, {"team_id": match["id"], "name": name, "payload": payload}
    saved_id = save_team(user_id, name, payload)
    return f"Team saved successfully at {datetime.now().strftime('%I:%M:%S %p').lstrip('0')}.", saved_id, name, *members, False, None


@callback(
    Output("saved-build-dropdown", "options"),
    Input("account-refresh", "n_intervals"), Input("build-message", "children"),
    Input("saved-build-dropdown", "value"),
)
def refresh_saved_build_options(_interval, _message, _selected_build):
    user_id, _ = user_identity()
    if not user_id:
        return []
    return [{"label": row["name"], "value": row["id"]} for row in list_builds(user_id)]


@callback(
    Output("build-name", "value"),
    Input("saved-build-dropdown", "value"),
    prevent_initial_call=True,
)
def selected_build_name(build_id):
    user_id, _ = user_identity()
    if not user_id or not build_id:
        return no_update
    row = next((row for row in list_builds(user_id) if row["id"] == int(build_id)), None)
    return row["name"] if row else no_update


@callback(
    Output("build-message", "children", allow_duplicate=True),
    Output("saved-build-dropdown", "value", allow_duplicate=True),
    Output("pending-build-load", "data", allow_duplicate=True),
    Output("character-name", "value", allow_duplicate=True),
    Output("race-dropdown", "value", allow_duplicate=True), Output("subrace-dropdown", "value", allow_duplicate=True),
    Output("background-dropdown", "value", allow_duplicate=True), Output("human-versatility-skill", "value", allow_duplicate=True),
    Output("abilities-store", "data", allow_duplicate=True),
    Output({"type": "level-class", "level": ALL}, "value", allow_duplicate=True),
    Output({"type": "level-subclass", "level": ALL}, "value", allow_duplicate=True),
    Output({"type": "level-feat", "level": ALL}, "value", allow_duplicate=True),
    Output("equipment-melee-main", "value", allow_duplicate=True), Output("equipment-melee-off", "value", allow_duplicate=True),
    Output("equipment-ranged-main", "value", allow_duplicate=True), Output("equipment-ranged-off", "value", allow_duplicate=True),
    Output("equipment-headwear", "value", allow_duplicate=True), Output("equipment-armour", "value", allow_duplicate=True),
    Output("equipment-handwear", "value", allow_duplicate=True), Output("equipment-footwear", "value", allow_duplicate=True),
    Output("equipment-cape", "value", allow_duplicate=True),
    Output("equipment-necklace", "value", allow_duplicate=True), Output("equipment-ring-1", "value", allow_duplicate=True),
    Output("equipment-ring-2", "value", allow_duplicate=True),
    Output("turn-visibility", "value", allow_duplicate=True), Output("turn-elevation", "value", allow_duplicate=True),
    Output("turn-attacker-conditions", "value", allow_duplicate=True), Output("turn-target-conditions", "value", allow_duplicate=True),
    Output("optimizer-active-features", "value", allow_duplicate=True),
    Output("optimizer-wild-shape", "value", allow_duplicate=True),
    Output("optimizer-elemental-cleaver-type", "value", allow_duplicate=True),
    Output("optimizer-lightning-charges", "value", allow_duplicate=True),
    Output("optimizer-use-limited-resources", "value", allow_duplicate=True),
    Output("proficient-equipment-only", "value", allow_duplicate=True),
    Output("item-location-checklist", "value", allow_duplicate=True),
    Output("act-equipment-loadouts", "data", allow_duplicate=True), Output("equipment-act-tab", "value", allow_duplicate=True),
    Output("confirm-build-overwrite", "displayed"),
    Output("pending-build-overwrite", "data"),
    Output("build-message-dismiss", "disabled", allow_duplicate=True),
    Output("build-message-dismiss", "n_intervals", allow_duplicate=True),
    Input("save-build", "n_clicks"), Input("open-build", "n_clicks"), Input("delete-build", "n_clicks"),
    Input("confirm-build-overwrite", "submit_n_clicks"),
    State("saved-build-dropdown", "value"), State("build-name", "value"),
    State("character-name", "value"), State("race-dropdown", "value"), State("subrace-dropdown", "value"),
    State("background-dropdown", "value"), State("human-versatility-skill", "value"), State("abilities-store", "data"),
    State({"type": "level-class", "level": ALL}, "value"), State({"type": "level-subclass", "level": ALL}, "value"),
    State({"type": "level-feat", "level": ALL}, "value"),
    State({"type": "feat-choice", "level": ALL, "field": ALL}, "value"), State({"type": "feat-choice", "level": ALL, "field": ALL}, "id"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"), State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value"), State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
    State("equipment-melee-main", "value"), State("equipment-melee-off", "value"),
    State("equipment-ranged-main", "value"), State("equipment-ranged-off", "value"),
    State("equipment-headwear", "value"), State("equipment-armour", "value"),
    State("equipment-handwear", "value"), State("equipment-footwear", "value"),
    State("equipment-cape", "value"),
    State("equipment-necklace", "value"), State("equipment-ring-1", "value"), State("equipment-ring-2", "value"),
    State("turn-visibility", "value"), State("turn-elevation", "value"),
    State("turn-attacker-conditions", "value"), State("turn-target-conditions", "value"),
    State("optimizer-active-features", "value"), State("optimizer-wild-shape", "value"), State("optimizer-elemental-cleaver-type", "value"),
    State("optimizer-lightning-charges", "value"), State("optimizer-use-limited-resources", "value"),
    State("proficient-equipment-only", "value"),
    State("item-location-checklist", "value"),
    State("act-equipment-loadouts", "data"), State("equipment-act-tab", "value"),
    State("pending-build-overwrite", "data"),
    prevent_initial_call=True,
)
def manage_saved_builds(_save, _open, _delete, _confirm_overwrite, build_id, build_name, character_name, race, subrace, background,
                        human_skill, abilities, classes, subclasses, feats, feat_choice_values, feat_choice_ids,
                        class_choice_values, class_choice_ids, spell_values, spell_ids, melee_main, melee_off,
                        ranged_main, ranged_off, headwear, armour, handwear, footwear, cape, necklace, ring_1, ring_2,
                        visibility, elevation, attacker_conditions, target_conditions, active_features,
                        wild_shape, cleaver_type, lightning_charges, limited_resources, proficient_only, acquired_items, act_loadouts, equipment_act, pending_overwrite):
    # The first three restore outputs are ALL-pattern level controls and must
    # return one value per matching component, even when none should change.
    empty_restore = [
        *([no_update] * 6),
        [no_update] * 12,
        [no_update] * 12,
        [no_update] * 12,
        *([no_update] * 25),
    ]
    user_id, _ = user_identity()
    if not user_id:
        return (build_notice("Sign in to manage saved builds."), no_update, no_update, *empty_restore, False, None, False, 0)
    trigger = ctx.triggered_id
    if trigger == "confirm-build-overwrite":
        if not pending_overwrite:
            return (build_notice("There is no pending build to overwrite."), no_update, no_update, *empty_restore, False, None, False, 0)
        saved_id = save_build(
            user_id,
            pending_overwrite["name"],
            pending_overwrite["payload"],
            int(pending_overwrite["build_id"]),
        )
        saved_at = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
        return (build_notice(f"Build overwritten successfully at {saved_at}."), saved_id, no_update, *empty_restore, False, None, False, 0)
    if trigger == "delete-build":
        if not build_id:
            return (build_notice("Choose a build to delete."), no_update, no_update, *empty_restore, False, None, False, 0)
        delete_build(user_id, int(build_id))
        return (build_notice("Build deleted."), None, None, *empty_restore, False, None, False, 0)
    if trigger == "open-build":
        if not build_id:
            return (build_notice("Choose a build to open."), no_update, no_update, *empty_restore, False, None, False, 0)
        payload = load_build(user_id, int(build_id))
        if not payload:
            return (build_notice("That build could not be found."), None, None, *empty_restore, False, None, False, 0)
        equipment = payload.get("equipment", {})
        conditions = payload.get("conditions", {})
        return (
            build_notice("Build opened."), build_id, payload,
            payload.get("character_name"), payload.get("race"), payload.get("subrace"), payload.get("background"),
            payload.get("human_skill"), payload.get("abilities"),
            (payload.get("classes") or [None] * 12)[:12], (payload.get("subclasses") or [None] * 12)[:12],
            (payload.get("feats") or [None] * 12)[:12],
            equipment.get("melee_main"), equipment.get("melee_off"), equipment.get("ranged_main"), equipment.get("ranged_off"),
            equipment.get("headwear"), equipment.get("armour"), equipment.get("handwear"), equipment.get("footwear"),
            equipment.get("cape"), equipment.get("necklace"), equipment.get("ring_1"), equipment.get("ring_2"),
            conditions.get("visibility", "No condition"), conditions.get("elevation", "No condition"),
            conditions.get("attacker", []), conditions.get("target", []), conditions.get("active_features", []),
            conditions.get("wild_shape"), conditions.get("cleaver_type"), conditions.get("lightning_charges", 0), conditions.get("limited_resources", []),
            payload.get("proficient_only", []),
            payload.get("acquired_items", []),
            payload.get("equipment_loadouts", {"active_act": payload.get("equipment_act", 1), "loadouts": {str(payload.get("equipment_act", 1)): {key.replace("_", "-"): value for key, value in equipment.items()}}}),
            payload.get("equipment_act", 1),
            False, None,
            False, 0,
        )
    name = (build_name or character_name or "Unnamed Build").strip()[:120]
    payload = {
        "schema_version": 1, "character_name": character_name, "race": race, "subrace": subrace,
        "background": background, "human_skill": human_skill, "abilities": abilities,
        "classes": list(classes or []), "subclasses": list(subclasses or []), "feats": list(feats or []),
        "feat_choices": packed_pattern_values(feat_choice_values, feat_choice_ids),
        "class_choices": packed_pattern_values(class_choice_values, class_choice_ids),
        "spell_choices": packed_pattern_values(spell_values, spell_ids),
        "equipment": {"melee_main": melee_main, "melee_off": melee_off, "ranged_main": ranged_main,
                      "ranged_off": ranged_off, "headwear": headwear, "armour": armour, "handwear": handwear,
                      "footwear": footwear, "cape": cape, "necklace": necklace, "ring_1": ring_1, "ring_2": ring_2},
        "conditions": {"visibility": visibility, "elevation": elevation, "attacker": attacker_conditions,
                       "target": target_conditions, "active_features": active_features, "wild_shape": wild_shape, "cleaver_type": cleaver_type,
                       "lightning_charges": lightning_charges, "limited_resources": limited_resources},
        "proficient_only": proficient_only,
        "acquired_items": list(acquired_items or []),
    }
    current_loadouts = dict(act_loadouts or {"active_act": int(equipment_act or 1), "loadouts": {}})
    saved_loadouts = dict(current_loadouts.get("loadouts") or {})
    saved_loadouts[str(int(equipment_act or 1))] = {
        "melee-main": melee_main, "melee-off": melee_off, "ranged-main": ranged_main, "ranged-off": ranged_off,
        "headwear": headwear, "armour": armour, "handwear": handwear, "footwear": footwear, "cape": cape,
        "necklace": necklace, "ring-1": ring_1, "ring-2": ring_2,
    }
    payload["equipment_act"] = int(equipment_act or 1)
    payload["equipment_loadouts"] = {"active_act": int(equipment_act or 1), "loadouts": saved_loadouts}
    matching_build = next(
        (row for row in list_builds(user_id) if row["name"].strip().casefold() == name.casefold()),
        None,
    )
    if matching_build:
        return (
            build_notice(f'A build named "{name}" already exists. Confirm to overwrite it.'),
            no_update, no_update, *empty_restore, True,
            {"build_id": matching_build["id"], "name": name, "payload": payload},
            False, 0,
        )
    saved_id = save_build(user_id, name, payload)
    saved_at = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
    return (build_notice(f"Build saved successfully at {saved_at}."), saved_id, no_update, *empty_restore, False, None, False, 0)


@callback(
    Output("build-message", "children", allow_duplicate=True),
    Output("build-message-dismiss", "disabled", allow_duplicate=True),
    Input("build-message-dismiss", "n_intervals"),
    prevent_initial_call=True,
)
def dismiss_build_notice(n_intervals):
    if not n_intervals:
        return no_update, no_update
    return None, True


@callback(
    Output({"type": "feat-choice", "level": ALL, "field": ALL}, "value", allow_duplicate=True),
    Output({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value", allow_duplicate=True),
    Output({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value", allow_duplicate=True),
    Output("pending-build-load", "data", allow_duplicate=True),
    Input("pending-build-load", "data"), Input({"type": "feat-choice-container", "level": ALL}, "children"),
    Input({"type": "class-choice-container", "level": ALL}, "children"), Input("spell-builder", "children"),
    State({"type": "feat-choice", "level": ALL, "field": ALL}, "id"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
    prevent_initial_call=True,
)
def restore_dynamic_build_choices(payload, _feat_children, _class_children, _spell_children,
                                  feat_ids, class_ids, spell_ids):
    if not payload:
        return [no_update] * len(feat_ids or []), [no_update] * len(class_ids or []), [no_update] * len(spell_ids or []), no_update
    feat_records = payload.get("feat_choices") or []
    class_records = payload.get("class_choices") or []
    spell_records = payload.get("spell_choices") or []

    def controls_ready(records, current_ids):
        current_ids = current_ids or []
        return all(any(record.get("id") == current_id for current_id in current_ids) for record in records)

    restoration_complete = (
        controls_ready(feat_records, feat_ids)
        and controls_ready(class_records, class_ids)
        and controls_ready(spell_records, spell_ids)
    )
    return (
        restored_pattern_values(feat_records, feat_ids),
        restored_pattern_values(class_records, class_ids),
        restored_pattern_values(spell_records, spell_ids),
        None if restoration_complete else no_update,
    )


@callback(
    Output({"type": "level-class", "level": ALL}, "value"),
    Output({"type": "level-subclass", "level": ALL}, "value"),
    Output({"type": "level-feat", "level": ALL}, "value"),
    Output({"type": "feat-choice", "level": ALL, "field": ALL}, "value"),
    Output({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("clear-leveling", "n_clicks"),
    State({"type": "level-class", "level": ALL}, "id"),
    State({"type": "level-subclass", "level": ALL}, "id"),
    State({"type": "level-feat", "level": ALL}, "id"),
    State({"type": "feat-choice", "level": ALL, "field": ALL}, "id"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
    prevent_initial_call=True,
)
def clear_leveling(_clicks, class_ids, subclass_ids, feat_ids, feat_choice_ids, class_choice_ids):
    return (
        [None] * len(class_ids or []), [None] * len(subclass_ids or []), [None] * len(feat_ids or []),
        [None] * len(feat_choice_ids or []), [None] * len(class_choice_ids or []),
    )


@callback(
    Output({"type": "level-class", "level": ALL}, "value", allow_duplicate=True),
    Input("level-up", "n_clicks"),
    State({"type": "level-class", "level": ALL}, "value"),
    prevent_initial_call=True,
)
def add_same_class_level(_clicks, class_values):
    values = list(class_values or [])
    if not values or not values[0]:
        return (values + [None] * 12)[:12]
    values.extend([None] * (12 - len(values)))
    try:
        next_level = values.index(None)
    except ValueError:
        return values[:12]
    if next_level == 0:
        return values[:12]
    values[next_level] = values[next_level - 1]
    return values[:12]


@callback(
    Output("level-up", "disabled"),
    Input({"type": "level-class", "level": ALL}, "value"),
)
def disable_level_up(class_values):
    values = list(class_values or [])
    return not values or not values[0] or all(values[:12])


@callback(
    Output("subrace-dropdown", "options"),
    Output("subrace-dropdown", "value"),
    Output("subrace-dropdown", "disabled"),
    Output("subrace-dropdown", "placeholder"),
    Output("subrace-field", "style"),
    Input("race-dropdown", "value"),
    Input("pending-build-load", "data"),
    State("subrace-dropdown", "value"),
)
def update_subraces(race: str | None, pending_build: dict | None, selected_subrace: str | None):
    if not race:
        return [], None, True, "Choose a race first", {"display": "none"}

    rows = [row for row in RACES if row["race"] == race and row["subrace"].strip()]
    options = []
    for row in rows:
        details = meaningful(row["subrace_proficiencies"], row["subrace_features"])
        options.append(
            {
                "label": option_label(row["subrace"], details),
                "value": row["subrace"],
                "search": f"{row['subrace']} {' '.join(details)}",
            }
        )
    if not options:
        return [], None, True, "This race has no subrace", {"display": "none"}
    valid_subraces = {option["value"] for option in options}
    pending_subrace = (pending_build or {}).get("subrace")
    restored_subrace = pending_subrace if pending_subrace in valid_subraces else selected_subrace
    restored_subrace = restored_subrace if restored_subrace in valid_subraces else None
    return options, restored_subrace, False, "Choose a subrace", {}


@callback(
    Output("human-versatility-field", "style"),
    Output("human-versatility-skill", "value"),
    Input("race-dropdown", "value"),
    State("human-versatility-skill", "value"),
)
def update_human_versatility(race, selected_skill):
    return ({}, selected_skill) if race == "Human" else ({"display": "none"}, None)


@callback(
    Output("item-location-checklist", "options"),
    Output("item-location-checklist", "value"),
    Output("item-location-empty", "style"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
    State("item-location-checklist", "value"),
)
def update_item_location_checklist(*values):
    equipment_ids, acquired_items = values[:-1], values[-1] or []
    selected_ids = list(dict.fromkeys(equipment_id for equipment_id in equipment_ids if equipment_id in EQUIPMENT_BY_ID))
    options = []
    for equipment_id in selected_ids:
        row = EQUIPMENT_BY_ID[equipment_id]
        location = (row.get("where_to_find") or "Location information is not available.").strip()
        options.append({
            "value": equipment_id,
            "label": html.Div([
                html.Div([
                    html.Strong(row["item"], className=f"item-location-name {equipment_rarity_class(row)}"),
                    html.A("Wiki", href=row.get("source_url") or "https://bg3.wiki/", target="_blank", className="item-location-link"),
                ], className="item-location-heading"),
                html.Span(location, className="item-location-description"),
            ], className="item-location-label"),
        })
    retained = [equipment_id for equipment_id in acquired_items if equipment_id in selected_ids]
    return options, retained, {"display": "none"} if options else {}


@callback(
    Output({"type": "level-class", "level": ALL}, "disabled"),
    Output({"type": "level-row", "level": ALL}, "style"),
    Output({"type": "level-subclass", "level": ALL}, "options"),
    Output({"type": "level-subclass", "level": ALL}, "disabled"),
    Output({"type": "level-subclass", "level": ALL}, "placeholder"),
    Output({"type": "level-subclass-field", "level": ALL}, "style"),
    Output({"type": "level-feat", "level": ALL}, "disabled"),
    Output({"type": "level-feat", "level": ALL}, "placeholder"),
    Output({"type": "level-feat-field", "level": ALL}, "style"),
    Output({"type": "level-details", "level": ALL}, "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
)
def update_level_rows(class_values, subclass_values):
    class_values = list(class_values or [])
    subclass_values = list(subclass_values or [])
    class_disabled = [False] + [not bool(class_values[index - 1]) for index in range(1, 12)]
    row_styles = [{} if index == 0 or bool(class_values[index - 1]) else {"display": "none"} for index in range(12)]
    subclass_options = []
    subclass_disabled = []
    subclass_placeholders = []
    feat_disabled = []
    feat_placeholders = []
    subclass_field_styles = []
    feat_field_styles = []
    details = []
    class_counts: Counter[str] = Counter()
    selected_subclasses: dict[str, str] = {}

    for index in range(12):
        class_name = class_values[index] if index < len(class_values) else None
        chosen_here = subclass_values[index] if index < len(subclass_values) else None
        if not class_name or (index > 0 and not class_values[index - 1]):
            subclass_options.append([])
            subclass_disabled.append(True)
            subclass_placeholders.append("Choose a class first")
            subclass_field_styles.append({"display": "none"})
            feat_disabled.append(True)
            feat_placeholders.append("No feat at this level")
            feat_field_styles.append({"display": "none"})
            details.append([])
            continue

        class_counts[class_name] += 1
        class_level = class_counts[class_name]
        class_row = next(row for row in CLASSES if row["class"] == class_name)
        progression_row = CLASS_PROGRESSIONS[class_name][class_level - 1]
        subclasses = class_row["subclasses"].split("; ")
        options = [{"label": subclass, "value": subclass} for subclass in subclasses]
        subclass_options.append(options)

        unlocks = []
        for subclass in subclasses:
            first = next(
                (row for row in CLASS_PROGRESSIONS[class_name] if meaningful(row.get(snake_case(subclass), ""))),
                None,
            )
            unlocks.append(int(first["level"]) if first else 1)
        unlock_level = min(unlocks) if unlocks else 1
        inherited_subclass = selected_subclasses.get(class_name)
        valid_choice = chosen_here if chosen_here in subclasses else None
        if valid_choice:
            selected_subclasses[class_name] = valid_choice
            inherited_subclass = valid_choice

        can_choose = class_level == unlock_level and not inherited_subclass
        subclass_disabled.append(not (can_choose or bool(valid_choice)))
        subclass_field_styles.append({} if can_choose or bool(valid_choice) else {"display": "none"})
        if inherited_subclass:
            subclass_placeholders.append(f"{inherited_subclass} selected")
        elif class_level < unlock_level:
            subclass_placeholders.append(f"Available at {class_name} level {unlock_level}")
        else:
            subclass_placeholders.append("Choose subclass")

        subclass_feature = progression_row.get(snake_case(inherited_subclass), "") if inherited_subclass else ""
        class_feature = progression_row.get("class_features", "")
        has_feat = bool(re.search(r"\bFeat\b", f"{class_feature} {subclass_feature}", re.IGNORECASE))
        feat_disabled.append(not has_feat)
        feat_placeholders.append("Choose a feat" if has_feat else "No feat at this level")
        feat_field_styles.append({} if has_feat else {"display": "none"})

        subclass_columns = {snake_case(value) for value in subclasses}
        progression_stats = []
        for field, value in progression_row.items():
            if field in {"level", "proficiency_bonus", "class_features", "source_url"} | subclass_columns:
                continue
            if meaningful(value):
                progression_stats.append(f"{field.replace('_', ' ').title()}: {value}")
        details.append(
            [
                html.Span(f"{class_name} level {class_level}", className="class-level-chip"),
                detail_block("Features", class_feature),
                detail_block("Subclass features", subclass_feature) if inherited_subclass else None,
                html.P(" • ".join(progression_stats), className="level-resource-line") if progression_stats else None,
            ]
        )

    return (
        class_disabled,
        row_styles,
        subclass_options,
        subclass_disabled,
        subclass_placeholders,
        subclass_field_styles,
        feat_disabled,
        feat_placeholders,
        feat_field_styles,
        details,
    )


@callback(
    Output({"type": "feat-choice-container", "level": ALL}, "children"),
    Input({"type": "level-feat", "level": ALL}, "value"),
)
def render_feat_choices(feat_values):
    cards = []
    for level, feat in enumerate(feat_values or [], 1):
        controls, note = [], ""
        if feat == "Ability Improvement":
            controls = [
                feat_choice_dropdown(level, "ability_primary", "First ability point", ABILITIES),
                feat_choice_dropdown(level, "ability_secondary", "Second ability point", ABILITIES),
            ]
            note = "Choose the same ability twice for +2, or two different abilities for +1 each. Scores cannot exceed 20."
        elif feat in CHOICE_FEAT_ABILITIES:
            controls.append(feat_choice_dropdown(level, "ability", "Ability +1", CHOICE_FEAT_ABILITIES[feat]))
            if feat == "Weapon Master":
                controls.append(feat_choice_dropdown(level, "weapons", "Four weapon types", WEAPON_TYPES, True))
        elif feat in FIXED_FEAT_ABILITIES:
            ability, amount = FIXED_FEAT_ABILITIES[feat]
            note = f"Applies {ability} +{amount} automatically."
        if feat == "Elemental Adept":
            controls.append(feat_choice_dropdown(level, "element", "Damage type", ["Acid", "Cold", "Fire", "Lightning", "Thunder"]))
        elif feat and feat.startswith("Magic Initiate:"):
            spell_class = feat.split(":", 1)[1].strip()
            cantrips = sorted({row["spell"] for row in MAGIC_INITIATE_SPELLS if row["class"] == spell_class and row["level"] == "C"})
            spells = sorted({row["spell"] for row in MAGIC_INITIATE_SPELLS if row["class"] == spell_class and row["level"] == "1"})
            controls += [feat_choice_dropdown(level, "cantrips", "Two cantrips", cantrips, True), feat_choice_dropdown(level, "spell", "Level 1 spell", spells)]
            note = "Select no more than two cantrips."
        elif feat == "Martial Adept":
            controls.append(feat_choice_dropdown(level, "manoeuvres", "Two manoeuvres", MANOEUVRES, True)); note = "Select no more than two manoeuvres."
        elif feat == "Ritual Caster":
            controls.append(feat_choice_dropdown(level, "rituals", "Two ritual spells", RITUAL_SPELLS, True)); note = "Select no more than two spells."
        elif feat == "Skilled":
            controls.append(feat_choice_dropdown(level, "skills", "Three skills", sorted(SKILL_TO_ABILITY), True)); note = "Select no more than three skills."
        elif feat == "Spell Sniper":
            controls.append(feat_choice_dropdown(level, "cantrip", "Cantrip", SPELL_SNIPER_CANTRIPS))
        if feat == "Actor":
            note += " Grants Deception and Performance proficiency and expertise automatically."
        if feat == "Resilient":
            note = "The selected ability also gains saving throw proficiency."
        cards.append(html.Div([html.Div(controls, className="feat-choice-grid"), html.P(note) if note else None], className="feat-choice-card") if controls or note else [])
    return cards


@callback(
    Output({"type": "class-choice-container", "level": ALL}, "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
)
def render_class_feature_choices(class_values, subclass_values):
    counts = Counter()
    choices = []
    chosen_subclasses = {}

    def choice_control(level, feature, label, values, multi=False, limit=None):
        option_rows = []
        for value in values:
            style = next((row for row in FIGHTING_STYLES if row["fighting_style"] == value), None)
            feature_row = next((row for row in CLASS_FEATURES if row["feature"].lower() == value.lower()), None)
            description = (style or {}).get("description", "") or (feature_row or {}).get("description", "") or ARCANE_SHOT_DESCRIPTIONS.get(value, "")
            option_rows.append({"label": option_label(value, [description]), "value": value, "search": f"{value} {description}"})
        return html.Div([
            html.Label(label),
            dcc.Dropdown(
                id={"type": "class-feature-choice", "level": level, "feature": feature}, options=option_rows,
                placeholder=f"Choose {label.lower()}", multi=multi, className="rich-dropdown",
                optionHeight=105, maxHeight=390, persistence=True, persistence_type="session",
            ),
            html.P(f"Choose up to {limit}." if multi and limit else "", className="spell-card-note"),
        ], className="feat-choice-field")

    for level, class_name in enumerate(class_values or [], 1):
        if not class_name:
            choices.append([])
            continue
        counts[class_name] += 1
        class_level = counts[class_name]
        selected_here = (subclass_values or [None] * 12)[level - 1] if level <= len(subclass_values or []) else None
        if selected_here:
            chosen_subclasses[class_name] = selected_here
        subclass = chosen_subclasses.get(class_name)
        controls = []

        style_owner = None
        if class_name == "Fighter" and class_level == 1:
            style_owner = "Fighter"
        elif class_name in {"Paladin", "Ranger"} and class_level == 2:
            style_owner = class_name
        elif class_name == "Bard" and class_level == 3 and subclass == "College of Swords":
            style_owner = "College of Swords Bard"
        elif class_name == "Fighter" and class_level == 10 and subclass == "Champion":
            style_owner = "Champion Fighter"
        if style_owner:
            style_values = [row["fighting_style"] for row in FIGHTING_STYLES if style_owner in row["available_to"].split("; ")]
            controls.append(choice_control(level, "Fighting Style", "Fighting Style", style_values))

        if class_name == "Fighter" and subclass == "Battle Master" and class_level in {3, 7, 10}:
            limit = {3: 3, 7: 2, 10: 2}[class_level]
            controls.append(choice_control(level, "Battle Manoeuvres", f"Battle Manoeuvres ({limit})", MANOEUVRES, True, limit))
        if class_name == "Fighter" and subclass == "Arcane Archer" and class_level in {3, 7, 10}:
            limit = 3 if class_level == 3 else 1
            controls.append(choice_control(level, "Arcane Shots", f"Arcane Shots ({limit})", ARCANE_SHOTS, True, limit))
        if class_name == "Sorcerer" and class_level in {2, 3, 10}:
            limit = 2 if class_level == 2 else 1
            metamagic_options = METAMAGIC_BASIC if class_level == 2 else METAMAGIC_BASIC + METAMAGIC_ADVANCED
            controls.append(choice_control(level, "Metamagic", f"Metamagic ({limit})", metamagic_options, True, limit))
        if class_name == "Ranger" and subclass == "Hunter" and class_level == 3:
            controls.append(choice_control(level, "Hunter's Prey", "Hunter's Prey", ["Colossus Slayer", "Giant Killer", "Horde Breaker"]))
        if class_name == "Ranger" and subclass == "Hunter" and class_level == 7:
            controls.append(choice_control(level, "Defensive Tactics", "Defensive Tactics", ["Escape the Horde", "Steel Will", "Multiattack Defence"]))
        if class_name == "Ranger" and subclass == "Swarmkeeper" and class_level == 3:
            controls.append(choice_control(level, "Gathered Swarm", "Gathered Swarm", ["Cloud of Jellyfish", "Flurry of Moths", "Legion of Bees"]))

        if class_name == "Warlock" and counts[class_name] == 3:
            controls.append(choice_control(level, "Pact Boon", "Pact Boon", list(PACT_BOONS)))
        choices.append(html.Div(controls, className="feat-choice-card") if controls else [])
    return choices


@callback(
    Output("feat-effects-store", "data"),
    Input({"type": "level-feat", "level": ALL}, "value"),
    Input({"type": "feat-choice", "level": ALL, "field": ALL}, "value"),
    State({"type": "feat-choice", "level": ALL, "field": ALL}, "id"),
)
def calculate_feat_effects(feat_values, choice_values, choice_ids):
    choices = {(item["level"], item["field"]): value for item, value in zip(choice_ids or [], choice_values or [])}
    bonuses, skills, expertise, saving_throws, proficiencies, selections = Counter(), set(), set(), set(), set(), {}
    for level, feat in enumerate(feat_values or [], 1):
        if not feat:
            continue
        selected = {field: value for (choice_level, field), value in choices.items() if choice_level == level and value}
        selections[str(level)] = selected
        if feat in FIXED_FEAT_ABILITIES:
            ability, amount = FIXED_FEAT_ABILITIES[feat]; bonuses[ability] += amount
        if feat == "Ability Improvement":
            first, second = selected.get("ability_primary"), selected.get("ability_secondary")
            if first:
                bonuses[first] += 1
            if second:
                bonuses[second] += 1
        elif feat in CHOICE_FEAT_ABILITIES and selected.get("ability"):
            bonuses[selected["ability"]] += 1
        if feat == "Actor":
            skills.update(["Deception", "Performance"]); expertise.update(["Deception", "Performance"])
        elif feat == "Skilled":
            skills.update((selected.get("skills") or [])[:3])
        elif feat == "Resilient" and selected.get("ability"):
            saving_throws.add(selected["ability"])
        if feat == "Lightly Armoured":
            proficiencies.add("Light armour")
        elif feat == "Moderately Armoured":
            proficiencies.update(["Medium armour", "Shields"])
        elif feat == "Heavily Armoured":
            proficiencies.add("Heavy armour")
        elif feat == "Weapon Master":
            proficiencies.update((selected.get("weapons") or [])[:4])
    return {"ability_bonuses": dict(bonuses), "skills": sorted(skills), "expertise": sorted(expertise), "saving_throws": sorted(saving_throws), "proficiencies": sorted(proficiencies), "selections": selections, "feats": [feat for feat in (feat_values or []) if feat]}


@callback(
    Output("sheet-class-level", "children"),
    Output("sheet-selected-feats", "children"),
    Output("sheet-initiative", "children"),
    Output("sheet-initiative", "title"),
    Output("sheet-class-features", "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "level-feat", "level": ALL}, "value"),
    Input("abilities-store", "data"),
    Input("feat-effects-store", "data"),
    Input("skill-state-store", "data"),
    Input("equipment-effects-store", "data"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
)
def render_sheet_leveling(class_values, subclass_values, feat_values, ability_data, feat_effects, skill_state, equipment_effects, class_choice_values, class_choice_ids):
    active_classes = []
    for class_name in class_values or []:
        if not class_name:
            break
        active_classes.append(class_name)
    counts = Counter(active_classes)
    total_level = len(active_classes)

    ability_data = ability_data or {}
    feat_effects = feat_effects or {}
    skill_state = skill_state or {}
    adjusted_scores = final_ability_scores(ability_data, feat_effects, equipment_effects)
    constitution = adjusted_scores["Constitution"]
    constitution_modifier = ability_modifier(constitution)

    hit_points = 0
    if active_classes:
        first_row = next(row for row in CLASSES if row["class"] == active_classes[0])
        hit_points = formula_base(first_row["hit_points_level_1"]) + constitution_modifier
        for class_name in active_classes[1:]:
            row = next(item for item in CLASSES if item["class"] == class_name)
            hit_points += formula_base(row["hit_points_per_level"]) + constitution_modifier

    first_class_row = next((row for row in CLASSES if active_classes and row["class"] == active_classes[0]), None)
    base_saves = first_class_row["saving_throw_proficiencies"] if first_class_row else ""
    resilient_saves = feat_effects.get("saving_throws", [])
    saving_throws = "; ".join(filter(None, [base_saves, ", ".join(resilient_saves)])) or "—"
    equipment = []
    seen_classes = set()
    spellcasting = []
    for index, class_name in enumerate(active_classes):
        row = next(item for item in CLASSES if item["class"] == class_name)
        if class_name not in seen_classes:
            equipment.append(row["equipment_proficiencies"] if index == 0 else row["multiclass_proficiencies"])
            spellcasting.append(f"{class_name}: {spellcasting_ability_name(row['spellcasting_ability'])}")
            seen_classes.add(class_name)

    selected_subclasses = []
    subclass_by_class = {}
    for class_name, subclass in zip(class_values or [], subclass_values or []):
        if class_name and subclass and subclass in next(row for row in CLASSES if row["class"] == class_name)["subclasses"].split("; "):
            value = f"{class_name}: {subclass}"
            if value not in selected_subclasses:
                selected_subclasses.append(value)
            subclass_by_class[class_name] = subclass

    features_by_class = progression_features_by_class(class_values, subclass_values)
    earned_features = [feature for values in features_by_class.values() for feature in values]
    feature_descriptions = progression_feature_descriptions(class_values, subclass_values)
    spell_names = {row["spell"].lower() for row in SPELLS}
    earned_features = [feature for feature in earned_features if feature.lower() not in spell_names]
    selected_class_choices = [item for value in class_choice_values or [] for item in (value if isinstance(value, list) else [value]) if item]
    if selected_class_choices:
        earned_features = [feature for feature in earned_features if feature != "Pact Boon"] + selected_class_choices
    if any(choice in {row["fighting_style"] for row in FIGHTING_STYLES} for choice in selected_class_choices):
        earned_features = [feature for feature in earned_features if not feature.lower().startswith("fighting style")]
        earned_features += [choice for choice in selected_class_choices if choice in {row["fighting_style"] for row in FIGHTING_STYLES}]
    automatic_class_attacks = earned_combat_actions(class_values, subclass_values)
    combat_actions = set(MANOEUVRES + ARCANE_SHOTS + SWORDS_BARD_ATTACKS + [feature for values in automatic_class_attacks.values() for feature in values])
    earned_features = [feature for feature in earned_features if feature not in combat_actions]

    selected_by_class = {}
    for value, item_id in zip(class_choice_values or [], class_choice_ids or []):
        level_index = int(item_id.get("level", 0)) - 1
        source_class = class_values[level_index] if 0 <= level_index < len(class_values or []) else None
        if source_class and value:
            selected_by_class.setdefault(source_class, []).extend(value if isinstance(value, list) else [value])
    style_names = {row["fighting_style"] for row in FIGHTING_STYLES}
    feature_groups = []
    for class_name, class_features in features_by_class.items():
        values = [feature for feature in class_features if feature.lower() not in spell_names and feature not in combat_actions]
        selected_values = selected_by_class.get(class_name, [])
        if "Pact Boon" in values and any(choice in PACT_BOONS for choice in selected_values):
            values = [feature for feature in values if feature != "Pact Boon"]
        if any(choice in style_names for choice in selected_values):
            values = [feature for feature in values if not feature.lower().startswith("fighting style")]
        values.extend(choice for choice in selected_values if choice not in combat_actions)
        values = list(dict.fromkeys(values))
        if values:
            feature_groups.append(html.Div([
                html.Strong(class_name, className="sheet-feature-source"),
                html.Div(class_feature_tooltips(values, feature_descriptions), className="sheet-feature-list"),
            ], className="sheet-class-feature-group"))

    dexterity = adjusted_scores["Dexterity"]
    dexterity_bonus = ability_modifier(dexterity)
    feat_initiative = 5 if "Alert" in (feat_values or []) else 0
    class_initiative = 0
    initiative_sources = [f"Dexterity {dexterity_bonus:+d}"]
    if counts.get("Barbarian", 0) >= 7:
        class_initiative += 3
        initiative_sources.append("Feral Instinct +3")
    if counts.get("Ranger", 0) >= 3 and "Ranger: Gloom Stalker" in selected_subclasses:
        class_initiative += 3
        initiative_sources.append("Dread Ambusher +3")
    rogue_level = counts.get("Rogue", 0)
    if rogue_level >= 3 and "Rogue: Swashbuckler" in selected_subclasses:
        rakish_bonus = 4 if rogue_level >= 10 else 3 if rogue_level >= 5 else 2
        class_initiative += rakish_bonus
        initiative_sources.append(f"Rakish Audacity +{rakish_bonus}")
    if feat_initiative:
        initiative_sources.append("Alert +5")
    equipment_initiative = int(skill_state.get("initiative_bonus", 0) or 0)
    if equipment_initiative:
        initiative_sources.append(f"Equipment {equipment_initiative:+d}")
    initiative = dexterity_bonus + feat_initiative + class_initiative + equipment_initiative

    class_summary = "; ".join(f"{name} {count}" for name, count in counts.items()) or "Not selected"
    children = [
        detail_block("Classes", class_summary),
        detail_block("Total level", str(total_level)),
        detail_block("Subclasses", "; ".join(selected_subclasses) or "Not selected"),
        detail_block("Hit points", str(hit_points) if active_classes else "—"),
        detail_block("Saving throws", saving_throws),
        detail_block("Spellcasting", "; ".join(spellcasting) or "—"),
    ]
    selected_feats = [feat for feat in feat_values or [] if feat]
    feat_children = [] if not selected_feats else [
        html.Span("Feats", className="summary-label"),
        html.Span(feat_tooltips(selected_feats)),
    ]
    return children, feat_children, f"{initiative:+d}", " + ".join(initiative_sources), feature_groups or html.P("Class features will appear as you level.", className="sheet-empty")


@callback(
    Output("abilities-store", "data"),
    Input({"type": "ability-step", "ability": ALL, "direction": ALL}, "n_clicks"),
    Input({"type": "ability-bonus-select", "ability": ALL, "bonus": ALL}, "n_clicks"),
    State("abilities-store", "data"),
    prevent_initial_call=True,
)
def update_ability_state(_step_clicks, _bonus_clicks, data):
    data = data or {}
    scores = {ability: int(data.get("scores", {}).get(ability, 8)) for ability in ABILITIES}
    plus_two = data.get("plus_two")
    plus_one = data.get("plus_one")
    triggered = ctx.triggered_id

    if isinstance(triggered, dict) and triggered.get("type") == "ability-step":
        ability = triggered["ability"]
        direction = int(triggered["direction"])
        current = scores[ability]
        candidate = current + direction
        spent = sum(POINT_BUY_COSTS[score] for score in scores.values())
        if direction > 0 and candidate <= 15:
            additional_cost = POINT_BUY_COSTS[candidate] - POINT_BUY_COSTS[current]
            if spent + additional_cost <= 27:
                scores[ability] = candidate
        elif direction < 0 and candidate >= 8:
            scores[ability] = candidate
    elif isinstance(triggered, dict) and triggered.get("type") == "ability-bonus-select":
        ability = triggered["ability"]
        bonus = int(triggered["bonus"])
        if bonus == 2:
            plus_two = None if plus_two == ability else ability
            if plus_two == plus_one:
                plus_one = None
        else:
            plus_one = None if plus_one == ability else ability
            if plus_one == plus_two:
                plus_two = None
    return {"scores": scores, "plus_two": plus_two, "plus_one": plus_one}


@callback(
    Output("equipment-effects-store", "data"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
)
def calculate_equipment_effects(*equipment_ids):
    return equipment_effect_data(equipment_ids)


@callback(
    Output({"type": "ability-score", "ability": ALL}, "children"),
    Output({"type": "ability-step", "ability": ALL, "direction": ALL}, "disabled"),
    Output({"type": "ability-bonus-select", "ability": ALL, "bonus": ALL}, "className"),
    Output("points-remaining", "children"),
    Output("points-remaining", "className"),
    Output("sheet-abilities", "children"),
    Input("abilities-store", "data"),
    Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
)
def render_abilities(data, feat_effects, equipment_effects):
    data = data or {}
    scores = {ability: int(data.get("scores", {}).get(ability, 8)) for ability in ABILITIES}
    plus_two = data.get("plus_two")
    plus_one = data.get("plus_one")
    spent = sum(POINT_BUY_COSTS[score] for score in scores.values())
    remaining = 27 - spent

    score_values = [str(scores[ability]) for ability in ABILITIES]
    button_disabled = []
    for ability in ABILITIES:
        score = scores[ability]
        button_disabled.append(score <= 8)
        next_cost = POINT_BUY_COSTS[score + 1] - POINT_BUY_COSTS[score] if score < 15 else 99
        button_disabled.append(score >= 15 or next_cost > remaining)

    bonus_classes = []
    for ability in ABILITIES:
        bonus_classes.append("bonus-check bonus-check--selected" if ability == plus_two else "bonus-check")
        bonus_classes.append("bonus-check bonus-check--selected" if ability == plus_one else "bonus-check")

    sheet_scores = []
    final_scores = final_ability_scores(data, feat_effects, equipment_effects)
    for ability in ABILITIES:
        final_score = final_scores[ability]
        modifier = ability_modifier(final_score)
        sheet_scores.append(
            html.Div(
                [
                    html.Span(ability[:3].upper(), className="sheet-ability-name"),
                    html.Strong(str(final_score), className="sheet-ability-score"),
                    html.Span(f"{modifier:+d}", className="sheet-ability-modifier"),
                ],
                className="sheet-ability",
            )
        )

    points_class = "points-value points-value--empty" if remaining == 0 else "points-value"
    return score_values, button_disabled, bonus_classes, str(remaining), points_class, sheet_scores


@callback(
    Output("sheet-skills", "children"),
    Output("sheet-proficiency-bonus", "children"),
    Input("abilities-store", "data"),
    Input("background-dropdown", "value"),
    Input("race-dropdown", "value"),
    Input("subrace-dropdown", "value"),
    Input("human-versatility-skill", "value"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input("feat-effects-store", "data"),
    Input("skill-state-store", "data"),
    Input("equipment-effects-store", "data"),
)
def render_skills(ability_data, background, race, subrace, human_skill, level_classes, feat_effects, skill_state, equipment_effects):
    ability_data = ability_data or {}
    skill_state = skill_state or {}
    feat_effects = feat_effects or {}
    final_scores = final_ability_scores(ability_data, feat_effects, equipment_effects)
    selected_levels = 0
    for class_name in level_classes or []:
        if not class_name:
            break
        selected_levels += 1
    level = max(1, min(12, selected_levels or int(skill_state.get("level", 1))))
    proficiency = proficiency_bonus(level)
    expertise = set(skill_state.get("expertise", [])) | set(feat_effects.get("expertise", []))
    item_bonuses = skill_state.get("item_bonuses", {}) or {}

    background_row = next((row for row in BACKGROUNDS if row["background"] == background), None)
    race_row = next((row for row in RACES if row["race"] == race), None)
    subrace_row = next(
        (row for row in RACES if row["race"] == race and row["subrace"] == subrace),
        None,
    )
    proficient = skills_mentioned(
        background_row["skill_proficiencies"] if background_row else "",
        race_row["race_proficiencies"] if race_row else "",
        subrace_row["subrace_proficiencies"] if subrace_row else "",
    )
    if race == "Human" and human_skill:
        proficient.add(human_skill)
    proficient |= set(feat_effects.get("skills", []))
    proficient |= expertise

    rows = []
    for skill in sorted(SKILL_TO_ABILITY):
        ability = SKILL_TO_ABILITY[skill]
        base_modifier = ability_modifier(final_scores[ability])
        proficiency_value = proficiency * (2 if skill in expertise else 1 if skill in proficient else 0)
        item_value = int(item_bonuses.get(skill, 0) or 0)
        total = base_modifier + proficiency_value + item_value
        marker = "◆" if skill in expertise else "●" if skill in proficient else "○"
        status = "expertise" if skill in expertise else "proficient" if skill in proficient else "untrained"
        calculation = f"{ability} {base_modifier:+d} + proficiency {proficiency_value:+d} + items {item_value:+d}"
        rows.append(
            html.Div(
                [
                    html.Span(marker, className=f"skill-marker skill-marker--{status}"),
                    html.Span(skill, className="skill-name"),
                    html.Span(ability[:3].upper(), className="skill-ability"),
                    html.Strong(f"{total:+d}", className="skill-total"),
                ],
                className="skill-row",
                title=calculation,
            )
        )
    return rows, f"Level {level} proficiency {proficiency:+d}"


@callback(
    Output("spell-builder", "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input("abilities-store", "data"),
    Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
)
def render_spell_builder(level_classes, ability_data, feat_effects, equipment_effects):
    counts = Counter()
    for class_name in level_classes or []:
        if not class_name:
            break
        counts[class_name] += 1
    cards = []
    for class_name, class_level in counts.items():
        profile = spell_profile(class_name, class_level, ability_data, feat_effects, equipment_effects)
        if not profile or (not profile["cantrips"] and not profile["max_spell_level"]):
            continue
        class_spells = [row for row in SPELLS if class_name in row["classes"].split("; ")]
        cantrip_options = [spell_option(row) for row in class_spells if row["level"] == "C"]
        levelled_options = [spell_option(row) for row in class_spells if row["level"].isdigit() and int(row["level"]) <= profile["max_spell_level"]]
        fields = []
        if profile["cantrips"] and cantrip_options:
            fields.append(spell_choice_field(class_name, "cantrips", "Cantrips known", cantrip_options, profile["cantrips"]))
        if class_name in KNOWN_CASTERS and profile["learned"] and levelled_options:
            fields.append(spell_choice_field(class_name, "known", "Spells known", levelled_options, profile["learned"]))
        elif class_name == "Wizard" and profile["learned"] and levelled_options:
            fields.append(spell_choice_field(class_name, "known", "Spells learned", levelled_options, profile["learned"]))
            fields.append(spell_choice_field(class_name, "prepared", "Prepared spells", levelled_options, profile["prepared"]))
        elif class_name in PREPARED_CASTERS and profile["prepared"] and levelled_options:
            fields.append(spell_choice_field(class_name, "prepared", "Prepared spells", levelled_options, profile["prepared"]))
        slots = ", ".join(
            f"L{level}: {numeric_progression_value(CLASS_PROGRESSIONS[class_name][class_level - 1], f'spell_slots_{level}')}"
            for level in range(1, profile["max_spell_level"] + 1)
            if numeric_progression_value(CLASS_PROGRESSIONS[class_name][class_level - 1], f"spell_slots_{level}")
        )
        cards.append(
            html.Section(
                [
                    html.Div([html.H3(f"{class_name} level {class_level}"), html.Span(f"{profile['ability']} • {slots}")], className="spell-card-heading"),
                    html.Div(fields, className="spell-choice-grid"),
                    html.P("Wizard prepared spells must also be among the spells learned.", className="spell-card-note") if class_name == "Wizard" else None,
                ],
                className="spell-card",
            )
        )
    return cards or html.P("Choose a spellcasting class on the Leveling tab to unlock spell selections.", className="leveling-empty")


@callback(
    Output({"type": "spell-choice-status", "class": ALL, "kind": ALL, "limit": ALL}, "children"),
    Output({"type": "spell-choice-status", "class": ALL, "kind": ALL, "limit": ALL}, "className"),
    Input({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
)
def update_spell_choice_status(values, ids):
    labels, classes = [], []
    for value, item_id in zip(values or [], ids or []):
        count, limit = len(value or []), int(item_id["limit"])
        labels.append(f"{count} / {limit} selected" + (" — remove extras" if count > limit else ""))
        classes.append("spell-choice-status spell-choice-status--over" if count > limit else "spell-choice-status")
    return labels, classes


def class_granted_spells(level_classes, level_subclasses, class_choice_values):
    canonical_spells = {row["spell"].lower(): row["spell"] for row in SPELLS}
    progression = progression_features_by_class(level_classes, level_subclasses)
    granted = {
        class_name: [canonical_spells[feature.lower()] for feature in features if feature.lower() in canonical_spells]
        for class_name, features in progression.items()
    }
    if "Pact of the Tome" in (class_choice_values or []):
        granted.setdefault("Warlock", []).extend(["Guidance", "Vicious Mockery", "Thorn Whip"])
    return {class_name: list(dict.fromkeys(spells)) for class_name, spells in granted.items() if spells}


def racial_granted_spells(race, subrace, character_level):
    race_row = next((row for row in RACES if row["race"] == race and (not subrace or row["subrace"] == subrace)), None)
    if not race_row:
        return []
    features = " ".join([race_row.get("race_features", ""), race_row.get("subrace_features", "")])
    canonical = {row["spell"].lower(): row["spell"] for row in SPELLS}
    granted = []
    for trait in RACIAL_TRAITS:
        if not re.search(re.escape(trait["trait"]), features, re.IGNORECASE):
            continue
        description = trait.get("description", "")
        matches = []
        for lower_name, spell_name in canonical.items():
            match = re.search(rf"\b{re.escape(lower_name)}\b", description, re.IGNORECASE)
            if match:
                matches.append((match.start(), match.end(), spell_name))
        if "Enlarge/Reduce" in canonical.values() and not any(spell == "Enlarge/Reduce" for _, _, spell in matches):
            match = re.search(r"\bEnlarge\b", description, re.IGNORECASE)
            if match:
                matches.append((match.start(), match.end(), "Enlarge/Reduce"))
        for index, (start, end, spell_name) in enumerate(sorted(matches)):
            next_start = sorted(matches)[index + 1][0] if index + 1 < len(matches) else len(description)
            nearby = description[end:next_start]
            level_match = re.search(r"(?:at|from) level\s+(\d+)", nearby, re.IGNORECASE)
            at_will = re.search(r"at-will spell", nearby, re.IGNORECASE)
            if not level_match and not at_will:
                continue
            required_level = int(level_match.group(1)) if level_match else 1
            if character_level >= required_level:
                granted.append(spell_name)
    return list(dict.fromkeys(granted))


@callback(
    Output({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "options"),
    Input({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
)
def filter_owned_spell_options(values, level_classes, level_subclasses, class_choice_values, race, subrace, ids):
    values, ids = values or [], ids or []
    selections = {(item_id["class"], item_id["kind"]): list(value or []) for value, item_id in zip(values, ids)}
    all_selected = {spell for selected in selections.values() for spell in selected}
    granted_by_class = class_granted_spells(level_classes, level_subclasses, class_choice_values)
    racial_grants = racial_granted_spells(race, subrace, len([value for value in (level_classes or []) if value]))
    all_granted = {spell for spells in granted_by_class.values() for spell in spells} | set(racial_grants)
    class_levels = Counter(value for value in (level_classes or []) if value)
    option_sets = []
    for value, item_id in zip(values, ids):
        class_name, kind = item_id["class"], item_id["kind"]
        own_selected = set(value or [])
        class_level = class_levels.get(class_name, 0)
        max_spell_level = 0
        if class_level and class_name in CLASS_PROGRESSIONS:
            row = CLASS_PROGRESSIONS[class_name][class_level - 1]
            max_spell_level = max((level for level in range(1, 7) if numeric_progression_value(row, f"spell_slots_{level}")), default=0)
        class_spells = [row for row in SPELLS if class_name in row["classes"].split("; ")]
        if kind == "cantrips":
            candidates = [row for row in class_spells if row["level"] == "C"]
        elif class_name == "Wizard" and kind == "prepared":
            learned = set(selections.get(("Wizard", "known"), []))
            candidates = [row for row in class_spells if row["spell"] in learned or row["spell"] in own_selected]
        else:
            candidates = [row for row in class_spells if row["level"].isdigit() and int(row["level"]) <= max_spell_level]
        unavailable = (all_selected - own_selected) | all_granted
        if class_name == "Wizard" and kind == "prepared":
            unavailable -= set(selections.get(("Wizard", "known"), []))
        option_sets.append([spell_option(row) for row in candidates if row["spell"] not in unavailable or row["spell"] in own_selected])
    return option_sets


def combat_action_tooltips(actions, descriptions=None):
    descriptions = descriptions or {}
    rendered = []
    for action in dict.fromkeys(actions or []):
        row = next((item for item in CLASS_FEATURES if item["feature"].lower() == action.lower()), None)
        description = descriptions.get(action) or ARCANE_SHOT_DESCRIPTIONS.get(action) or (row or {}).get("description", "") or f"Combat action: {action}."
        if rendered:
            rendered.append(", ")
        rendered.append(html.Span(action, className="sheet-tooltip-term", tabIndex=0, **{"data-tooltip": description[:900]}))
    return rendered


MANOEUVRE_EFFECTS = {
    "Commander's Strike": "Expend one attack and a bonus action to direct an ally to make a weapon attack using their reaction.",
    "Disarming Attack": "Weapon damage + Superiority Die; the target may drop its held weapons on a failed Strength save.",
    "Distracting Strike": "Weapon damage + Superiority Die; the next allied attack against the target has Advantage.",
    "Evasive Footwork": "No damage. Spend a Superiority Die to impose Disadvantage on melee attacks against you for one round.",
    "Feinting Attack": "Weapon damage + Superiority Die, made with Advantage; consumes both an action and bonus action.",
    "Goading Attack": "Weapon damage + Superiority Die; on a failed Wisdom save the target has Disadvantage against other creatures.",
    "Manoeuvring Attack": "Weapon damage + Superiority Die; an ally gains half its movement speed without provoking Opportunity Attacks.",
    "Menacing Attack": "Weapon damage + Superiority Die; may Frighten the target on a failed Wisdom save.",
    "Precision Attack": "Add the Superiority Die to the attack roll; it does not add damage.",
    "Pushing Attack": "Weapon damage + Superiority Die; may push the target 4.5 m on a failed Strength save.",
    "Rally": "No damage. Grant an ally 8 temporary hit points.",
    "Riposte": "After a creature misses you in melee, retaliate for melee weapon damage + Superiority Die.",
    "Sweeping Attack": "Hit multiple nearby enemies; damage is the Superiority Die rather than normal weapon damage.",
    "Trip Attack": "Weapon damage + Superiority Die; may knock a Large-or-smaller target Prone on a failed Strength save.",
}


def final_ability_modifiers(ability_data, feat_effects, equipment_effects=None) -> dict[str, int]:
    return {ability: ability_modifier(score) for ability, score in final_ability_scores(ability_data, feat_effects, equipment_effects).items()}


def damage_expression_stats(expression: str, multiplier: int = 1) -> tuple[float, float, float]:
    dice = [(int(count or 1), int(sides)) for count, sides in re.findall(r"(\d*)d(\d+)", expression or "", re.IGNORECASE)]
    flat = sum(int(value.replace(" ", "")) for value in re.findall(r"(?<![dD])([+-]\s*\d+)", expression or ""))
    flat += sum(int(value) for value in re.findall(r"(?:^|;)\s*(\d+)\s*(?=;|$)", expression or ""))
    minimum = sum(count for count, _ in dice) + flat
    maximum = sum(count * sides for count, sides in dice) + flat
    mean = sum(count * (sides + 1) / 2 for count, sides in dice) + flat
    return minimum * multiplier, maximum * multiplier, mean * multiplier


def add_damage_stats(base, addition):
    return tuple(left + right for left, right in zip(base, addition))


def damage_types_in(value: str) -> list[str]:
    return [damage_type for damage_type in DAMAGE_TYPES if re.search(rf"\b{re.escape(damage_type)}\b", value or "", re.IGNORECASE)]


def equipment_granted_spells(equipment_ids) -> dict[str, list[str]]:
    grants = {}
    for equipment_id in equipment_ids or []:
        row = EQUIPMENT_BY_ID.get(equipment_id)
        if not row:
            continue
        special = row.get("special", "")
        spells = []
        for spell_row in SPELLS:
            spell = spell_row["spell"]
            pattern = rf"(?<![A-Za-z]){re.escape(spell)}(?![A-Za-z])[^;]*;\s*Cast as\b"
            if re.search(pattern, special, re.IGNORECASE):
                spells.append(spell)
        if spells:
            grants[row["item"]] = list(dict.fromkeys(spells))
    return grants


def equipment_effect_data(equipment_ids) -> dict:
    adjustments, lightning_items, reverberation_items, equipped_items = [], [], [], []
    for equipment_id in equipment_ids or []:
        row = EQUIPMENT_BY_ID.get(equipment_id)
        if not row:
            continue
        special, item = row.get("special", ""), row["item"]
        equipped_items.append(item)
        if re.search(r"Lightning Charges", special, re.IGNORECASE):
            lightning_items.append(item)
        if re.search(r"Reverberation", special, re.IGNORECASE):
            reverberation_items.append(item)
        for ability in ABILITIES:
            fixed_patterns = [
                rf"set(?:s)? the wearer's {ability} score to\s*(\d+)",
                rf"increases? {ability} to\s*(\d+)",
            ]
            for pattern in fixed_patterns:
                match = re.search(pattern, special, re.IGNORECASE)
                if match:
                    adjustments.append({"ability": ability, "kind": "minimum", "value": int(match.group(1)), "source": item})
                    break
            additive = re.search(rf"\b{ability}\s*([+-]\s*\d+)\b(?:\s*\((?:up to|max)\s*(\d+)\))?", special, re.IGNORECASE)
            increase = re.search(rf"increase your {ability} by\s*(\d+),?\s*(?:to a maximum of|up to)\s*(\d+)", special, re.IGNORECASE)
            if additive:
                adjustments.append({"ability": ability, "kind": "add", "value": int(additive.group(1).replace(" ", "")), "cap": int(additive.group(2) or 30), "source": item})
            elif increase:
                adjustments.append({"ability": ability, "kind": "add", "value": int(increase.group(1)), "cap": int(increase.group(2)), "source": item})
    return {
        "ability_adjustments": adjustments,
        "lightning_items": list(dict.fromkeys(lightning_items)),
        "reverberation_items": list(dict.fromkeys(reverberation_items)),
        "equipped_items": list(dict.fromkeys(equipped_items)),
    }


def final_ability_scores(ability_data, feat_effects, equipment_effects=None) -> dict[str, int]:
    ability_data, feat_effects = ability_data or {}, feat_effects or {}
    scores = {}
    for ability in ABILITIES:
        score = int(ability_data.get("scores", {}).get(ability, 8))
        score += 2 if ability_data.get("plus_two") == ability else 1 if ability_data.get("plus_one") == ability else 0
        scores[ability] = min(20, score + int(feat_effects.get("ability_bonuses", {}).get(ability, 0)))
    adjustments = (equipment_effects or {}).get("ability_adjustments", [])
    for item in adjustments:
        if item["kind"] == "add":
            scores[item["ability"]] = min(int(item.get("cap", 30)), scores[item["ability"]] + int(item["value"]))
    for item in adjustments:
        if item["kind"] == "minimum":
            scores[item["ability"]] = max(scores[item["ability"]], int(item["value"]))
    return scores


CONDITION_PATTERNS = {
    "Banished": r"\bbanish(?:ed|ment)?\b", "Blinded": r"\bblind(?:ed|ness)?\b",
    "Burning": r"\bburning\b", "Charmed": r"\bcharm(?:ed)?\b", "Cursed": r"\bcurse[ds]?\b",
    "Disarmed": r"\bdisarm(?:ed|ing)?\b", "Enfeebled": r"\bfeeble|enfeebl",
    "Ensnared": r"\bensnar(?:e|ed|ing)\b", "Faerie Fire": r"\bfaerie fire\b",
    "Frightened": r"\bfrighten(?:ed|ing)?\b", "Marked": r"\bmark(?:ed|ing)?\b",
    "Poisoned": r"\bpoison(?:ed)?\b", "Prone": r"\bprone\b|\bknock[^.]{0,25}down\b",
    "Pushed": r"\bpush(?:ed|ing)?\b", "Restrained": r"\brestrain(?:ed)?\b",
    "Silenced": r"\bsilenc(?:e|ed)\b", "Stunned": r"\bstun(?:ned)?\b",
}


def possible_conditions_for_sequence(sequence, equipped_rows, active_features):
    results, seen = [], set()
    for step in sequence:
        name = step["name"]
        sources = [(name, step.get("detail", ""))]
        for row in SPELLS:
            if row["spell"] in name:
                sources.append((row["spell"], f"{row.get('description', '')} {row.get('damage_effect', '')}"))
        for action, description in {**ARCANE_SHOT_DESCRIPTIONS, **MANOEUVRE_EFFECTS, **COMBAT_ACTION_DESCRIPTIONS}.items():
            if action in name:
                sources.append((action, description))
        for row in CLASS_FEATURES:
            if row["feature"] in name:
                sources.append((row["feature"], row.get("description", "")))
        for row in equipped_rows:
            if not row or not row.get("special"):
                continue
            special = row["special"]
            weapon_used = row.get("category") in {"melee", "ranged"} and row.get("item", "") in name
            offensive_rider = row.get("category") not in {"melee", "ranged"} and re.search(
                r"\b(?:target|enemy|foe|creature you|when you (?:attack|hit|damage)|on a hit|inflict|apply)\b",
                special, re.IGNORECASE,
            )
            if weapon_used or offensive_rider:
                sources.append((row["item"], special))
                for damage_type in DAMAGE_TYPES:
                    vulnerability = rf"Vulnerability to\s+{re.escape(damage_type)}"
                    key = (f"Vulnerable to {damage_type}", row["item"])
                    if key not in seen and re.search(vulnerability, special, re.IGNORECASE):
                        seen.add(key)
                        results.append({"condition": f"Vulnerable to {damage_type}", "source": row["item"]})
        if "Booming Blade" in name:
            key = ("Booming Blade resonance", "Booming Blade")
            if key not in seen:
                seen.add(key)
                results.append({"condition": "Booming Blade resonance", "source": "Booming Blade"})
        for source, description in sources:
            for condition, pattern in CONDITION_PATTERNS.items():
                key = (condition, source)
                if key not in seen and re.search(pattern, description or "", re.IGNORECASE):
                    seen.add(key)
                    results.append({"condition": condition, "source": source})
    if "Hexblade's Curse" in active_features and ("Cursed", "Hexblade's Curse") not in seen:
        results.append({"condition": "Cursed", "source": "Hexblade's Curse"})
    return results


def apply_charge_and_reverberation_effects(sequence, equipped_rows, starting_charges=0):
    item_names = {row["item"] for row in equipped_rows if row}
    charges, reverberation = max(0, min(5, int(starting_charges or 0))), 0
    extra_conditions = []
    for step in sequence:
        stats = (step["min"], step["max"], step["mean"])
        detail, name = step.get("detail", ""), step["name"]
        if charges:
            stats = add_damage_stats(stats, (1, 1, 1))
            detail += " Lightning Charges: +1 Lightning damage."
            if charges >= 5:
                stats = add_damage_stats(stats, damage_expression_stats("1d8"))
                detail += " Five charges discharge for +1d8 Lightning damage and are consumed."
                charges = 0
        generated = 0
        if ({"The Joltshooter", "The Sparky Points"} & item_names) and any(item in name for item in ("The Joltshooter", "The Sparky Points")):
            generated += 2
        if "The Sparkle Hands" in item_names and "Unarmed" in name:
            generated += 2
        if "The Spellsparkler" in item_names and any(row["spell"] in name for row in SPELLS):
            generated += 2
        if generated:
            charges = min(5, charges + generated)
            detail += f" Generates {generated} Lightning Charges (now {charges})."

        applied_reverberation = 0
        if "Gloves of Belligerent Skies" in item_names and any(damage_type in detail for damage_type in ("Thunder", "Lightning", "Radiant")):
            applied_reverberation += 2
        spell_row = next((row for row in SPELLS if row["spell"] in name), None)
        if "Spineshudder Amulet" in item_names and spell_row and "Attack Roll" in spell_row.get("attack_save", "") and "Melee" not in spell_row.get("range_area", ""):
            applied_reverberation += 2
        base_conditions = possible_conditions_for_sequence([step], [], set())
        if "Boots of Stormy Clamour" in item_names and base_conditions:
            applied_reverberation += 2
        if applied_reverberation:
            reverberation += applied_reverberation
            detail += f" Inflicts {applied_reverberation} turns of Reverberation (running total {reverberation})."
            if reverberation >= 5:
                stats = add_damage_stats(stats, damage_expression_stats("1d4"))
                detail += " Reverberation reaches 5: +1d4 Thunder and a DC 10 Constitution save against Prone; stacks are removed."
                extra_conditions.append({"condition": "Prone", "source": "Reverberation (5 turns)"})
                reverberation = 0
            extra_conditions.append({"condition": "Reverberation", "source": "Equipment"})
        step.update({"min": stats[0], "max": stats[1], "mean": stats[2], "detail": detail})
    total = tuple(sum(step[key] for step in sequence) for key in ("min", "max", "mean"))
    return total, list({(item["condition"], item["source"]): item for item in extra_conditions}.values())


def weapon_damage_stats(row, modifiers, styles, slot, offhand_present, monk_level=0, active_features=None, barbarian_level=0, thrown=False):
    active_features = set(active_features or [])
    properties = row.get("shared_properties", "").lower()
    finesse = "finesse" in properties
    ranged = row["category"] == "ranged" and not thrown
    monk_weapon = monk_level > 0 and "heavy" not in properties and "two-handed" not in properties
    hexed_weapon = bool(active_features & {"Hexed Weapon", "Pact Weapon"}) and slot == "melee main" and not thrown
    charge_bound = row.get("item") == "Charge-Bound Warhammer" and slot == "melee main" and not thrown and bool(active_features & {"Hexed Weapon", "Pact Weapon", "Bound Weapon"})
    ability = "Charisma" if hexed_weapon else "Dexterity" if ranged or (finesse or monk_weapon) and modifiers["Dexterity"] > modifiers["Strength"] else "Strength"
    add_modifier = (thrown or "off" not in slot or "Two-Weapon Fighting" in styles) and not row.get("improvised_throw")
    flat = modifiers[ability] if add_modifier else 0
    if "Rage" in active_features and (row["category"] == "melee" or thrown):
        flat += 3 if barbarian_level >= 9 else 2
    if charge_bound:
        flat += 1
    if "Duelling" in styles and row["category"] == "melee" and "main" in slot and not offhand_present and "two-handed" not in properties:
        flat += 2
    expression = row.get("damage", "1")
    if charge_bound:
        expression += "; 1d6"
    if not thrown and row["category"] == "melee" and "versatile" in properties and not offhand_present and "main" in slot:
        versatile = re.search(r"(\d+d\d+)\s*\([^)]*\)\s*\+", row.get("shared_properties", ""), re.IGNORECASE)
        if versatile:
            expression = re.sub(r"^\d+d\d+", versatile.group(1), expression)
    stats = damage_expression_stats(expression)
    return (stats[0] + flat, stats[1] + flat, stats[2] + flat), expression, ability, flat


def optimizer_result_card(sequence, total, limitations, mode, inflicted_conditions=None):
    inflicted_conditions = inflicted_conditions or []
    return html.Div([
        html.Div([
            html.Div([html.Span("Minimum", className="optimizer-total-label"), html.Strong(f"{total[0]:g}")]),
            html.Div([html.Span("Maximum", className="optimizer-total-label"), html.Strong(f"{total[1]:g}")]),
            html.Div([html.Span("Mean", className="optimizer-total-label"), html.Strong(f"{total[2]:.1f}")]),
        ], className="optimizer-totals"),
        html.P(mode, className="optimizer-mode"),
        html.Ol([
            html.Li([html.Strong(step["name"]), html.Span(f" — {step['min']:g}–{step['max']:g}, mean {step['mean']:.1f}"), html.Small(step.get("detail", ""))])
            for step in sequence
        ], className="optimizer-sequence"),
        html.Div([
            html.H4("Possible conditions inflicted"),
            html.Div([
                html.Div([html.Strong(item["condition"]), html.Small(f"Via: {item['source']}")], className="optimizer-condition")
                for item in inflicted_conditions
            ], className="optimizer-condition-list") if inflicted_conditions else html.P("No inflicted conditions identified in this turn.", className="optimized-turn-empty"),
            html.P("Listed without assuming that attack rolls, saving throws, or secondary triggers succeed.", className="condition-help"),
        ], className="optimizer-conditions"),
        html.Details([html.Summary(f"Current model limitations ({len(limitations)})"), html.Ul([html.Li(value) for value in limitations])], className="optimizer-limitations"),
    ], className="optimized-turn-result")


def optimizer_attack_count(name, detail, cantrip_scale=1):
    text = f"{name} {detail}"
    if "Flurry of Blows" in text:
        return 2
    multiplier = re.search(r"(?:×|Ã—|x)(\d+)", name)
    if multiplier and any(term in text for term in ("Attack", "Unarmed", "Throwing")):
        return int(multiplier.group(1))
    if any(term in text for term in ("Melee Attack", "Ranged Attack", "Throwing Attack", "Unarmed Attack", "Off-Hand", "Booming Blade", "Smite", "Strike", "Claws", "Bite", "Beak", "Gore", "Flail", "Trident")):
        return 1
    spell = next((row for row in SPELLS if row["spell"] in name), None)
    if spell and "attack roll" in spell.get("attack_save", "").lower():
        return cantrip_scale if spell["spell"] == "Eldritch Blast" else 1
    return 0


def critical_dice_bonus(detail):
    expressions = re.findall(r"\b\d+d\d+\b", detail or "", re.IGNORECASE)
    return tuple(sum(damage_expression_stats(expression)[index] for expression in expressions) for index in range(3))


def critical_probability(threshold, advantage=False):
    base = max(0.05, min(1.0, (21 - threshold) / 20))
    return 1 - (1 - base) ** 2 if advantage else base


def crit_result_card(normal_sequence, crit_sequence, threshold, advantage, crit_sources, crit_riders):
    per_attack = critical_probability(threshold, advantage)

    def sequence_stats(sequence):
        attacks = sum(step.get("attack_count", 0) for step in sequence)
        no_crit = 1.0
        for step in sequence:
            no_crit *= (1 - step.get("crit_chance", per_attack)) ** step.get("attack_count", 0)
        chance = 1 - no_crit if attacks else 0
        base_mean = sum(step["mean"] for step in sequence)
        bonus_mean = sum(step.get("crit_bonus", (0, 0, 0))[2] * step.get("attack_count", 0) for step in sequence)
        return attacks, chance, base_mean, bonus_mean

    normal_attacks, normal_chance, normal_mean, normal_bonus = sequence_stats(normal_sequence)
    crit_attacks, crit_chance, crit_mean, crit_bonus = sequence_stats(crit_sequence)
    return html.Div([
        html.Div([html.P("CRITICAL HIT MODEL", className="eyebrow"), html.H3("Crit Calculator")], className="condition-heading"),
        html.Div([
            html.Div([html.Span("Base critical range", className="optimizer-total-label"), html.Strong(f"{threshold}–20")]),
            html.Div([html.Span("Base per attack", className="optimizer-total-label"), html.Strong(f"{per_attack:.1%}")]),
            html.Div([html.Span("Normal plan: ≥1 crit", className="optimizer-total-label"), html.Strong(f"{normal_chance:.1%}")]),
        ], className="optimizer-totals"),
        html.P(("Advantage applied. " if advantage else "Normal attack rolls. ") + f"Sources: {', '.join(crit_sources) if crit_sources else 'natural 20 only'}." , className="optimizer-mode"),
        html.Div([html.Strong("Normal damage plan"), html.P(f"{normal_attacks} attack roll(s); mean {normal_mean:.1f}; estimated mean on a critical outcome {normal_mean + normal_bonus:.1f}.")], className="crit-plan-summary"),
        html.Div([html.Strong("Crit-optimized alternative"), html.P(f"{crit_attacks} attack roll(s); {crit_chance:.1%} chance of at least one critical hit; base mean {crit_mean:.1f}; estimated mean with doubled critical dice {crit_mean + crit_bonus:.1f}."),
                  html.Ol([html.Li(step["name"]) for step in crit_sequence], className="optimizer-sequence")], className="crit-plan-summary"),
        html.P(f"Critical riders considered: {', '.join(crit_riders) if crit_riders else 'standard doubled damage dice only'}.", className="condition-help"),
        html.P("Estimates assume attacks hit and report the probability of rolling at least one critical hit; enemy AC and confirmation of conditional riders are not included.", className="condition-help"),
    ], className="optimized-turn-result crit-result-card")


def has_thrown_property(row):
    return bool(row) and (
        "thrown" in row.get("shared_properties", "").lower()
        or row.get("item") in {"Dwarven Thrower", "Orphic Hammer", "Returning Pike"}
    )


def throwing_attack_row(row):
    """Return the damage profile used when the equipped main-hand item is thrown."""
    if not row:
        return row
    if has_thrown_property(row):
        # Throw attacks normally use only the weapon's base physical damage;
        # innate elemental riders do not transfer unless explicitly enabled.
        damage_parts = [part.strip() for part in row.get("damage", "1").split(";") if part.strip()]
        type_parts = [part.strip() for part in row.get("damage_type", "Weapon").split(";") if part.strip()]
        damage = damage_parts[0] if damage_parts else "1"
        damage_type = type_parts[0] if type_parts else "Weapon"
        if row.get("item") == "Lightning Jabber":
            damage += "; 1d4"
            damage_type += "; Lightning"
        return {**row, "damage": damage, "damage_type": damage_type, "shared_properties": row.get("shared_properties", "") + "; Thrown"}
    try:
        weight = float(row.get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight = 0
    damage = "2d4" if weight > 50 else "1d4" if weight >= 10 else "1"
    return {
        **row,
        "damage": damage,
        "damage_type": "Bludgeoning",
        "enchantment": "",
        "shared_properties": "Improvised Throw",
        "special": "",
        "improvised_throw": True,
    }


def weapon_attack_description(row, slot, modifiers, proficiency, styles, offhand_present=False, thrown=False,
                              proficient=True, monk_weapon=False, elevation="Level", active_features=None):
    active_features = set(active_features or [])
    properties = row.get("shared_properties", "")
    finesse = "finesse" in properties.lower()
    ranged = row["category"] == "ranged" and not thrown
    flexible_ability = finesse or monk_weapon
    hexed_weapon = bool(active_features & {"Hexed Weapon", "Pact Weapon"}) and slot == "melee main" and not thrown
    charge_bound = row.get("item") == "Charge-Bound Warhammer" and slot == "melee main" and not thrown and bool(active_features & {"Hexed Weapon", "Pact Weapon", "Bound Weapon"})
    ability = "Charisma" if hexed_weapon else "Dexterity" if ranged else ("Dexterity" if flexible_ability and modifiers["Dexterity"] > modifiers["Strength"] else "Strength")
    proficient = proficient or hexed_weapon
    modifier = modifiers[ability]
    damage = row.get("damage", "1")
    if not thrown and row["category"] == "melee" and "versatile" in properties.lower() and not offhand_present and "main" in slot:
        versatile = re.search(r"(\d+d\d+)\s*\([^)]*\)\s*\+", properties, re.IGNORECASE)
        if versatile:
            damage = re.sub(r"^\d+d\d+", versatile.group(1), damage)
    add_modifier = ("off" not in slot or "Two-Weapon Fighting" in styles or thrown) and not row.get("improvised_throw")
    modifier_text = (
        f" {modifier:+d} {ability}" if add_modifier else
        " (weight-based improvised damage; no ability modifier)" if row.get("improvised_throw") else
        " (no ability modifier on an off-hand damage roll)"
    )
    duelling = 2 if "Duelling" in styles and row["category"] == "melee" and "main" in slot and not offhand_present and "two-handed" not in properties.lower() else 0
    attack_enchantment = formula_base(row.get("enchantment", ""))
    style_attack_bonus = 2 if ranged and "Archery" in styles else 0
    proficiency_bonus = proficiency if proficient else 0
    elevation_bonus = 2 if elevation == "High Ground" else -2 if elevation == "Low Ground" else 0
    attack_bonus = proficiency_bonus + modifier + attack_enchantment + style_attack_bonus + elevation_bonus + (1 if charge_bound else 0)
    formula = f"{damage}{modifier:+d}" if add_modifier else damage
    if duelling:
        formula += "+2"
    if charge_bound:
        formula += "+1+1d6 Lightning"
    extras = f" Special: {row['special']}" if row.get("special") else ""
    mode = "Improvised throwing attack" if thrown and row.get("improvised_throw") else "Thrown weapon attack" if thrown else ("Ranged weapon attack" if ranged else "Melee weapon attack")
    proficiency_text = f"proficiency +{proficiency}" if proficient else "not proficient +0"
    binding_name = "Hexed Weapon" if "Hexed Weapon" in active_features else "Pact Weapon"
    ability_reason = binding_name if hexed_weapon else "Finesse" if finesse else "Monk weapon" if monk_weapon else "Ranged weapon" if ranged else "standard Strength weapon"
    elevation_text = f", {elevation} {elevation_bonus:+d}" if elevation_bonus else ""
    weight_text = ""
    if thrown:
        weight = row.get("weight_kg") or "unknown"
        weight_text = f" Weight: {weight} kg. Knocks a target back when this is over half its weight, and knocks it Prone when this is heavier than the target."
    return f"{mode} with {row['item']}. Attack roll: +{attack_bonus} ({ability} {modifier:+d} from {ability_reason}, {proficiency_text}, enchantment +{attack_enchantment}{', Favoured Weapon +1' if charge_bound else ''}{', Archery +2' if style_attack_bonus else ''}{elevation_text}). Damage: {formula} {row.get('damage_type', '')}.{modifier_text}{weight_text}{f' Damage is magical from {binding_name}.' if hexed_weapon else ''}{' Charge-bound bonuses active.' if charge_bound else ''}{' Duelling +2.' if duelling else ''}{extras}"


@callback(
    Output("attack-builder", "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    Input("abilities-store", "data"), Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("turn-visibility", "value"), Input("turn-elevation", "value"),
    Input("turn-attacker-conditions", "value"), Input("turn-target-conditions", "value"),
    Input("optimizer-active-features", "value"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
)
def render_attack_builder(class_values, subclass_values, choice_values, race, subrace, ability_data, feat_effects,
                          equipment_effects, melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, visibility, elevation,
                          attacker_conditions, target_conditions, active_features, choice_ids):
    counts = Counter(value for value in class_values or [] if value)
    subclasses = {(class_name, subclass) for class_name, subclass in zip(class_values or [], subclass_values or []) if class_name and subclass}
    active_features = set(active_features or [])
    if ("Warlock", "The Hexblade") not in subclasses:
        active_features -= {"Hexed Weapon", "Hexblade's Curse"}
    selected = {}
    for value, item_id in zip(choice_values or [], choice_ids or []):
        if not value:
            continue
        selected.setdefault(item_id["feature"], []).extend(value if isinstance(value, list) else [value])
    selected_values = {item for values in selected.values() for item in values}
    if ("Fighter", "Eldritch Knight") not in subclasses:
        active_features.discard("Bound Weapon")
    if "Pact of the Blade" not in selected_values:
        active_features.discard("Pact Weapon")
    cards = []
    styles = list(dict.fromkeys(selected.get("Fighting Style", [])))
    profs = character_equipment_proficiencies(race, subrace, class_values, feat_effects)

    def describe_weapon(row, slot, modifiers, proficiency, offhand_present=False, thrown=False):
        properties = row.get("shared_properties", "").lower()
        hexed_weapon = bool(active_features & {"Hexed Weapon", "Pact Weapon"}) and slot == "melee main" and not thrown
        proficient = proficient_with_item(row, profs) or hexed_weapon
        monk_weapon = counts.get("Monk", 0) > 0 and proficient and "heavy" not in properties and "two-handed" not in properties
        return weapon_attack_description(row, slot, modifiers, proficiency, styles, offhand_present, thrown, proficient, monk_weapon, elevation, active_features)
    if styles:
        cards.append(html.Section([html.H3("Fighting Styles"), html.P(combat_action_tooltips(styles), className="attack-list")], className="spell-card"))
    attacks = []
    for feature in ("Battle Manoeuvres", "Arcane Shots", "Hunter's Prey", "Gathered Swarm"):
        attacks.extend(selected.get(feature, []))
    automatic_attacks = earned_combat_actions(class_values, subclass_values)
    for values in automatic_attacks.values():
        attacks.extend(values)
    attacks = list(dict.fromkeys(attacks))
    if attacks:
        superiority_die = "1d10" if counts.get("Fighter", 0) >= 10 and ("Fighter", "Battle Master") in subclasses else "1d8"
        melee_row, ranged_row = EQUIPMENT_BY_ID.get(melee_main_id), EQUIPMENT_BY_ID.get(ranged_main_id)
        modifiers = final_ability_modifiers(ability_data, feat_effects, equipment_effects)
        proficiency = 4 if sum(counts.values()) >= 9 else 3 if sum(counts.values()) >= 5 else 2
        attack_descriptions = {}
        manoeuvre_dc = 8 + proficiency + max(modifiers["Strength"], modifiers["Dexterity"])
        arcane_shot_dc = 8 + proficiency + modifiers["Intelligence"]
        for attack in attacks:
            if attack in MANOEUVRE_EFFECTS:
                base = MANOEUVRE_EFFECTS[attack].replace("Superiority Die", superiority_die)
                if "save" in base.lower():
                    base += f" Manoeuvre save DC: {manoeuvre_dc}."
                formulas = []
                if melee_row and attack not in {"Commander's Strike", "Evasive Footwork", "Precision Attack", "Rally", "Sweeping Attack"}:
                    formulas.append("Melee: " + describe_weapon(melee_row, "melee main", modifiers, proficiency, bool(melee_off_id)))
                if ranged_row and attack not in {"Commander's Strike", "Evasive Footwork", "Feinting Attack", "Precision Attack", "Rally", "Riposte", "Sweeping Attack"}:
                    formulas.append("Ranged: " + describe_weapon(ranged_row, "ranged main", modifiers, proficiency, bool(ranged_off_id)))
                attack_descriptions[attack] = f"{base} {' '.join(formulas)}"
            elif attack in ARCANE_SHOTS and ranged_row:
                attack_descriptions[attack] = f"{ARCANE_SHOT_DESCRIPTIONS[attack]} Arcane Shot save DC: {arcane_shot_dc}. Base shot: {describe_weapon(ranged_row, 'ranged main', modifiers, proficiency, bool(ranged_off_id))}"
            elif "Flourish" in attack:
                bard_level = counts.get("Bard", 0)
                inspiration = "1d10" if bard_level >= 10 else "1d8" if bard_level >= 5 else "1d6"
                weapon = ranged_row if "Ranged" in attack else melee_row
                base = describe_weapon(weapon, "ranged main" if "Ranged" in attack else "melee main", modifiers, proficiency, bool(ranged_off_id if "Ranged" in attack else melee_off_id)) if weapon else "Equip the corresponding weapon to calculate base damage."
                special = "Gain +4 AC on a hit." if "Defensive" in attack else "Attack up to two targets." if "Slashing" in attack else "Push the target 6 m, then you may teleport to it."
                attack_descriptions[attack] = f"{base} Add {inspiration} weapon damage from Bardic Inspiration. {special}"
            else:
                feature_row = next((row for row in CLASS_FEATURES if row["feature"].lower() == attack.lower()), None)
                description = COMBAT_ACTION_DESCRIPTIONS.get(attack) or (feature_row or {}).get("description", f"Combat action: {attack}.")
                if attack.startswith("Sneak Attack") and counts.get("Rogue", 0):
                    sneak_die = CLASS_PROGRESSIONS["Rogue"][counts["Rogue"] - 1].get("sneak_attack_damage", "")
                    description += f" Current bonus damage: {sneak_die}."
                formulas = []
                lowered = description.lower()
                if ranged_row and ("ranged" in attack.lower() or attack in {"Volley", "Curving Shot"} or "either melee or ranged" in lowered):
                    formulas.append("Ranged calculation: " + describe_weapon(ranged_row, "ranged main", modifiers, proficiency, bool(ranged_off_id)))
                if melee_row and ("melee" in attack.lower() or "weapon action" in lowered or "melee attack" in lowered or "either melee or ranged" in lowered):
                    formulas.append("Melee calculation: " + describe_weapon(melee_row, "melee main", modifiers, proficiency, bool(melee_off_id)))
                if attack == "Enraged Throw" and melee_row and "thrown" in melee_row.get("shared_properties", "").lower():
                    formulas.append("Throw calculation: " + describe_weapon(melee_row, "melee main", modifiers, proficiency, bool(melee_off_id), True))
                if any(term in attack.lower() for term in ("unarmed", "punch", "fist", "flurry", "martial arts", "intoxicating strike", "redirect attack")):
                    monk_level = counts.get("Monk", 0)
                    die = CLASS_PROGRESSIONS["Monk"][monk_level - 1].get("martial_arts", "1") if monk_level else "1"
                    ability = "Dexterity" if modifiers["Dexterity"] > modifiers["Strength"] else "Strength"
                    strikes = 2 if "flurry" in attack.lower() else 1
                    formulas.append(f"Unarmed calculation: attack +{proficiency + modifiers[ability]}, damage {'2 × ' if strikes == 2 else ''}({die}{modifiers[ability]:+d}) Bludgeoning using {ability}.")
                attack_descriptions[attack] = " ".join([description, *formulas])
        cards.append(html.Section([
            html.Div([html.H3("Combat Actions"), html.Span(f"{len(attacks)} available")], className="spell-card-heading"),
            html.P(combat_action_tooltips(attacks, attack_descriptions), className="attack-list"),
        ], className="spell-card"))

    modifiers = final_ability_modifiers(ability_data, feat_effects, equipment_effects)
    proficiency = 4 if sum(counts.values()) >= 9 else 3 if sum(counts.values()) >= 5 else 2
    basic_attacks, basic_descriptions = [], {}
    monk_level = counts.get("Monk", 0)
    unarmed_die = CLASS_PROGRESSIONS["Monk"][monk_level - 1].get("martial_arts", "1") if monk_level else "1"
    unarmed_ability = "Dexterity" if monk_level and modifiers["Dexterity"] > modifiers["Strength"] else "Strength"
    unarmed_mod = modifiers[unarmed_ability]
    basic_attacks.append("Unarmed Strike")
    basic_descriptions["Unarmed Strike"] = f"Melee attack roll +{proficiency + unarmed_mod}. Damage: {unarmed_die}{unarmed_mod:+d} Bludgeoning ({unarmed_ability} {unarmed_mod:+d} plus proficiency +{proficiency} to hit)."
    equipped_weapons = [
        ("Melee Attack", "melee main", EQUIPMENT_BY_ID.get(melee_main_id), bool(melee_off_id)),
        ("Off-Hand Melee Attack", "melee off", EQUIPMENT_BY_ID.get(melee_off_id), True),
        ("Ranged Attack", "ranged main", EQUIPMENT_BY_ID.get(ranged_main_id), bool(ranged_off_id)),
        ("Off-Hand Ranged Attack", "ranged off", EQUIPMENT_BY_ID.get(ranged_off_id), True),
    ]
    for title, slot, row, offhand_present in equipped_weapons:
        if not row or row["category"] not in {"melee", "ranged"}:
            continue
        label = f"{title}: {row['item']}"
        basic_attacks.append(label)
        basic_descriptions[label] = describe_weapon(row, slot, modifiers, proficiency, offhand_present)
        if slot == "melee main":
            throw_row = throwing_attack_row(row)
            throw_stats, _, _, _ = weapon_damage_stats(
                throw_row, modifiers, styles, slot, offhand_present, counts.get("Monk", 0),
                active_features, counts.get("Barbarian", 0), thrown=True,
            )
            equipped_names = set((equipment_effects or {}).get("equipped_items", []))
            for item_name, bonus in (("Ring of Flinging", "1d4"), ("Gloves of Uninhibited Kushigo", "1d4"),
                                     ("Helldusk Gloves", "1d6"), ("Flawed Helldusk Gloves", "1d4")):
                if item_name in equipped_names and not (item_name == "Flawed Helldusk Gloves" and "Helldusk Gloves" in equipped_names):
                    throw_stats = add_damage_stats(throw_stats, damage_expression_stats(bonus))
            if "Legacy of the Masters" in equipped_names:
                throw_stats = tuple(value + 2 for value in throw_stats)
            if "Horns of the Berserker" in equipped_names and "Below 50% HP" in (attacker_conditions or []):
                throw_stats = tuple(value + 2 for value in throw_stats)
            if "Tavern Brawler" in (feat_effects or {}).get("feats", []):
                throw_stats = tuple(value + modifiers["Strength"] for value in throw_stats)
            if row["item"] == "Nyrulna":
                throw_stats = add_damage_stats(throw_stats, damage_expression_stats("3d4"))
            if row["item"] == "Dwarven Thrower" and "Dwarf" in f"{race or ''} {subrace or ''}":
                throw_stats = add_damage_stats(throw_stats, damage_expression_stats("1d8"))
            if row["item"] == "Dwarven Thrower" and "Large or Larger" in (target_conditions or []):
                throw_stats = add_damage_stats(throw_stats, damage_expression_stats("2d8"))
            if "Hunter's Marked" in (target_conditions or []):
                throw_stats = add_damage_stats(throw_stats, damage_expression_stats("1d6"))
            throw_type = throw_row.get("damage_type", "Bludgeoning").replace(";", " +")
            throw_label = f"Throwing Attack: {row['item']} — {throw_stats[0]:g}–{throw_stats[1]:g} {throw_type}"
            basic_attacks.append(throw_label)
            basic_descriptions[throw_label] = describe_weapon(throw_row, slot, modifiers, proficiency, offhand_present, True)
    cards.insert(1 if styles else 0, html.Section([
        html.Div([html.H3("Basic attacks"), html.Span(f"{len(basic_attacks)} available")], className="spell-card-heading"),
        html.P(combat_action_tooltips(basic_attacks, basic_descriptions), className="attack-list"),
    ], className="spell-card"))
    assumptions = [value for value in [visibility, elevation] if value and value != "No condition"]
    assumptions += list(attacker_conditions or []) + [f"Target: {value}" for value in (target_conditions or [])]
    return [html.Div([
        html.P("CLASS ATTACKS", className="eyebrow"), html.H2("Combat actions"),
        html.P("Active assumptions: " + (" • ".join(assumptions) if assumptions else "None"), className="combat-assumptions"),
    ], className="leveling-header"), *cards]


@callback(
    Output("optimizer-active-features", "options"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
)
def optimizer_active_feature_options(class_values, subclass_values, choice_values, choice_ids):
    counts = Counter(value for value in class_values or [] if value)
    subclasses = {(class_name, subclass) for class_name, subclass in zip(class_values or [], subclass_values or []) if class_name and subclass}
    options = []
    if counts.get("Rogue"):
        options.append({"label": " Sneak Attack available", "value": "Sneak Attack"})
    if counts.get("Barbarian"):
        options.append({"label": " Rage active", "value": "Rage"})
    if counts.get("Barbarian", 0) >= 6 and ("Barbarian", "Giant") in subclasses:
        options.append({"label": " Elemental Cleaver applied", "value": "Elemental Cleaver"})
    if ("Warlock", "The Hexblade") in subclasses:
        options.extend([
            {"label": " Bind Hexed Weapon to melee main hand", "value": "Hexed Weapon"},
            {"label": " Target has Hexblade's Curse", "value": "Hexblade's Curse"},
        ])
    selected_metamagic = {
        item for value, item_id in zip(choice_values or [], choice_ids or [])
        if item_id.get("feature") == "Metamagic"
        for item in (value if isinstance(value, list) else [value]) if item
    }
    selected_choices = {
        item for value in choice_values or []
        for item in (value if isinstance(value, list) else [value]) if item
    }
    if ("Fighter", "Eldritch Knight") in subclasses:
        options.append({"label": " Weapon Bond on melee main hand", "value": "Bound Weapon"})
    if "Pact of the Blade" in selected_choices:
        options.append({"label": " Bind Pact Weapon to melee main hand", "value": "Pact Weapon"})
    if "Quickened Spell" in selected_metamagic:
        options.append({"label": " Use Quickened Spell", "value": "Quickened Spell"})
    if "Twinned Spell" in selected_metamagic:
        options.append({"label": " Use Twinned Spell", "value": "Twinned Spell"})
    return options


@callback(
    Output("optimizer-wild-shape", "options"),
    Output("optimizer-wild-shape-field", "style"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
)
def wild_shape_options(class_values, subclass_values):
    druid_level = sum(value == "Druid" for value in (class_values or []))
    if druid_level < 2:
        return [], {"display": "none"}
    moon_druid = any(
        class_name == "Druid" and subclass == "Circle of the Moon"
        for class_name, subclass in zip(class_values or [], subclass_values or [])
    )
    options = [
        {"label": f"{name} (Druid {data['level']}+{' · Moon' if data.get('moon') else ''})", "value": name}
        for name, data in WILD_SHAPE_FORMS.items()
        if druid_level >= data["level"] and (not data.get("moon") or moon_druid)
    ]
    return options, {"display": "block"}


@callback(
    Output("optimizer-elemental-cleaver-type", "style"),
    Input("optimizer-active-features", "value"),
)
def show_elemental_cleaver_type(active_features):
    return {"display": "block", "marginTop": "8px"} if "Elemental Cleaver" in (active_features or []) else {"display": "none"}


@callback(
    Output("optimizer-lightning-charges", "style"),
    Input("equipment-effects-store", "data"),
)
def show_lightning_charge_selector(equipment_effects):
    return {"display": "block", "marginTop": "8px"} if (equipment_effects or {}).get("lightning_items") else {"display": "none"}


@callback(
    Output("optimized-turn", "children"),
    Input("optimizer-use-limited-resources", "value"),
    Input({"type": "level-class", "level": ALL}, "value"), Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "level-feat", "level": ALL}, "value"), Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    Input("abilities-store", "data"), Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
    Input({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value"),
    Input("turn-attacker-conditions", "value"),
    Input("turn-visibility", "value"),
    Input("turn-target-conditions", "value"),
    Input("optimizer-active-features", "value"),
    Input("optimizer-wild-shape", "value"),
    Input("optimizer-elemental-cleaver-type", "value"),
    Input("optimizer-lightning-charges", "value"),
    State({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "id"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
)
def optimize_turn(use_limited, class_values, subclass_values, feat_values, race, subrace, ability_data, feat_effects, equipment_effects, class_choice_values,
                  melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, headwear_id, armour_id,
                  handwear_id, footwear_id, cape_id, necklace_id, ring_1_id, ring_2_id, spell_values, attacker_conditions, visibility, target_conditions,
                  active_features, wild_shape, elemental_cleaver_type, lightning_charges, class_choice_ids, spell_ids):
    active_classes = [value for value in class_values or [] if value]
    if not active_classes:
        return html.P("Choose at least one class level to calculate an optimized turn.", className="optimized-turn-empty")
    limited = "limited" in (use_limited or [])
    counts = Counter(active_classes)
    active_features = set(active_features or [])
    selected_subclasses = {(class_name, subclass) for class_name, subclass in zip(class_values or [], subclass_values or []) if class_name and subclass}
    if not counts.get("Barbarian"):
        active_features.discard("Rage")
    if counts.get("Barbarian", 0) < 6 or ("Barbarian", "Giant") not in selected_subclasses:
        active_features.discard("Elemental Cleaver")
    if ("Warlock", "The Hexblade") not in selected_subclasses:
        active_features -= {"Hexed Weapon", "Hexblade's Curse"}
    if not counts.get("Rogue"):
        active_features.discard("Sneak Attack")
    level = len(active_classes)
    modifiers = final_ability_modifiers(ability_data, feat_effects, equipment_effects)
    selected_choices = [item for value in class_choice_values or [] for item in (value if isinstance(value, list) else [value]) if item]
    if ("Fighter", "Eldritch Knight") not in selected_subclasses:
        active_features.discard("Bound Weapon")
    if "Pact of the Blade" not in selected_choices:
        active_features.discard("Pact Weapon")
    if "Quickened Spell" not in selected_choices:
        active_features.discard("Quickened Spell")
    if "Twinned Spell" not in selected_choices:
        active_features.discard("Twinned Spell")
    styles = [value for value in selected_choices if value in {row["fighting_style"] for row in FIGHTING_STYLES}]
    progression = progression_features_by_class(class_values, subclass_values)
    features = {feature for values in progression.values() for feature in values}

    full_caster_level = sum(counts.get(name, 0) for name in ["Bard", "Cleric", "Druid", "Sorcerer", "Wizard"])
    half_caster_level = counts.get("Paladin", 0) // 2 + counts.get("Ranger", 0) // 2
    third_caster_level = 0
    if ("Fighter", "Eldritch Knight") in selected_subclasses:
        third_caster_level += counts.get("Fighter", 0) // 3
    if ("Rogue", "Arcane Trickster") in selected_subclasses:
        third_caster_level += counts.get("Rogue", 0) // 3
    caster_level = min(12, full_caster_level + half_caster_level + third_caster_level)
    standard_slot_counts = MULTICLASS_SPELL_SLOTS.get(caster_level, [0] * 6)
    spell_slot_inventory = [
        slot_level for slot_level, slot_count in enumerate(standard_slot_counts, 1)
        for _ in range(slot_count)
    ]
    warlock_level = counts.get("Warlock", 0)
    if warlock_level:
        warlock_row = CLASS_PROGRESSIONS["Warlock"][warlock_level - 1]
        for slot_level in range(1, 6):
            spell_slot_inventory.extend([slot_level] * numeric_progression_value(warlock_row, f"spell_slots_{slot_level}"))
    spell_slot_inventory.sort(reverse=True)

    actions = 1
    bonus_actions = 2 if "Fast Hands" in features else 1
    if limited and "Action Surge" in features:
        actions += 1
    attacks_per_action = 3 if counts.get("Fighter", 0) >= 11 else 2 if "Extra Attack" in features or "Improved Extra Attack" in features else 1
    monk_level = counts.get("Monk", 0)

    action_candidates, bonus_candidates = [], []
    melee_attack = ranged_attack = None
    melee_main, melee_off = EQUIPMENT_BY_ID.get(melee_main_id), EQUIPMENT_BY_ID.get(melee_off_id)
    ranged_main, ranged_off = EQUIPMENT_BY_ID.get(ranged_main_id), EQUIPMENT_BY_ID.get(ranged_off_id)
    main_weapons = [("Melee Attack", melee_main, "melee main", bool(melee_off)), ("Ranged Attack", ranged_main, "ranged main", bool(ranged_off))]
    weapon_attacks = []
    for name, row, slot, offhand_present in main_weapons:
        if row and row["category"] in {"melee", "ranged"}:
            per_hit, expression, ability, flat = weapon_damage_stats(row, modifiers, styles, slot, offhand_present, monk_level, active_features, counts.get("Barbarian", 0))
            improved_divine_smite = counts.get("Paladin", 0) >= 11 and row["category"] == "melee"
            if improved_divine_smite:
                per_hit = add_damage_stats(per_hit, damage_expression_stats("1d8"))
            aura_of_hate = counts.get("Paladin", 0) >= 7 and ("Paladin", "Oathbreaker") in selected_subclasses and row["category"] == "melee"
            if aura_of_hate:
                per_hit = tuple(value + modifiers["Charisma"] for value in per_hit)
            cleaver_active = "Elemental Cleaver" in active_features and "Rage" in active_features and elemental_cleaver_type
            if cleaver_active:
                cleaver_stats = damage_expression_stats("1d6")
                if "Wet" in (target_conditions or []) and elemental_cleaver_type in {"Cold", "Lightning"}:
                    cleaver_stats = tuple(value * 2 for value in cleaver_stats)
                per_hit = add_damage_stats(per_hit, cleaver_stats)
            charge_bound_active = row["item"] == "Charge-Bound Warhammer" and slot == "melee main" and bool(active_features & {"Hexed Weapon", "Pact Weapon", "Bound Weapon"})
            if charge_bound_active and "Wet" in (target_conditions or []):
                per_hit = add_damage_stats(per_hit, damage_expression_stats("1d6"))
            if "Hexblade's Curse" in active_features:
                per_hit = tuple(value + (4 if level >= 9 else 3 if level >= 5 else 2) for value in per_hit)
            stats = tuple(value * attacks_per_action for value in per_hit)
            weapon_types = damage_types_in(row.get("damage_type", ""))
            if charge_bound_active:
                weapon_types.append("Lightning")
            active_notes = []
            if "Rage" in active_features and row["category"] == "melee":
                active_notes.append(f"Rage +{3 if counts.get('Barbarian', 0) >= 9 else 2} per hit")
            if active_features & {"Hexed Weapon", "Pact Weapon"} and slot == "melee main":
                active_notes.append(("Hexed Weapon" if "Hexed Weapon" in active_features else "Pact Weapon") + " uses Charisma")
            if charge_bound_active:
                active_notes.append("Favoured Weapon +1 attack/damage and +1d6 Lightning" + (" (doubled by Wet)" if "Wet" in (target_conditions or []) else ""))
            if "Hexblade's Curse" in active_features:
                active_notes.append(f"Hexblade's Curse +{4 if level >= 9 else 3 if level >= 5 else 2} per hit")
            if cleaver_active:
                active_notes.append(f"Elemental Cleaver +1d6 {elemental_cleaver_type}" + (" (doubled by Wet)" if "Wet" in (target_conditions or []) and elemental_cleaver_type in {"Cold", "Lightning"} else ""))
            if improved_divine_smite:
                active_notes.append("Improved Divine Smite +1d8 Radiant")
            if aura_of_hate:
                active_notes.append(f"Aura of Hate {modifiers['Charisma']:+d} weapon damage")
            note = f" Includes {', '.join(active_notes)}." if active_notes else ""
            hit_detail = f" {expression}{flat:+d} using {ability}. Damage type: {', '.join(weapon_types) or row.get('damage_type', 'Weapon')}.{note}"
            components = [{"name": f"{name}: {row['item']}", "stats": per_hit, "detail": hit_detail} for _ in range(attacks_per_action)]
            candidate = {"name": f"{name} ×{attacks_per_action}: {row['item']}", "stats": stats, "detail": f" {expression}{flat:+d} per hit using {ability}. Damage type: {', '.join(weapon_types) or row.get('damage_type', 'Weapon')}.{note}", "components": components}
            action_candidates.append(candidate)
            attack_data = {"row": row, "per_hit": per_hit, "candidate": candidate, "ability": ability}
            weapon_attacks.append(attack_data)
            if row["category"] == "ranged":
                ranged_attack = attack_data
            else:
                melee_attack = attack_data

    # Divine Smite is a per-hit rider, so Extra Attack can spend a separate
    # spell slot on each successful melee strike in the same Attack action.
    if limited and counts.get("Paladin", 0) >= 2 and melee_attack and spell_slot_inventory:
        smite_slots = spell_slot_inventory[:attacks_per_action]
        components, divine_total = [], (0.0, 0.0, 0.0)
        base_components = melee_attack["candidate"].get("components", [])
        for attack_index in range(attacks_per_action):
            base_component = dict(base_components[attack_index])
            if attack_index < len(smite_slots):
                slot_level = smite_slots[attack_index]
                dice_count = min(5, slot_level + 1)
                smite_expression = f"{dice_count}d8"
                if "Fiend or Undead" in (target_conditions or []):
                    smite_expression += "; 1d8"
                smite_stats = damage_expression_stats(smite_expression)
                base_component["stats"] = add_damage_stats(base_component["stats"], smite_stats)
                base_component["name"] = f"Divine Smite (level {slot_level}): {melee_attack['row']['item']}"
                base_component["detail"] += f" Divine Smite adds {smite_expression} Radiant and consumes one level {slot_level} spell slot on hit."
            components.append(base_component)
            divine_total = add_damage_stats(divine_total, base_component["stats"])
        action_candidates.append({
            "name": f"Divine Smite ×{len(smite_slots)}: {melee_attack['row']['item']}",
            "stats": divine_total,
            "detail": f"Applies Divine Smite separately to {len(smite_slots)} melee hit{'s' if len(smite_slots) != 1 else ''} and uses {len(smite_slots)} spell slot{'s' if len(smite_slots) != 1 else ''}.",
            "components": components,
            "max_per_turn": 1,
        })

    # Throwing is its own weapon attack mode. It uses Strength unless the
    # thrown weapon is Finesse (or a Monk weapon), and receives modifiers that
    # explicitly apply to thrown attacks.
    equipped_rows = [EQUIPMENT_BY_ID.get(value) for value in (
        melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, headwear_id,
        armour_id, handwear_id, footwear_id, cape_id, necklace_id, ring_1_id, ring_2_id,
    ) if value]
    equipped_names = {row["item"] for row in equipped_rows if row}
    throwing_boosts = []
    if "Ring of Flinging" in equipped_names:
        throwing_boosts.append(("1d4", "Ring of Flinging"))
    if "Gloves of Uninhibited Kushigo" in equipped_names:
        throwing_boosts.append(("1d4", "Gloves of Uninhibited Kushigo"))
    tavern_brawler = "Tavern Brawler" in (feat_values or [])
    seen_throwables = set()
    for row, slot in ((melee_main, "melee main"),):
        if not row or row["equipment_id"] in seen_throwables:
            continue
        naturally_thrown = has_thrown_property(row)
        cleaver_thrown = "Elemental Cleaver" in active_features and "Rage" in active_features and slot == "melee main"
        seen_throwables.add(row["equipment_id"])
        if cleaver_thrown and not naturally_thrown:
            row = {**row, "shared_properties": row.get("shared_properties", "") + "; Thrown"}
        else:
            row = throwing_attack_row(row)
        per_hit, expression, ability, flat = weapon_damage_stats(
            row, modifiers, styles, slot, True, monk_level, active_features,
            counts.get("Barbarian", 0), thrown=True,
        )
        notes = []
        for bonus_expression, source in throwing_boosts:
            per_hit = add_damage_stats(per_hit, damage_expression_stats(bonus_expression))
            notes.append(f"{source} +{bonus_expression}")
        if tavern_brawler:
            per_hit = tuple(value + modifiers["Strength"] for value in per_hit)
            notes.append(f"Tavern Brawler {modifiers['Strength']:+d}")
        if "Legacy of the Masters" in equipped_names:
            per_hit = tuple(value + 2 for value in per_hit)
            notes.append("Legacy of the Masters +2")
        if "Helldusk Gloves" in equipped_names:
            per_hit = add_damage_stats(per_hit, damage_expression_stats("1d6"))
            notes.append("Helldusk Gloves +1d6 Fire")
        elif "Flawed Helldusk Gloves" in equipped_names:
            per_hit = add_damage_stats(per_hit, damage_expression_stats("1d4"))
            notes.append("Flawed Helldusk Gloves +1d4 Fire")
        if "Horns of the Berserker" in equipped_names and "Below 50% HP" in (attacker_conditions or []):
            per_hit = tuple(value + 2 for value in per_hit)
            notes.append("Horns of the Berserker +2 Necrotic")
        if "Hunter's Marked" in (target_conditions or []):
            per_hit = add_damage_stats(per_hit, damage_expression_stats("1d6"))
            notes.append("Hunter's Mark +1d6 Weapon")
        if row["item"] == "Nyrulna":
            per_hit = add_damage_stats(per_hit, damage_expression_stats("3d4"))
            notes.append("Zephyr Connection +3d4 Thunder to the target-area explosion")
        if row["item"] == "Dwarven Thrower" and "Dwarf" in f"{race or ''} {subrace or ''}":
            per_hit = add_damage_stats(per_hit, damage_expression_stats("1d8"))
            notes.append("Dwarven Thrower +1d8 Bludgeoning for a dwarf")
        if row["item"] == "Dwarven Thrower" and "Large or Larger" in (target_conditions or []):
            per_hit = add_damage_stats(per_hit, damage_expression_stats("2d8"))
            notes.append("Dwarven Thrower +2d8 Bludgeoning against a Large or larger target")
        if "Hexblade's Curse" in active_features:
            curse_bonus = 4 if level >= 9 else 3 if level >= 5 else 2
            per_hit = tuple(value + curse_bonus for value in per_hit)
            notes.append(f"Hexblade's Curse +{curse_bonus}")
        cleaver_active = cleaver_thrown and elemental_cleaver_type
        if cleaver_active:
            cleaver_stats = damage_expression_stats("1d6")
            if "Wet" in (target_conditions or []) and elemental_cleaver_type in {"Cold", "Lightning"}:
                cleaver_stats = tuple(value * 2 for value in cleaver_stats)
            per_hit = add_damage_stats(per_hit, cleaver_stats)
            notes.append(f"Elemental Cleaver +1d6 {elemental_cleaver_type}")
        stats = tuple(value * attacks_per_action for value in per_hit)
        damage_types = damage_types_in(row.get("damage_type", ""))
        if row["item"] == "Nyrulna":
            damage_types.append("Thunder")
        detail = f" {expression}{flat:+d} per hit using {ability}. Damage type: {', '.join(dict.fromkeys(damage_types)) or 'Weapon'}."
        if notes:
            detail += f" Includes {', '.join(notes)}."
        components = [{"name": f"Throwing Attack: {row['item']}", "stats": per_hit, "detail": detail} for _ in range(attacks_per_action)]
        candidate = {
            "name": f"Throwing Attack ×{attacks_per_action}: {row['item']}",
            "stats": stats, "detail": detail, "components": components,
        }
        action_candidates.append(candidate)

    rogue_level = counts.get("Rogue", 0)
    sneak_general = "Sneak Attack" in active_features or bool({"Advantage", "Hidden", "Invisible"} & set(attacker_conditions or [])) or bool({"Threatened by Ally", "Restrained"} & set(target_conditions or []))
    sneak_context = sneak_general or "Prone" in (target_conditions or [])
    if rogue_level and sneak_context:
        sneak_expression = f"{(rogue_level + 1) // 2}d6"
        sneak_stats = damage_expression_stats(sneak_expression)
        for attack in weapon_attacks:
            row = attack["row"]
            if row["category"] != "ranged" and "finesse" not in row.get("shared_properties", "").lower():
                continue
            if not sneak_general and row["category"] == "ranged":
                continue
            base = attack["candidate"]
            components = [dict(component) for component in base.get("components", [])]
            if components:
                components[0]["stats"] = add_damage_stats(components[0]["stats"], sneak_stats)
                components[0]["name"] = f"Sneak Attack: {components[0]['name']}"
                components[0]["detail"] += f" Sneak Attack adds {sneak_expression} once this turn."
            action_candidates.append({
                **base,
                "name": f"Sneak Attack ({sneak_expression}): {base['name']}",
                "stats": add_damage_stats(base["stats"], sneak_stats),
                "detail": base["detail"] + f" Sneak Attack adds {sneak_expression} once this turn.",
                "components": components,
                "max_per_turn": 1,
            })
    unarmed_ability = "Dexterity" if monk_level and modifiers["Dexterity"] > modifiers["Strength"] else "Strength"
    unarmed_die = CLASS_PROGRESSIONS["Monk"][monk_level - 1].get("martial_arts", "1") if monk_level else "1"
    unarmed_base = damage_expression_stats(unarmed_die)
    unarmed_base = tuple(value + modifiers[unarmed_ability] for value in unarmed_base)
    if "Rage" in active_features:
        rage_bonus = 3 if counts.get("Barbarian", 0) >= 9 else 2
        unarmed_base = tuple(value + rage_bonus for value in unarmed_base)
    if "Hexblade's Curse" in active_features:
        curse_bonus = 4 if level >= 9 else 3 if level >= 5 else 2
        unarmed_base = tuple(value + curse_bonus for value in unarmed_base)
    unarmed_action = tuple(value * attacks_per_action for value in unarmed_base)
    unarmed_detail = f" {unarmed_die}{modifiers[unarmed_ability]:+d} using {unarmed_ability}. Damage type: Bludgeoning."
    action_candidates.append({"name": f"Unarmed Attack ×{attacks_per_action}", "stats": unarmed_action, "detail": f" {unarmed_die}{modifiers[unarmed_ability]:+d} per hit using {unarmed_ability}.", "components": [{"name": "Unarmed Attack", "stats": unarmed_base, "detail": unarmed_detail} for _ in range(attacks_per_action)]})

    for name, row, slot in [("Off-Hand Melee", melee_off, "melee off"), ("Off-Hand Ranged", ranged_off, "ranged off")]:
        if row and row["category"] in {"melee", "ranged"}:
            stats, expression, ability, flat = weapon_damage_stats(row, modifiers, styles, slot, True, monk_level, active_features, counts.get("Barbarian", 0))
            if counts.get("Paladin", 0) >= 11 and row["category"] == "melee":
                stats = add_damage_stats(stats, damage_expression_stats("1d8"))
            if counts.get("Paladin", 0) >= 7 and ("Paladin", "Oathbreaker") in selected_subclasses and row["category"] == "melee":
                stats = tuple(value + modifiers["Charisma"] for value in stats)
            if "Elemental Cleaver" in active_features and "Rage" in active_features and elemental_cleaver_type:
                cleaver_stats = damage_expression_stats("1d6")
                if "Wet" in (target_conditions or []) and elemental_cleaver_type in {"Cold", "Lightning"}:
                    cleaver_stats = tuple(value * 2 for value in cleaver_stats)
                stats = add_damage_stats(stats, cleaver_stats)
            if "Hexblade's Curse" in active_features:
                stats = tuple(value + (4 if level >= 9 else 3 if level >= 5 else 2) for value in stats)
            weapon_types = damage_types_in(row.get("damage_type", ""))
            bonus_candidates.append({"name": f"{name}: {row['item']}", "stats": stats, "detail": f" {expression}{flat:+d} using {ability}. Damage type: {', '.join(weapon_types) or row.get('damage_type', 'Weapon')}."})
    if monk_level:
        bonus_candidates.append({"name": "Martial Arts: Bonus Unarmed Strike", "stats": unarmed_base, "detail": f" {unarmed_die}{modifiers[unarmed_ability]:+d}."})
        if limited:
            flurry = tuple(value * 2 for value in unarmed_base)
            bonus_candidates.append({"name": "Flurry of Blows", "stats": flurry, "detail": " Costs 1 Ki Point; two unarmed strikes."})

    selections = {}
    for values, item_id in zip(spell_values or [], spell_ids or []):
        selections.setdefault(item_id["kind"], []).extend(values or [])
    equipped_ids = [melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, headwear_id, armour_id,
                    handwear_id, footwear_id, cape_id, necklace_id, ring_1_id, ring_2_id]
    equipment_spell_grants = equipment_granted_spells(equipped_ids)
    equipment_spell_sources = {
        spell: [item for item, spells in equipment_spell_grants.items() if spell in spells]
        for spell in {spell for spells in equipment_spell_grants.values() for spell in spells}
    }
    equipment_spell_names = list(equipment_spell_sources)
    star_map_guiding_bolt = counts.get("Druid", 0) >= 2 and ("Druid", "Circle of the Stars") in selected_subclasses
    spell_names = list(dict.fromkeys(
        selections.get("cantrips", [])
        + (selections.get("known", []) + selections.get("prepared", []) if limited else [])
        + equipment_spell_names
        + (["Guiding Bolt"] if limited and star_map_guiding_bolt else [])
    ))
    cantrip_scale = 3 if level >= 10 else 2 if level >= 5 else 1

    def add_spell_candidate(candidate, spell_row, is_cantrip, twin_eligible=True):
        destination = bonus_candidates if "bonus action" in spell_row["cast_time"].lower() else action_candidates
        destination.append(candidate)
        if not limited:
            return
        if "Quickened Spell" in active_features and spell_row["cast_time"].strip().lower() == "action":
            bonus_candidates.append({
                **candidate,
                "name": f"Quickened Spell: {candidate['name']}",
                "detail": candidate["detail"] + " Quickened Spell costs 3 Sorcery Points and changes this to a Bonus Action.",
            })
        if "Twinned Spell" in active_features and twin_eligible:
            spell_level = 1 if is_cantrip else max(1, formula_base(spell_row["level"]))
            twinned = {
                **candidate,
                "name": f"Twinned Spell: {candidate['name']}",
                "stats": tuple(value * 2 for value in candidate["stats"]),
                "detail": candidate["detail"] + f" Twinned Spell targets two creatures and costs {spell_level} Sorcery Point{'s' if spell_level != 1 else ''}; displayed damage is the total across both targets.",
            }
            destination.append(twinned)

    for spell_name in spell_names:
        if "Rage" in active_features:
            continue
        row = next((item for item in SPELLS if item["spell"] == spell_name), None)
        if not row or row["damage_effect"] in {"", "-"}:
            continue
        is_cantrip = row["level"] == "C"
        is_equipment_spell = spell_name in equipment_spell_sources
        if not is_cantrip and not limited:
            continue
        spell_resource_text = (
            f"Granted by {', '.join(equipment_spell_sources[spell_name])}; uses the item's recharge."
            if is_equipment_spell else "Uses a spell slot." if not is_cantrip else "Cantrip; unlimited use."
        )
        if spell_name == "Guiding Bolt" and star_map_guiding_bolt:
            star_map_uses = 4 if level >= 9 else 3 if level >= 5 else 2
            spell_resource_text = f"Uses one of {star_map_uses} Star Map charges per Long Rest instead of a spell slot."
        damage_types = damage_types_in(row["damage_effect"])

        if spell_name == "Booming Blade":
            if not melee_attack:
                continue
            immediate_dice = "2d8" if level >= 11 else "1d8" if level >= 5 else ""
            movement_dice = "3d8" if level >= 11 else "2d8" if level >= 5 else "1d8"
            stats = melee_attack["candidate"]["stats"]
            if immediate_dice:
                stats = add_damage_stats(stats, damage_expression_stats(immediate_dice))
            movement_applies = "Will Move" in (target_conditions or [])
            if movement_applies:
                stats = add_damage_stats(stats, damage_expression_stats(movement_dice))
            detail = f" Unlimited cantrip: {melee_attack['row']['damage']} {melee_attack['row'].get('damage_type', '')} weapon damage"
            detail += f" plus {immediate_dice} Thunder immediately" if immediate_dice else "; no immediate Thunder die before level 5"
            detail += f" plus {movement_dice} Thunder because Will Move is selected." if movement_applies else f". Conditional {movement_dice} Thunder on movement is not counted."
            remaining_attacks = max(0, attacks_per_action - 1)
            name = f"Booming Blade: {melee_attack['row']['item']}"
            if remaining_attacks:
                name += f" + {remaining_attacks} additional melee attack{'s' if remaining_attacks != 1 else ''}"
                detail += f" Booming Blade replaces one attack; Extra Attack supplies {remaining_attacks} normal weapon attack{'s' if remaining_attacks != 1 else ''}."
            booming_stats = melee_attack["per_hit"]
            if immediate_dice:
                booming_stats = add_damage_stats(booming_stats, damage_expression_stats(immediate_dice))
            if movement_applies:
                booming_stats = add_damage_stats(booming_stats, damage_expression_stats(movement_dice))
            components = [{"name": f"Booming Blade: {melee_attack['row']['item']}", "stats": booming_stats, "detail": detail}]
            extra_attack_detail = melee_attack["candidate"]["components"][0]["detail"] + " Extra Attack granted by the same Action."
            components.extend({"name": f"Melee Attack: {melee_attack['row']['item']}", "stats": melee_attack["per_hit"], "detail": extra_attack_detail} for _ in range(remaining_attacks))
            booming_candidate = {"name": name, "stats": stats, "detail": detail, "max_per_turn": 1, "components": components}
            action_candidates.append(booming_candidate)
            if limited and "Quickened Spell" in active_features:
                quickened_stats = booming_stats
                bonus_candidates.append({
                    "name": f"Quickened Spell: Booming Blade: {melee_attack['row']['item']}", "stats": quickened_stats,
                    "detail": detail + " As a Bonus Action it makes one weapon attack and costs 3 Sorcery Points.",
                    "max_per_turn": 1,
                })
            continue

        if "normal weapon damage" in row["damage_effect"].lower():
            if spell_name in {"Searing Smite", "Thunderous Smite", "Wrathful Smite", "Blinding Smite"}:
                attack = melee_attack
            elif spell_name == "Branding Smite":
                available = [item for item in (melee_attack, ranged_attack) if item]
                attack = max(available, key=lambda item: item["per_hit"][2]) if available else None
            elif spell_name == "Hail of Thorns":
                attack = ranged_attack
            else:
                available = [item for item in (melee_attack, ranged_attack) if item]
                attack = max(available, key=lambda item: item["per_hit"][2]) if available else None
            if not attack:
                continue
            smite_spells = {"Searing Smite", "Thunderous Smite", "Wrathful Smite", "Branding Smite", "Blinding Smite"}
            required_slot = max(1, formula_base(row["level"]))
            usable_slots = [slot for slot in spell_slot_inventory if slot >= required_slot]
            if spell_name in smite_spells and not usable_slots and not is_equipment_spell:
                continue
            cast_slot = required_slot if is_equipment_spell else usable_slots[0] if usable_slots else required_slot
            immediate_dice = {
                "Ensnaring Strike": "", "Hail of Thorns": "1d10",
                "Searing Smite": f"{cast_slot}d6",
                "Thunderous Smite": "2d6", "Wrathful Smite": "1d6",
                "Branding Smite": f"{cast_slot}d6",
                "Blinding Smite": f"{cast_slot}d8", "Conjure Barrage": "2d8",
            }.get(spell_name, "")
            bonus_stats = damage_expression_stats(immediate_dice)
            stats = add_damage_stats(attack["candidate"]["stats"], bonus_stats) if spell_name in smite_spells else add_damage_stats(attack["per_hit"], bonus_stats)
            types = list(dict.fromkeys(damage_types_in(attack["row"].get("damage_type", "")) + damage_types))
            components = None
            if spell_name in smite_spells:
                components = [dict(component) for component in attack["candidate"].get("components", [])]
                if components:
                    components[0]["stats"] = add_damage_stats(components[0]["stats"], bonus_stats)
                    components[0]["name"] = f"{spell_name}: {attack['row']['item']}"
                    smite_resource = "the granting item's use" if is_equipment_spell else f"one level {cast_slot} spell slot"
                    components[0]["detail"] += f" {spell_name} adds {immediate_dice} and consumes {smite_resource} plus one Bonus Action on hit. {row.get('description', '')}"

                    # A Paladin can also trigger Divine Smite on the same hit as
                    # a smite spell and again on the Extra Attack hit. Allocate
                    # the named spell's slot first, then use the best remaining
                    # slots for those independent on-hit reactions.
                    remaining_slots = list(spell_slot_inventory)
                    if not is_equipment_spell and cast_slot in remaining_slots:
                        remaining_slots.remove(cast_slot)
                    if limited and counts.get("Paladin", 0) >= 2 and attack is melee_attack:
                        for component_index, divine_slot in enumerate(remaining_slots[:len(components)]):
                            divine_dice = min(5, divine_slot + 1)
                            divine_expression = f"{divine_dice}d8"
                            if "Fiend or Undead" in (target_conditions or []):
                                divine_expression += "; 1d8"
                            divine_stats = damage_expression_stats(divine_expression)
                            components[component_index]["stats"] = add_damage_stats(components[component_index]["stats"], divine_stats)
                            components[component_index]["name"] = f"{components[component_index]['name']} + Divine Smite (level {divine_slot})"
                            components[component_index]["detail"] += f" Divine Smite adds {divine_expression} Radiant and consumes one level {divine_slot} spell slot on hit."
                        stats = (0.0, 0.0, 0.0)
                        for component in components:
                            stats = add_damage_stats(stats, component["stats"])
            candidate = {
                "name": f"{spell_name}: {attack['row']['item']}", "stats": stats,
                "detail": f" {attack['row']['damage']} weapon damage" + (f" plus {immediate_dice}." if immediate_dice else ". Ongoing conditional damage is not counted.") + f" Damage types: {', '.join(types) or 'Weapon'}. {row.get('description', '')} {spell_resource_text}",
            }
            if components:
                candidate.update({"components": components, "uses_bonus_action": True, "max_per_turn": 1})
            if spell_name in smite_spells:
                # Smite spells make a weapon attack as the character's Action
                # and also consume a Bonus Action. They are not standalone
                # bonus-action damage and cannot be Quickened or Twinned.
                action_candidates.append(candidate)
            else:
                add_spell_candidate(candidate, row, is_cantrip, twin_eligible=False)
            continue

        stats = damage_expression_stats(row["damage_effect"], cantrip_scale if is_cantrip else 1)
        if "Hexblade's Curse" in active_features:
            curse_bonus = 4 if level >= 9 else 3 if level >= 5 else 2
            damage_rolls = cantrip_scale if is_cantrip else 1
            stats = tuple(value + curse_bonus * damage_rolls for value in stats)
        if not stats[1]:
            continue
        if "Wet" in (target_conditions or []) and any(kind in row["damage_effect"] for kind in ("Cold", "Lightning")):
            stats = tuple(value * 2 for value in stats)
        type_text = f" Damage type: {', '.join(damage_types)}." if damage_types else ""
        resource_text = f" {spell_resource_text}"
        candidate = {"name": spell_name, "stats": stats, "detail": f" {row['damage_effect']}.{type_text}{resource_text}"}
        area_text = f"{row.get('range_area', '')} {row.get('description', '')}".lower()
        twin_eligible = not any(term in area_text for term in ("radius", "cone", " line", "surface", "surrounding", "all creatures", "each creature", "self"))
        add_spell_candidate(candidate, row, is_cantrip, twin_eligible)

    # An Arcane Shot modifies one arrow within the Attack action; any remaining
    # attacks granted by Extra Attack still deal their normal weapon damage.
    selected_arcane_shots = [value for value in selected_choices if value in ARCANE_SHOTS]
    if limited and ranged_attack:
        for shot in selected_arcane_shots:
            description = ARCANE_SHOT_DESCRIPTIONS[shot]
            bonus_match = re.search(r"(?:plus|\+)\s*(\d+d\d+)", description, re.IGNORECASE)
            bonus_expression = bonus_match.group(1) if bonus_match else ""
            bonus_stats = damage_expression_stats(bonus_expression)
            stats = add_damage_stats(ranged_attack["candidate"]["stats"], bonus_stats)
            weapon_type = ranged_attack["row"].get("damage_type", "Weapon")
            shot_types = damage_types_in(description)
            detail = f" One Arcane Arrow; {ranged_attack['row']['damage']} {weapon_type} weapon damage"
            detail += f" plus {bonus_expression}." if bonus_expression else "; no additional initial damage die."
            detail += f" Damage types: {', '.join(list(dict.fromkeys(damage_types_in(weapon_type) + shot_types))) or 'Weapon'}."
            shot_stats = add_damage_stats(ranged_attack["per_hit"], bonus_stats)
            components = [{"name": f"{shot}: {ranged_attack['row']['item']}", "stats": shot_stats, "detail": detail}]
            extra_attack_detail = ranged_attack["candidate"]["components"][0]["detail"] + " Extra Attack granted by the same Action."
            components.extend({"name": f"Ranged Attack: {ranged_attack['row']['item']}", "stats": ranged_attack["per_hit"], "detail": extra_attack_detail} for _ in range(max(0, attacks_per_action - 1)))
            action_candidates.append({"name": f"{shot}: {ranged_attack['row']['item']}", "stats": stats, "detail": detail, "components": components})

    if limited and any(value in MANOEUVRES for value in selected_choices) and action_candidates:
        die = "1d10" if counts.get("Fighter", 0) >= 10 else "1d8"
        best_weapon = max(action_candidates, key=lambda item: item["stats"][2])
        manoeuvre = next(value for value in selected_choices if value in MANOEUVRES)
        action_candidates.append({"name": f"{best_weapon['name']} + {manoeuvre}", "stats": add_damage_stats(best_weapon["stats"], damage_expression_stats(die)), "detail": f" Costs 1 Superiority Die ({die})."})

    if wild_shape and wild_shape in WILD_SHAPE_FORMS:
        form = WILD_SHAPE_FORMS[wild_shape]
        druid_level = counts.get("Druid", 0)
        moon_druid = ("Druid", "Circle of the Moon") in selected_subclasses
        form_available = druid_level >= form["level"] and (not form.get("moon") or moon_druid)
        if form_available:
            # A selected form represents a turn that begins already transformed.
            # Wild Strike and martial Extra Attack can stack to three attacks.
            wild_strikes = 3 if druid_level >= 10 else 2 if druid_level >= 5 else 1
            if attacks_per_action > 1 and druid_level >= 5:
                wild_strikes = max(wild_strikes, 3)
            strength_modifier = (WILD_SHAPE_STRENGTH[wild_shape] - 10) // 2
            improvement_die = None
            if not form.get("myrmidon") and druid_level >= 4:
                smaller_die = wild_shape in {"Cat", "Bear", "Dire Raven", "Panther", "Owlbear"}
                improvement_die = (
                    "1d8" if smaller_die and druid_level >= 12 else
                    "1d6" if smaller_die and druid_level >= 8 else
                    "1d4" if smaller_die else
                    "1d10" if druid_level >= 12 else
                    "1d8" if druid_level >= 8 else "1d6"
                )

            def wild_shape_candidate(action_name, expression, damage_type, attack_count=1):
                per_hit = damage_expression_stats(expression)
                notes = []
                if improvement_die:
                    per_hit = add_damage_stats(per_hit, damage_expression_stats(improvement_die))
                    notes.append(f"Wild Shape Improvement +{improvement_die}")
                if "Tavern Brawler" in (feat_values or []) and not form.get("myrmidon"):
                    per_hit = tuple(value + strength_modifier for value in per_hit)
                    notes.append(f"Tavern Brawler {strength_modifier:+d}")
                detail = f" {expression} {damage_type} per hit in {wild_shape} form."
                if action_name in {"Pounce", "Crushing Flight", "Charge"}:
                    detail += " May knock the target Prone."
                elif action_name == "Rend Vision":
                    detail += " May Blind the target."
                elif action_name == "Corrosive Spit":
                    detail += " Reduces the target's Armour Class on a failed Constitution save."
                elif action_name == "Scorching Strike":
                    detail += " May inflict Burning."
                if notes:
                    detail += f" Includes {', '.join(notes)}."
                components = [{
                    "name": f"{wild_shape} — {action_name}", "stats": per_hit, "detail": detail,
                } for _ in range(attack_count)]
                return {
                    "name": f"{wild_shape} — {action_name}" + (f" ×{attack_count}" if attack_count > 1 else ""),
                    "stats": tuple(value * attack_count for value in per_hit),
                    "detail": detail, "components": components,
                }

            action_candidates = [
                wild_shape_candidate(name, expression, damage_type, wild_strikes)
                for name, expression, damage_type in form.get("actions", [])
            ]
            bonus_candidates = [
                wild_shape_candidate(name, expression, damage_type)
                for name, expression, damage_type in form.get("bonus", [])
            ]

    stars_druid = counts.get("Druid", 0) >= 2 and ("Druid", "Circle of the Stars") in selected_subclasses
    if limited and stars_druid and not wild_shape:
        druid_level = counts.get("Druid", 0)
        wisdom_modifier = modifiers["Wisdom"]
        archer_expression = "2d8" if druid_level >= 10 else "1d8"
        archer_stats = tuple(value + wisdom_modifier for value in damage_expression_stats(archer_expression))
        bonus_candidates.append({
            "name": "Starry Form: Archer — Luminous Arrow",
            "stats": archer_stats,
            "detail": f" {archer_expression}{wisdom_modifier:+d} Radiant using Wisdom. Bonus Action; requires Archer form and a Wild Shape Charge to enter the form.",
        })
        dragon_expression = "4d6" if druid_level >= 10 else "3d6" if druid_level >= 5 else "2d6"
        dragon_stats = tuple(value + wisdom_modifier for value in damage_expression_stats(dragon_expression))
        bonus_candidates.append({
            "name": "Starry Form: Dragon — Dazzling Breath",
            "stats": dragon_stats,
            "detail": f" {dragon_expression}{wisdom_modifier:+d} Radiant in a 5 m cone using Wisdom. Bonus Action; Dexterity save for half damage. Requires Dragon form and a Wild Shape Charge to enter the form.",
        })

    best_bonus = max(bonus_candidates, key=lambda item: item["stats"][2]) if bonus_candidates else None
    sequence, total = [], (0.0, 0.0, 0.0)
    action_uses = Counter()
    spent_bonus_actions = 0
    for index in range(actions):
        eligible = [item for item in action_candidates if action_uses[item["name"]] < item.get("max_per_turn", actions)]
        if not eligible:
            break
        best_action = max(eligible, key=lambda item: item["stats"][2])
        action_uses[best_action["name"]] += 1
        if best_action.get("uses_bonus_action"):
            spent_bonus_actions += 1
        components = best_action.get("components") or [{"name": best_action["name"], "stats": best_action["stats"], "detail": best_action["detail"]}]
        for component_index, component in enumerate(components):
            suffix = chr(ord("a") + component_index) if len(components) > 1 else ""
            component_stats = component["stats"]
            sequence.append({"name": f"Action {index + 1}{suffix}: {component['name']}", "min": component_stats[0], "max": component_stats[1], "mean": component_stats[2], "detail": component["detail"]})
            total = add_damage_stats(total, component_stats)
    if best_bonus and "Booming Blade" in best_bonus["name"] and any("Booming Blade" in step["name"] for step in sequence):
        alternatives = [item for item in bonus_candidates if "Booming Blade" not in item["name"]]
        best_bonus = max(alternatives, key=lambda item: item["stats"][2]) if alternatives else None
    if best_bonus:
        for index in range(max(0, bonus_actions - spent_bonus_actions)):
            sequence.append({"name": f"Bonus Action {index + 1}: {best_bonus['name']}", "min": best_bonus["stats"][0], "max": best_bonus["stats"][1], "mean": best_bonus["stats"][2], "detail": best_bonus["detail"]})
            total = add_damage_stats(total, best_bonus["stats"])

    equipped_rows = [] if wild_shape else [EQUIPMENT_BY_ID.get(equipment_id) for equipment_id in equipped_ids if equipment_id]
    total, equipment_conditions = apply_charge_and_reverberation_effects(sequence, equipped_rows, lightning_charges)

    def candidate_steps(candidate, prefix):
        components = candidate.get("components") or [{"name": candidate["name"], "stats": candidate["stats"], "detail": candidate.get("detail", "")}]
        return [{
            "name": f"{prefix}{chr(ord('a') + index) if len(components) > 1 else ''}: {component['name']}",
            "min": component["stats"][0], "max": component["stats"][1], "mean": component["stats"][2],
            "detail": component.get("detail", ""),
        } for index, component in enumerate(components)]

    crit_sequence = []
    crit_action_uses = Counter()
    crit_spent_bonus_actions = 0
    for index in range(actions):
        eligible = [item for item in action_candidates if crit_action_uses[item["name"]] < item.get("max_per_turn", actions)]
        if not eligible:
            break
        best = max(eligible, key=lambda item: (sum(optimizer_attack_count(c.get("name", item["name"]), c.get("detail", item.get("detail", "")), cantrip_scale) for c in (item.get("components") or [item])), item["stats"][2]))
        crit_action_uses[best["name"]] += 1
        if best.get("uses_bonus_action"):
            crit_spent_bonus_actions += 1
        crit_sequence.extend(candidate_steps(best, f"Action {index + 1}"))
    if bonus_candidates:
        best_crit_bonus = max(bonus_candidates, key=lambda item: (optimizer_attack_count(item["name"], item.get("detail", ""), cantrip_scale), item["stats"][2]))
        for index in range(max(0, bonus_actions - crit_spent_bonus_actions)):
            crit_sequence.extend(candidate_steps(best_crit_bonus, f"Bonus Action {index + 1}"))

    crit_sources, crit_riders = [], []
    threshold = 20
    if "Improved Critical Hit" in features:
        threshold -= 1; crit_sources.append("Champion: Improved Critical Hit")
    if "Hexblade's Curse" in active_features:
        threshold -= 1; crit_sources.append("Hexblade's Curse")
    item_names = {row["item"] for row in equipped_rows if row}
    for row in equipped_rows:
        special = row.get("special", "")
        if re.search(r"number you need to roll (?:a )?Critical Hit.*reduced by (?:1|one)|reduce the number you need to roll a Critical Hit.*by 1", special, re.IGNORECASE):
            conditional = "while obscured" in special.lower() or "while hiding" in special.lower()
            active = not conditional or visibility in {"Lightly Obscured", "Heavily Obscured"} or bool({"Hidden", "Invisible"} & set(attacker_conditions or []))
            if active:
                threshold -= 1; crit_sources.append(row["item"])
    if "Unseen Menace" in item_names:
        threshold = min(threshold, 19); crit_sources.append("Unseen Menace (its attacks)")
    if "Duellist's Prerogative" in item_names and not melee_off_id:
        threshold = min(threshold, 19); crit_sources.append("Duellist's Prerogative (empty off-hand)")
    spell_sniper = "Spell Sniper" in (feat_values or [])
    if spell_sniper:
        crit_sources.append("Spell Sniper (spell attacks only)")
    advantage = bool({"Advantage", "Hidden", "Invisible"} & set(attacker_conditions or [])) or bool({"Prone", "Restrained"} & set(target_conditions or []))
    savage_critical = race == "Half-Orc"
    brutal_critical = "Brutal Critical" in features
    if savage_critical: crit_riders.append("Savage Attacks (+1 weapon die)")
    if brutal_critical: crit_riders.append("Brutal Critical (+1 weapon die)")
    if "Craterflesh Gloves" in item_names: crit_riders.append("Craterflesh Gloves (+1d6 Force)")
    if item_names & {"Dolor Amarus", "Vicious Battleaxe", "Vicious Shortbow"}: crit_riders.append("Dolor Amarus (+7)")
    if "Sword of Life Stealing" in item_names: crit_riders.append("Life Stealing Critical (+10 Necrotic)")

    def annotate_crit_steps(steps):
        for step in steps:
            count = optimizer_attack_count(step["name"], step.get("detail", ""), cantrip_scale)
            step["attack_count"] = count
            spell_attack = next((row for row in SPELLS if row["spell"] in step["name"] and "attack roll" in row.get("attack_save", "").lower()), None)
            step_threshold = max(2, threshold - (1 if spell_sniper and spell_attack else 0))
            step["crit_chance"] = critical_probability(step_threshold, advantage)
            bonus = critical_dice_bonus(step.get("detail", "")) if count else (0, 0, 0)
            if count and (savage_critical or brutal_critical) and any(term in step["name"] for term in ("Attack", "Unarmed", "Blade", "Smite", "Strike")):
                first_die = re.search(r"\b\d+d\d+\b", step.get("detail", ""))
                if first_die:
                    extra = damage_expression_stats(first_die.group())
                    multiplier = int(savage_critical) + int(brutal_critical)
                    bonus = add_damage_stats(bonus, tuple(value * multiplier for value in extra))
            if count and "Craterflesh Gloves" in item_names:
                bonus = add_damage_stats(bonus, damage_expression_stats("1d6"))
            if count and item_names & {"Dolor Amarus", "Vicious Battleaxe", "Vicious Shortbow"}:
                bonus = tuple(value + 7 for value in bonus)
            if count and "Sword of Life Stealing" in step["name"]:
                bonus = tuple(value + 10 for value in bonus)
            step["crit_bonus"] = bonus
        return steps

    sequence = annotate_crit_steps(sequence)
    crit_sequence = annotate_crit_steps(crit_sequence)

    limitations = [
        "The base damage plan assumes every attack hits; critical-hit odds are reported separately.",
        "Enemy Armour Class, saving-throw success rates, resistances, immunities, and vulnerability are not yet included.",
        "Named smite spells are upcast for immediate damage; other spell upcasting, damage-over-time, areas hitting multiple targets, and concentration value are not yet optimized.",
        "Conditional equipment riders and most once-per-turn damage riders are not yet included.",
        "Smite spell slots are allocated within each Attack action, but limited resources are not yet decremented globally across Action Surge or repeated setup sequences.",
        "Arcane Shot delayed and area damage is excluded; only the selected target's immediate damage is counted.",
        "The current search repeats the highest-mean Action and Bonus Action; mutually exclusive setup sequences are not yet simulated.",
    ]
    mode = "Limited resources allowed" if limited else "Unlimited attacks and cantrips only"
    if active_features:
        mode += f"; active: {', '.join(sorted(active_features))}"
    inflicted_conditions = possible_conditions_for_sequence(sequence, equipped_rows, active_features)
    inflicted_conditions = list({(item["condition"], item["source"]): item for item in inflicted_conditions + equipment_conditions}.values())
    return html.Div([
        optimizer_result_card(sequence, total, limitations, mode, inflicted_conditions),
        crit_result_card(sequence, crit_sequence, max(2, threshold), advantage, crit_sources, crit_riders),
    ], className="optimizer-results-stack")


@callback(
    Output("sheet-spell-slots", "children"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "level-feat", "level": ALL}, "value"),
)
def render_spell_slots(level_classes, level_subclasses, feat_values):
    active_classes = []
    for class_name in level_classes or []:
        if not class_name:
            break
        active_classes.append(class_name)
    counts = Counter(active_classes)
    selected_subclasses = set()
    for class_name, subclass in zip(level_classes or [], level_subclasses or []):
        if class_name and subclass:
            selected_subclasses.add((class_name, subclass))

    standard_slots = []
    distinct_classes = set(active_classes)
    if len(distinct_classes) == 1:
        only_class = active_classes[0] if active_classes else None
        only_level = counts.get(only_class, 0)
        if only_class in ["Bard", "Cleric", "Druid", "Paladin", "Ranger", "Sorcerer", "Wizard"]:
            row = CLASS_PROGRESSIONS[only_class][only_level - 1]
            standard_slots = [
                (level, numeric_progression_value(row, f"spell_slots_{level}"))
                for level in range(1, 7)
                if numeric_progression_value(row, f"spell_slots_{level}")
            ]
        elif (only_class, "Eldritch Knight") in selected_subclasses or (only_class, "Arcane Trickster") in selected_subclasses:
            third_slots = (
                [2, 0] if only_level == 3 else
                [3, 0] if only_level in range(4, 7) else
                [4, 2] if only_level in range(7, 10) else
                [4, 3] if only_level >= 10 else [0, 0]
            )
            standard_slots = [(level, count) for level, count in enumerate(third_slots, 1) if count]
    else:
        full_caster_level = sum(counts.get(name, 0) for name in ["Bard", "Cleric", "Druid", "Sorcerer", "Wizard"])
        half_caster_level = counts.get("Paladin", 0) // 2 + counts.get("Ranger", 0) // 2
        third_caster_level = 0
        if ("Fighter", "Eldritch Knight") in selected_subclasses:
            third_caster_level += counts.get("Fighter", 0) // 3
        if ("Rogue", "Arcane Trickster") in selected_subclasses:
            third_caster_level += counts.get("Rogue", 0) // 3
        caster_level = min(12, full_caster_level + half_caster_level + third_caster_level)
        standard_counts = MULTICLASS_SPELL_SLOTS.get(caster_level, [0] * 6)
        standard_slots = [(level, count) for level, count in enumerate(standard_counts, 1) if count]

    pact_slots = []
    warlock_level = counts.get("Warlock", 0)
    if warlock_level:
        row = CLASS_PROGRESSIONS["Warlock"][warlock_level - 1]
        pact_slots = [
            (level, numeric_progression_value(row, f"spell_slots_{level}"))
            for level in range(1, 6)
            if numeric_progression_value(row, f"spell_slots_{level}")
        ]

    groups = []
    if standard_slots:
        groups.append(spell_slot_group("Spell Slots", standard_slots, "standard"))
    if pact_slots:
        groups.append(spell_slot_group("Pact Magic", pact_slots, "pact"))

    resource_fields = {
        "Barbarian": ("rage_charges", "Rage", "Long Rest", "Rage Charges used to enter Rage or a subclass Rage variant."),
        "Bard": ("bardic_inspirations", "Bardic Inspiration", "Long Rest", "Bardic Inspiration charges; from Bard level 5, Font of Inspiration also restores them on a Short Rest."),
        "Cleric": ("channel_divinity_charges", "Channel Divinity", "Short Rest", "Channel Divinity Charges used by domain-specific divine actions."),
        "Monk": ("ki_points", "Ki Points", "Short Rest", "Ki Points used to fuel Monk techniques."),
        "Paladin": ("lay_on_hands_charges", "Lay on Hands", "Long Rest", "Lay on Hands Charges used to heal or cure diseases and poisons."),
        "Sorcerer": ("sorcery_points", "Sorcery Points", "Long Rest", "Sorcery Points used for Metamagic and conversion between points and spell slots."),
        "Wizard": ("arcane_recovery_charges", "Arcane Recovery", "Long Rest", "Arcane Recovery Charges used outside combat to restore expended spell slots."),
    }
    resources = []
    for class_name, (field, label, recharge, description) in resource_fields.items():
        class_level = counts.get(class_name, 0)
        if not class_level:
            continue
        count = numeric_progression_value(CLASS_PROGRESSIONS[class_name][class_level - 1], field)
        if count:
            if class_name == "Bard" and class_level >= 5:
                recharge = "Short Rest"
            resources.append({"name": label, "count": count, "recharge": recharge, "description": description})

    druid_level = counts.get("Druid", 0)
    if druid_level >= 2:
        resources.append({"name": "Wild Shape", "count": 2, "recharge": "Short Rest", "description": "Wild Shape Charges fuel Wild Shape, Combat Wild Shape, Symbiotic Entity, or Starry Form. Moon Druid Myrmidon forms cost 2 charges."})
    if druid_level >= 2 and ("Druid", "Circle of the Stars") in selected_subclasses:
        star_map_charges = 4 if sum(counts.values()) >= 9 else 3 if sum(counts.values()) >= 5 else 2
        resources.append({"name": "Star Map: Guiding Bolt", "count": star_map_charges, "recharge": "Long Rest", "description": "Cast Guiding Bolt without expending a spell slot. Available uses equal the character's proficiency bonus."})
    paladin_level = counts.get("Paladin", 0)
    if paladin_level:
        resources.append({"name": "Channel Oath", "count": 1, "recharge": "Short Rest", "description": "A Paladin has one Channel Oath Charge for oath-specific actions."})
    fighter_level = counts.get("Fighter", 0)
    if fighter_level >= 3 and ("Fighter", "Battle Master") in selected_subclasses:
        count = 5 if fighter_level >= 7 else 4
        if "Martial Adept" in (feat_values or []):
            count += 1
        die = "d10" if fighter_level >= 10 else "d8"
        resources.append({"name": f"Superiority Dice ({die})", "count": count, "recharge": "Short Rest", "description": "Superiority Dice fuel selected Battle Master manoeuvres."})
    elif "Martial Adept" in (feat_values or []):
        resources.append({"name": "Superiority Die (d8)", "count": 1, "recharge": "Short Rest", "description": "The Martial Adept feat grants one Superiority Die."})
    if fighter_level >= 3 and ("Fighter", "Arcane Archer") in selected_subclasses:
        count = 10 if fighter_level >= 10 else 7 if fighter_level >= 7 else 4
        resources.append({"name": "Arcane Arrows", "count": count, "recharge": "Short Rest", "description": "Arcane Arrows are spent to fire selected Arcane Shots."})

    if resources:
        groups.append(class_resource_group(resources))
    return groups or html.P("Spell slots and class resources will appear as your levels grant them.", className="sheet-empty spell-slot-empty")


@callback(
    Output("sheet-spells", "children"),
    Input({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "value"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    Input("abilities-store", "data"), Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
    State({"type": "spell-choice", "class": ALL, "kind": ALL, "limit": ALL}, "id"),
)
def render_sheet_spells(values, level_classes, level_subclasses, class_choice_values, race, subrace, ability_data, feat_effects, equipment_effects,
                        melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, headwear_id, armour_id,
                        handwear_id, footwear_id, cape_id, necklace_id, ring_1_id, ring_2_id, ids):
    selections = {}
    for value, item_id in zip(values or [], ids or []):
        selections[(item_id["class"], item_id["kind"])] = list(value or [])[:int(item_id["limit"])]
    granted_by_class = class_granted_spells(level_classes, level_subclasses, class_choice_values)
    racial_grants = racial_granted_spells(race, subrace, len([value for value in (level_classes or []) if value]))
    if racial_grants:
        granted_by_class["Racial"] = racial_grants
    classes = list(dict.fromkeys([item_id["class"] for item_id in ids or []] + list(granted_by_class)))
    modifiers = final_ability_modifiers(ability_data, feat_effects, equipment_effects)
    character_level = len([value for value in level_classes or [] if value])
    proficiency = 4 if character_level >= 9 else 3 if character_level >= 5 else 2
    cards = []
    for class_name in classes:
        class_row = next((row for row in CLASSES if row["class"] == class_name), None)
        casting_ability = "Intelligence" if class_name in {"Fighter", "Rogue"} else spellcasting_ability_name(class_row["spellcasting_ability"]) if class_row else None
        spell_attack_bonus = proficiency + modifiers.get(casting_ability, 0) if casting_ability in modifiers else None
        cantrips = selections.get((class_name, "cantrips"), [])
        known = selections.get((class_name, "known"), [])
        prepared = selections.get((class_name, "prepared"), [])
        granted = granted_by_class.get(class_name, [])
        prepared_display = [spell for spell in prepared if class_name != "Wizard" or spell in known]
        usable_levelled = prepared_display if class_name in PREPARED_CASTERS else known
        usable = list(dict.fromkeys(cantrips + usable_levelled + granted))
        rows = []
        if granted:
            rows.append(html.Div([html.Span("Granted", className="summary-label"), html.Span(spell_tooltip_list(granted, spell_attack_bonus, casting_ability))], className="summary-row"))
        if prepared_display:
            rows.append(html.Div([html.Span("Prepared", className="summary-label"), html.Span(spell_tooltip_list(prepared_display, spell_attack_bonus, casting_ability))], className="summary-row"))
        if usable:
            rows.append(html.Div([html.Span("Usable", className="summary-label"), html.Span(spell_tooltip_list(usable, spell_attack_bonus, casting_ability))], className="summary-row"))
        if rows:
            cards.append(html.Div([html.Strong(class_name, className="sheet-spell-class"), *rows], className="sheet-spell-class-card"))
    equipment_grants = equipment_granted_spells([
        melee_main_id, melee_off_id, ranged_main_id, ranged_off_id, headwear_id, armour_id,
        handwear_id, footwear_id, cape_id, necklace_id, ring_1_id, ring_2_id,
    ])
    if equipment_grants:
        equipment_rows = [
            html.Div([
                html.Span(item, className="summary-label"),
                html.Span(spell_tooltip_list(spells, None, None)),
            ], className="summary-row")
            for item, spells in equipment_grants.items()
        ]
        cards.append(html.Div([html.Strong("Equipment", className="sheet-spell-class"), *equipment_rows], className="sheet-spell-class-card"))
    return cards or html.P("Selected spells will appear here.", className="sheet-empty")


def character_equipment_proficiencies(race, subrace, level_classes, feat_effects) -> set[str]:
    race_row = next((row for row in RACES if row["race"] == race), None)
    subrace_row = next((row for row in RACES if row["race"] == race and row["subrace"] == subrace), None)
    values = [race_row["race_proficiencies"] if race_row else "", subrace_row["subrace_proficiencies"] if subrace_row else ""]
    seen = set()
    for index, class_name in enumerate(level_classes or []):
        if not class_name:
            break
        if class_name in seen:
            continue
        row = next(item for item in CLASSES if item["class"] == class_name)
        values.append(row["equipment_proficiencies"] if index == 0 else row["multiclass_proficiencies"])
        seen.add(class_name)
    values.extend((feat_effects or {}).get("proficiencies", []))
    profs = {item.lower() for item in proficiency_items(*values)}
    for row in WEAPON_PROFICIENCIES:
        if row["proficiency"].lower() in profs:
            profs.update(value.strip().lower() for value in row["included_weapon_types"].split(";") if value.strip())
    return profs


def proficient_with_item(row: dict[str, str], profs: set[str]) -> bool:
    requirement = row.get("proficiency", "").strip()
    if row["category"] in {"melee", "ranged"}:
        return row["item_type"].lower() in profs
    if row["category"] == "shield":
        return "shields" in profs or "shield" in profs
    if not requirement or requirement.lower() in {"none", "-", "n/a"}:
        return True
    return requirement.lower() in profs or requirement.lower().replace(" proficiency", "") in profs


def static_item_ac_bonus(row: dict[str, str], slot: str) -> int:
    """Read always-on AC bonuses; conditional activated effects are left out."""
    total = 0
    for part in re.split(r";", row.get("special", "") or ""):
        lowered = part.lower()
        if not ("armour class" in lowered or "armor class" in lowered):
            continue
        if any(condition in lowered for condition in ("while ", "after ", "as long as", "until ", "when ", "increase your armour class by 2")):
            continue
        if "off-hand only" in lowered and "off" not in slot:
            continue
        patterns = [
            r"armou?r class\s*\+(\d+)",
            r"\+(\d+)\s+(?:bonus\s+)?to armou?r class",
            r"armou?r class increases by\s*\+?(\d+)",
        ]
        values = [int(match.group(1)) for pattern in patterns for match in re.finditer(pattern, lowered)]
        if values:
            total += max(values)
    return total


@callback(
    Output("sheet-ac", "children"), Output("sheet-ac", "title"),
    Input("abilities-store", "data"), Input("feat-effects-store", "data"),
    Input("equipment-effects-store", "data"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
)
def calculate_armour_class(ability_data, feat_effects, equipment_effects, class_choices, *item_ids):
    ability_data, feat_effects = ability_data or {}, feat_effects or {}
    dexterity = final_ability_scores(ability_data, feat_effects, equipment_effects)["Dexterity"]
    dexterity_bonus = ability_modifier(dexterity)
    slots = ["melee main", "melee off", "ranged main", "ranged off", "headwear", "armour", "handwear", "footwear", "cape", "necklace", "ring 1", "ring 2"]
    equipped = [(slot, EQUIPMENT_BY_ID.get(item_id)) for slot, item_id in zip(slots, item_ids) if EQUIPMENT_BY_ID.get(item_id)]

    armour_row = next((row for slot, row in equipped if slot == "armour" and row["category"] == "armour"), None)
    armour_bonus = max(0, formula_base(armour_row.get("armour_class", "")) - 10) if armour_row else 0
    shield_bonus = sum(formula_base(row.get("armour_class", "")) for slot, row in equipped if row["category"] == "shield")
    other_bonus = sum(static_item_ac_bonus(row, slot) for slot, row in equipped if row is not armour_row and row["category"] != "shield")
    selected_choices = [item for value in class_choices or [] for item in (value if isinstance(value, list) else [value]) if item]
    fighting_style_bonus = 1 if armour_row and "Defence" in selected_choices else 0
    armour_class = 10 + dexterity_bonus + armour_bonus + shield_bonus + other_bonus + fighting_style_bonus
    sources = [f"10 base", f"Dexterity {dexterity_bonus:+d}"]
    if armour_bonus:
        sources.append(f"Armour {armour_bonus:+d}")
    if shield_bonus:
        sources.append(f"Shield {shield_bonus:+d}")
    if other_bonus:
        sources.append(f"Other equipment {other_bonus:+d}")
    if fighting_style_bonus:
        sources.append("Defence fighting style +1")
    return str(armour_class), " + ".join(sources)


@callback(
    Output("sheet-actions", "children"), Output("sheet-actions", "title"),
    Output("sheet-bonus-actions", "children"), Output("sheet-bonus-actions", "title"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input({"type": "level-subclass", "level": ALL}, "value"),
)
def calculate_action_economy(class_values, subclass_values):
    progression = progression_features_by_class(class_values, subclass_values)
    features = {feature for values in progression.values() for feature in values}
    actions, bonus_actions = 1, 1
    action_conditionals, bonus_conditionals = [], []

    if "Fast Hands" in features:
        bonus_actions += 1
    if "Action Surge" in features:
        action_conditionals.append("Action Surge: +1 Action once per Short Rest")
    if "Wholeness of Body" in features:
        bonus_conditionals.append("Wholeness of Body: +1 Bonus Action each turn for 3 turns, once per Long Rest")

    action_display = f"{actions} (+{len(action_conditionals)}*)" if action_conditionals else str(actions)
    bonus_display = f"{bonus_actions} (+{len(bonus_conditionals)}*)" if bonus_conditionals else str(bonus_actions)
    action_title = f"{actions} Action per turn"
    bonus_title = f"{bonus_actions} Bonus Action{'s' if bonus_actions != 1 else ''} per turn"
    if action_conditionals:
        action_title += ". Conditional: " + "; ".join(action_conditionals)
    if bonus_conditionals:
        bonus_title += ". Conditional: " + "; ".join(bonus_conditionals)
    return action_display, action_title, bonus_display, bonus_title


@callback(
    Output("equipment-melee-main", "options"), Output("equipment-melee-off", "options"),
    Output("equipment-melee-off", "disabled"), Output("equipment-melee-off", "value"),
    Output("equipment-ranged-main", "options"), Output("equipment-ranged-off", "options"),
    Output("equipment-ranged-off", "disabled"), Output("equipment-ranged-off", "value"),
    Output("equipment-headwear", "options"), Output("equipment-armour", "options"),
    Output("equipment-handwear", "options"), Output("equipment-footwear", "options"),
    Output("equipment-cape", "options"),
    Output("equipment-necklace", "options"), Output("equipment-ring-1", "options"), Output("equipment-ring-2", "options"),
    Input("equipment-act-tab", "value"),
    Input("proficient-equipment-only", "value"), Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    Input({"type": "level-class", "level": ALL}, "value"), Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "level-feat", "level": ALL}, "value"), Input("feat-effects-store", "data"),
    Input({"type": "class-feature-choice", "level": ALL, "feature": ALL}, "value"),
    Input("equipment-melee-main", "value"), Input("equipment-ranged-main", "value"),
    Input("pending-build-load", "data"),
    State("equipment-melee-off", "value"), State("equipment-ranged-off", "value"),
)
def update_equipment_options(equipment_act, filter_values, race, subrace, classes, subclasses, feats, feat_effects, class_choices,
                             melee_main_id, ranged_main_id, pending_build, melee_off_id, ranged_off_id):
    if pending_build:
        race = pending_build.get("race") or race
        subrace = pending_build.get("subrace") or subrace
        classes = pending_build.get("classes") or classes
        subclasses = pending_build.get("subclasses") or subclasses
        feats = pending_build.get("feats") or feats
        saved_feat_choices = pending_build.get("feat_choices") or []
        if saved_feat_choices:
            feat_effects = calculate_feat_effects(
                feats,
                [record.get("value") for record in saved_feat_choices],
                [record.get("id") for record in saved_feat_choices],
            )
        saved_class_choices = pending_build.get("class_choices") or []
        if saved_class_choices:
            class_choices = [record.get("value") for record in saved_class_choices]
        saved_equipment = pending_build.get("equipment") or {}
        melee_main_id = saved_equipment.get("melee_main") or melee_main_id
        ranged_main_id = saved_equipment.get("ranged_main") or ranged_main_id
        melee_off_id = saved_equipment.get("melee_off") or melee_off_id
        ranged_off_id = saved_equipment.get("ranged_off") or ranged_off_id
    profs = character_equipment_proficiencies(race, subrace, classes, feat_effects)
    only_proficient = "proficient" in (filter_values or [])
    usable = [row for row in EQUIPMENT if equipment_earliest_act(row) <= int(equipment_act or 1) and "not usable by humanoids" not in row.get("special", "").lower()]
    if only_proficient:
        usable = [row for row in usable if proficient_with_item(row, profs)]
    by_category = lambda *names: [row for row in usable if row["category"] in names]
    melee_main = EQUIPMENT_BY_ID.get(melee_main_id)
    ranged_main = EQUIPMENT_BY_ID.get(ranged_main_id)
    features = [feature for values in progression_features_by_class(classes, subclasses).values() for feature in values]
    selected_choices = [item for value in class_choices or [] for item in (value if isinstance(value, list) else [value]) if item]
    dual_wielder = "Dual Wielder" in (feats or []) or "Two-Weapon Fighting" in selected_choices or any("two-weapon fighting" in value.lower() or "dual wielder" in value.lower() for value in features)

    melee_off_disabled = item_has_property(melee_main, "Two-Handed")
    if melee_off_disabled:
        melee_off_rows = []
    elif dual_wielder:
        melee_off_rows = [row for row in by_category("melee") if not item_has_property(row, "Two-Handed")] + by_category("shield")
    else:
        melee_off_rows = [row for row in by_category("melee") if item_has_property(row, "Light")] + by_category("shield")
    melee_off_options = [equipment_option(row) for row in melee_off_rows]
    valid_melee_off = {row["equipment_id"] for row in melee_off_rows}
    melee_off_value = melee_off_id if melee_off_id in valid_melee_off else None

    ranged_off_disabled = bool(ranged_main and item_has_property(ranged_main, "Two-Handed"))
    ranged_off_rows = [] if ranged_off_disabled else [row for row in by_category("ranged") if row["item_type"] == "Hand Crossbows"]
    ranged_off_options = [equipment_option(row) for row in ranged_off_rows]
    valid_ranged_off = {row["equipment_id"] for row in ranged_off_rows}
    ranged_off_value = ranged_off_id if ranged_off_id in valid_ranged_off else None

    options = lambda rows: [equipment_option(row) for row in rows]
    return (
        options(by_category("melee")), melee_off_options, melee_off_disabled, melee_off_value,
        options(by_category("ranged")), ranged_off_options, ranged_off_disabled, ranged_off_value,
        options(by_category("headwear")), options(by_category("armour", "clothing")),
        options(by_category("handwear")), options(by_category("footwear")),
        options(by_category("cloaks")),
        options(by_category("amulets")), options(by_category("rings")), options(by_category("rings")),
    )


EQUIPMENT_SLOT_IDS = ["melee-main", "melee-off", "ranged-main", "ranged-off", "headwear", "armour", "handwear", "footwear", "cape", "necklace", "ring-1", "ring-2"]


@callback(
    *[Output(f"equipment-{slot}", "value", allow_duplicate=True) for slot in EQUIPMENT_SLOT_IDS],
    Output("act-equipment-loadouts", "data", allow_duplicate=True),
    Input("equipment-act-tab", "value"),
    *[Input(f"equipment-{slot}", "value") for slot in EQUIPMENT_SLOT_IDS],
    State("act-equipment-loadouts", "data"),
    prevent_initial_call=True,
)
def manage_act_loadouts(selected_act, *args):
    values, stored = list(args[:-1]), dict(args[-1] or {})
    loadouts = dict(stored.get("loadouts") or {})
    previous_act = int(stored.get("active_act") or 1)
    if ctx.triggered_id == "equipment-act-tab":
        loadouts[str(previous_act)] = dict(zip(EQUIPMENT_SLOT_IDS, values))
        target = loadouts.get(str(int(selected_act)), {})
        stored.update({"active_act": int(selected_act), "loadouts": loadouts})
        return *[target.get(slot) for slot in EQUIPMENT_SLOT_IDS], stored
    loadouts[str(int(selected_act or previous_act))] = dict(zip(EQUIPMENT_SLOT_IDS, values))
    stored.update({"active_act": int(selected_act or previous_act), "loadouts": loadouts})
    return *([no_update] * len(EQUIPMENT_SLOT_IDS)), stored


@callback(
    Output("sheet-equipment", "children"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
)
def render_sheet_equipment(*values):
    labels = ["Melee", "Melee off hand", "Ranged", "Ranged off hand", "Headwear", "Armour", "Gloves", "Boots", "Cape", "Necklace", "Ring 1", "Ring 2"]
    rows = []
    for label, item_id in zip(labels, values):
        row = EQUIPMENT_BY_ID.get(item_id)
        if row:
            item = html.Span(
                row["item"], className=f"sheet-tooltip-term {equipment_rarity_class(row)}",
                tabIndex=0, **{"data-tooltip": equipment_tooltip(row)},
            )
            rows.append(html.Div([html.Span(label, className="summary-label"), item], className="summary-row"))
    return rows or html.P("Selected equipment will appear here.", className="sheet-empty")


@callback(
    Output("sheet-defences", "children"),
    Input("race-dropdown", "value"), Input("subrace-dropdown", "value"),
    Input({"type": "level-class", "level": ALL}, "value"), Input({"type": "level-subclass", "level": ALL}, "value"),
    Input({"type": "level-feat", "level": ALL}, "value"),
    Input("equipment-melee-main", "value"), Input("equipment-melee-off", "value"),
    Input("equipment-ranged-main", "value"), Input("equipment-ranged-off", "value"),
    Input("equipment-headwear", "value"), Input("equipment-armour", "value"),
    Input("equipment-handwear", "value"), Input("equipment-footwear", "value"),
    Input("equipment-cape", "value"),
    Input("equipment-necklace", "value"), Input("equipment-ring-1", "value"), Input("equipment-ring-2", "value"),
)
def render_sheet_defences(race, subrace, class_values, subclass_values, feat_values, *item_ids):
    combined = {"resistances": [], "immunities": [], "vulnerabilities": []}

    def merge(effects):
        for category in combined:
            combined[category].extend(effects[category])

    race_row = next((row for row in RACES if row["race"] == race), None)
    subrace_row = next((row for row in RACES if row["race"] == race and row["subrace"] == subrace), None)
    if race_row:
        merge(defensive_effects(race_row.get("race_features", ""), race))
    if subrace_row:
        merge(defensive_effects(subrace_row.get("subrace_features", ""), subrace or race))

    spell_names = {row["spell"].lower() for row in SPELLS}
    progression = progression_features_by_class(class_values, subclass_values)
    for class_name, features in progression.items():
        for feature in features:
            if feature.lower() in spell_names:
                continue
            feature_row = next((row for row in CLASS_FEATURES if row["feature"].lower() == feature.lower()), None)
            if feature_row:
                merge(defensive_effects(feature_row["description"], f"{class_name} — {feature}"))

    for feat in dict.fromkeys(value for value in feat_values or [] if value):
        feat_row = next((row for row in FEATS if row["feat"] == feat), None)
        if feat_row:
            merge(defensive_effects(feat_row["description"], f"Feat — {feat}"))

    slot_names = ["Melee main hand", "Melee off hand", "Ranged main hand", "Ranged off hand", "Headwear", "Armour", "Handwear", "Footwear", "Cape", "Necklace", "Ring 1", "Ring 2"]
    for slot, item_id in zip(slot_names, item_ids):
        row = EQUIPMENT_BY_ID.get(item_id)
        if row:
            merge(defensive_effects(row.get("special", ""), f"{row['item']} ({slot})"))

    return [
        defence_column("Resistances", combined["resistances"], "resistance"),
        defence_column("Immunities", combined["immunities"], "immunity"),
        defence_column("Vulnerabilities", combined["vulnerabilities"], "vulnerability"),
    ]


@callback(
    Output("summary-name", "children"),
    Output("character-summary", "children"),
    Output("character-store", "data"),
    Input("character-name", "value"),
    Input("race-dropdown", "value"),
    Input("subrace-dropdown", "value"),
    Input("background-dropdown", "value"),
    Input("human-versatility-skill", "value"),
    Input({"type": "level-class", "level": ALL}, "value"),
    Input("feat-effects-store", "data"),
    State("character-store", "data"),
)
def update_summary(name, race, subrace, background, human_skill, level_classes, feat_effects, _stored):
    race_row = next((row for row in RACES if row["race"] == race), None)
    subrace_row = next(
        (row for row in RACES if row["race"] == race and row["subrace"] == subrace),
        None,
    )
    background_row = next((row for row in BACKGROUNDS if row["background"] == background), None)

    identity = html.Div(
        [
            detail_block("Race", race or "Not selected"),
            detail_block("Subrace", subrace or ("No subrace" if race and not subrace_row else "Not selected")),
            detail_block("Background", background or "Not selected"),
        ],
        className="sheet-identity",
    )

    movement = metric_movement(race_row["base_speed"]) if race_row else "—"
    class_proficiencies = []
    seen_classes = set()
    for index, class_name in enumerate(level_classes or []):
        if not class_name:
            break
        if class_name in seen_classes:
            continue
        class_row = next(row for row in CLASSES if row["class"] == class_name)
        class_proficiencies.append(class_row["equipment_proficiencies"] if index == 0 else class_row["multiclass_proficiencies"])
        seen_classes.add(class_name)

    feat_effects = feat_effects or {}
    feat_proficiencies = list(feat_effects.get("proficiencies", []))
    feat_proficiencies += [f"Skill: {skill}" for skill in feat_effects.get("skills", [])]
    feat_proficiencies += [f"Expertise: {skill}" for skill in feat_effects.get("expertise", [])]
    feat_proficiencies += [f"{ability} saving throws" for ability in feat_effects.get("saving_throws", [])]
    merged_proficiencies = collapse_weapon_proficiencies(proficiency_items(
        race_row["race_proficiencies"] if race_row else "",
        subrace_row["subrace_proficiencies"] if subrace_row else "",
        background_row["skill_proficiencies"] if background_row else "",
        [human_skill] if race == "Human" and human_skill else [],
        *class_proficiencies,
        feat_proficiencies,
    ))
    weapon_names = {
        row["proficiency"].lower() for row in WEAPON_PROFICIENCIES
    } | {
        weapon.strip().lower()
        for row in WEAPON_PROFICIENCIES
        for weapon in row["included_weapon_types"].split(";")
        if weapon.strip()
    }
    skill_names = {skill.lower() for skill in SKILL_TO_ABILITY}
    weapon_proficiencies, skill_proficiencies = [], []
    armour_proficiencies, saving_proficiencies, other_proficiencies = [], [], []
    for item in merged_proficiencies:
        lowered = item.lower()
        if lowered in weapon_names:
            weapon_proficiencies.append(item)
        elif lowered in skill_names or lowered.startswith("expertise:"):
            skill_proficiencies.append(item)
        elif "armour" in lowered or lowered == "shields":
            armour_proficiencies.append(item)
        elif "saving throw" in lowered:
            saving_proficiencies.append(item)
        else:
            other_proficiencies.append(item)

    proficiency_groups = [
        ("Weapon proficiencies", weapon_proficiencies, True),
        ("Skill proficiencies", skill_proficiencies, False),
        ("Armour proficiencies", armour_proficiencies, False),
        ("Saving throw proficiencies", saving_proficiencies, False),
        ("Other proficiencies", other_proficiencies, False),
    ]
    proficiencies = [
        html.Div(
            [
                html.Span(label, className="summary-label"),
                html.Span(proficiency_tooltip_text("; ".join(items)) if weapon_group else "; ".join(items)),
            ],
            className="summary-row",
        )
        for label, items, weapon_group in proficiency_groups
        if items
    ]
    if not proficiencies:
        proficiencies.append(html.P("Make selections to record proficiencies.", className="sheet-empty"))

    features = []
    if race_row:
        features.append(html.Div([html.Span("Racial traits", className="summary-label"), html.Span(racial_trait_tooltips(race_row["race_features"]))], className="summary-row"))
    if subrace_row:
        features.append(html.Div([html.Span("Subrace traits", className="summary-label"), html.Span(racial_trait_tooltips(subrace_row["subrace_features"]))], className="summary-row"))
    if not features:
        features.append(html.P("Racial features will appear here.", className="sheet-empty"))

    summary = html.Div(
        [
            identity,
            html.Div(
                [
                    html.Section(
                        [html.H3("Movement"), html.Div(movement, className="movement-value")],
                        className="sheet-panel movement-panel",
                    ),
                    html.Section([html.H3("Proficiencies"), *proficiencies], className="sheet-panel"),
                    html.Section([html.H3("Features & Traits"), *features], className="sheet-panel sheet-panel--wide"),
                ],
                className="sheet-grid",
            ),
        ]
    )

    data = {"name": name or "", "race": race, "subrace": subrace, "background": background, "human_versatility_skill": human_skill if race == "Human" else None}
    return name.strip() if name and name.strip() else "Unnamed Adventurer", summary, data
