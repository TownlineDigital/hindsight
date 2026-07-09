"""
Cascading event corrections.

The problem this solves: a user fixes ONE misread Pokemon name by hand (say,
event #12 said "Charminion" and they correct it to "Charizard"). A team's
roster is fixed for the whole match, so if the vision/OCR pipeline misread
that Pokemon once, it very likely misread it the SAME way every other time
it appears for that same side in that same match - across move_used,
item_or_ability_activated, status_inflicted, fainted, field_state's
player_active/opponent_active strings, field_state's nested field_status
entries, and team_preview's team/brought/lead strings (see analyze_matches.py
for how each of these gets written). Without this module, a user fixing a
recurring misread would have to find and hand-correct every single
occurrence themselves - exactly the "changes don't do anything" complaint
that prompted building this: the ONE event they corrected would look right,
but every other event still carrying the old wrong name would still feed
into Record/Report/Skill Scores with the wrong identity.

Scoped deliberately narrow: only touches events in the SAME match, and only
the SAME side (`actor`: "player" or "opponent") as the event being
corrected - never blind-replaces every occurrence of a name game-wide,
since the same species can legitimately appear on both sides, or in a
DIFFERENT, unrelated match, without being the same misread.
"""

from typing import Optional


def _replace_token(joined: Optional[str], old: str, new: str) -> Optional[str]:
    """player_active/opponent_active/team_preview fields are stored as
    comma-joined strings (see analyze_matches.py's ", ".join(...) calls),
    not lists - this splits on ",", replaces EXACT token matches only
    (never a substring match, so correcting "Char" could never accidentally
    also touch "Charizard"), and rejoins. Returns `joined` unchanged
    (same object) if nothing matched, so callers can cheaply detect "did
    this field actually change" via `is`/`!=` comparison."""
    if not joined:
        return joined
    parts = [p.strip() for p in joined.split(",")]
    changed = False
    for i, p in enumerate(parts):
        if p == old:
            parts[i] = new
            changed = True
    return ", ".join(parts) if changed else joined


# Which comma-joined fields belong to which side - see this module's
# docstring for where each gets written in analyze_matches.py.
_SIDE_STRING_FIELDS = {
    "player": ["player_active", "player_team", "player_brought", "player_lead"],
    "opponent": ["opponent_active", "opponent_team", "opponent_brought", "opponent_lead"],
}


def cascade_pokemon_correction(events: list, match, actor: str, old_name: str, new_name: str) -> list:
    """Applies a pokemon-identity correction (old_name -> new_name) to every
    OTHER event in `match` that shares the same side (`actor`) and currently
    reads `old_name` - not just the one event a user directly edited. Marks
    each touched event `corrected = True` (mirrors what main.py's
    correct_event already does for the event edited directly) so the
    dashboard's "corrected" badge shows on every event this fixed, not just
    the one that was hand-edited. Returns the list of event indices this
    touched (the caller's own directly-edited index is naturally excluded,
    since by the time this runs that event's `pokemon` field already reads
    `new_name`, not `old_name`, so it can't match `old_name` again here).

    No-ops (returns []) if `actor` isn't "player"/"opponent" - a "both" or
    missing actor (e.g. some team_preview events have actor="both", and
    field_state events have no actor field of their own at all) means there
    is no reliable way to know which side's roster this correction belongs
    to, so cascading would risk touching the wrong side's genuinely
    different Pokemon. It also no-ops if `old_name` is falsy or equals
    `new_name` (nothing to cascade)."""
    if actor not in ("player", "opponent") or not old_name or old_name == new_name:
        return []

    touched = []
    string_fields = _SIDE_STRING_FIELDS[actor]
    for i, e in enumerate(events):
        if e.get("match") != match:
            continue
        changed = False

        # Flat top-level pokemon field - move_used, item_or_ability_activated,
        # status_inflicted, fainted, and similar single-actor events.
        if e.get("actor") == actor and e.get("pokemon") == old_name:
            e["pokemon"] = new_name
            changed = True

        # field_state's own player_active/opponent_active strings, and
        # team_preview's team/brought/lead strings - all comma-joined text.
        for field in string_fields:
            if field in e:
                new_val = _replace_token(e.get(field), old_name, new_name)
                if new_val != e.get(field):
                    e[field] = new_val
                    changed = True

        # field_state's nested field_status entries, e.g.
        # {"field_status": {"opponent_active": [{"pokemon": "Dragonite",
        # "status": "Defense fell"}]}} - a separate, more detailed structure
        # from the plain player_active/opponent_active strings above.
        field_status = e.get("field_status")
        if isinstance(field_status, dict):
            entries = field_status.get(f"{actor}_active")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("pokemon") == old_name:
                        entry["pokemon"] = new_name
                        changed = True

        if changed:
            e["corrected"] = True
            touched.append(i)

    return touched
