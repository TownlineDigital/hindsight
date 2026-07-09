"""
Compose a runnable schema.json from layered adapters.

The scalable structure:
    adapters/_core.json                      - universal ontology (write once, every game reuses)
    adapters/<game>/game.json                 - one game's vocabulary + mapping to the core
    adapters/<game>/<mode>.json                - a small per-mode delta (e.g. singles vs doubles)
    adapters/<game>/regulations/<reg>.json    - a small per-REGULATION delta (which species/
                                                 mechanics are actually legal RIGHT NOW - see
                                                 ARCHITECTURE_HANDOFF.md section 3a). Optional:
                                                 a game without a regulation concept just omits
                                                 --regulation and this layer is skipped entirely.

This merges  core + game + mode (+ regulation)  into schema.json, which is exactly
what analyze_matches.py already reads. So adding a game = a new folder of small JSON
files; adding a mode = one tiny file; adding a regulation = one tiny file. Nothing
else in the pipeline changes.

Why regulation is a SEPARATE layer from mode: mode (singles vs doubles) and
regulation (which specific Pokemon/mechanics are legal today) are independent
axes - the same doubles rules apply whether Regulation M-A or M-B is active, and
mode.json shouldn't need editing every time a regulation rotates (which happens
every couple months). Regulation rules win over mode rules on overlapping keys
(e.g. this regulation's own legal_mechanics over anything a mode file might
otherwise imply), since regulation is the more specific, more frequently-updated
fact. The regulation's own species roster is NOT duplicated into schema.json here -
that's read directly from the same regulation file by analyze_matches.py's
--regulation flag (see analyze_matches.configure_regulation) at extraction time,
since it's an enforced allowlist, not just AI guidance text.

Usage:
  py compose_schema.py --game pokemon --mode doubles --regulation m-b
  py compose_schema.py --game pokemon --mode singles --regulation m-b --out schema.json
  py compose_schema.py --list
"""

import argparse
import json
import os
import sys


def load(path):
    if not os.path.exists(path):
        sys.exit(f"Missing adapter file: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_available(adapters_dir):
    print("Available games / modes:")
    if not os.path.isdir(adapters_dir):
        print("  (no adapters folder found)")
        return
    for game in sorted(os.listdir(adapters_dir)):
        gdir = os.path.join(adapters_dir, game)
        if not os.path.isdir(gdir):
            continue
        modes = [f[:-5] for f in os.listdir(gdir) if f.endswith(".json") and f != "game.json"]
        print(f"  {game}: {', '.join(sorted(modes)) or '(no modes yet)'}")
        regs_dir = os.path.join(gdir, "regulations")
        if os.path.isdir(regs_dir):
            regs = sorted(f[:-5] for f in os.listdir(regs_dir) if f.endswith(".json"))
            print(f"    regulations: {', '.join(regs) or '(none yet)'}")


def compose(adapters_dir, game, mode, regulation=None):
    core = load(os.path.join(adapters_dir, "_core.json"))
    gmod = load(os.path.join(adapters_dir, game, "game.json"))
    mmod = load(os.path.join(adapters_dir, game, f"{mode}.json"))
    # Regulation is OPTIONAL and additive - a game with no regulations/ folder at
    # all (or a game not yet using this concept) composes exactly as before with
    # regulation=None. Only actually loads a file when a regulation was named.
    rmod = None
    if regulation:
        reg_path = os.path.join(adapters_dir, game, "regulations", f"{regulation}.json")
        if not os.path.exists(reg_path):
            sys.exit(f"Unknown regulation '{regulation}' for {game} "
                     f"(expected {reg_path}) - run --list to see what's available.")
        rmod = load(reg_path)

    uf = core["universal_fields"]

    # fields: universal core -> game additions -> mode additions, with detail/confidence last
    fields = {"timestamp": uf["timestamp"], "event": uf["event"], "actor": uf["actor"]}
    fields.update(gmod.get("fields", {}))
    fields.update(mmod.get("fields", {}))
    fields["detail"] = uf["detail"]
    fields["confidence"] = uf["confidence"]

    # event types: game + mode additions (deduped, order preserved)
    event_types = list(gmod.get("event_types", []))
    for t in mmod.get("event_types", []):
        if t not in event_types:
            event_types.append(t)
    for t in mmod.get("remove_event_types", []):   # mechanics this format doesn't have
        if t in event_types:
            event_types.remove(t)

    # notes: universal + game + mode + regulation's own format_notes, concatenated.
    # Regulation's format_notes comes LAST - it's the most specific, most likely to
    # actually matter to an in-the-moment read (which species/mechanics are legal
    # RIGHT NOW), so it should be the freshest thing in the AI's context.
    notes = " ".join(s for s in [core.get("universal_notes", ""),
                                 gmod.get("notes", ""),
                                 mmod.get("notes", ""),
                                 (rmod or {}).get("format_notes", "")] if s)

    # rules: game -> mode -> regulation, each layer's keys winning over the last -
    # regulation is the most specific/frequently-updated layer, so its rules
    # (e.g. legal_mechanics, banned_species_categories) take priority over
    # whatever a mode file might otherwise imply.
    schema = {
        "game": mmod.get("display_name") or gmod.get("game"),
        "_composed_from": [f"_core", f"{game}/game", f"{game}/{mode}"] +
                          ([f"{game}/regulations/{regulation}"] if rmod else []),
        "description": mmod.get("description") or gmod.get("description", ""),
        "event_types": event_types,
        "fields_to_capture": fields,
        "notes_for_the_ai": notes,
        "core_mapping": gmod.get("core_mapping", {}),   # for cross-game analytics later
        "example_output": mmod.get("example_output") or gmod.get("example_output") or [],
        "rules": {**gmod.get("rules", {}), **mmod.get("rules", {}), **(rmod or {}).get("legal_mechanics", {}),
                  **({"banned_species_categories": rmod["banned_species_categories"]} if rmod and "banned_species_categories" in rmod else {}),
                  **({"regulation": rmod["regulation"], "regulation_display_name": rmod.get("display_name"),
                      "regulation_active_from": rmod.get("active_from"),
                      "regulation_active_until": rmod.get("active_until")} if rmod else {})},
    }
    return schema


def main():
    ap = argparse.ArgumentParser(description="Compose schema.json from layered game/mode/regulation adapters.")
    ap.add_argument("--game", help="Game folder under adapters/ (e.g. pokemon)")
    ap.add_argument("--mode", help="Mode file under that game (e.g. doubles)")
    ap.add_argument("--regulation", default="", help="Regulation file under <game>/regulations/ (e.g. "
                    "m-b) - optional; merges that regulation's legal_mechanics/species-category rules "
                    "and format_notes into schema.json. Leave blank for a game with no regulation "
                    "concept, or to compose without one.")
    ap.add_argument("--adapters", default="adapters", help="Adapters directory (default: adapters)")
    ap.add_argument("--out", default="schema.json", help="Output schema (default: schema.json)")
    ap.add_argument("--list", action="store_true", help="List available games, modes, and regulations")
    args = ap.parse_args()

    if args.list or not (args.game and args.mode):
        list_available(args.adapters)
        if not (args.game and args.mode):
            print("\nThen run:  py compose_schema.py --game <game> --mode <mode> --regulation <reg>")
        return

    schema = compose(args.adapters, args.game, args.mode, args.regulation or None)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    print(f"Composed {args.out}: {schema['game']}")
    print(f"  layers: {' + '.join(schema['_composed_from'])}")
    print(f"  event types: {len(schema['event_types'])}  |  fields: {len(schema['fields_to_capture'])}")
    print("Now run:  py analyze_matches.py --video <file> --regulation " + (args.regulation or "<none>"))


if __name__ == "__main__":
    main()
