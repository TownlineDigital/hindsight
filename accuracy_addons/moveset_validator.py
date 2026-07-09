"""
Free, local (no API call) move-legality check against Pokemon Showdown's
own learnset data - the same class of fix as analyze_matches.py's
reject_banned_species() (which catches an implausible SPECIES read), applied
to MOVES instead. If OCR/vision reports "Pikachu used Hydro Pump," that's
checkable as immediately implausible - Pikachu has never legally learned
Hydro Pump in any generation - the same kind of misread the Staraptor/
Charizard bug (see ARCHITECTURE_HANDOFF.md's "Known bugs fixed" box) was
really an instance of, just for a move instead of a species.

Why Showdown's data specifically (not PokeAPI, which meta_build.py already
uses for the type chart/Pokedex): Showdown's learnset/format data is what
actually powers real ladder legality enforcement, so it's kept current fast
after every game patch or regulation rotation - more actively maintained for
CURRENT competitive legality specifically than a general-purpose reference
API. Source: https://github.com/smogon/pokemon-showdown/blob/master/data/learnsets.ts

CURRENT SCOPE (updated 2026-07-05 - full-dex export now generated and
verified, closing the gap this section used to describe):
  - `data/showdown_learnsets_full.json` is now present and IS the active
    DEFAULT_DATA_PATH - a real, generated (not fabricated) export covering
    818 species' complete gen-9 learnsets, produced by actually running
    `accuracy_addons/tools/export_showdown_learnsets.js` against the real
    @pkmn/data package (this sandbox's node_modules already had @pkmn/data
    and @pkmn/sim installed, so the earlier "npm registry blocked" problem
    that stopped this in an prior session no longer applied - the export
    ran clean, exit 0, no stderr). Spot-checked against every VGC-relevant
    species this project's real match footage actually features -
    Hydreigon, Primarina, Rotom, Incineroar, Whimsicott, Rillaboom,
    Kingambit, Bisharp - all present with real, non-empty learnsets (58-104
    moves each). `data/showdown_learnsets_starter.json` (the original
    15-species Gen-1-starters file) is kept on disk purely as the
    auto-detection fallback/test fixture described below - it's no longer
    what a real analyze_matches.py run actually uses.
  - A move's PRESENCE in a species' list means "this species has legally
    learned this move in gen 9, by some method" - the generation/level/
    method detail (Showdown's source codes like "9L12", "8M") is
    deliberately dropped, and only gen 9 is exported (see the export
    script's own comment: gen 9 = current-generation mechanics, matching
    what adapters/pokemon/regulations/*.json already targets for the
    current Pokemon Champions regulations). This is a lenient,
    ever-learned-in-this-generation check, not a strict "legal in the
    CURRENT regulation" check - deliberately, since the goal here is
    catching genuinely implausible reads (a move a species has NEVER been
    able to learn this generation), not fully replacing the hand-maintained
    format `rules` in adapters/pokemon/doubles.json, which already encodes
    current-regulation-specific legality (e.g. no Tera in Champions).
  - A species not present in the data returns None (unknown - not "every
    move is illegal for it"), the same "flag, don't force a guess" pattern
    used elsewhere in this pipeline. With the full-dex file in place this
    should now be rare - effectively only for species outside the gen-9
    dex entirely.
  - REAL DATA QUIRK FOUND (not a bug in this module - a Showdown-data
    observation, honestly left as-is rather than "fixed" by fabricating
    moves): Bisharp/Kingambit's export has no Sucker Punch or Rock Slide,
    which reads as surprising for a Pokemon famous for Sucker Punch - but
    it's what Showdown's own gen-9 learnsets.ts genuinely contains (Gen 9's
    move pools were broadly trimmed vs past generations; this project has
    no independent way to confirm whether that's accurate to the real
    Pokemon Champions title this project targets, or a Showdown-side gap).
    is_plausible_move("Kingambit", "Sucker Punch") returns False on real
    footage as a result - flagged here as a known, unresolved caveat rather
    than silently patched, per this project's own "flag, don't guess"
    convention.

Re-generating: `accuracy_addons/tools/export_showdown_learnsets.js` (Node,
official @pkmn/data package) can be re-run any time a game patch or new
regulation changes what's learnable - `cd accuracy_addons/tools && node
export_showdown_learnsets.js > ../data/showdown_learnsets_full.json`. TRULY
zero code changes needed after re-running it: this module always
auto-detects `data/showdown_learnsets_full.json` (see DEFAULT_DATA_PATH
below) the moment it exists on disk, so overwriting it with a fresher
export is picked up automatically on the next process start (module-level
load is cached per path within a process - see load_learnsets()'s cache).

TRUE FORMAT-SPECIFIC OVERRIDES (added 2026-07-05, closing a real accuracy gap
a user directly asked about - "does the system know what moves are legal in
what FORMATS, not just what generation"): the answer had been "no" up to this
point - everything above is a lenient "ever learnable in gen 9, ignoring
regulation" check, explicitly NOT format-specific, by design. This section
changes that for a real subset of species. Confirmed by directly browsing
Smogon's live GitHub repo (2026-07-05) that `data/mods/champions/` exists -
a genuine, dedicated Showdown mod for THIS game specifically (abilities.ts,
items.ts, learnsets.ts, moves.ts, rulesets.ts, scripts.ts, conditions.ts,
formats-data.ts - the full shape of a real format mod, not a stub). The
locally-installed `@pkmn/sim` npm package (0.10.11) predates this mod
entirely (its own `data/mods/` only goes up to `gen8legends` - no
`champions` folder at all), so `export_showdown_learnsets.js`'s output
above is vanilla Gen 9 (Scarlet/Violet) data, NOT Champions-specific data,
despite this whole project targeting Champions. That's a real, meaningful
gap: `data/mods/champions/learnsets.ts` is a DELTA file - only 48 species
have their own entry there (every other species, unlisted, falls through to
vanilla Gen 9 unchanged, standard Showdown mod-inheritance behavior) - and
for those 48, the override is NOT a superset. Real, confirmed examples
(fetched directly from
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/learnsets.ts
on 2026-07-05, not fabricated): Champions-Charizard can learn 72 moves vs.
vanilla Gen 9 Charizard's 129 - genuinely missing Dynamic Punch, False
Swipe, Fissure, Headbutt, Hidden Power, and 55 others that vanilla Gen 9
allows but this actual game does not - while separately gaining Ancient
Power, Bite, and Dragon Rush, which vanilla Gen 9 Charizard can't learn.
Raichu (66 vs 110), Ninetales-Alola (64 vs 118), Slowking-Galar (14 vs 151 -
a very tightly curated signature-move-focused forme), Politoed (57 vs 90),
and Arcanine-Hisui (64 vs 101) show the same pattern. This is a real,
material accuracy improvement for exactly these 48 species (mostly
long-standing fully-evolved lines whose classic-game movepools Champions
evidently curated down) - `is_plausible_move()` now checks TRUE Champions
legality for them, not just "ever learnable somewhere in gen 9."
`data/showdown_learnsets_champions_overrides.json` holds this real,
directly-fetched data (48 species, 3002 total move entries) and is merged
on top of the base full-dex data by `load_learnsets()` below, REPLACING
(not unioning with) those 48 species' entries - every other species (the
other ~770) is still governed by the lenient generation-wide check
described above, since Champions' own data has nothing to say about them
(they fall through to vanilla Gen 9 in the real client too). Re-fetch
`accuracy_addons/tools/fetch_champions_learnset_overrides.py`'s target URL
whenever the Champions mod itself is updated (new regulation, balance
patch) to refresh this file - see that script's own header for exactly how
(a plain HTTPS GET, no npm/node required at all, since GitHub serves the
raw mod source directly - this sidesteps the whole
npm-registry-sometimes-blocked problem the vanilla export has hit before).
"""

import json
import os
import re

_FULL_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "showdown_learnsets_full.json")
_STARTER_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "showdown_learnsets_starter.json")
_CHAMPIONS_OVERRIDES_PATH = os.path.join(
    os.path.dirname(__file__), "data", "showdown_learnsets_champions_overrides.json"
)


def _resolve_default_data_path(full_path=_FULL_DATA_PATH, starter_path=_STARTER_DATA_PATH):
    """Prefers the full-dex export the moment it exists on disk - see the
    module docstring's "TRULY zero code changes" note. Falls back to the
    15-species starter file (real data, just narrow coverage) if the full
    export hasn't been generated yet. Pulled out as its own function (rather
    than an inline expression) purely so a test can call it directly with
    fake paths, without needing to reload this whole module to exercise the
    fallback branch."""
    return full_path if os.path.exists(full_path) else starter_path


DEFAULT_DATA_PATH = _resolve_default_data_path()

_cache = {}


def _norm(name):
    """Same normalization convention as pokemon_identity.py's _norm() and
    analyze_matches.py's _canon() - lowercase, letters/digits only - so
    "Fire Blast", "fire-blast", "FIREBLAST" all compare the same way
    Showdown's own move ids do (Showdown ids are already exactly this
    format, e.g. "fireblast")."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _read_json_robust_encoding(path):
    """Reads and json-decodes `path` regardless of which text encoding it was
    saved with. Exists specifically because Windows PowerShell's `>`
    redirection (the exact command this project's own
    tools/export_showdown_learnsets.js usage instructions tell a user to run:
    `node export_showdown_learnsets.js > ../data/showdown_learnsets_full.json`)
    writes UTF-16LE-with-BOM by default, NOT UTF-8 - even though node itself
    printed plain UTF-8 text to stdout. A plain `open(path, encoding="utf-8")`
    chokes on that BOM (`UnicodeDecodeError: ... can't decode byte 0xff in
    position 0`) - confirmed for real against a file a user generated exactly
    this way. Rather than requiring every user to know to re-run the export
    with an extra `-Encoding utf8` flag, this sniffs the BOM and decodes
    correctly either way - the same "don't make the user work around a
    footgun we can absorb" spirit as this file's own auto-detecting
    DEFAULT_DATA_PATH."""
    with open(path, "rb") as f:
        raw_bytes = f.read()
    if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff"):
        # "utf-16" (no explicit -le/-be) auto-detects endianness FROM the BOM
        # and strips it from the decoded string. Using "utf-16-le"/"utf-16-be"
        # directly (an earlier version of this function did) decodes the BOM
        # bytes as a literal U+FEFF character instead of consuming it, which
        # then makes json.loads reject the string with a "Unexpected UTF-8
        # BOM" error - caught by this module's own tests against a real
        # UTF-16LE file before this shipped.
        text = raw_bytes.decode("utf-16")
    elif raw_bytes.startswith(b"\xef\xbb\xbf"):
        text = raw_bytes.decode("utf-8-sig")
    else:
        text = raw_bytes.decode("utf-8")
    return json.loads(text)


def load_learnsets(path=DEFAULT_DATA_PATH):
    """Loads (and caches, by path, so repeated calls in one process don't
    re-read the file) the species -> [move ids] mapping. Returns {} (not an
    error) if the file is missing, so a caller can distinguish "no data
    available, skip this check" from a real answer - the same
    fail-soft-not-fail-loud pattern as backend/audit.py.

    Champions-mod overrides (see module docstring's "TRUE FORMAT-SPECIFIC
    OVERRIDES" section) are merged in ONLY when `path` is the real
    `_FULL_DATA_PATH` - deliberately not for any other path (including the
    starter file or a caller-supplied custom/test path), so a test pointed
    at a synthetic fixture never has real production species data silently
    injected into it. Overrides REPLACE (not union with) the base data for
    each of their ~48 species - see `showdown_learnsets_champions_overrides.json`
    and its own fetch script for why a replace, not a merge, is correct
    here (Champions' own data for those species is a curated, deliberately
    NARROWER list than vanilla gen 9, not an addition to it)."""
    if path in _cache:
        return _cache[path]
    if not os.path.exists(path):
        print(f"[moveset_validator] no learnset data at {path} - checks will return None")
        _cache[path] = {}
        return _cache[path]
    raw = _read_json_robust_encoding(path)
    # normalize both species and move keys once at load time, not per call
    data = {_norm(species): {_norm(m) for m in moves} for species, moves in raw.items()}
    if path == _FULL_DATA_PATH and os.path.exists(_CHAMPIONS_OVERRIDES_PATH):
        overrides_raw = _read_json_robust_encoding(_CHAMPIONS_OVERRIDES_PATH)
        for species, moves in overrides_raw.items():
            data[_norm(species)] = {_norm(m) for m in moves}
    _cache[path] = data
    return data


def is_plausible_move(species, move, path=DEFAULT_DATA_PATH):
    """Returns True if `species` has ever legally learned `move` (any
    generation/method) per the loaded data, False if the species IS in the
    data but this move definitely isn't among its learnable moves, or None
    if `species` isn't covered by the currently-loaded data at all (see
    module docstring's coverage caveat - None means "can't check," not
    "fails the check"). Callers should treat None the same way
    pokemon_identity.py treats an unresolved nickname - not confidently
    wrong, just not yet checkable."""
    if not species or not move:
        return None
    data = load_learnsets(path)
    species_key = _norm(species)
    if species_key not in data:
        return None
    return _norm(move) in data[species_key]


_TRAILING_BRACKET = re.compile(r"\s*\[[^\]]*\]\s*$")
_FAILED_SUFFIX = re.compile(r"\s*\(failed[^)]*\)\s*$", re.IGNORECASE)   # "(failed)" AND "(failed due to Taunt)"
_BARE_FAILED_SUFFIX = re.compile(r"\s*failed\s*[!.]?\s*$", re.IGNORECASE)   # "Sacred Sword failed" (no parens)
_TRAILING_BANG = re.compile(r"\s*!\s*$")
_TRAILING_PERIOD = re.compile(r"\s*\.\s*$")
# "Muddy Water hit Garchomp (Effective)" / "Will-O-Wisp on Weavile (Scrafty on screen)."
# - in all three shapes the move name is the leading clause and everything
# from the connector word onward describes the TARGET/effectiveness/an
# unrelated on-screen annotation, not the move itself.
_HIT_OR_MISSED_SUFFIX = re.compile(r"\s+(?:hit|missed|on)\b.*$", re.IGNORECASE)
_BARE_USED_PREFIX = re.compile(r"^used\s+", re.IGNORECASE)
# "a Dark-type move" / "a Grass-type move" - real events where a vision read
# could only tell the MOVE'S TYPE, not its actual name (e.g. "Meowscarada used
# a Dark-type move on Primarina" - found on real footage 2026-07-05 during the
# accuracy-test pass that also found the two gaps above). This is not a move
# name at all - treating it as one produces a nonsense "implausible move"
# flag on every single occurrence, which is worse than useless (a human
# reviewer sees a flag that isn't checkable and can't be resolved by looking
# at the source frame - the frame already IS all the info there is). Returns
# None instead, the same "not a real name, don't force a guess" treatment
# _move_name already gives to a missing detail/move field entirely.
_VAGUE_TYPE_ONLY_MOVE = re.compile(r"^an?\s+\S+-type\s+move$", re.IGNORECASE)


def _strip_used_prefix(name, species):
    """Strips a leading "<Species> used ", "The opposing <Species> used ", or
    bare "used " wrapper - real battle-log sentence shapes found in this
    project's own jobs/ footage on 2026-07-05 while validating the full-dex
    learnset export (task #131) and again during a later accuracy-test pass
    the same day (task #139): e.g. detail="Hydreigon used Draco Meteor", "The
    opposing Primarina used Sparkling Aria!", or just "used Sparkling Aria"
    (the species isn't always repeated in the sentence - it's already known
    from the event's own `pokemon` field) - previously passed through to
    is_plausible_move() AS-IS, so the "move" being checked was actually the
    whole sentence, which normalizes to a string no real move id matches -
    a false "implausible" flag on a perfectly legal move, not a real
    legality catch. The species-specific prefixes are anchored to the
    event's OWN `pokemon` field (not a generic regex) so a move whose real
    name happens to contain "used" is never accidentally mangled; the bare
    "used " fallback is safe precisely because it only matches when "used"
    is the very FIRST word (`^used\\s+`) - a sentence naming a DIFFERENT
    Pokemon (e.g. "The opposing Hydreigon used Draco Meteor" attached to a
    `pokemon: "Porygon2"` event - a real species-misattribution bug this
    checker should keep catching, not paper over) never starts with the bare
    word "used", so it's left untouched and still correctly flagged."""
    if species:
        for prefix in (f"the opposing {species} used ", f"{species} used "):
            if name.lower().startswith(prefix.lower()):
                return name[len(prefix):]
    return _BARE_USED_PREFIX.sub("", name)


def _move_name(e):
    """Best-effort move name for a move_used event.

    REAL GAP FOUND while building decision_windows.py (2026-07-04): no code
    path in this project actually populates a structured `move` field on a
    real event. battle_text_parser.py's _event() (the OCR tier's own event
    builder) and every Gemini-vision-derived event both put the move name in
    `detail` instead (see doubles.json's own example_output: `{"event":
    "move_used", ..., "detail": "Hyper Voice"}` - no `move` key at all). That
    means this function's OLD `e.get("move")`-only lookup never actually
    matched a single real event - a second, more fundamental reason (beyond
    the already-documented 15-species learnset-coverage gap above) this
    check has found nothing on real jobs.

    Fixed the same pragmatic way decision_windows.py's own _move_name()
    does: prefer a structured `move` field if one's ever populated (future-
    proof), else fall back to `detail` (what's actually there today).

    SECOND ROUND of cleanup added 2026-07-05 while cross-checking the new
    full-dex learnset export against every real move_used event in jobs/
    (see moveset_validator.py's module docstring + task #131): roughly half
    of what looked like genuine "implausible move" flags turned out to be
    this function failing to unwrap a full battle-log SENTENCE rather than
    a bare move name - e.g. "Rotom used Discharge", "The opposing Primarina
    used Sparkling Aria!", "Muddy Water hit Garchomp (Effective)", "Sacred
    Sword failed" (no parens, so the old _FAILED_SUFFIX regex missed it).
    `detail` now goes through, in order:
      - strip a leading "<pokemon> used "/"The opposing <pokemon> used "
        wrapper (see _strip_used_prefix - anchored to the event's own
        `pokemon` field, not a blind regex).
      - repeatedly strip any trailing " [...]" bracketed annotation another
        accuracy check may have ALREADY appended (e.g. a reference-frame
        check's note, or a previous run of THIS function's own
        "[move-legality check: ...]" note on a re-run).
      - strip a trailing "!" (battle-log sentences, not move names, end
        with one).
      - strip a trailing " hit ..."/" missed ..." clause - in these
        specific two shapes the move name is the leading clause and the
        rest describes the TARGET/effectiveness, e.g. "Muddy Water hit
        Garchomp (Effective)" -> "Muddy Water". Deliberately narrow (only
        these two connector words) rather than a broader heuristic, since
        this project's "flag, don't guess" convention would rather leave a
        genuinely ambiguous sentence unparsed (falls through to returning
        the ungainly full string, which then correctly resolves to
        is_plausible_move() returning False/flagged - loud, not silently
        wrong) than confidently mis-split one.
      - strip a trailing "(failed ...)" parenthetical (broadened from the
        original exact "(failed)" to also match "(failed due to Taunt)")
        OR a bare trailing "failed" with no parens at all.

    KNOWN REMAINING GAP (not attempted here - see this function's own "flag,
    don't guess" spirit): sentences like "Protect blocked Thunder Punch" are
    genuinely ambiguous (Charizard's own move_used event, but is the "move"
    Charizard used Protect - the blocking move - or Thunder Punch, the
    incoming move Protect blocked? Almost certainly Protect, but this
    function does NOT special-case "Protect"/"Detect"/"Spiky Shield"/etc. by
    name to guess that - left as a real, undocumented-no-longer gap rather
    than a fabricated fix).

    THIRD ROUND of cleanup added 2026-07-05 (task #139), found by actually
    re-running the whole flag_implausible_moves() pipeline against every real
    jobs/*/events.json on disk (not just spot-checking a few species) as an
    end-to-end accuracy test of everything task #131/#138 shipped:
      - a bare "used <Move>" detail with NO species repeated at all (e.g.
        "used Sparkling Aria" - the species is already known from the
        event's own `pokemon` field, so the sentence doesn't always restate
        it) is now also stripped, not just the species-anchored "<Species>
        used ..." shape (see _strip_used_prefix's own docstring for why this
        is safe).
      - "<Move> on <target> (<annotation>)." - a trailing " on ..." clause
        (describing the TARGET, same spirit as the existing hit/missed
        clause strip) plus whatever parenthetical/period follows it is now
        stripped in one pass (_HIT_OR_MISSED_SUFFIX's alternation gained
        "on"), e.g. "Will-O-Wisp on Weavile (Scrafty on screen)." ->
        "Will-O-Wisp".
      - a detail that only describes the move's TYPE, not its actual name
        (e.g. "a Dark-type move" from "Meowscarada used a Dark-type move on
        Primarina") now returns None instead of being checked as a literal
        (and always-nonsense) move name - see _VAGUE_TYPE_ONLY_MOVE's own
        comment for why a flag here would be worse than useless."""
    name = e.get("move")
    if not name:
        name = str(e.get("detail") or "")
        name = _strip_used_prefix(name, e.get("pokemon"))
        while True:
            stripped = _TRAILING_BRACKET.sub("", name).strip()
            if stripped == name:
                break
            name = stripped
        name = _TRAILING_BANG.sub("", name).strip()
        name = _HIT_OR_MISSED_SUFFIX.sub("", name).strip()
        name = _TRAILING_PERIOD.sub("", name).strip()
    if not name:
        return None
    cleaned = _FAILED_SUFFIX.sub("", str(name)).strip()
    cleaned = _BARE_FAILED_SUFFIX.sub("", cleaned).strip()
    if not cleaned or _VAGUE_TYPE_ONLY_MOVE.match(cleaned):
        return None
    return cleaned


def flag_implausible_moves(events, path=DEFAULT_DATA_PATH):
    """Scans a list of events (the events.json shape - see
    ARCHITECTURE_HANDOFF.md section 4) for move_used events whose
    (pokemon, move) pairing is_plausible_move() confidently rejects, and
    lowers that event's confidence + appends a note to `detail` - the exact
    "flag, don't force a guess, don't silently drop it" pattern
    build_event_prompt() already uses for a roster mismatch (see the
    Staraptor/Charizard bug writeup) and pokemon_identity.py uses for an
    unresolved nickname. Does NOT touch events this module has no opinion on
    (anything without both a `pokemon` and a recognizable move name, or
    where is_plausible_move() returns None because the species isn't in the
    loaded data yet). Mutates and returns `events`.

    Move name comes from _move_name(e) - see its own docstring for why this
    now falls back to `detail` rather than requiring a `move` field nothing
    actually populates."""
    for e in events:
        if e.get("event") != "move_used":
            continue
        species, move = e.get("pokemon"), _move_name(e)
        if not species or not move:
            continue
        plausible = is_plausible_move(species, move, path)
        if plausible is False:
            e["confidence"] = min(e.get("confidence", 1.0), 0.3)
            e["detail"] = (
                (e.get("detail") or "")
                + f" [move-legality check: '{move}' is not in {species}'s known learnset - "
                  f"worth verifying against the source frame]"
            ).strip()
    return events
