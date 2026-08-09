"""Pure build-completeness checks used by the Dash validation panel."""

from __future__ import annotations

from dataclasses import dataclass

from bg3_rules import point_buy_spent


DEFAULT_SELECTION_COUNTS = {
    "ability_primary": 1, "ability_secondary": 1, "ability": 1,
    "weapons": 4, "cantrips": 2, "spell": 1, "manoeuvres": 2,
    "rituals": 2, "skills": 3, "cantrip": 1, "element": 1,
}


@dataclass(frozen=True)
class BuildIssue:
    section: str
    message: str
    severity: str = "warning"


def validate_identity(race, subrace, background, races_with_subraces) -> list[BuildIssue]:
    issues = []
    if not race:
        issues.append(BuildIssue("Background", "Choose a race."))
    elif race in set(races_with_subraces) and not subrace:
        issues.append(BuildIssue("Background", f"Choose a {race} subrace."))
    if not background:
        issues.append(BuildIssue("Background", "Choose a background."))
    return issues


def validate_abilities(ability_data) -> list[BuildIssue]:
    data = ability_data or {}
    scores = data.get("scores", {})
    if not scores:
        return [BuildIssue("Abilities", "Assign the six base ability scores.")]
    spent = point_buy_spent(scores)
    issues = []
    if spent != 27:
        issues.append(BuildIssue("Abilities", f"Spend exactly 27 ability points ({spent}/27 currently spent)."))
    if not data.get("plus_two"):
        issues.append(BuildIssue("Abilities", "Assign the +2 ability bonus."))
    if not data.get("plus_one"):
        issues.append(BuildIssue("Abilities", "Assign the +1 ability bonus."))
    if data.get("plus_two") and data.get("plus_two") == data.get("plus_one"):
        issues.append(BuildIssue("Abilities", "The +2 and +1 bonuses must be assigned to different abilities.", "error"))
    return issues


def validate_level_chain(classes) -> list[BuildIssue]:
    values = list(classes or [])
    issues = []
    seen_gap = False
    for index, value in enumerate(values, 1):
        if not value:
            seen_gap = True
        elif seen_gap:
            issues.append(BuildIssue("Leveling", f"Level {index} is filled after an empty earlier level.", "error"))
    if not any(values):
        issues.append(BuildIssue("Leveling", "Choose a class at level 1."))
    return issues


def validate_required_controls(values, ids, section, optional_categories=()) -> list[BuildIssue]:
    issues = []
    optional = set(optional_categories)
    for value, item_id in zip(values or [], ids or []):
        category = item_id.get("feature") or (item_id.get("kind", "").split("|", 1)[0]) or item_id.get("field", "choice")
        if category in optional:
            continue
        selected = value if isinstance(value, list) else ([value] if value else [])
        limit = int(item_id.get("limit", DEFAULT_SELECTION_COUNTS.get(category, 1)))
        if len(selected) < limit:
            level = item_id.get("level")
            location = f" at character level {level}" if level else ""
            issues.append(BuildIssue(section, f"Complete {str(category).replace('_', ' ')}{location} ({len(selected)}/{limit} selected)."))
    return issues
