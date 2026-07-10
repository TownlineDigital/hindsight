"""
META / KNOWLEDGE-BASE builder.

Builds meta/<format>.json - the grounding the coach uses so its advice is both
LEGAL (format rules) and RELEVANT (meta usage). Three knowledge sources:

  1. Game mechanics (rarely changes) - type chart + each Pokemon's types/abilities,
     pulled from the free PokeAPI (pokeapi.co). Cached; refresh occasionally.
  2. Your OWN data flywheel - usage, win rates, leads, and opponent threats computed
     from events.json. Works for ANY format (incl. brand-new ones) and improves with
     every match you process.
  3. THE WIDER FIELD (added 2026-07-05, task #130) - real, official monthly usage
     stats for this exact game+regulation, fetched from Smogon's own published stats
     pages (smogon.com/stats/) - see fetch_external_meta()'s own docstring for the
     full "why this source, why it's ToS-safe, why it's the same format" writeup.
     This exists specifically because own_meta (source 2) is only as broad as YOUR
     own upload history - a new user, or a user who's never faced a given Pokemon,
     gets nothing from it. external_meta answers "what is everyone else actually
     playing this month," which own_meta structurally cannot.

Plus it copies the format 'rules' from schema.json (legal mechanics) so the coach
never recommends something the format doesn't have (e.g. Terastallization in Champions).

Run:
  py meta_build.py                 (fetch mechanics + external meta + fold in your own data)
  py meta_build.py --no-fetch      (rebuild own-data only, offline)
  py meta_build.py --no-external-meta   (fetch PokeAPI mechanics but skip the Smogon stats pull)

Schedule it (monthly) so the knowledge base stays current automatically.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

POKEAPI = "https://pokeapi.co/api/v2"
TYPES = ["normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison",
         "ground", "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark",
         "steel", "fairy"]

# ---- external_meta (Smogon official usage stats) -------------------------
SMOGON_STATS_BASE = "https://www.smogon.com/stats"
# Highest-to-lowest rating cutoff, tried in this order (see fetch_external_meta's
# docstring for why 1760 first) - "0" (no cutoff/every rated battle) is always
# last since it's the noisiest signal but the one guaranteed to have SOME data.
_RATING_CUTOFFS = (1760, 1630, 1500, 0)
_USAGE_ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<name>.+?)\s*\|\s*(?P<pct>[\d.]+)%\s*\|", re.MULTILINE
)
_TOTAL_BATTLES = re.compile(r"Total battles:\s*(\d+)")


def get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "vgc-coach/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def slug(name):
    s = name.lower().strip().replace("’", "").replace("é", "e")
    s = re.sub(r"[.'`]", "", s)
    return s.replace(" ", "-")


def ev(e):
    return str(e.get("event", "")).strip()


def split(s):
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def own_meta(events):
    """The flywheel: usage / win rates / leads / opponent threats from your matches."""
    g = defaultdict(list)
    for e in events:
        if e.get("match") is not None:
            g[e["match"]].append(e)
    usage = defaultdict(lambda: [0, 0])       # mon -> [brought, wins]
    leads = defaultdict(lambda: [0, 0])
    threats = defaultdict(lambda: [0, 0])     # opp mon -> [faced, player_wins]
    names = set()
    for evs in g.values():
        tp = next((x for x in evs if ev(x) == "team_preview"), {})
        be = next((x for x in evs if ev(x) == "battle_end"), {})
        won = str(be.get("winner") or be.get("actor") or "").lower() == "player"
        for m in set(split(tp.get("player_brought"))):
            usage[m][0] += 1
            usage[m][1] += won
            names.add(m)
        lead = " + ".join(sorted(split(tp.get("player_lead"))))
        if lead:
            leads[lead][0] += 1
            leads[lead][1] += won
        for m in set(split(tp.get("opponent_brought")) or split(tp.get("opponent_team"))):
            threats[m][0] += 1
            threats[m][1] += won
            names.add(m)
    def tbl(d):
        return {k: {"n": v[0], "wins": v[1], "win_pct": round(v[1] / v[0] * 100, 1) if v[0] else 0}
                for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])}
    return {"pokemon_usage": tbl(usage), "leads": tbl(leads), "opponent_threats": tbl(threats)}, names


def fetch_type_chart():
    chart = {}
    for t in TYPES:
        d = get_json(f"{POKEAPI}/type/{t}")["damage_relations"]
        chart[t] = {
            "double_to": [x["name"] for x in d["double_damage_to"]],
            "half_to": [x["name"] for x in d["half_damage_to"]],
            "no_to": [x["name"] for x in d["no_damage_to"]],
        }
        time.sleep(0.1)
    return chart


def fetch_pokedex(names, cache):
    """`base_stats` (added 2026-07-09, Phase 1 of the live-coaching/damage-
    calculator roadmap - see ARCHITECTURE_HANDOFF.md) is the one new field
    here: HP/Attack/Defense/Special-Attack/Special-Defense/Speed, straight
    off PokeAPI's own `stats` array (a stable, long-unchanged part of its
    schema). This is foundational data a real damage calculator and any
    speed-tier inference needs - type/ability alone (what this function
    already fetched) can't answer "how much damage does this do" or "who
    moves first."

    Cache entries from before this field existed are missing `base_stats` -
    the `"base_stats" not in dex[name]` check below re-fetches those ONE
    more time to backfill it, rather than skipping them forever just because
    `name in dex` was already true. Same "no-op once already there, but
    don't silently skip a newly-added field on old rows" principle
    supabase_schema.sql's `alter table add column if not exists` uses for
    its own migrations, applied here to this JSON cache instead of a SQL
    table."""
    dex = dict(cache)
    for name in sorted(names):
        if name in dex and "base_stats" in dex[name]:
            continue
        try:
            d = get_json(f"{POKEAPI}/pokemon/{slug(name)}")
            dex[name] = {
                "types": [t["type"]["name"] for t in d["types"]],
                "abilities": [a["ability"]["name"] for a in d["abilities"]],
                "base_stats": {s["stat"]["name"]: s["base_stat"] for s in d.get("stats", [])},
            }
            time.sleep(0.1)
        except Exception:
            dex[name] = {"types": [], "abilities": [], "base_stats": {},
                         "note": "not resolved from PokeAPI"}
    return dex


def _smogon_tier_slug(regulation, year):
    """Maps this project's own regulation code ("M-A"/"M-B", from schema.json's
    rules.regulation - see adapters/pokemon/regulations/*.json) to Smogon's real
    stats-page tier slug. Confirmed by directly fetching Smogon's own June-2026
    stats directory listing (smogon.com/stats/2026-06/) on 2026-07-05: this game
    ("Pokemon Champions") is tracked there as "[Gen 9 Champions]," with per-
    regulation VGC tiers named exactly gen9championsvgc<year>reg<code> - e.g.
    "M-A" -> gen9championsvgc2026regma (confirmed present, 1.48M real battles in
    the June 2026 dump), "M-B" -> gen9championsvgc2026regmb (also confirmed
    present). Not a guess or a mapping from a DIFFERENT game's tier naming -
    this is the actual slug this actual game's actual ladder data is filed
    under."""
    code = re.sub(r"[^a-z0-9]", "", str(regulation or "").lower())
    return f"gen9championsvgc{year}reg{code}" if code else None


def _parse_smogon_usage_text(text):
    """Parses Smogon's plain-text usage-stats table format (the same format
    every https://www.smogon.com/stats/<month>/<tier>-<cutoff>.txt file uses,
    confirmed against a real fetched file on 2026-07-05) into
    (total_battles, {pokemon_name: usage_pct}). Returns (None, {}) if the text
    doesn't look like a real stats table at all (e.g. an HTML 404 page slipped
    through) - fail soft, same "don't guess, don't crash" convention as the
    rest of this pipeline."""
    battles_match = _TOTAL_BATTLES.search(text)
    total_battles = int(battles_match.group(1)) if battles_match else None
    usage = {}
    for row in _USAGE_ROW.finditer(text):
        usage[row.group("name")] = float(row.group("pct"))
    return total_battles, usage


def fetch_external_meta(regulation, year=None, timeout=15):
    """THE WIDER FIELD (task #130): real, official monthly Pokemon usage stats
    for this exact game + regulation, from Smogon's own published stats pages.

    Why this source specifically (over any scraped/third-party alternative -
    see the research this was based on): smogon.com/stats/ is Smogon's OWN
    first-party data dump, published by them for exactly this kind of
    consumption - no scraping, no ToS gray area, no fragile reverse-engineered
    API (the community "smogon-usage-stats" Heroku wrapper some tools use is
    run by someone since banned from Smogon and needs a CORS proxy now - the
    opposite of a stable foundation to build on). It's also the ONLY option
    researched that's genuinely FORMAT-SPECIFIC to this project: confirmed by
    direct fetch (2026-07-05) that Smogon tracks this exact game under
    "[Gen 9 Champions]" with per-regulation VGC tiers
    (gen9championsvgc2026regma/regmb) - real, current, current-regulation
    battles (1.48M in the M-A June-2026 dump alone), not a mainline-game
    format being awkwardly repurposed as a stand-in.

    Tries, in order: the current calendar month, then up to 2 prior months
    (Smogon's own monthly dumps lag a few days into the new month, and this
    keeps working even right at a month boundary); within each month, the
    rating cutoffs in _RATING_CUTOFFS order (highest/most-skilled-play first,
    falling back to "0"/uncapped only if no higher cutoff has enough games to
    have been published for this tier yet). Returns None (not an exception,
    not a fabricated empty-but-present dict) if every attempt fails - the
    caller (main() below) treats that exactly like a failed PokeAPI fetch:
    keep whatever was cached from the previous run, don't overwrite good data
    with nothing."""
    slug_year = year or time.strftime("%Y")
    tier = _smogon_tier_slug(regulation, slug_year)
    if not tier:
        return None

    now = time.time()
    for months_back in range(3):
        t = time.gmtime(now - months_back * 30 * 86400)
        month = time.strftime("%Y-%m", t)
        for cutoff in _RATING_CUTOFFS:
            url = f"{SMOGON_STATS_BASE}/{month}/{tier}-{cutoff}.txt"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "vgc-coach/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    text = r.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                continue
            total_battles, usage = _parse_smogon_usage_text(text)
            if not usage:
                continue   # looked like a 404/empty page, not real stats - try the next cutoff/month
            return {
                "source": "https://www.smogon.com/stats",
                "tier": tier,
                "month": month,
                "rating_cutoff": cutoff,
                "total_battles": total_battles,
                "pokemon_usage_pct": usage,
            }
    return None


# ---- external_moveset_meta (Smogon's per-species BUILD breakdown) --------
# Phase 1 of the live-coaching/damage-calculator roadmap (added 2026-07-09 -
# see ARCHITECTURE_HANDOFF.md for the full 4-phase plan). external_meta
# above only ever answers "how popular is this species" (a single usage %);
# this answers "what is it actually running" - abilities/items/EV spreads/
# moves/teammates, each with their own real percentage - which a build-
# inference engine needs as its starting prior before narrowing based on
# what a given opponent's Pokemon actually reveals in a real match.

_MOVESET_BORDER = re.compile(r"^\+-+\+\s*$")
_MOVESET_RAW_COUNT = re.compile(r"Raw count:\s*(\d+)")
_MOVESET_ROW = re.compile(r"^\|\s*(?P<label>.+?)\s+(?P<pct>[\d.]+)%\s*\|?\s*$")
_MOVESET_SECTIONS = ("Abilities", "Items", "Spreads", "Moves", "Teammates")


def _strip_cell(line):
    """"| Garchomp                               |" -> "Garchomp" - every
    real content line in Smogon's moveset table is a `|`-bordered cell
    shaped exactly like this, whether it's a species name, a section
    header, or a data row."""
    return line.strip().strip("|").strip()


def _parse_smogon_moveset_text(text):
    """Parses Smogon's per-species "moveset" stats table - confirmed against
    a real fetched file (https://www.smogon.com/stats/2026-06/moveset/
    gen9championsvgc2026regmb-1760.txt, fetched 2026-07-09 while building
    this) - a DIFFERENT, richer file than the plain usage-percentage table
    _parse_smogon_usage_text already handles (same source, same tier slug,
    just a "moveset/" subdirectory). Each species gets one block:

      +----------------------------------------+
      | Garchomp                               |
      +----------------------------------------+
      | Raw count: 736366                      |
      | Avg. weight: 0.004678881611271098      |
      | Viability Ceiling: 85                  |
      +----------------------------------------+
      | Abilities                              |
      | Rough Skin 96.191%                     |
      | Sand Veil 3.809%                       |
      +----------------------------------------+
      | Items / Spreads / Moves / Teammates ... (same "<label> <pct>%" row shape)

    Every section - INCLUDING Spreads, where label is the whole
    "Nature:HP/Atk/Def/SpA/SpD/Spe" string (e.g. "Jolly:2/32/0/0/0/32") - is
    kept as one raw string mapped to its percentage, rather than split into
    individual EV numbers here. A future build-inference layer can parse
    that string itself when it actually needs individual stat values; this
    function stays a faithful, un-opinionated transcription of what Smogon
    published rather than guessing at a caller's preferred shape.

    Returns {species_name: {"raw_count": int, "abilities": {name: pct}, ...
    "spreads": {...}, "moves": {...}, "teammates": {...}}} - an empty dict if
    the text doesn't look like a real moveset table at all (e.g. an HTML 404
    page slipped through), same "don't guess, don't crash" convention
    _parse_smogon_usage_text already follows."""
    lines = text.splitlines()
    raw_count_idx = [i for i, ln in enumerate(lines) if _MOVESET_RAW_COUNT.search(ln)]
    if not raw_count_idx:
        return {}

    # The species name is always exactly 2 lines above its own "Raw count:"
    # line (name line, then a border line, then "Raw count:") - see the real
    # excerpt in this function's own docstring above.
    name_idx = [i - 2 for i in raw_count_idx]
    boundaries = list(zip(name_idx, name_idx[1:] + [len(lines)]))

    out = {}
    for start, end in boundaries:
        if start < 0:
            continue
        chunk = lines[start:end]
        species = _strip_cell(chunk[0])
        if not species:
            continue

        raw_count_m = _MOVESET_RAW_COUNT.search("\n".join(chunk))
        entry = {"raw_count": int(raw_count_m.group(1)) if raw_count_m else None}

        # Find each section header's line index within this chunk (a cell
        # whose stripped text is exactly one of the known section names),
        # then collect "<label> <pct>%" rows until the next table border.
        section_idx = {}
        for i, ln in enumerate(chunk):
            cell = _strip_cell(ln)
            if cell in _MOVESET_SECTIONS and cell not in section_idx:
                section_idx[cell] = i

        for section, hdr_i in section_idx.items():
            rows = {}
            for ln in chunk[hdr_i + 1:]:
                if _MOVESET_BORDER.match(ln):
                    break
                m = _MOVESET_ROW.match(ln)
                if m:
                    rows[m.group("label")] = float(m.group("pct"))
            entry[section.lower()] = rows

        out[species] = entry
    return out


def fetch_external_moveset_meta(regulation, year=None, timeout=15):
    """Same official-Smogon-source, same month/rating-cutoff walking
    strategy as fetch_external_meta() (see that function's docstring for the
    full "why this source, why it's ToS-safe" writeup - identical reasoning
    applies here, it's the same publisher and same first-party dump, just a
    different file) - but hits the "moveset/" breakdown file instead of the
    plain usage-percent one, giving per-species ability/item/EV-spread/move/
    teammate percentages instead of just one overall usage number.

    Returns {"source", "tier", "month", "rating_cutoff", "movesets": {...}}
    or None if every month/cutoff attempt failed - same "don't fabricate an
    empty-but-present result" rule as fetch_external_meta."""
    slug_year = year or time.strftime("%Y")
    tier = _smogon_tier_slug(regulation, slug_year)
    if not tier:
        return None

    now = time.time()
    for months_back in range(3):
        t = time.gmtime(now - months_back * 30 * 86400)
        month = time.strftime("%Y-%m", t)
        for cutoff in _RATING_CUTOFFS:
            url = f"{SMOGON_STATS_BASE}/{month}/moveset/{tier}-{cutoff}.txt"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "vgc-coach/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    text = r.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                continue
            movesets = _parse_smogon_moveset_text(text)
            if not movesets:
                continue   # looked like a 404/empty page - try the next cutoff/month
            return {
                "source": "https://www.smogon.com/stats",
                "tier": tier,
                "month": month,
                "rating_cutoff": cutoff,
                "movesets": movesets,
            }
    return None


def main():
    ap = argparse.ArgumentParser(description="Build the meta/knowledge base for the coach.")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--schema", default="schema.json")
    ap.add_argument("--no-fetch", action="store_true", help="skip PokeAPI (own-data only)")
    ap.add_argument("--no-external-meta", action="store_true",
                     help="skip the Smogon external usage-stats fetch (task #130); "
                          "implied by --no-fetch")
    ap.add_argument("--out-dir", default="meta")
    args = ap.parse_args()

    schema = json.load(open(args.schema, encoding="utf-8")) if os.path.exists(args.schema) else {}
    rules = schema.get("rules", {})
    fmt = re.sub(r"[^a-z0-9]+", "_", (rules.get("format_name") or schema.get("game") or "format").lower()).strip("_")
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{fmt}.json")

    prev = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}

    events = json.load(open(args.events, encoding="utf-8")) if os.path.exists(args.events) else []
    om, names = own_meta(events)
    print(f"Own-data meta: {len(om['pokemon_usage'])} of your Pokemon, "
          f"{len(om['opponent_threats'])} opponent Pokemon faced.")

    type_chart = prev.get("type_chart", {})
    pokedex = prev.get("pokedex", {})
    if not args.no_fetch:
        try:
            print("Fetching type chart + Pokedex from PokeAPI...")
            type_chart = fetch_type_chart()
            pokedex = fetch_pokedex(names, pokedex)
            print(f"  mechanics: {len(type_chart)} types, {len(pokedex)} Pokemon cached.")
        except Exception as e:
            print(f"  (PokeAPI fetch failed: {str(e)[:80]} — keeping any cached mechanics.)")

    external_meta = prev.get("external_meta")
    external_moveset_meta = prev.get("external_moveset_meta")
    if not args.no_fetch and not args.no_external_meta:
        regulation = rules.get("regulation")
        if regulation:
            print(f"Fetching official Smogon usage stats for regulation {regulation}...")
            fetched = fetch_external_meta(regulation)
            if fetched:
                external_meta = fetched
                print(f"  external meta: tier {fetched['tier']}, {fetched['month']}, "
                      f"{len(fetched['pokemon_usage_pct'])} Pokemon, "
                      f"{fetched['total_battles']} total battles.")
            else:
                print("  (Smogon stats fetch failed/not yet published this month — "
                      "keeping any cached external meta.)")

            # Phase 1 of the live-coaching/damage-calculator roadmap (see
            # ARCHITECTURE_HANDOFF.md) - the richer per-species build
            # breakdown (abilities/items/EV spreads/moves/teammates), same
            # source, same regulation, fetched alongside the plain usage %
            # above rather than as a separate CLI step.
            print(f"Fetching official Smogon build breakdowns for regulation {regulation}...")
            fetched_ms = fetch_external_moveset_meta(regulation)
            if fetched_ms:
                external_moveset_meta = fetched_ms
                print(f"  external moveset meta: tier {fetched_ms['tier']}, {fetched_ms['month']}, "
                      f"{len(fetched_ms['movesets'])} Pokemon with build breakdowns.")
            else:
                print("  (Smogon moveset-stats fetch failed/not yet published this month — "
                      "keeping any cached external moveset meta.)")
        else:
            print("  (no rules.regulation in schema.json — skipping external meta fetch.)")

    out = {
        "format": rules.get("format_name") or schema.get("game"),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "rules": rules,
        "type_chart": type_chart,
        "pokedex": pokedex,
        "own_meta": om,
        "external_meta": external_meta,
        "external_moveset_meta": external_moveset_meta,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
