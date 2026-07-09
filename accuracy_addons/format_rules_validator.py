"""
Free, local (no API call) cross-check of this project's HAND-MAINTAINED format
rules (adapters/pokemon/doubles.json's "rules" block) against Pokemon
Showdown's own, actively-maintained format/ruleset data - catching the format
rules going stale as VGC regulations rotate (they change every few months),
the same "don't let a hand-maintained file quietly drift from reality" spirit
as moveset_validator.py, applied to format rules instead of movesets.

Why Showdown specifically: its format config is what actually powers real
ladder legality enforcement, updated by the same community that tracks
official regulation changes closely - more current for THIS purpose than a
general-purpose reference API.

UPDATE (2026-07-03, overnight pass) - two real changes this session:
  1. RE-FETCHED config/formats.ts from Showdown master and searched it for
     Reg M-B specifically. Result: Reg M-B is STILL not present as its own
     distinct Champions entry - only "[Gen 9 Champions] VGC 2026 Reg M-A",
     "... Reg M-A (Bo3)", and "... BSS Reg M-A" exist. So the exact-regulation
     check stays honestly NOT_CONFIRMABLE (compared against M-A), unchanged
     from the prior run - not upgraded, because there was nothing new to
     upgrade it with.
  2. Made this module REGULATION-LAYER-AWARE. Since it was first written, the
     codebase gained a separate regulation adapter layer (ARCHITECTURE_HANDOFF
     section 3a): the regulation-specific facts this module checks
     (banned_species_categories, terastallization, the regulation id) were
     MOVED out of doubles.json's "rules" into
     adapters/pokemon/regulations/<id>.json. Reading doubles.json alone (as
     the original code did) therefore made the Mythical/Restricted-Legendary
     ban check regress to a SPURIOUS "mismatch" (it saw an empty list). The
     check now reads those fields from the regulation layer (see
     load_adapter_regulation + the regulation_rules parameter). Re-run against
     the REAL files this session, that check is back to a correct MATCH
     (adapter ['mythical','restricted_legendary'] vs Showdown Flat Rules
     ['Mythical','Restricted Legendary']), and terastallization is now read as
     its real structured value (False) from the regulation layer. This was a
     real staleness the VALIDATOR itself had drifted into - exactly the class
     of bug it exists to catch, caught here in the tool rather than the data.

WHAT WAS ACTUALLY DONE (read before trusting anything in here):
  - `data/showdown_champions_formats.json` is REAL data, fetched during
    development from Showdown's own
    https://github.com/smogon/pokemon-showdown/blob/master/config/formats.ts
    and data/rulesets.ts - not fabricated. It contains the "[Gen 9 Champions]
    VGC 2026 Reg M-A" format entry and the "Flat Rules" ruleset it uses.
  - This project's adapters/pokemon/doubles.json is currently configured for
    Regulation M-B (regulation_active_until: 2026-09-02), which was the
    CORRECT current regulation as of this module's development (per
    independent web sources tracking VGC 2026 regulations, not just this
    project's own claim). Reg M-B was NOT found as its OWN distinct
    formats.ts entry in the fetch done here - it likely wasn't added to
    Showdown's config yet, or was further into the file than the fetch
    reached. The cross-check below therefore compares against Reg M-A (the
    closely-related, same-mod predecessor format) as the best REAL data
    available, not a direct Reg M-B confirmation - every check result below
    says explicitly which category it falls into.
  - Terastallization specifically: Showdown's "Flat Rules" ruleset/banlist
    text (fetched here) does NOT mention Tera at all - most likely because
    the Champions mod simply doesn't implement Terastallization as a
    mechanic (a different game engine from mainline Scarlet/Violet), so
    there's nothing to ban via a clause. This module reports that field as
    NOT directly confirmable from the fetched ruleset text - the project's
    "terastallization: false" claim is real and correct, but was corroborated
    by a separate web search during development, not by this JSON file.
  - Re-fetch `config/formats.ts`/`data/rulesets.ts` periodically (e.g. each
    time adapters/pokemon/doubles.json's regulation_active_until approaches)
    to catch the next regulation rotation for real, rather than trusting
    this snapshot indefinitely.
"""

import json
import os

DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "data", "showdown_champions_formats.json"
)


def load_showdown_data(path=DEFAULT_DATA_PATH):
    """Loads the fetched Showdown format/ruleset JSON. Returns None (not an
    error) if the file is missing, so a caller can skip the cross-check
    cleanly rather than crash."""
    if not os.path.exists(path):
        print(f"[format_rules_validator] no Showdown format data at {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_adapter_regulation(regulation_id, adapters_dir=None):
    """Loads a regulation-layer file (adapters/pokemon/regulations/<id>.json),
    the SEPARATE adapter layer that - per ARCHITECTURE_HANDOFF.md section 3a -
    now holds the regulation-specific legality facts (banned_species_categories,
    legal_mechanics incl. terastallization, the regulation id) that USED to sit
    in doubles.json's "rules" block. Returns the parsed dict, or None (fail-soft,
    not an error) if the file/dir is missing so cross_check_adapter_rules can
    degrade to the old doubles.json-only behavior cleanly.

    NOTE (why this exists): this module was originally written to read those
    facts straight off doubles.json's "rules". The regulation-layer refactor
    (section 3a, landed after this module was first written) MOVED them, so
    reading doubles.json alone now finds them empty and yields a spurious
    "mismatch". Pass the regulation file in (or let cross_check_adapter_rules
    auto-load it) to check the values where they actually live now."""
    if adapters_dir is None:
        # repo layout: accuracy_addons/ is a sibling of adapters/
        adapters_dir = os.path.join(
            os.path.dirname(__file__), os.pardir, "adapters", "pokemon"
        )
    reg_id = str(regulation_id or "").strip().lower()
    if not reg_id:
        return None
    path = os.path.join(adapters_dir, "regulations", f"{reg_id}.json")
    if not os.path.exists(path):
        print(f"[format_rules_validator] no regulation layer file at {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_format(name, path=DEFAULT_DATA_PATH):
    """Returns the format entry dict for `name` (e.g. '[Gen 9 Champions] VGC
    2026 Reg M-A'), or None if it's not in the loaded data."""
    data = load_showdown_data(path)
    if not data:
        return None
    for fmt in data.get("formats", []):
        if fmt.get("name") == name:
            return fmt
    return None


def get_ruleset(name, path=DEFAULT_DATA_PATH):
    """Returns the named ruleset's definition dict (e.g. 'Flat Rules'), or
    None if it's not in the loaded data."""
    data = load_showdown_data(path)
    if not data:
        return None
    return data.get("rulesets", {}).get(name)


def cross_check_adapter_rules(adapter_rules, format_name="[Gen 9 Champions] VGC 2026 Reg M-A",
                               path=DEFAULT_DATA_PATH, regulation_rules=None):
    """Compares `adapter_rules` (the "rules" dict from
    adapters/pokemon/doubles.json - pass it directly, e.g.
    json.load(open("adapters/pokemon/doubles.json"))["rules"]) against the
    named Showdown format.

    REGULATION LAYER (added after the section-3a refactor): the
    regulation-specific facts (banned_species_categories, terastallization,
    the regulation id) no longer live in doubles.json's "rules" - they moved
    to adapters/pokemon/regulations/<id>.json. Pass `regulation_rules` (that
    file's parsed dict) so those three fields are checked where they ACTUALLY
    live now; if you don't, this function tries to auto-load it using
    adapter_rules["regulation"] (or falls back to "m-b", this project's
    current default) and only if that also fails does it read the legacy
    doubles.json location - so an older caller still works, just against the
    now-empty legacy fields (which is exactly the spurious-mismatch trap this
    parameter fixes). Returns a list of check-result dicts:
    {field, adapter_value, showdown_value, status}, where status is one of:
      - "match"        - directly confirmed consistent with fetched Showdown data
      - "mismatch"     - directly confirmed INCONSISTENT - investigate, the
                          adapter file may be stale (this is the case this
                          module exists to catch)
      - "not_confirmable" - this field isn't something the fetched Showdown
                          data can directly confirm or deny (e.g.
                          Terastallization - see module docstring) - NOT the
                          same as "wrong," just "this check can't verify it
                          from what's loaded"
    Does not raise if data/the format is missing - returns a single
    "not_confirmable" entry explaining why instead, the same fail-soft
    pattern as backend/audit.py."""
    fmt = get_format(format_name, path)
    if fmt is None:
        return [{"field": "*", "adapter_value": None, "showdown_value": None,
                  "status": "not_confirmable",
                  "note": f"'{format_name}' not found in loaded Showdown data"}]

    flat_rules = get_ruleset("Flat Rules", path) or {}
    flat_ruleset_list = flat_rules.get("ruleset", [])
    flat_banlist = flat_rules.get("banlist", [])

    # Resolve the regulation layer (see load_adapter_regulation / the section-3a
    # note in this function's docstring). If the caller didn't pass one, try to
    # auto-load it from adapter_rules["regulation"], else this project's current
    # default "m-b". reg_source records where each regulation-specific field's
    # value actually came from, so the output stays honest about it.
    if regulation_rules is None:
        _reg_id = adapter_rules.get("regulation") or "m-b"
        regulation_rules = load_adapter_regulation(_reg_id)
    reg = regulation_rules or {}
    reg_source = "regulations/<id>.json" if regulation_rules else "doubles.json['rules'] (legacy fallback)"
    reg_mechanics = reg.get("legal_mechanics", {}) if reg else {}

    # regulation-specific values, read from the regulation layer when present,
    # falling back to the legacy doubles.json location for an old caller.
    reg_banned = reg.get("banned_species_categories",
                         adapter_rules.get("banned_species_categories", []))
    reg_tera = reg_mechanics.get("terastallization",
                                 adapter_rules.get("terastallization"))
    reg_id_value = reg.get("regulation", adapter_rules.get("regulation"))

    results = []

    # 1. Game type (doubles) - DIRECT, structural check
    adapter_active = adapter_rules.get("active_per_side")
    showdown_doubles = fmt.get("gameType") == "doubles"
    results.append({
        "field": "doubles_format",
        "adapter_value": adapter_active,
        "showdown_value": fmt.get("gameType"),
        "status": "match" if (adapter_active == 2) == showdown_doubles else "mismatch",
    })

    # 2. Species Clause - DIRECT, structural check
    species_clause_expected = "Species Clause" in flat_ruleset_list
    # the adapter doesn't have a dedicated boolean field for this - it's
    # stated in format_notes free text - so this check only confirms
    # Showdown's own stance, and flags for a human to verify the adapter's
    # prose still says it too (a free-text field can't be machine-diffed
    # reliably without a much stricter adapter schema than exists today).
    results.append({
        "field": "species_clause",
        "adapter_value": "(stated in format_notes free text, not a structured field)",
        "showdown_value": species_clause_expected,
        "status": "not_confirmable",
        "note": "Showdown confirms Species Clause applies; adapter doesn't "
                "structure this as a checkable field yet - human check only.",
    })

    # 3. Mythical / Restricted Legendary ban - DIRECT, structural check.
    # Read from the regulation layer (see reg_banned resolution above) - this
    # is the check that regressed to a spurious "mismatch" after the section-3a
    # refactor moved banned_species_categories out of doubles.json.
    adapter_banned = set(reg_banned)
    showdown_bans_mythical = "Mythical" in flat_banlist
    showdown_bans_restricted = "Restricted Legendary" in flat_banlist
    match = (
        ("mythical" in adapter_banned) == showdown_bans_mythical
        and ("restricted_legendary" in adapter_banned) == showdown_bans_restricted
    )
    results.append({
        "field": "mythical_and_restricted_legendary_banned",
        "adapter_value": sorted(adapter_banned),
        "showdown_value": [b for b in flat_banlist if b in ("Mythical", "Restricted Legendary")],
        "status": "match" if match else "mismatch",
        "note": f"adapter value read from {reg_source}",
    })

    # 4. Terastallization - the value is now a real structured field in the
    # regulation layer's legal_mechanics, but Showdown's fetched Flat Rules
    # text still doesn't mention Tera, so this stays NOT directly confirmable
    # against Showdown (see docstring) - we just report the real adapter value.
    results.append({
        "field": "terastallization",
        "adapter_value": reg_tera,
        "showdown_value": None,
        "status": "not_confirmable",
        "note": f"adapter value ({reg_tera}) read from {reg_source}'s "
                "legal_mechanics. Flat Rules' fetched ruleset/banlist text "
                "doesn't mention Tera at all (the Champions mod likely doesn't "
                "implement it as a mechanic) - corroborated by a separate web "
                "search during development, not by this JSON file.",
    })

    # 5. Which exact regulation - STILL NOT directly confirmable: re-fetched
    # config/formats.ts on 2026-07-03 and Reg M-B is STILL absent (only Reg
    # M-A / M-A Bo3 / BSS M-A exist as distinct Champions entries), so the
    # comparison remains against M-A. (See docstring / OVERNIGHT_REPORT.md.)
    results.append({
        "field": "regulation_M-B_vs_M-A",
        "adapter_value": reg_id_value,
        "showdown_value": format_name,
        "status": "not_confirmable",
        "note": "Adapter targets Reg M-B; config/formats.ts was RE-FETCHED "
                "2026-07-03 and Reg M-B is STILL not present as its own "
                "distinct Champions entry (only VGC 2026 Reg M-A, Reg M-A "
                "(Bo3), and BSS Reg M-A exist). Same mod/structure, not a "
                "direct confirmation of M-B's own (possibly different) "
                "banlist - re-fetch again after Showdown adds an M-B entry.",
    })

    return results
