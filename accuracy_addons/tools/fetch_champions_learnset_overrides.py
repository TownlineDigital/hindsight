"""
Fetches Pokemon Showdown's dedicated `champions` mod learnset overrides -
the REAL, format-specific move-legality data for this game (see
../moveset_validator.py's "TRUE FORMAT-SPECIFIC OVERRIDES" module docstring
section for the full writeup of why this exists and what it fixes).

Why this is a plain HTTPS GET + regex parse, not another @pkmn/data Node
script like export_showdown_learnsets.js: the locally-available @pkmn/sim
npm package (0.10.11, confirmed 2026-07-05) predates the `champions` mod
entirely - its own bundled data/mods/ only goes up to gen8legends, no
champions folder at all. Rather than depend on a newer @pkmn package release
(and the npm-registry-sometimes-blocked problem that already bit
export_showdown_learnsets.js once), this fetches Smogon's own GitHub repo
directly - data/mods/champions/learnsets.ts is committed source, served as
plain text by raw.githubusercontent.com, no build step or npm install
needed at all.

Confirmed for real on 2026-07-05 (not assumed): fetched this exact URL,
found 48 species entries (venusaur, charizard, blastoise, ... slowkinggalar
- see the output file for the full list), each a REPLACEMENT movepool for
that species specifically (NOT additive to vanilla gen 9 - e.g. Champions-
Charizard has 72 moves vs vanilla gen 9's 129, missing Dynamic Punch, False
Swipe, Hidden Power, etc., while separately gaining Ancient Power, Bite, and
Dragon Rush that vanilla gen 9 Charizard can't learn). Every OTHER species
NOT listed in this file has no Champions-specific override at all - it
falls through to vanilla gen 9 data unchanged, the same inheritance model
Pokemon Showdown's own mod system uses. This is why
moveset_validator.load_learnsets() REPLACES (not unions) the base full-dex
data for just these ~48 species rather than merging every species through
this file.

The parser here is a small, targeted regex extractor for this ONE file's
specific (and simple - no `inherit: true` deltas, unlike the base
learnsets.ts) shape:

    export const Learnsets: ... = {
        speciesid: {
            learnset: {
                moveid: ["9M"],
                ...
            },
        },
        ...
    }

Not a general TypeScript parser (no `tsc`/`typescript` package available in
this sandbox either - npm registry access has been unreliable throughout
this project's development, see moveset_validator.py's own history) - just
enough regex to reliably split this one well-known, regular shape into
{species: [moveids]}.

Usage:
    python fetch_champions_learnset_overrides.py > ../data/showdown_learnsets_champions_overrides.json

No further code changes needed after running it: moveset_validator.py's
load_learnsets() already merges this file's content on top of the full-dex
export the moment it exists on disk (see _CHAMPIONS_OVERRIDES_PATH there).
Re-run this any time the Champions mod itself changes (a new regulation, a
balance patch to one of these 48 species' movepools).
"""

import json
import re
import sys
import urllib.request

CHAMPIONS_LEARNSETS_URL = (
    "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/"
    "data/mods/champions/learnsets.ts"
)

_SPECIES_BLOCK_SPLIT = re.compile(r"\n\t([a-z0-9]+): \{\n\t\tlearnset: \{\n")
_MOVE_LINE = re.compile(r"^\t\t\t([a-z0-9]+):", re.MULTILINE)


def parse_champions_learnsets_ts(text):
    """Splits the fetched .ts source on each top-level species block
    (`\\tspeciesid: {\\n\\t\\tlearnset: {\\n`) and pulls every move id out of
    that block's body (`\\t\\t\\tmoveid: [...]`) - see this module's own
    docstring for the exact shape this is built against. Returns
    {species_id: [move_id, ...]}, sorted for a stable/diffable output file."""
    parts = _SPECIES_BLOCK_SPLIT.split(text)
    # parts[0] is the header before the first species; then alternating
    # [species_name, block_body, species_name, block_body, ...]
    data = {}
    for i in range(1, len(parts), 2):
        name = parts[i]
        body = parts[i + 1]
        moves = sorted(set(_MOVE_LINE.findall(body)))
        data[name] = moves
    return data


def fetch_and_parse(timeout=15):
    req = urllib.request.Request(CHAMPIONS_LEARNSETS_URL, headers={"User-Agent": "vgc-coach/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8")
    return parse_champions_learnsets_ts(text)


def main():
    data = fetch_and_parse()
    print(f"Parsed {len(data)} species, {sum(len(v) for v in data.values())} total move entries.",
          file=sys.stderr)
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
