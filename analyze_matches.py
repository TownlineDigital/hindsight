"""
PER-MATCH ANALYSIS - runs inside each match window from matches.csv.

For each match it:
  1. Reads the TEAM PREVIEW (a few frames just before the battle) -> both teams' rosters.
  2. Extracts battle frames densely and identifies events, with Pokemon CONSTRAINED to
     the known rosters (so "unknown" stops happening).
  3. Reads the RESULT screen at the end -> the winner.

It writes events.json / events.csv in the SAME format as before, so battle_record.py
and player_report.py work on the output unchanged - but now match-aware and accurate.

Run AFTER structure_pass.py (which makes matches.csv):
  py analyze_matches.py --video test.mp4
  py analyze_matches.py --video test.mp4 --limit 3        (test on first 3 matches)
  py analyze_matches.py --video test.mp4 --only 3,14,20   (re-analyze just these match numbers)
"""

import argparse
import concurrent.futures
import csv
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

import frame_dedup
import frame_quality
import gemini_batch

# moveset_validator is pure stdlib (json/os) - no extra dependency risk, same
# as flag_roster_conflicts/reject_banned_species, so it's imported and used
# unconditionally (see flag_implausible_moves' call sites) rather than gated
# behind a flag. hp_bar_reader/icon_template_matcher need cv2/numpy (already
# a hard requirement - see requirements.txt's opencv-python) but open and
# scan an image file PER relevant event, so they're kept behind the opt-in
# --use-accuracy-addons flag (see main()) the same way --use-ocr-tier gates
# ocr_pipeline - deliberate, measurable opt-in for newer/narrower-coverage
# tooling, not a silent default. See accuracy_addons/README.md and
# ARCHITECTURE_HANDOFF.md section 2e for what each tool does and doesn't
# cover yet.
from accuracy_addons import moveset_validator

try:
    from google import genai
    from google.genai import types
except ImportError:
    # Deliberately NOT sys.exit() here - that would kill the whole module (and
    # anything importing it, e.g. a test suite) even though most of this file
    # (species allowlist checks, name normalization, derive_brought, ...) is
    # pure logic that needs no API client at all. The dependency is only
    # actually required once something tries to call the API - see call()
    # and main(), which check _GENAI_IMPORT_ERROR and fail there instead.
    genai = None
    types = None
    _GENAI_IMPORT_ERROR = "Run:  pip install google-genai"
else:
    _GENAI_IMPORT_ERROR = None

# ALLOWLIST, not a blocklist. Pokemon Champions has a small CLOSED roster (~190-200
# species total, not the full Pokedex) - trying to enumerate everything that's NOT in
# it (Paradox, Legendaries, Mythicals, AND every regular Pokemon simply not added yet -
# Fletchinder, Amoonguss, Ogerpon, Cradily, Dondozo, Porygon2, Drapion all fall in that
# last bucket) is an unbounded, unwinnable list. Instead: only species confirmed to
# actually be IN the game are legal; anything else is disregarded as a misread.
#
# Source: Bulbapedia "List of Pokemon in Pokemon Champions" raw wikitext, fetched
# 2026-07-01 (186 species, Regulation M-A roster - the page itself was stale/behind
# the current M-B regulation, e.g. it still listed Metagross as absent). Cross-checked
# against this project's own footage + user confirmation for M-B-era additions.
# UPDATE THIS when the regulation changes (see the scheduled check already set up for
# 2026-08-26) - re-fetch https://bulbapedia.bulbagarden.net/w/index.php?action=raw&title=List_of_Pok%C3%A9mon_in_Pok%C3%A9mon_Champions
ALLOWED_SPECIES = {
    'abomasnow', 'absol', 'aegislash', 'aerodactyl', 'aggron', 'alakazam',
    'alcremie', 'altaria', 'ampharos', 'appletun', 'araquanid', 'arbok',
    'arcanine', 'archaludon', 'ariados', 'armarouge', 'aromatisse', 'audino',
    'aurorus', 'avalugg', 'azumarill', 'banette', 'basculegion', 'bastiodon',
    'beartic', 'beedrill', 'bellibolt', 'blastoise', 'camerupt', 'castform',
    'ceruledge', 'chandelure', 'charizard', 'chesnaught', 'chimecho', 'clawitzer',
    'clefable', 'cofagrigus', 'conkeldurr', 'corviknight', 'crabominable', 'decidueye',
    'dedenne', 'delphox', 'diggersby', 'ditto', 'dragapult', 'dragonite',
    'drampa', 'emboar', 'emolga', 'empoleon', 'espathra', 'espeon',
    'excadrill', 'farigiraf', 'feraligatr', 'flapple', 'flareon', 'floette',
    'florges', 'forretress', 'froslass', 'furfrou', 'gallade', 'garbodor',
    'garchomp', 'gardevoir', 'garganacl', 'gengar', 'glaceon', 'glalie',
    'glimmora', 'gliscor', 'golurk', 'goodra', 'gourgeist', 'greninja',
    'gyarados', 'hatterene', 'hawlucha', 'heliolisk', 'heracross', 'hippowdon',
    'houndoom', 'hydrapple', 'hydreigon', 'incineroar', 'infernape', 'jolteon',
    'kangaskhan', 'kingambit', 'kleavor', 'klefki', 'kommo-o', 'krookodile',
    'leafeon', 'liepard', 'lopunny', 'lucario', 'luxray', 'lycanroc',
    'machamp', 'mamoswine', 'manectric', 'maushold', 'medicham', 'meganium',
    'meowscarada', 'meowstic', 'milotic', 'mimikyu', 'morpeko', 'mr. rime',
    'mudsdale', 'ninetales', 'noivern', 'oranguru', 'orthworm', 'palafin',
    'pangoro', 'passimian', 'pelipper', 'pidgeot', 'pikachu', 'pinsir',
    'politoed', 'polteageist', 'primarina', 'quaquaval', 'raichu', 'rampardos',
    'reuniclus', 'rhyperior', 'roserade', 'rotom', 'runerigus', 'sableye',
    'salazzle', 'samurott', 'sandaconda', 'scizor', 'scovillain', 'serperior',
    'sharpedo', 'simipour', 'simisage', 'simisear', 'sinistcha', 'skarmory',
    'skeledirge', 'slowbro', 'slowking', 'slurpuff', 'sneasler', 'snorlax',
    'spiritomb', 'starmie', 'steelix', 'stunfisk', 'sylveon', 'talonflame',
    'tauros', 'tinkaton', 'torkoal', 'torterra', 'toucannon', 'toxapex',
    'toxicroak', 'trevenant', 'tsareena', 'typhlosion', 'tyranitar', 'tyrantrum',
    'umbreon', 'vanilluxe', 'vaporeon', 'venusaur', 'victreebel', 'vivillon',
    'volcarona', 'watchog', 'weavile', 'whimsicott', 'wyrdeer', 'zoroark',
    # Confirmed M-B additions - the FULL list of all 22 new base species added in
    # Regulation M-B, per StrataDex "All 22 New Pokemon in Pokemon Champions Reg
    # M-B" (fetched 2026-07-01, page dated "Updated 2026-06-19" - matches the
    # regulation's own June 16, 2026 start date): https://stratadex.net/guides/m-b-new-pokemon
    # (Earlier version of this list only had 6 of these 22 confirmed - Dragalge and
    # Qwilfish were being wrongly auto-rejected as illegal before this fix.)
    'metagross', 'mawile', 'grimmsnarl', 'sceptile', 'gholdengo', 'annihilape',
    'eelektross', 'blaziken', 'swampert', 'staraptor', 'scolipede', 'scrafty',
    'pyroar', 'malamar', 'barbaracle', 'dragalge', 'falinks', 'vileplume',
    'qwilfish', 'musharna', 'overqwil', 'houndstone',
    # Seen repeatedly in this project's footage without being flagged as wrong -
    # PROVISIONAL (not independently source-confirmed the way the rest of this list
    # is). If any of these turn out wrong, remove the one line; if a legal M-B
    # Pokemon gets wrongly rejected, add it the same way.
    'basculin', 'duraludon', 'girafarig', 'glimmet',
}
_ALLOWED_NORM = {re.sub(r"[^a-z0-9]", "", s) for s in ALLOWED_SPECIES}

# The hardcoded ALLOWED_SPECIES above is the CURRENT regulation's (M-B) roster,
# kept as a literal Python constant so every existing test/import of this module
# keeps working with zero file I/O and zero behavior change - see
# tests/test_species_legality.py, which has always exercised this exact data.
# It should be IDENTICAL to adapters/pokemon/regulations/m-b.json's own "species"
# list (test_regulation_loading.py's cross-check test catches the two drifting
# apart). --regulation (see configure_regulation() below) is the real mechanism
# for actually SWITCHING regulations at runtime - this constant is just the
# zero-configuration default for anything that never calls it.


def load_regulation(adapters_dir, regulation):
    """Loads one regulation's data (adapters/pokemon/regulations/<id>.json) -
    its species roster plus legal_mechanics/format_notes/active dates. Raises
    FileNotFoundError (with a clear message) if the file doesn't exist -
    callers decide how to handle that (configure_regulation turns it into a
    sys.exit, since an explicitly-requested regulation that doesn't exist
    should stop the run rather than silently keep whatever was loaded
    before)."""
    path = os.path.join(adapters_dir, "pokemon", "regulations", f"{regulation}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No regulation data file: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def configure_regulation(adapters_dir, regulation):
    """Switches the enforced species allowlist (ALLOWED_SPECIES/_ALLOWED_NORM)
    to the given regulation's roster, loaded from
    adapters/pokemon/regulations/<regulation>.json - this is what actually
    makes --regulation do something, rather than just being a label. Every
    function in this module that checks species legality
    (flag_banned_species, reject_banned_species, _species_base_norm, ...)
    reads these two module-level names directly, so overwriting them here
    (via `global`) is all that's needed - no other function needs to change
    to respect the chosen regulation.

    Called once, early in main(), for every run (including a resumed batch
    job) - so a job always has an explicit, correct allowlist rather than
    silently trusting whatever ALLOWED_SPECIES happened to default to at
    import time. Exits with a clear message if the requested regulation's
    file is missing or has an empty/malformed species list - refusing to
    silently run with an empty allowlist (which would reject every single
    Pokemon read as illegal) or a stale one."""
    global ALLOWED_SPECIES, _ALLOWED_NORM
    try:
        data = load_regulation(adapters_dir, regulation)
    except FileNotFoundError as e:
        sys.exit(f"{e} - run `py compose_schema.py --list` to see available regulations.")
    species = {str(s).strip().lower() for s in data.get("species", []) if str(s).strip()}
    if not species:
        sys.exit(f"Regulation '{regulation}' has no species list ({adapters_dir}/pokemon/regulations/"
                 f"{regulation}.json) - refusing to run with an empty allowlist.")
    ALLOWED_SPECIES = species
    _ALLOWED_NORM = {re.sub(r"[^a-z0-9]", "", s) for s in ALLOWED_SPECIES}
    return data


def check_regulation_staleness(adapter_rules, regulation_rules):
    """Runs accuracy_addons/format_rules_validator.py's cross-check once at
    job startup and prints anything it confirms is an actual MISMATCH -
    unlike the per-event accuracy_addons checks, this isn't a per-frame/
    per-event thing (see ARCHITECTURE_HANDOFF.md section 2e), it's a cheap,
    always-on staleness reminder: catching the hand-maintained adapter/
    regulation files quietly drifting from reality as VGC regulations rotate
    (they change every few months). Silent if the check finds no confirmed
    mismatch, or if the bundled Showdown snapshot data is missing entirely
    (accuracy_addons/data/showdown_champions_formats.json) - this never
    blocks a run, only informs it. "not_confirmable" results are deliberately
    NOT printed here (they're not wrong, just not checkable from this
    snapshot - see the module's own docstring for why) to keep this startup
    print short and only surface things actually worth a look."""
    try:
        from accuracy_addons import format_rules_validator
        results = format_rules_validator.cross_check_adapter_rules(
            adapter_rules, regulation_rules=regulation_rules)
    except Exception as e:
        print(f"  (regulation staleness check skipped: {str(e)[:80]})")
        return
    mismatches = [r for r in results if r.get("status") == "mismatch"]
    if mismatches:
        print("  ⚠ regulation-rules staleness check found possible drift from Showdown's own data:")
        for r in mismatches:
            print(f"    - {r['field']}: adapter says {r['adapter_value']!r}, "
                  f"Showdown says {r['showdown_value']!r}")
        print("    (see accuracy_addons/format_rules_validator.py - the adapter file may need updating)")


# Regional-form adjectives can appear as a PREFIX ("Alolan Ninetales") or a SUFFIX
# ("Ninetales-Alola" / "Ninetales Alola") depending on how the AI transcribes the
# on-screen name - both need stripping before the legality/dedup check.
_REGION_WORDS = r"(?:alolan?|galarian?|hisuian?|paldean?)"


def _species_base_norm(name):
    """Normalized base-species key, with Mega/regional/form annotations stripped -
    used both for the legality check and for Species Clause deduplication (Mega
    Evolution is a transformation of a Pokemon you already have, not a second team
    member - "Mawile" and "Mawile (Mega)" must count as ONE slot, not two).
    Prefix-matches against ALLOWED_SPECIES rather than blindly stripping trailing
    "-Word" so species whose own name has a hyphen (Kommo-o, Ho-Oh) aren't mangled.

    Also handles Pokemon Showdown's own notation (verified against Showdown's
    real protocol/replay format - see showdown_import.py): Showdown writes Mega
    Evolution as a SUFFIX, and X/Y megas specifically as "Species-Mega-X"/
    "Species-Mega-Y" (e.g. "Charizard-Mega-Y") - a real gap found when building
    Showdown replay support, since the original suffix regex only stripped a
    bare trailing "-Mega", not "-Mega-X"/"-Mega-Y"."""
    n = re.sub(r"\(.*?\)", "", str(name or ""))              # "Mawile (Mega)" -> "Mawile "
    n = re.sub(r"(?i)^mega\s+", "", n)                        # "Mega Mawile" -> "Mawile"
    n = re.sub(r"(?i)[\s\-]mega[\s\-][xy]$", "", n)           # "Charizard-Mega-Y"/"Charizard Mega X" -> "Charizard"
    n = re.sub(r"(?i)[\s\-]mega$", "", n)                     # "Mawile-Mega"/"Mawile Mega" -> "Mawile"
    n = re.sub(rf"(?i)^{_REGION_WORDS}\s+", "", n)            # "Alolan Ninetales" -> "Ninetales"
    n = re.sub(rf"(?i)[\s\-]{_REGION_WORDS}$", "", n)         # "Ninetales-Alola"/"Ninetales Alolan" -> "Ninetales"
    key = _norm(n)
    if key in _ALLOWED_NORM:
        return key
    for base in sorted(_ALLOWED_NORM, key=len, reverse=True):
        if base and key.startswith(base):
            return base
    return key   # not a known species - caller (flag_banned_species) treats as illegal


def flag_banned_species(names):
    """Return the subset of `names` that aren't a confirmed-legal species in this format.
    Skips None/empty entries - a blank isn't an illegal species, just nothing read."""
    return [n for n in names if n and _species_base_norm(n) not in _ALLOWED_NORM]


# The team-preview roster prompt used to be a single hardcoded constant that
# always described DOUBLES specifically ("both players' teams of 6", "which 4
# of the 6 each player has chosen to bring") - accurate for doubles, but
# actively wrong once singles became a real, user-selectable mode: per
# Serebii's Regulation M-A page (unchanged under M-B), a Singles team is
# whatever size the player registered (3-6) with NO separate "pick 4"
# team-preview step. build_roster_prompt() is parameterized on the composed
# schema's own `rules` (team_size/bring_count - see adapters/pokemon/
# doubles.json vs singles.json) so a singles job doesn't get asked a
# doubles-shaped question it can't sensibly answer.
def build_roster_prompt(rules=None):
    # rules=None means "no schema rules were threaded through at all" (an
    # older/external caller that doesn't know about this parameter) - that
    # must still get the ORIGINAL doubles-shaped prompt for backward
    # compatibility, not silently fall through to singles-shaped wording.
    # This is distinct from rules={} or singles.json's own rules (which
    # explicitly set "bring_count": null) - both of those are a real,
    # resolved schema saying "this mode has no bring-4 step", and correctly
    # take the singles branch below.
    if rules is None:
        rules = {"bring_count": 4, "team_size": 6}
    bring_count = rules.get("bring_count")
    team_size = rules.get("team_size")

    if bring_count:
        team_desc = (f"a Pokemon VGC DOUBLES team preview showing both players' teams of {team_size or 6}")
        bring_txt = (
            f"Also: Species Clause is in effect (no two of the same species on one team) - "
            f"if a Pokemon Mega Evolves mid-battle it is STILL THE SAME TEAM MEMBER, not a second "
            f"Pokemon; don't list both 'X' and 'X (Mega)' as if they were two different picks. The "
            f"selection screen highlights/checkmarks which {bring_count} of the {team_size or 6} each "
            f"player has chosen to bring - read that directly, don't guess. ")
        brought_field = (
            f'"player_brought": ["..the {bring_count} actually selected/highlighted, if the screen shows '
            f'the pick..."], "opponent_brought": ["..same for the opponent.."]')
        brought_fallback = ("If the selected-4 screen isn't visible in these frames, return an empty list "
                            "for player_brought/opponent_brought rather than guessing - do not leave it "
                            "out of the JSON.")
    else:
        # Singles-style: no separate team-preview "pick N of M" step - whatever
        # team was registered IS what's played with, so there's no second
        # "brought" concept distinct from the full team at all.
        team_desc = "a Pokemon VGC SINGLES team preview showing both players' teams"
        bring_txt = (
            "Also: Species Clause is in effect (no two of the same species on one team) - "
            "if a Pokemon Mega Evolves mid-battle it is STILL THE SAME TEAM MEMBER, not a second "
            "Pokemon; don't list both 'X' and 'X (Mega)' as if they were two different picks. "
            "There is NO separate 'pick 4' selection step in Singles - the whole team shown IS what "
            "gets played with, so leave player_brought/opponent_brought as empty lists; they don't "
            "apply here. ")
        brought_field = '"player_brought": [], "opponent_brought": []'
        brought_fallback = ""

    return (
        f"These frames are {team_desc}. "
        "Read the Pokemon SPECIES NAMES ONLY (as text/sprites) - the creature icons/portraits. "
        "Do NOT include held items, moves, Mega Stones, abilities, or any other UI text (e.g. 'Life Orb', "
        "'Focus Sash', 'Choice Scarf', 'Charizardite Y' are NOT Pokemon and must never appear in these "
        "lists) - only the Pokemon species themselves. IMPORTANT: Pokemon Champions has a SMALL, "
        "CLOSED roster for whichever regulation is currently active - only a specific set of Pokemon are "
        "in the game at all (no Paradox Pokemon, no Legendaries/Mythicals, and many otherwise-ordinary "
        "Pokemon simply aren't included yet). If a sprite looks unfamiliar or like something exotic, it "
        "is almost always a more common Pokemon that looks similar - read the on-screen NAME TEXT "
        "literally rather than guessing from the sprite alone. "
        "Some of the attached images are ADDITIONAL zoomed-in crops showing ONLY the opponent's "
        "icon-only team column - the opponent's side is frequently shown as icons alone with NO name "
        "text at all (unlike the player's own side, which is normally fully labeled), so these crops "
        "exist purely to make those icons bigger and easier to identify; use them alongside the full "
        "frames, not instead of them. Each row in that column also shows 1-2 small TYPE badge icons "
        "(Fire/Water/Dark/Steel/etc.) next to the sprite - when the sprite itself is too small or blurry "
        "to call confidently, use those type badges as a strong secondary clue: within this closed "
        "roster, a given type COMBINATION (e.g. Dark+Steel) usually only matches one or two possible "
        "species, so cross-check your best guess against the visible types rather than relying on the "
        "sprite silhouette alone. " + bring_txt +
        "Return ONLY JSON: "
        '{"player_team": ["...6.."], "opponent_team": ["...6.."], ' + brought_field + "}. "
        "Player = the streamer's own side. Best-guess any unclear name from the sprite. " + brought_fallback)

WINNER_PROMPT = (
    "These frames span from just before to well after the END of a Pokemon match - a result / "
    "win-loss screen, OR a forfeit/concede/disconnect screen, should appear somewhere in this range. "
    "A winner is ALWAYS determined in a completed match - only one side can have all of their brought "
    "Pokemon faint, or one side can forfeit/concede/disconnect (in which case the OTHER side won). "
    "Read any visible text literally: 'You win!'/'Victory' = player won; 'You lose!'/'Defeat' = "
    "opponent won; if a player's name is shown forfeiting/conceding/disconnecting, the OTHER player "
    "won. Look at every frame provided before giving up. "
    'Return ONLY JSON: {"winner": "player" | "opponent" | "unknown", "detail": "<the exact win/loss/forfeit '
    'text shown, or a brief description of the last visible board state if no explicit text appears>"}. '
    "Player = the streamer's own side. Only return \"unknown\" if truly nothing in ANY of these frames "
    "indicates who won - it should be rare.")


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    sys.exit("FFmpeg not found. Run: pip install imageio-ffmpeg")


def sample_window(ffmpeg, video, start, duration, fps, out_dir, prefix, hwaccel="", scale_w=640, quality=4):
    """quality is ffmpeg's mjpeg -q:v scale: 2 (best/least-compressed) to 31
    (worst). Default 4 is unchanged from before this parameter existed
    (battle-frame sampling, the dominant cost driver, stays exactly as it
    was). Gemini's vision cost is tokenized by image PIXEL DIMENSIONS
    (scale_w/fps here), not JPEG byte size/compression - so callers that
    pass a lower (better) quality for a low-frequency, high-value read (see
    read_roster's ROSTER_JPEG_QUALITY) get less compression-artifact noise
    at effectively zero added Gemini cost, distinct from bumping scale_w
    (which does cost more, since that changes actual pixel dimensions).

    CRASH-SAFE (fixed 2026-07-08): ffmpeg failing here used to propagate a
    raw subprocess.CalledProcessError all the way up through EVERY caller
    (read_roster, read_winner, and main()'s own battle-frame sampling) since
    none of them wrapped this specific call in a try/except - only the
    Gemini API calls further down each of those functions were protected.
    Real production case that found this: a --only run against 19 matches
    crashed and lost ALL of them (matches 14-21 never even attempted) when
    match 13 alone hit ffmpeg's mjpeg encoder rejecting a "Non full-range
    YUV" frame - which turned out to be a symptom of a bigger issue (see
    below), but the CRASH ITSELF was a separate, real robustness gap: one
    bad timestamp/frame anywhere in a multi-match batch should never be able
    to take down every other match's results with it. Every caller already
    treats an EMPTY frame list gracefully (`if not frames: continue`-style
    checks are already used everywhere this is called), so catching the
    failure here and returning [] instead of raising is a strict
    improvement with no caller changes needed - a failed window just
    contributes zero frames, exactly like a window that legitimately had
    nothing to sample.

    Investigating that real case further found the DEEPER root cause: the
    video file this happened on (vod_2814338033_fixed.mp4) is genuinely only
    03:02:50 (10970s) long, but matches.csv (from an earlier structure_pass.py
    run, apparently against a different/longer source) listed matches all the
    way out to 19770s - almost double the real video length. Matches 13-21
    simply have no footage in this file at all; ffmpeg failing/returning
    nothing there is the CORRECT outcome, not a bug in ffmpeg or this
    function - see main()'s new video-duration sanity check (added the same
    day) for the real fix to that specific problem. This crash-safety fix is
    still worth keeping regardless - "the video is shorter than expected"
    won't be the only way a single bad frame/timestamp can make ffmpeg
    fail, and none of those other ways should be able to lose an entire
    batch's results either."""
    os.makedirs(out_dir, exist_ok=True)
    pre = [ffmpeg, "-y", "-loglevel", "error"]
    if hwaccel:
        pre += ["-hwaccel", hwaccel]
    if start > 0:
        pre += ["-ss", str(start)]
    if duration > 0:
        pre += ["-t", str(duration)]
    pattern = os.path.join(out_dir, f"{prefix}_%05d.jpg")
    try:
        subprocess.run(pre + ["-i", video, "-vf", f"fps={fps},scale={scale_w}:-1", "-q:v", str(quality), pattern],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")[-300:]
        print(f"  ffmpeg sample_window failed (start={start:.1f}s, prefix={prefix}) - treating as 0 frames: "
              f"{stderr.strip() or str(e)}")
        return []
    files = sorted(f for f in os.listdir(out_dir) if f.startswith(prefix + "_"))
    return [(os.path.join(out_dir, f), start + i / fps) for i, f in enumerate(files)]


def _json_from_text(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"[\[{].*[\]}]", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


# Error substrings worth retrying: rate-limits AND transient server-side outages.
# The original version only retried 429/RESOURCE_EXHAUSTED - a 503 UNAVAILABLE
# (Google's model temporarily overloaded, common on gemini-3.5-flash) fell straight
# through to `raise`, which is why one bad patch of API capacity could quietly
# blank out several matches' rosters/winners in a row instead of waiting it out.
# "timeout"/"timed out" was added after a real production hang: a single
# generate_content() call stalled on the network with no exception at ALL
# (see CALL_TIMEOUT_MS below for the actual fix - this substring only matters
# for whatever timeout exception DOES eventually surface once that fires).
TRANSIENT_ERROR_MARKERS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                           "500", "INTERNAL", "504", "DEADLINE_EXCEEDED",
                           "timeout", "timed out")

# HARD BOUND on a single Gemini call, in milliseconds. Real production bug this
# fixes: analyze_matches.py got stuck "running" for HOURS on one match's roster
# read - client.models.generate_content() had no timeout at all, so a single
# stalled network request blocked the ENTIRE job forever (no exception, nothing
# for the retry loop in call() to even catch). 120s is generous for a vision
# call with several images attached; a genuinely healthy call finishes in
# seconds. Known SDK caveat (googleapis/python-genai#911): some SDK versions
# don't always honor this cleanly - if hangs recur even with this set, that's
# the next thing to escalate, but this is strictly better than no bound at all.
CALL_TIMEOUT_MS = 120_000


def call(client, model, prompt, paths, retries=5):
    if _GENAI_IMPORT_ERROR:
        sys.exit(_GENAI_IMPORT_ERROR)
    parts = [prompt]
    for p in paths:
        with open(p, "rb") as img:
            parts.append(types.Part.from_bytes(data=img.read(), mime_type="image/jpeg"))
    for attempt in range(retries):
        try:
            r = client.models.generate_content(
                model=model, contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.1,
                    http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS)))
            return _json_from_text(r.text)
        except Exception as e:
            transient = any(marker.lower() in str(e).lower() for marker in TRANSIENT_ERROR_MARKERS)
            if transient and attempt < retries - 1:
                wait = min(60, 5 * (2 ** attempt))   # 5s, 10s, 20s, 40s, 60s
                print(f"    ({model} busy, retry {attempt + 1}/{retries - 1} in {wait}s -> {str(e)[:70]})")
                time.sleep(wait)
                continue
            raise


def call_with_fallback(client, primary_model, fallback_model, prompt, paths):
    """Try the (usually stronger) primary model first; if it's STILL failing after
    all retries - a sustained outage on that specific model, not just a blip -
    fall back to the other model once rather than giving up and leaving the read
    blank. Only matters when the two models differ (--hard-model was actually set)."""
    try:
        return call(client, primary_model, prompt, paths)
    except Exception as e:
        if primary_model == fallback_model:
            raise
        print(f"    {primary_model} still unavailable, falling back to {fallback_model} -> {str(e)[:70]}")
        return call(client, fallback_model, prompt, paths)


WINNER_SEARCH_ATTEMPTS = [
    (10, 60, 1 / 2.5, 24),
    (5, 150, 1 / 3.1, 48),
]
WINNER_SCALE_W = 1024


def read_winner(client, hard_model, cheap_model, ffmpeg, video, end, workdir, hwaccel):
    """Find the winner for one match. Returns (winner, detail, had_failure)."""
    had_failure = False
    for i, (pre, dur, fps, cap) in enumerate(WINNER_SEARCH_ATTEMPTS):
        res = sample_window(ffmpeg, video, max(0, end - pre), dur, fps, workdir, f"res{i}", hwaccel, scale_w=WINNER_SCALE_W)
        if not res:
            continue
        try:
            w = call_with_fallback(client, hard_model, cheap_model, WINNER_PROMPT, [p for p, _ in res][:cap])
            if isinstance(w, dict):
                winner = str(w.get("winner", "unknown")).lower()
                detail = w.get("detail", "")
                if winner in ("player", "opponent"):
                    return winner, detail, had_failure
                if i < len(WINNER_SEARCH_ATTEMPTS) - 1:
                    print(f"  winner unclear on attempt {i + 1} ({dur:.0f}s window) - widening search and retrying...")
        except Exception as e:
            had_failure = True
            print(f"  winner read error (attempt {i + 1}) -> {str(e)[:80]}")
    return "unknown", "", had_failure


ROSTER_SEARCH_ATTEMPTS = [
    (90, 90, 1 / 9.0, 10),
    (150, 150, 1 / 7.5, 20),
    (60, 60, 1 / 6.0, 12),
    (120, 120, 1 / 8.0, 15),
    (180, 180, 1 / 10.0, 15),
]
ROSTER_SCALE_W = 1024   # FALLBACK ONLY - see detect_video_width() below; real
                        # roster reads now sample at this video's own NATIVE
                        # width instead (capped at ROSTER_SCALE_W_MAX), and only
                        # fall back to this fixed number if that probe fails.
ROSTER_SCALE_W_MAX = 2560   # sanity ceiling even when native resolution is
                            # higher than this (e.g. a future 4K source) - a
                            # deliberate, defensive cap against unbounded local
                            # ffmpeg/upload cost on unusually high-res footage,
                            # not a problem actually observed yet.
# ffmpeg -q:v for roster-read frames specifically (see sample_window's own
# docstring for why this is effectively free - Gemini tokenizes by pixel
# dimensions, not JPEG compression level). 2 is ffmpeg's best/least-lossy
# mjpeg setting; the shared default elsewhere (battle frames, the actual
# cost driver) stays at 4, untouched.
ROSTER_JPEG_QUALITY = 2
# NOTE: read_roster() used to gate its retry/widen logic on a
# ROSTER_MIN_ACCEPTABLE threshold (player_team length only) - removed along
# with that early-exit behavior when read_roster switched to always running
# every attempt and merging (_merge_roster_reads); see that function's own
# docstring for why a single "looks complete" sample was never sufficient.

# EXTENDED 2 -> 5 attempts (2026-07-07), at the user's own request, as a
# direct, measured test of "does more/better roster-read frames close the
# remaining opponent-roster gap" - see read_roster's own docstring for the
# honest evidence this responds to: two back-to-back re-runs of job
# 8c10092ac4a9 match 3, with IDENTICAL video/crops/resolution, still came
# back with a DIFFERENT opponent roster completeness (5/5 vs 4/5) purely
# from Gemini's own run-to-run variance - which argues the remaining gap may
# be model non-determinism / inherent icon-only-sprite ambiguity rather than
# frame starvation. Attempts 3-5 deliberately sample DIFFERENT fps/windows
# than 1-2 (not just a repeat) so each is a genuinely independent look
# (different exact frames/JPEG encodes of the same roster screen) for
# _merge_roster_reads' union to draw from, rather than 3 near-duplicate
# samples unlikely to add new information. This is a REAL cost increase
# (2.5x the roster-read Gemini calls per match - roster reads are the
# small/cheap side of the pipeline, not the bulk battle-event extraction
# that dominates spend, but it is not zero) - explicitly a paid experiment
# to measure, not assumed to help; if a re-test on real footage doesn't show
# a meaningful accuracy improvement over the 2-attempt version, this should
# be dialed back rather than kept on faith.

# Zoom bumped 4 -> 6 and crop cap 6 -> 8 after a real user benchmark
# comparison (job 8c10092ac4a9, manual match notes vs. the pipeline's own
# events.json) found opponent-roster accuracy ranging 2/6-5/6 across 5
# matches while the player's own (fully-labeled) side was 5/5 correct every
# time - the opponent icon column is the dominant source of misreads, so a
# larger zoomed crop (more pixels per icon) and more candidate crops per
# roster read (more distinct pre-match frames to draw from) are the direct,
# free (no extra Gemini calls - same images, just bigger/more of them) levers
# available before reaching for anything heavier.
OPPONENT_COLUMN_BOX = (0.78, 0.02, 1.0, 0.78)
OPPONENT_COLUMN_ZOOM = 6
OPPONENT_COLUMN_CROP_CAP = 8

_ROSTER_PANEL_HUE_RANGE = (300, 350)   # degrees
_ROSTER_PANEL_MIN_SAT = 0.25
_ROSTER_PANEL_MIN_VAL = 0.15
_ROSTER_PANEL_MIN_FRACTION = 0.15   # real noise measured <0.04; real panels measured ~0.45-0.51


def _looks_like_roster_panel(im, hue_range=_ROSTER_PANEL_HUE_RANGE,
                              min_sat=_ROSTER_PANEL_MIN_SAT, min_val=_ROSTER_PANEL_MIN_VAL,
                              min_fraction=_ROSTER_PANEL_MIN_FRACTION):
    """Cheap, free, purely-local heuristic: does this crop contain enough of
    the roster panel's distinctive magenta/maroon background to be worth
    spending API tokens on at all? Downsamples aggressively first since this
    only needs to be roughly right, not pixel-perfect - it's a noise filter,
    not a classifier that has to be exact."""
    import colorsys
    small = im.convert("RGB").resize((max(1, im.width // 8), max(1, im.height // 8)))
    pixels = list(small.getdata())
    if not pixels:
        return False
    hue_lo, hue_hi = hue_range
    matches = 0
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if hue_lo <= h * 360 <= hue_hi and s >= min_sat and v >= min_val:
            matches += 1
    return (matches / len(pixels)) >= min_fraction


def crop_opponent_icon_column(frames, box=OPPONENT_COLUMN_BOX, zoom=OPPONENT_COLUMN_ZOOM,
                               max_output=OPPONENT_COLUMN_CROP_CAP):
    """Given a list of (path, timestamp) tuples, crop each frame down to just
    the opponent's icon-only column, filter out crops that don't look like
    the roster panel, and save a zoomed-in copy of each survivor. Returns a
    plain list of the new cropped file paths."""
    if not frames:
        return []
    from PIL import Image
    left, top, right, bottom = box
    out = []
    for path, _ts in frames:
        if len(out) >= max_output:
            break
        try:
            with Image.open(path) as im:
                w, h = im.size
                box_px = (int(w * left), int(h * top), int(w * right), int(h * bottom))
                cropped = im.crop(box_px)
                if cropped.width <= 0 or cropped.height <= 0:
                    continue
                if not _looks_like_roster_panel(cropped):
                    continue
                zoomed = cropped.resize((cropped.width * zoom, cropped.height * zoom), Image.LANCZOS)
                out_path = os.path.splitext(path)[0] + "_oppcol.png"
                zoomed.save(out_path)
                out.append(out_path)
        except Exception:
            continue
    return out


# A SEPARATE box from OPPONENT_COLUMN_BOX above - that box (x 0.78-1.0) was
# tuned for the TYPE/status BADGES next to each row (what icon_template_matcher
# reads), and deliberately excludes the actual sprite art, which sits further
# left. Measured directly from a real frame (jobs/8c10092ac4a9/vod.mp4 at
# 70s, match 1) via a row-divider brightness scan: dividers land at a very
# consistent ~150px apart (in the ORIGINAL, un-zoomed frame's own pixel
# space) regardless of row depth, confirming a real fixed-height card layout,
# not a guessed one. A first attempt at this box also cut the 6th row off
# partway - that turned out to be this box's own bottom edge, not something
# actually missing from the game's UI (widening the box all the way to the
# bottom of the frame showed the real 6th row fully, undamaged) - so
# "opponent's 6th Pokemon is sometimes only partially visible" was WRONG;
# corrected here rather than carried into species_icon_matcher.py's docs.
OPPONENT_SPRITE_COLUMN_BOX = (0.655, 0.02, 0.76, 0.86)
OPPONENT_SPRITE_COLUMN_ZOOM = 2
OPPONENT_SPRITE_COLUMN_CROP_CAP = 8


def crop_opponent_sprite_column(frames, box=OPPONENT_SPRITE_COLUMN_BOX,
                                 zoom=OPPONENT_SPRITE_COLUMN_ZOOM,
                                 max_output=OPPONENT_SPRITE_COLUMN_CROP_CAP):
    """Same idea as crop_opponent_icon_column, but framed on the opponent's
    actual SPRITE ART column instead of the type/gender badges next to it -
    used by accuracy_addons/species_icon_matcher.py, which needs the sprite
    itself, not the badges. Kept as a separate function/box (rather than
    widening OPPONENT_COLUMN_BOX) so the existing, already-tuned badge crop
    used elsewhere is untouched."""
    if not frames:
        return []
    from PIL import Image
    left, top, right, bottom = box
    out = []
    for path, _ts in frames:
        if len(out) >= max_output:
            break
        try:
            with Image.open(path) as im:
                w, h = im.size
                box_px = (int(w * left), int(h * top), int(w * right), int(h * bottom))
                cropped = im.crop(box_px)
                if cropped.width <= 0 or cropped.height <= 0:
                    continue
                if not _looks_like_roster_panel(cropped):
                    continue
                zoomed = cropped.resize((cropped.width * zoom, cropped.height * zoom), Image.LANCZOS)
                out_path = os.path.splitext(path)[0] + "_oppsprite.png"
                zoomed.save(out_path)
                out.append(out_path)
        except Exception:
            continue
    return out


# Type-badge column box (used by accuracy_addons/team_preview_type_matcher.py).
# Found 2026-07-06 while investigating why OPPONENT_COLUMN_BOX (tuned for
# icon_template_matcher.py's move-type templates, which are the wrong scale
# for this specific UI element - see that discovery in
# team_preview_type_matcher.py's own docstring) only ever showed ONE of a
# row's two type badges: this box cleanly shows BOTH badges plus the gender
# icon below them, per row, confirmed against real frames from
# jobs/8c10092ac4a9/vod.mp4 (match 1, ~70s). Deliberately a separate box/
# function from crop_opponent_icon_column (still used by the existing
# Gemini-facing badge-reading prompt) and crop_opponent_sprite_column (sprite
# art only) - three different crops for three different real UI elements in
# the same panel, not three variations of one box.
OPPONENT_BADGE_COLUMN_BOX = (0.74, 0.02, 0.80, 0.86)
OPPONENT_BADGE_COLUMN_ZOOM = 2
OPPONENT_BADGE_COLUMN_CROP_CAP = 8


def crop_opponent_badge_column(frames, box=OPPONENT_BADGE_COLUMN_BOX,
                                zoom=OPPONENT_BADGE_COLUMN_ZOOM,
                                max_output=OPPONENT_BADGE_COLUMN_CROP_CAP):
    """Same idea as crop_opponent_sprite_column, but framed on the two
    type-badge icons (+ gender icon) next to each opponent sprite, instead of
    the sprite art itself - used by
    accuracy_addons/team_preview_type_matcher.py to identify each row's
    Pokemon type(s) directly from the badge icons (found, in real testing, to
    be a far more reliable signal than whole-sprite pixel correlation - see
    that module's docstring for the real validated numbers)."""
    if not frames:
        return []
    from PIL import Image
    left, top, right, bottom = box
    out = []
    for path, _ts in frames:
        if len(out) >= max_output:
            break
        try:
            with Image.open(path) as im:
                w, h = im.size
                box_px = (int(w * left), int(h * top), int(w * right), int(h * bottom))
                cropped = im.crop(box_px)
                if cropped.width <= 0 or cropped.height <= 0:
                    continue
                if not _looks_like_roster_panel(cropped):
                    continue
                zoomed = cropped.resize((cropped.width * zoom, cropped.height * zoom), Image.LANCZOS)
                out_path = os.path.splitext(path)[0] + "_oppbadge.png"
                zoomed.save(out_path)
                out.append(out_path)
        except Exception:
            continue
    return out


# LANDSCAPE variant of OPPONENT_BADGE_COLUMN_BOX, plus the row-slicing
# geometry team_preview_type_matcher.slice_badge_rows() needs alongside it.
# Found 2026-07-08: analyze_matches --only 3-12 against a real Twitch VOD
# (1280x720, 16:9 landscape stream capture) came back with attach_opponent_
# type_hints reporting a literal 0% confident-badge-read rate across all 10
# matches ("row(s) found badge-shaped component(s) that scored below the
# confidence threshold") - including match 3, where the user manually
# confirmed row 2's opponent Pokemon was genuinely Kingambit (Gemini's own
# vision read wrongly called it "Heracross") and row 5 was genuinely
# Vanilluxe (wrongly called "Alcremie"). Both are exactly the kind of
# misread apply_type_badge_override (task #204) was built to catch
# automatically - Kingambit is the unique Dark/Steel species in this
# format, Vanilluxe the unique mono-Ice one - but the override never got a
# chance because attach_opponent_type_hints found zero confident type
# reads on ANY row of ANY of these 10 matches.
#
# ROOT CAUSE, confirmed by direct reproduction against this video's own
# real team-preview frame (~1710s into the VOD): OPPONENT_BADGE_COLUMN_BOX
# above (0.74-0.80 of frame width) was tuned entirely from a PORTRAIT
# mobile recording (1290x2796 - see detect_video_width's own docstring).
# Applied unmodified to this LANDSCAPE (1280x720) frame, that x-range crops
# pure background stage-light decoration - zero Pokemon content at all, not
# even a badly-aligned badge. The correct opponent badge column on THIS
# video's own aspect ratio sits much further right (measured directly:
# x 0.895-0.975 of frame width cleanly isolates all 6 rows' real badges,
# confirmed by eye - Kingambit's actual dark-crescent + teal-diamond Dark/
# Steel badges are clearly visible and correctly cropped).
#
# A SECOND, independent bug compounded this: team_preview_type_matcher's
# ROW_TOP_FRAC/ROW_HEIGHT_FRAC (147.5/1083.6, 149.7/1083.6) assume a
# specific header-gap-before-row-1 proportion that was also measured from
# the SAME portrait source and does not transfer - even with the corrected
# box above, slicing with the original fractions still misaligned every
# row band. Measured directly against this landscape box (which is already
# cropped tightly to span exactly row 1's top through row 6's bottom, with
# no header gap included): the 6 rows divide the crop height EXACTLY
# evenly (540px crop / 6 = 90px per row, confirmed by inspecting the actual
# card-divider positions), so row_top_frac=0.0 and row_height_frac=1/6 are
# the correct values for THIS box - not team_preview_type_matcher's module
# defaults.
#
# REAL VALIDATION after both fixes (row_top_frac/row_height_frac passed
# explicitly to slice_badge_rows, landscape box used for the crop): re-run
# against the same real frame - row 0 (Blaziken) correctly identified
# Fire+Fighting, row 1 (Kingambit) correctly identified Dark+Steel (exactly
# the read that would have triggered apply_type_badge_override), row 2
# (Mimikyu) correctly identified Ghost+Fairy. Rows 3-5 did not reach a
# confident read on this SINGLE frame (partly obscured by an on-screen
# laser-light overlay crossing Garchomp's row, and a "0/4 Done" button
# overlapping the bottom two rows in this particular frame) - a single-
# frame limitation, not a geometry problem; identify_row_types_multi_frame's
# aggregation across the 5 real ROSTER_SEARCH_ATTEMPTS windows (many more
# frames, mostly without that specific overlay) is expected to recover
# these, the same way it already smooths over single-frame noise on the
# portrait footage this module was originally validated against.
#
# HONEST SCOPE: this fixes the badge-column geometry specifically (the
# piece apply_type_badge_override depends on). OPPONENT_COLUMN_BOX/
# OPPONENT_SPRITE_COLUMN_BOX (the Gemini-facing icon/sprite crops used to
# build the roster-read PROMPT itself) are the same class of portrait-
# tuned-fraction issue and likely also imprecise on landscape video, but
# were NOT re-measured/fixed here - Gemini's own vision read still mostly
# succeeded even with an imprecise crop on this video (it also sees the
# full, un-cropped frames), so this was scoped to the piece with a
# measured, total (0%) failure rather than a partial one. A real follow-up,
# not yet done.
LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX = (0.895, 0.13, 0.975, 0.88)
LANDSCAPE_ROW_TOP_FRAC = 0.0
LANDSCAPE_ROW_HEIGHT_FRAC = 1 / 6


def badge_column_geometry(width, height):
    """Returns (badge_box, row_top_frac, row_height_frac) appropriate for a
    video of the given pixel dimensions - see LANDSCAPE_OPPONENT_BADGE_
    COLUMN_BOX's own comment for the real, measured bug this fixes.

    `row_top_frac`/`row_height_frac` are None when the ORIGINAL portrait-
    tuned defaults (team_preview_type_matcher.ROW_TOP_FRAC/ROW_HEIGHT_FRAC)
    should be used instead of an override - callers (attach_opponent_type_
    hints) should treat None as "don't pass this kwarg, let slice_badge_
    rows' own default apply," not as a literal 0.

    Falls back to the original portrait geometry (None, None for the row
    fractions) whenever width/height can't be determined (an unknown
    orientation must never silently switch away from the ONE geometry this
    whole module has actually been validated against) or the video is
    portrait/square (width <= height) - landscape is specifically
    width > height, not just "not portrait," since an unusual video could
    be neither and should get the conservative, already-validated
    default."""
    if width and height and width > height:
        return LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX, LANDSCAPE_ROW_TOP_FRAC, LANDSCAPE_ROW_HEIGHT_FRAC
    return OPPONENT_BADGE_COLUMN_BOX, None, None


def _roster_sparsity(roster):
    """(worst_side_n, pteam_n, oteam_n) for one roster read. Keyed on the
    WORSE of the two sides deliberately: the player's own side is always
    fully labeled on screen and reads correctly almost immediately, so a
    metric based on player_team alone - what this function replaced - never
    actually caught a bad read. A real user benchmark comparison (job
    8c10092ac4a9, manual match notes vs. events.json) confirmed this
    directly: the player's own roster/brought/leads were correct in all 5
    matches, while opponent-roster accuracy ranged 2/6-5/6 match to match -
    because read_roster's old sparsity check only ever looked at
    player_team, attempt 1's already-complete player_team satisfied it
    immediately every time, so the wider, more-frames second attempt was
    never actually used to help the harder (opponent) side."""
    pteam_n = len(roster.get("player_team") or [])
    oteam_n = len(roster.get("opponent_team") or [])
    return min(pteam_n, oteam_n), pteam_n, oteam_n


def _merge_roster_reads(a, b, team_size=6):
    """Combine two independent roster reads into one. A single Gemini sample
    isn't fully reliable on its own - a real re-run of job 8c10092ac4a9 got
    WORSE on one match's opponent read purely from run-to-run model
    non-determinism between two otherwise-identical runs, and match 2's
    misread (Kingambit -> Heracross) happened even though that attempt's
    opponent_team already LOOKED complete (6/6), so "stop once it looks
    full" was never going to catch that kind of error anyway.

    Team lists are unioned - deduped via _species_base_norm (so a Mega/
    regional-form variant of a species already present isn't added as a
    second slot) and capped to `team_size`, so combining two wrong-but-
    different guesses can't inflate a team past its real size. Order is a's
    species first, then any new ones from b.

    Brought/pick-4 fields use whichever read is non-empty (preferring a,
    i.e. attempt 1, when both have one) - two DIFFERENT non-empty brought-4
    picks can't be soundly unioned the same way a full team list can,
    without risking more than `bring_count` entries."""
    def merge_team(key):
        out = list(a.get(key) or [])
        seen = {_species_base_norm(x) for x in out}
        for x in (b.get(key) or []):
            k = _species_base_norm(x)
            if k not in seen and len(out) < team_size:
                out.append(x)
                seen.add(k)
        return out

    return {
        "player_team": merge_team("player_team"),
        "opponent_team": merge_team("opponent_team"),
        "player_brought": a.get("player_brought") or b.get("player_brought") or [],
        "opponent_brought": a.get("opponent_brought") or b.get("opponent_brought") or [],
    }


def attach_opponent_type_hints(roster, badge_paths_by_attempt, MAX_ROW_TYPE_HINTS=6,
                                use_color_check=True, row_top_frac=None, row_height_frac=None):
    """Supplementary, NON-forcing signal for the opponent roster: runs
    accuracy_addons/team_preview_type_matcher.py's free, local (no extra
    Gemini call) type-badge identification over the crop_opponent_badge_
    column() crops already produced while sampling the roster read (see
    read_roster, which passes its own already-extracted frames here at zero
    extra cost), and attaches per-row candidate-species lists as
    roster["opponent_row_type_hints"] - informational only, the same
    "flag, don't force a guess" pattern already used elsewhere in this file
    for roster_conflict/likely_missed_opponent_species. This is deliberately
    NOT auto-applied to opponent_team/opponent_brought the way
    apply_likely_missed_species_correction is: team_preview_type_matcher.py's
    own HONEST CURRENT SCOPE docstring reports a real, strong candidate-list-
    recall result (42/42 on real footage) but validated against only ONE
    real match so far, and full both-badge accuracy is still frame-sensitive
    - not yet the kind of result this codebase trusts enough to overwrite a
    Gemini read the way the roster-conflict correction does.

    `use_color_check` (default True, added 2026-07-08 at the user's own
    request - "I think it will improve accuracy at scale, it's another
    metric to look at") is forwarded to identify_row_types_multi_frame(),
    which turns on the additive color-bonus cross-check (see
    team_preview_type_matcher.py's identify_badge_type_with_color and its
    module docstring's 2026-07-08 UPDATE). Honest framing: on the one real
    match this was measured against so far, the color check resolved zero
    additional badges by itself, but it also caused zero regressions (it
    can only raise a badge's score toward the threshold, never push a
    passing one back below it) - it's turned on here because it's a real,
    previously-unused signal that is safe by construction, not because
    single-match testing already proved a measurable lift. Pass
    use_color_check=False to fall back to the original shape-only
    behavior if this ever needs to be isolated for debugging.

    `row_top_frac`/`row_height_frac` (both default None, added 2026-07-08
    alongside badge_column_geometry()) override team_preview_type_matcher's
    own ROW_TOP_FRAC/ROW_HEIGHT_FRAC module defaults when given - see
    LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX's own comment (near
    crop_opponent_badge_column) for the real, measured bug this fixes: the
    module defaults were tuned against a portrait-oriented source and
    misslice every row band on a landscape video, even once the crop BOX
    itself is corrected. None (the default) means "don't override, use
    slice_badge_rows' own default" - this keeps existing callers (and the
    original portrait-video behavior) completely unchanged.

    `badge_paths_by_attempt` is a list of lists of crop_opponent_badge_
    column() output paths, one inner list per ROSTER_SEARCH_ATTEMPTS window
    - frames from every attempt are pooled together (not just one) so
    identify_row_types_multi_frame has more real material to vote over than
    a single attempt would offer alone (see that function's own docstring
    on why more frames help).

    No-op (leaves `roster` completely untouched) if
    accuracy_addons/cv2 aren't importable, if there are no badge crops to
    read at all, or if no row produces any confidently-identified type -
    this can only ADD an opponent_row_type_hints field, never change any
    other part of the roster. Mutates and returns `roster`.

    DIAGNOSTIC LOGGING (added 2026-07-07 after real matches 2/3/5 of job
    8c10092ac4a9 all came back with no hints at all - a gap the module's
    own real-footage validation, limited to one match's frames, never
    exercised): prints exactly which of the two possible reasons applies
    (no badge crops passed the panel-color filter at all vs. crops existed
    but none scored confidently) so a future run says WHY instead of
    silently producing nothing - the same "measure before guessing" method
    that root-caused the earlier Kingambit steel-badge bug (see
    ARCHITECTURE_HANDOFF.md section 2k).

    CONFIRMED 2026-07-07 via real re-test (job 8c10092ac4a9, "match 2"):
    "0 badge crop(s) passed the roster-panel color filter" turned out to be
    the color filter working CORRECTLY, not a bug in it - the re-test that
    surfaced this was accidentally reading a stale, unrelated root-level
    matches.csv (from a different, longer video) instead of this job's own
    jobs/8c10092ac4a9/matches.csv, because the run omitted --matches and the
    CLI used to default to matches.csv in the current directory (see
    --matches' own help text and main()'s new default-next-to-video logic
    below) - so the roster-search window it sampled was mid-battle footage
    with no team-preview screen in it at all, and the filter correctly
    found nothing to accept. Once re-tested against the RIGHT window, this
    diagnostic message may or may not still fire; if it does, that's real
    signal again."""
    try:
        from accuracy_addons import team_preview_type_matcher as tptm
        import cv2
    except ImportError as e:
        print(f"  type-badge hints: skipped - accuracy_addons/cv2 not importable ({str(e)[:80]})")
        return roster

    all_badge_paths = [p for attempt in badge_paths_by_attempt for p in attempt]
    if not all_badge_paths:
        print("  type-badge hints: 0 badge crop(s) passed the roster-panel color filter across "
              f"{len(badge_paths_by_attempt)} attempt(s) - skipping (see crop_opponent_badge_column/"
              "_looks_like_roster_panel; this module's templates/thresholds were only validated "
              "against one real match's frames so far, see team_preview_type_matcher.py)")
        return roster

    slice_kwargs = {}
    if row_top_frac is not None:
        slice_kwargs["row_top_frac"] = row_top_frac
    if row_height_frac is not None:
        slice_kwargs["row_height_frac"] = row_height_frac

    rows_by_index = [[] for _ in range(min(tptm.MAX_ROWS, MAX_ROW_TYPE_HINTS))]
    for path in all_badge_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        for i, row_img in enumerate(tptm.slice_badge_rows(img, max_rows=len(rows_by_index), **slice_kwargs)):
            if row_img is not None:
                rows_by_index[i].append(row_img)

    # Restrict the narrowing search to species actually legal in the
    # currently configured regulation (ALLOWED_SPECIES) - a tighter, more
    # relevant candidate list than the full 212-species data file offers.
    full_species_types = tptm.load_species_types()
    species_map = {sp: types for sp, types in full_species_types.items() if sp in ALLOWED_SPECIES}

    hints = []
    rows_with_crops = 0
    rows_with_unclassified_components = 0
    for i, row_crops in enumerate(rows_by_index):
        if not row_crops:
            continue
        rows_with_crops += 1
        result = tptm.identify_row_types_multi_frame(row_crops, use_color_check=use_color_check)
        if not result["identified_types"]:
            if any(count > 0 for count in result.get("badge_count_votes", {})):
                rows_with_unclassified_components += 1
            continue
        candidates = tptm.narrow_species_by_types(
            result["identified_types"], result["num_badges_found"],
            candidate_species_types=species_map or None)
        hints.append({
            "row": i,
            "identified_types": result["identified_types"],
            "num_badges_found": result["num_badges_found"],
            "n_frames_used": result["n_frames_used"],
            "candidate_species": candidates,
        })
    if hints:
        roster["opponent_row_type_hints"] = hints
        print(f"  type-badge hints: {len(hints)}/{rows_with_crops} row(s) with badge crops got a "
              "confident type read")
    elif rows_with_crops:
        print(f"  type-badge hints: {rows_with_crops} row(s) had badge crops, but none reached a "
              f"confident type match ({rows_with_unclassified_components} row(s) found badge-shaped "
              "component(s) that scored below the confidence threshold - see "
              "team_preview_type_matcher.py's MIN_BADGE_MATCH_SCORE)")
    return roster


def apply_type_badge_override(roster):
    """Overrides a row's opponent_team species guess when this row's
    type-badge read (see attach_opponent_type_hints/opponent_row_type_hints,
    called right before this in read_roster()) uniquely identifies exactly
    ONE legal species and that differs from Gemini's own sprite-based guess
    at the same row - the real, found case this was built from: match 1 of
    the 2026-07-08 Twitch VOD run had a row showing Kingambit's actual icon
    (dark bipedal body, gold blade) next to two clean Dark+Steel badges -
    Kingambit is the ONLY Dark/Steel dual-type in this format's 212-species
    legal pool - but Gemini's own roster read called that row "Heracross"
    (a completely different-looking Bug/Fighting species) anyway. The user
    confirmed by eye that the badges were correct and asked for exactly this
    kind of case to override the guess instead of just noting it.

    Deliberately more conservative than a blanket "trust the badges" rule -
    attach_opponent_type_hints stays informational-only in the general case
    (see its own docstring: the matcher's real-footage validation is still
    limited to a handful of real matches, not enough to trust broadly) -
    this override only fires when EVERY one of these holds:
      - the row's candidate_species list has EXACTLY ONE entry (the type
        combination is unique across the whole legal pool - no ambiguity
        left for a wrong badge read or a coincidental type overlap to hide
        behind)
      - both badge slots were confidently read (num_badges_found == 2) - a
        single-badge partial match (see narrow_species_by_types) is a
        broader, less certain signal and is not trusted enough to override
      - the row index is a valid position in roster["opponent_team"]
        (nothing to replace otherwise)
      - the unique candidate isn't ALREADY the name at that row (nothing to
        do), and doesn't already appear ELSEWHERE in opponent_team - Species
        Clause forbids duplicates on one team, so if the candidate is
        already present elsewhere, this is far more likely a row-ordering
        mismatch between the badge column and Gemini's own list order (the
        roster prompt never explicitly pins the two to the same order) than
        a genuine correction, so this backs off rather than risk creating a
        duplicate or clobbering a row that was actually right.

    Mutates and returns `roster`. Adds roster["type_badge_overrides"] (a
    list of {row, was, now, identified_types} dicts) documenting exactly
    what changed and why - the same "don't silently correct, write down
    what happened" pattern already used for team_preview_event.manual_
    correction and likely_missed_opponent_species elsewhere in this file.
    No-op (roster unchanged, no new field added) if there is nothing to
    override."""
    hints = roster.get("opponent_row_type_hints")
    oteam = roster.get("opponent_team")
    if not hints or not isinstance(oteam, list):
        return roster
    overrides = []
    for hint in hints:
        candidates = hint.get("candidate_species") or []
        if len(candidates) != 1:
            continue
        if hint.get("num_badges_found") != 2:
            continue
        row = hint.get("row")
        if row is None or row < 0 or row >= len(oteam):
            continue
        candidate = candidates[0]
        current = oteam[row]
        if _norm(current) == _norm(candidate):
            continue
        if any(_norm(sp) == _norm(candidate) for j, sp in enumerate(oteam) if j != row):
            continue
        overrides.append({"row": row, "was": current, "now": candidate,
                          "identified_types": hint.get("identified_types")})
        oteam[row] = candidate
    if overrides:
        roster["type_badge_overrides"] = overrides
        for o in overrides:
            print(f"  type-badge OVERRIDE: row {o['row']} '{o['was']}' -> '{o['now']}' "
                  f"(types {o['identified_types']} uniquely identify this species in this format)")
    return roster


def detect_video_dimensions(ffmpeg, video):
    """Returns (width, height) as ints, read from ffmpeg's own stream-info
    banner (same probe call detect_video_width/detect_video_duration each
    use - metadata only, no real decode, fast and safe to call once per
    match), or (None, None) if it can't be determined. Callers MUST treat
    (None, None) as "unknown" and fall back to fixed defaults rather than
    let a probe failure crash the run.

    Added 2026-07-08 alongside badge_column_geometry() below:
    detect_video_width's own regex already captured BOTH width and height
    in one match, but the function only ever returned the width - this
    exposes both from the SAME single ffmpeg call (no extra process spawned)
    so a video's ORIENTATION (portrait vs landscape) can be determined too,
    not just its width. See badge_column_geometry's own docstring for the
    real, found bug this lets read_roster() fix: the whole opponent-badge-
    column geometry (OPPONENT_BADGE_COLUMN_BOX + team_preview_type_matcher's
    ROW_TOP_FRAC/ROW_HEIGHT_FRAC) was tuned entirely from one PORTRAIT
    mobile recording (1290x2796) and produces pure background noise - zero
    real badge content - when applied unmodified to a LANDSCAPE (16:9)
    stream capture."""
    try:
        result = subprocess.run([ffmpeg, "-i", video], stderr=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, text=True, timeout=15)
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def detect_video_width(ffmpeg, video):
    """Returns this video's native pixel width, or None if it can't be
    determined - e.g. an unusual container/codec whose stderr the shared
    regex doesn't match, or the file being unreadable. Callers MUST treat
    None as "unknown" and fall back to a fixed default (see ROSTER_SCALE_W)
    rather than let a probe failure crash the run.

    Added 2026-07-07 at the user's own request, after real per-pixel math
    on this exact video (see the cost discussion this session, and
    ROSTER_SCALE_W_MAX's own comment) found: (1) this video's real native
    resolution is 1290x2796 - ABOVE the fixed 1024px roster-read default,
    meaning that default was leaving real, free detail on the table; (2)
    Gemini's own documented image-tiling formula (tokens scale with
    ceil(dimension/crop_unit), where crop_unit is itself derived from the
    image's own dimensions) makes token cost roughly resolution-INVARIANT
    for a fixed aspect ratio - so sampling at native resolution instead of
    an arbitrary fixed guess costs about the same, not dramatically more.

    Delegates to detect_video_dimensions() (added 2026-07-08) rather than
    probing separately - same single ffmpeg call, this just keeps the
    width-only call sites (e.g. ROSTER_SCALE_W_MAX capping) unchanged."""
    return detect_video_dimensions(ffmpeg, video)[0]


def detect_video_duration(ffmpeg, video):
    """Returns this video's real total duration in seconds (parsed from
    ffmpeg's own "Duration: HH:MM:SS.ms" stream-info line, same probe call
    as detect_video_width - one `ffmpeg -i` invocation, no real decode), or
    None if it can't be determined. Callers MUST treat None as "unknown" and
    skip the sanity check rather than assume anything.

    Added 2026-07-08 after a real, concrete case: a 21-match matches.csv had
    matches all the way out to 19770s (5.49h), but the actual video file
    (vod_2814338033_fixed.mp4) is genuinely only 03:02:50 (10970s) long -
    matches 13-21 had literally no footage in this file at all (likely
    matches.csv was generated by an earlier structure_pass.py run against a
    different/longer source - see main()'s own sanity-check comment for how
    this gets surfaced to the user rather than silently attempted). Without
    this check, main() would try to sample well past the real end of the
    file for every one of those matches - which used to CRASH the entire
    run the first time ffmpeg hit a truly unreadable timestamp there (see
    sample_window's own crash-safety fix, added the same day) instead of
    cleanly explaining why those matches can't be processed from this
    file."""
    try:
        result = subprocess.run([ffmpeg, "-i", video], stderr=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, text=True, timeout=15)
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stderr or "")
        if m:
            hours, minutes, seconds = m.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        pass
    return None


def filter_matches_within_video_duration(matches, ffmpeg, video):
    """Drops any (idx, start, end) whose START is at/beyond this video's real
    duration (see detect_video_duration) and prints a clear explanation -
    the real, found alternative to letting ffmpeg fail/crash deep inside
    read_roster or read_winner for a match with no footage at all in this
    file (see sample_window's own crash-safety fix for the other half of
    this real production bug). Deliberately checks START only, not END: a
    match whose start is legitimately inside the video but whose end
    overruns slightly (e.g. the video cuts off mid-match) still has SOME
    real footage worth attempting - read_roster/read_winner/sample_window
    already degrade gracefully (return no frames) for whatever tail portion
    doesn't exist, per sample_window's own crash-safety fix, rather than
    needing this coarser per-match filter to handle that case too.

    No-op (returns `matches` unchanged) if the duration probe fails - an
    unknown duration must never silently exclude real, processable matches."""
    duration = detect_video_duration(ffmpeg, video)
    if duration is None:
        return matches
    kept, dropped = [], []
    for idx, start, end in matches:
        if start >= duration:
            dropped.append((idx, start, end))
        else:
            kept.append((idx, start, end))
    if dropped:
        video_hms = f"{int(duration // 3600)}:{int((duration % 3600) // 60):02d}:{duration % 60:05.2f}"
        print(f"  ⚠ {len(dropped)} match(es) start at or past this video's actual length ({video_hms}) - "
              f"skipping (no footage in this file for them, not an error): "
              f"{[idx for idx, _, _ in dropped]}")
        print(f"    If this video is supposed to be longer, matches.csv may have been generated against a "
              f"different/longer source - re-run structure_pass.py against THIS video to get accurate "
              f"match windows.")
    return kept


def read_roster(client, hard_model, cheap_model, ffmpeg, video, start, workdir, hwaccel, rules=None):
    """Read the team-preview roster. Returns (roster_dict, had_failure).

    Runs EVERY configured ROSTER_SEARCH_ATTEMPTS window unconditionally and
    merges the results (see _merge_roster_reads), rather than stopping at
    the first attempt that merely looks "good enough" the way this function
    used to. See _merge_roster_reads' docstring for why a single sample
    isn't trusted alone anymore. This costs exactly len(ROSTER_SEARCH_ATTEMPTS)
    Gemini calls per match's roster read now (previously as few as 1, when
    attempt 1's player_team/opponent_team already cleared
    ROSTER_MIN_ACCEPTABLE; bumped 2 -> 5 attempts 2026-07-07, see
    ROSTER_SEARCH_ATTEMPTS' own comment for the real evidence behind that
    change and its honest cost tradeoff) - a deliberate, bounded (not
    unbounded retries) trade of a bit more cost for not depending on one
    roll of the dice for the harder (opponent) side.

    Frames are sampled at ROSTER_JPEG_QUALITY (a less-compressed JPEG
    setting than the shared battle-frame default) - effectively free, since
    Gemini's cost is driven by pixel dimensions, not compression level; see
    sample_window's own docstring. Frame WIDTH now defaults to this video's
    own native resolution (see detect_video_width), capped at
    ROSTER_SCALE_W_MAX, rather than the fixed ROSTER_SCALE_W guess - falling
    back to that fixed value only if the probe fails.

    Also runs attach_opponent_type_hints (free, local, zero extra Gemini
    cost - see that function's own docstring) over the SAME frames already
    sampled for each attempt above, via crop_opponent_badge_column - a
    purely additive, non-forcing supplementary signal on the returned
    roster dict. The badge-column BOX and row-slicing geometry passed to
    both of those are chosen via badge_column_geometry() based on this
    video's own detected orientation (portrait vs landscape) - see that
    function's own comment (near LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX) for
    the real, measured bug this fixes (a portrait-tuned geometry produces a
    0% confident-badge-read rate on landscape footage)."""
    had_failure = False
    roster_prompt = build_roster_prompt(rules)
    team_size = (rules or {}).get("team_size") or 6
    reads = []
    badge_paths_by_attempt = []
    native_width, native_height = detect_video_dimensions(ffmpeg, video)
    roster_scale_w = min(native_width, ROSTER_SCALE_W_MAX) if native_width else ROSTER_SCALE_W
    badge_box, row_top_frac, row_height_frac = badge_column_geometry(native_width, native_height)
    print(f"  roster frames: sampling at {roster_scale_w}px wide "
          f"({'video native res, capped at ' + str(ROSTER_SCALE_W_MAX) if native_width else 'fallback default'}"
          f"{', ' + str(native_width) + 'px native' if native_width else ''})")
    for i, (pre, dur, fps, cap) in enumerate(ROSTER_SEARCH_ATTEMPTS):
        prev = sample_window(ffmpeg, video, max(0, start - pre), min(dur, start), fps,
                             workdir, f"prev{i}", hwaccel, scale_w=roster_scale_w,
                             quality=ROSTER_JPEG_QUALITY)
        if not prev:
            continue
        try:
            capped = prev[:cap]
            crop_paths = crop_opponent_icon_column(capped)
            r = call_with_fallback(client, hard_model, cheap_model, roster_prompt,
                                    [p for p, _ in capped] + crop_paths)
            roster = r if isinstance(r, dict) else {}
        except Exception as e:
            had_failure = True
            print(f"  roster read error (attempt {i + 1}) -> {str(e)[:80]}")
            roster = {}
        _worst_n, pteam_n, oteam_n = _roster_sparsity(roster)
        print(f"  roster attempt {i + 1}: player_team={pteam_n} opponent_team={oteam_n}")
        reads.append(roster)
        try:
            badge_paths_by_attempt.append(crop_opponent_badge_column(capped, box=badge_box))
        except Exception:
            badge_paths_by_attempt.append([])
    if not reads:
        return {}, had_failure
    merged = reads[0]
    for r in reads[1:]:
        merged = _merge_roster_reads(merged, r, team_size=team_size)
    attach_opponent_type_hints(merged, badge_paths_by_attempt,
                                row_top_frac=row_top_frac, row_height_frac=row_height_frac)
    apply_type_badge_override(merged)
    return merged, had_failure


def parse_events(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("events", "results", "data"):
            if isinstance(data.get(k), list):
                return data[k]
        if "event" in data:
            return [data]
    return []


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _canon(name, name_map):
    """Match an event's Pokemon name to the known roster (exact, then light fuzzy)."""
    key = _norm(name)
    if key in name_map:
        return name_map[key]
    for k, v in name_map.items():
        if k and (k.startswith(key) or key.startswith(k) or key in k or k in key):
            return v
    return name.strip()


def names_of(value):
    """Return a clean list of Pokemon names from whatever shape the AI returned."""
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, dict):
        n = value.get("name") or value.get("pokemon") or value.get("species")
        return [str(n).strip()] if n else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("pokemon") or item.get("species")
                if n:
                    out.append(str(n).strip())
        return out
    return [str(value).strip()]


def derive_brought(events, roster, rules=None):
    """The CHOSEN N = the Pokemon that actually appeared on each side during the match,
    matched to the known roster. Lead = the first `active_per_side` that appeared.
    Order = appearance.

    `rules` (the composed schema's own "rules" dict) makes this mode-aware:
    doubles brings up to 4 of 6 with 2 active per side, while singles has NO
    separate "brought" concept at all and only 1 active per side."""
    if rules is None:
        rules = {"bring_count": 4, "active_per_side": 2}
    active_per_side = rules.get("active_per_side") or 2
    bring_count = rules.get("bring_count")
    brought_cap = bring_count if bring_count else (rules.get("team_size_max") or rules.get("team_size") or 6)

    pmap = {_norm(n): n for n in (roster.get("player_team") or [])}
    omap = {_norm(n): n for n in (roster.get("opponent_team") or [])}

    def ts(e):
        try:
            return float(e.get("timestamp"))
        except (TypeError, ValueError):
            return 0.0

    single = {"move_used", "pokemon_sent_out", "pokemon_fainted", "terastallized",
              "hp_change", "status_inflicted", "item_or_ability_activated"}
    p_seen, o_seen = [], []
    p_species_seen, o_species_seen = set(), set()   # Species Clause: "X" and "X (Mega)" are ONE slot
    for e in sorted(events, key=ts):
        ev = str(e.get("event", ""))
        side = str(e.get("actor", "")).lower()
        pairs = []
        if ev in single and e.get("pokemon"):
            for nm in names_of(e.get("pokemon")):
                pairs.append((side, nm))
        if ev == "field_state":
            for nm in names_of(e.get("player_active")):
                pairs.append(("player", nm))
            for nm in names_of(e.get("opponent_active")):
                pairs.append(("opponent", nm))
        for s, nm in pairs:
            if flag_banned_species([nm]):
                continue   # can't legally exist in this format - disregard entirely, don't guess
            species_key = _species_base_norm(nm)
            if s == "player":
                c = _canon(nm, pmap) if pmap else nm.strip()
                if c and species_key not in p_species_seen:
                    p_seen.append(c)
                    p_species_seen.add(species_key)
            elif s == "opponent":
                c = _canon(nm, omap) if omap else nm.strip()
                if c and species_key not in o_species_seen:
                    o_seen.append(c)
                    o_species_seen.add(species_key)
    return p_seen[:brought_cap], o_seen[:brought_cap], p_seen[:active_per_side], o_seen[:active_per_side]


# Some Pokemon were cut from Champions' roster entirely, but their EVOLVED
# form was kept - Bisharp isn't in the game at all, but Kingambit (what it
# evolves into) is. Keys are normalized (_species_base_norm) lowercase;
# extend this dict if other similar cut-pre-evolution cases turn up.
EVOLUTION_SUBSTITUTES = {
    "bisharp": "Kingambit",
}


def _substitute_known_evolutions(names):
    """Replace any name matching a documented cut-pre-evolution
    (EVOLUTION_SUBSTITUTES) with its legal evolution, before banned-species
    rejection ever runs. Names not in the map pass through unchanged."""
    out = []
    for n in names:
        if not n:
            out.append(n)
            continue
        sub = EVOLUTION_SUBSTITUTES.get(_species_base_norm(n))
        out.append(sub if sub else n)
    return out


def reject_banned_species(names):
    """Remove species that can't legally exist in this format entirely - treated as if
    never detected, not kept-with-a-warning. Returns (clean_list, rejected_list)."""
    names = [n for n in names if n]
    names = _substitute_known_evolutions(names)
    banned = set(flag_banned_species(names))
    if not banned:
        return list(names), []
    return [n for n in names if n not in banned], sorted(str(b) for b in banned)


_RAW_READ_RE = re.compile(r"Read\s+(.+?)\s+on screen", re.IGNORECASE)
_SUBSTITUTE_RE = re.compile(r"reporting closest match(?:es)?,?\s*(.+?)\.", re.IGNORECASE)


def _extract_names(chunk):
    """Pulls individual names out of a "'A' and 'B'"-style (or plain "A and B")
    fragment, in order."""
    quoted = re.findall(r"'([^']+)'", chunk)
    if quoted:
        return [q.strip() for q in quoted if q.strip()]
    return [p.strip() for p in re.split(r",|\band\b", chunk, flags=re.IGNORECASE) if p.strip()]


def detect_roster_conflict_species(detail):
    """Scans one event's `detail` text for the roster-substitution pattern.
    Returns the list of RAW read name(s) that ARE a real, legal species in the
    currently configured regulation but weren't in this match's identified
    roster - empty list if the text doesn't match this pattern at all."""
    if not detail:
        return []
    if "reporting closest match" not in detail.lower():
        return []
    raw_match = _RAW_READ_RE.search(detail)
    sub_match = _SUBSTITUTE_RE.search(detail)
    if not raw_match or not sub_match:
        return []
    raw_names = _extract_names(raw_match.group(1))
    return [n for n in raw_names if n and not flag_banned_species([n])]


def flag_roster_conflicts(events):
    """Tags every event whose `detail` matches the roster-substitution pattern
    AND whose raw read is a real species with `roster_conflict=True` and
    `roster_conflict_species=[...]`. Mutates events in place."""
    for e in events:
        conflicts = detect_roster_conflict_species(e.get("detail", ""))
        if conflicts:
            e["roster_conflict"] = True
            e["roster_conflict_species"] = conflicts
    return events


def summarize_roster_conflicts(match_events, team_preview_event, min_occurrences=2):
    """Rolls per-event roster_conflict flags (see flag_roster_conflicts, which
    must run first) up into a match-level signal on the team_preview event.
    A single flagged event could just be one bad OCR/vision read of an
    unrelated on-screen glitch, but the SAME legal species recurring across
    several distinct events in one match is a much stronger signal that the
    TEAM-PREVIEW ROSTER READ ITSELF missed a real teammate, not that each
    individual event misread something independently.

    Grounded in a real case (job 8c10092ac4a9, match 5, found via a user's
    manual benchmark comparison): the roster read for that match never
    identified the opponent's Dragalge at all, so an event whose battle text
    literally said "Dragalge" got substituted to "Latias" (the closest known
    name in the wrong roster) and flagged roster_conflict=True. This function
    surfaces "Dragalge" as a likely-missed opponent species directly on that
    match's team_preview event, rather than requiring someone to notice the
    same recurring name buried across several separate event corrections.

    Mutates `team_preview_event` in place, adding
    "likely_missed_opponent_species" (sorted list) only when at least one
    species clears `min_occurrences`; leaves it out entirely otherwise so
    existing team_preview events/tests without this field are unaffected.

    ACTOR-FILTERED (fixed 2026-07-07): only rolls up conflicts from events
    whose `actor` is "opponent" - a real bug, found via a user's real-footage
    accuracy re-test (job 8c10092ac4a9, match 3), had this counting
    roster-conflict events from EITHER side and unconditionally labeling the
    result a MISSED OPPONENT species. Concretely: match 3's own battle text
    twice read "Drampa" for a PLAYER-side action (actor="player") - Drampa
    wasn't in that match's player roster read, so it got substituted to
    "Staraptor" and flagged roster_conflict=True, same as any other
    conflict. With no actor check, those two player-side recurrences alone
    were enough to trip min_occurrences and inject "Drampa" - a real
    Pokemon, just on the WRONG side - into the OPPONENT's roster via
    apply_likely_missed_species_correction, corrupting a side that was
    never actually wrong. The field is named and consumed everywhere
    downstream as an OPPONENT-side signal (see that function's own
    docstring and ARCHITECTURE_HANDOFF.md), so only actor="opponent"
    conflicts belong in it - a player-side roster miss like this is a real,
    separate problem (the player's own roster read missed a real teammate)
    that this function does not attempt to fix; it only avoids
    misattributing it to the wrong side."""
    counts = {}
    display_name = {}
    for e in match_events:
        if not e.get("roster_conflict"):
            continue
        if e.get("actor") != "opponent":
            continue
        for sp in (e.get("roster_conflict_species") or []):
            key = _species_base_norm(sp)
            counts[key] = counts.get(key, 0) + 1
            display_name.setdefault(key, sp)
    recurring = sorted(display_name[k] for k, n in counts.items() if n >= min_occurrences)
    if recurring:
        team_preview_event["likely_missed_opponent_species"] = recurring
    return team_preview_event


def apply_likely_missed_species_correction(team_preview_event, opponent_bring_cap=4, opponent_team_cap=6):
    """Folds `likely_missed_opponent_species` (see summarize_roster_conflicts,
    which must run first and populate that field) directly INTO
    opponent_team/opponent_brought, instead of leaving them as a note next
    to a roster that's still wrong. A species flagged this way recurred as a
    roster_conflict, which by definition means it was actually seen fighting
    in this match's own battle events - it isn't a guess to say it was on
    the opponent's team and was brought to battle, and everything downstream
    (the dashboard, career aggregation, strategic_analysis) reads
    opponent_team/opponent_brought directly, not this flag. Leaving the
    flag as pure decoration would mean the one place people/other code
    actually look stays wrong even when the correct name is sitting right
    there in the same event.

    No-op if `likely_missed_opponent_species` is absent/empty. Species
    already present (matched via _species_base_norm, so Mega/regional-form
    variants of an existing entry don't get duplicated) are skipped.
    opponent_brought is only extended up to `opponent_bring_cap` (matching
    merge_brought's own hardcoded cap) - never appends past the real max a
    side can bring. Does NOT touch `detail` (the hand-written prose summary)
    or retroactively fix which roster this match's own battle-event
    identification prompt was built against - see ARCHITECTURE_HANDOFF.md
    §2g for that honest scope boundary.

    `opponent_team_cap` (default 6 - Pokemon Champions' Species Clause caps
    a team at 6, and callers pass the format's own team_size when it
    differs) bounds how many entries opponent_team can grow to. Added
    2026-07-08 after a real, found bug: this function previously had NO
    size check on opponent_team at all - only the duplicate check above -
    so a species genuinely seen fighting but not already in the (possibly
    incomplete) roster read got appended unconditionally. A fresh 10-match
    production run turned up 3 real cases of this producing an impossible
    7-member opponent_team (matches 3, 10, 12 of that run) - match 3's was
    caused by a separate, now-fixed root cause (the landscape badge-column
    geometry bug, task #206, plus the user's own manual correction of that
    match's roster - see events.json's team_preview.manual_correction note
    for that match), but the underlying missing-cap bug is independent of
    that root cause and could still happen on any match. A species that
    can't be added because opponent_team is already at the cap is recorded
    in `likely_missed_but_team_full` instead of being silently discarded -
    that's a real signal something in the roster is already wrong (a
    misread slot masquerading as a different real species) and worth
    surfacing for manual review, not something to just drop."""
    missed = team_preview_event.get("likely_missed_opponent_species")
    if not missed:
        return team_preview_event
    oteam = [s.strip() for s in (team_preview_event.get("opponent_team") or "").split(",") if s.strip()]
    obrought = [s.strip() for s in (team_preview_event.get("opponent_brought") or "").split(",") if s.strip()]
    oteam_keys = {_species_base_norm(s) for s in oteam}
    obrought_keys = {_species_base_norm(s) for s in obrought}
    team_full = []
    for sp in missed:
        key = _species_base_norm(sp)
        if key not in oteam_keys:
            if len(oteam) >= opponent_team_cap:
                team_full.append(sp)
                continue
            oteam.append(sp)
            oteam_keys.add(key)
        if key not in obrought_keys and len(obrought) < opponent_bring_cap:
            obrought.append(sp)
            obrought_keys.add(key)
    team_preview_event["opponent_team"] = ", ".join(oteam)
    team_preview_event["opponent_brought"] = ", ".join(obrought)
    if team_full:
        team_preview_event["likely_missed_but_team_full"] = team_full
    return team_preview_event


def _team_species_key(team_preview_event):
    """frozenset of normalized species keys for one team_preview event's
    player_team - order-independent, and Mega/regional-form variants of the
    same species collapse to one key (via _species_base_norm), so those
    aren't treated as a "different team" from one match to the next.

    player_team is SUPPOSED to always be a comma-joined string by the time
    it's written to events.json (see the ", ".join(...) call sites in
    main()/_wait_and_finish()/showdown_import.py, and
    backend/event_corrections.py's _SIDE_STRING_FIELDS, which all assume
    that convention) - but a real crash on job 8c10092ac4a9 (found running
    --only 2: 'list' object has no attribute 'split') showed at least one
    existing team_preview event in that job's events.json has it stored as
    a raw list instead, most likely a leftover from an older script version
    or a manual repair pass before the string convention was consistently
    enforced everywhere. Rather than track down and re-normalize that one
    historical write, this uses names_of() - the same shape-tolerant helper
    already used elsewhere in this file for exactly this kind of
    ambiguity (str / list-of-str / list-of-dict) - so this function (and
    reconcile_player_rosters_across_matches, its only caller) works
    regardless of which shape happens to be on disk."""
    raw = names_of(team_preview_event.get("player_team"))
    return frozenset(_species_base_norm(s) for s in raw if s and s.strip())


def reconcile_player_rosters_across_matches(all_events, min_matches=3):
    """A player's own team is very likely IDENTICAL across every match in one
    job/video - VGC streamers overwhelmingly play the same team for a whole
    session. That makes cross-match agreement a strong, free (no extra
    Gemini calls) signal: if every match but one agrees unanimously on
    player_team, and exactly one match's read disagrees, that one match's
    roster read is almost certainly the wrong one, not the other several.

    Grounded in a real case (job 8c10092ac4a9, match 3, found via a user's
    manual benchmark comparison): 4 of 5 matches read the identical player
    team; match 3 alone came back with a badly different, partly-mixed-up
    list (including a Pokemon that was actually the OPPONENT's). This
    function would flag and correct exactly that match.

    Deliberately conservative - only acts when ALL BUT ONE team_preview
    event agree on the exact same species set (a genuine "everyone else
    agrees, this one's the odd one out" pattern), never on a mere plurality
    among several disagreeing reads, which could just mean the player
    legitimately changed teams partway through the session. Requires at
    least `min_matches` team_preview events to even consider it (2 agreeing
    against 1 disagreeing is too thin a signal with fewer than 3 total).

    On the one outlier found, keeps the original read in
    "player_team_original_read", overwrites "player_team" with the
    unanimous majority's own text, and stamps
    "player_team_corrected_by_cross_match_consistency": True so this is
    never silent. Does NOT retroactively re-derive that match's
    player_brought/player_lead or re-run its battle-event identification
    (both already happened against the original, wrong roster) - this only
    corrects the roster record itself. Mutates events in `all_events` in
    place; returns it for convenience."""
    team_previews = [e for e in all_events if e.get("event") == "team_preview"]
    if len(team_previews) < min_matches:
        return all_events
    keyed = [(e, _team_species_key(e)) for e in team_previews]
    counts = Counter(k for _, k in keyed)
    if not counts:
        return all_events
    dominant_key, _dominant_count = counts.most_common(1)[0]
    if not dominant_key:
        return all_events   # nothing meaningful (every match came back empty)
    outliers = [e for e, k in keyed if k != dominant_key]
    if len(outliers) != 1:
        return all_events   # no correction unless exactly one match disagrees
    dominant_event = next(e for e, k in keyed if k == dominant_key)
    outlier = outliers[0]
    outlier["player_team_original_read"] = outlier.get("player_team")
    outlier["player_team"] = dominant_event.get("player_team")
    outlier["player_team_corrected_by_cross_match_consistency"] = True
    return all_events


_HP_BAR_REGION_BY_ACTOR = None


def cross_check_hp_bar_events(events, workdir=None):
    """For every hp_change event with a reference_frame, a numeric hp_percent,
    and a validated actor plate position, reads the frame's HP-bar fill
    pixels directly and cross-checks against the existing hp_percent. On
    disagreement, lowers confidence and appends a note. Mutates in place."""
    global _HP_BAR_REGION_BY_ACTOR
    if _HP_BAR_REGION_BY_ACTOR is None:
        from accuracy_addons import hp_bar_reader
        _HP_BAR_REGION_BY_ACTOR = {
            "player": hp_bar_reader.PLAYER_BOTTOM_LEFT_HP_BAR,
            "opponent": hp_bar_reader.OPPONENT_TOP_RIGHT_HP_BAR,
        }
    from accuracy_addons import hp_bar_reader
    import cv2

    for e in events:
        if e.get("event") != "hp_change":
            continue
        ref = e.get("reference_frame")
        actor = e.get("actor")
        hp_percent = e.get("hp_percent")
        if not ref or actor not in _HP_BAR_REGION_BY_ACTOR or hp_percent in (None, ""):
            continue
        try:
            hp_percent = float(hp_percent)
        except (TypeError, ValueError):
            continue
        path = ref if not workdir else os.path.join(workdir, ref)
        frame = cv2.imread(path)
        if frame is None:
            continue
        region = _HP_BAR_REGION_BY_ACTOR[actor]
        pixel_fraction = hp_bar_reader.hp_fraction_from_bar(frame, region=region)
        result = hp_bar_reader.cross_check_hp(hp_percent, pixel_fraction)
        if result["agree"] is False:
            e["confidence"] = min(e.get("confidence", 1.0) if isinstance(e.get("confidence"), (int, float)) else 1.0, 0.5)
            e["detail"] = (
                (e.get("detail") or "")
                + f" [HP pixel-check: bar fill reads ~{round(pixel_fraction * 100)}%, "
                  f"disagrees with the {round(hp_percent)}% recorded here - worth verifying "
                  f"against the reference frame]"
            ).strip()
    return events


# 2026-07-05 FIX: the top bound was 0.02 (int(0.02*360)=7), which clips the
# very first row of the real burn badge - confirmed by direct matching that
# the badge sits at absolute y=6 in its own 360-tall validation frame
# (jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg), one row above where
# this region used to start. That single clipped row was enough to drop
# match_icon_in_region's score below DEFAULT_THRESHOLD (0.559 vs the 0.9999
# an unrestricted whole-frame search finds at the same location) - meaning
# cross_check_status_events below silently failed to confirm "burn" even on
# the exact frame the whole feature (task/#80) was originally validated
# against. Found while adding tests/test_icon_template_matcher.py for a
# different task (#132) and re-running this exact check against real
# footage rather than trusting the existing region unverified. Top bound
# moved to 0.0 to include that row; re-verified this still returns "burn"
# on the source frame (see that test file).
_STATUS_BADGE_SEARCH_REGION = (0.0, 0.20, 0.78, 1.0)


def cross_check_status_events(events, workdir=None):
    """For every status_inflicted event claiming "burn" on the OPPONENT's
    side with a reference_frame, runs a free local template match over the
    approximate plate region and flags a disagreement if the pixel check
    does NOT confirm a burn badge there. Mutates in place."""
    from accuracy_addons import icon_template_matcher
    import cv2

    for e in events:
        if e.get("event") != "status_inflicted":
            continue
        if e.get("actor") != "opponent":
            continue
        if str(e.get("status", "")).strip().lower() != "burn":
            continue
        ref = e.get("reference_frame")
        if not ref:
            continue
        path = ref if not workdir else os.path.join(workdir, ref)
        frame = cv2.imread(path)
        if frame is None:
            continue
        found = icon_template_matcher.identify_status_icon(frame, region=_STATUS_BADGE_SEARCH_REGION)
        if found != "burn":
            e["confidence"] = min(e.get("confidence", 1.0) if isinstance(e.get("confidence"), (int, float)) else 1.0, 0.5)
            e["detail"] = (
                (e.get("detail") or "")
                + " [status pixel-check: burn badge not confirmed at the expected plate position - "
                  "worth verifying against the reference frame]"
            ).strip()
    return events


def cross_check_reference_frame_visibility(events, workdir=None):
    """For every event with a `pokemon`, an `actor`, and a `reference_frame`,
    checks whether that Pokemon's name is actually legible ANYWHERE in the
    photo attached to it and stamps the result as
    `reference_frame_shows_subject` (True/False). Mutates in place."""
    import cv2
    import ocr_battle_reader

    for e in events:
        pokemon = e.get("pokemon")
        actor = e.get("actor")
        ref = e.get("reference_frame")
        if not pokemon or actor not in ("player", "opponent") or not ref:
            continue
        path = ref if not workdir else os.path.join(workdir, ref)
        frame = cv2.imread(path)
        if frame is None:
            continue
        candidates = [pokemon] + list(e.get("roster_conflict_species") or [])
        visible = ocr_battle_reader.species_readable_in_frame(frame, candidates)
        e["reference_frame_shows_subject"] = visible
        if not visible:
            e["confidence"] = min(e.get("confidence", 1.0) if isinstance(e.get("confidence"), (int, float)) else 1.0, 0.5)
            e["detail"] = (
                (e.get("detail") or "")
                + f" [reference-frame check: '{pokemon}' wasn't found readable anywhere in this photo - "
                  "the camera may have been pointed elsewhere at this moment]"
            ).strip()
    return events


def run_accuracy_addons_checks(args, match_events):
    """Runs the three image-scanning accuracy_addons cross-checks if
    args.use_accuracy_addons is still True, guarding against a missing
    accuracy_addons/cv2 install."""
    if not args.use_accuracy_addons:
        return
    try:
        cross_check_hp_bar_events(match_events)
        cross_check_status_events(match_events)
        cross_check_reference_frame_visibility(match_events)
    except ImportError as e:
        print(f"Note: --use-accuracy-addons is on by default but a dependency is missing ({e}) - "
              f"disabling these cross-checks for the rest of this run (pass --no-accuracy-addons to "
              f"silence this check next time).")
        args.use_accuracy_addons = False


def merge_brought(derived, direct_raw, name_map):
    """Combine appearance-derived brought with the team-preview's own
    DIRECTLY-READ selection. Returns (brought_list_max_4,
    rejected_species_from_this_merge)."""
    out = list(derived)
    out_species = {_species_base_norm(x) for x in out}
    rejected = []
    for n in (direct_raw or []):
        if not str(n or "").strip():
            continue
        if flag_banned_species([n]):
            rejected.append(str(n).strip())
            continue
        species_key = _species_base_norm(n)
        if species_key in out_species:
            continue
        c = _canon(str(n), name_map) if name_map else str(n).strip()
        if c:
            out.append(c)
            out_species.add(species_key)
    return out[:4], rejected


def build_event_prompt(schema, roster, timestamps):
    """Builds the prompt for one batch of battle frames. Framed as a
    CLOSED-SET identification task rather than open recognition - see
    module history/ARCHITECTURE_HANDOFF.md for why."""
    lines = "\n".join(f"  Image {i+1} -> {ts:.0f}s" for i, ts in enumerate(timestamps))
    pteam = ", ".join(roster.get("player_team") or [])
    oteam = ", ".join(roster.get("opponent_team") or [])
    pbrought = ", ".join(roster.get("player_brought") or [])
    obrought = ", ".join(roster.get("opponent_brought") or [])
    roster_txt = ""
    if pteam or oteam:
        brought_txt = ""
        if pbrought or obrought:
            brought_txt = (
                f"Of those, the Pokemon actually BROUGHT to battle (team preview's own 'pick 4' screen) "
                f"are — Player: [{pbrought or 'not confidently read'}]. "
                f"Opponent: [{obrought or 'not confidently read'}]. Every Pokemon you see in an actual "
                f"battle frame should be one of ITS SIDE'S brought list, when that list isn't empty - "
                f"check there FIRST, since it's a smaller and more reliable candidate set than the full "
                f"team below.\n")
        roster_txt = (
            f"KNOWN TEAMS this match — Player: [{pteam}]. Opponent: [{oteam}]. " + brought_txt +
            "This is a CLOSED-SET identification task, not open recognition: every Pokemon on the field "
            "must be one of its side's known Pokemon above (brought list first if given, else the full "
            "team) - don't identify a sprite from scratch across the whole game's roster and only check "
            "afterward, actively match what you see against THIS SHORT LIST first. Identify each by "
            "reading its NAME LABEL by the HP bar and matching it to the closest name on that side's "
            "list.\n"
            "- If what you read is a close/plausible match to one of these names (a minor misspelling or "
            "partial read), use that known name and keep your normal confidence.\n"
            "- If what you read clearly does NOT match any of these names at all (a different species "
            "entirely, not just a fuzzy misspelling), it likely means this frame doesn't actually belong "
            "to this match, or the roster itself was misread. In that case still pick the CLOSEST known-"
            "team name for the 'pokemon' field (never output 'unknown'), but set confidence to 0.3 or "
            "lower AND say plainly in 'detail' what you actually read versus what you're reporting - e.g. "
            "\"Read 'Staraptor' on screen, but that's not in the known roster - reporting closest match, "
            "Charizard.\"\n\n")
    return (f"Analyze frames from ONE Pokemon doubles match (timestamps in seconds):\n{lines}\n\n" + roster_txt +
            f"Event types: {schema['event_types']}\n"
            f"Fields per event: {list(schema['fields_to_capture'].keys())}\n"
            f"Guidance: {schema.get('notes_for_the_ai','')}\n\n"
            "OUTPUT EFFICIENCY (important): emit a 'field_state' ONLY when the board CHANGES from the "
            "previous frame — a new turn, a faint, a switch, or a clear HP change. Do NOT emit a field_state "
            "for every image; skip near-duplicate frames. Keep every 'detail' terse (a few words). "
            "Still capture every discrete action (moves, faints, etc.) once.\n\n"
            "Return ONLY a JSON array of event objects, using the timestamp of the image where you saw each.")


def nearest_frame(frames, timestamp):
    """frames: [(path, ts), ...]. Returns the path of whichever frame's
    timestamp is closest to `timestamp`, or None if frames is empty or the
    timestamp isn't usable."""
    if not frames:
        return None
    try:
        target = float(timestamp)
    except (TypeError, ValueError):
        return None
    best = min(frames, key=lambda pt: abs(pt[1] - target))
    return best[0]


# How far (seconds) from an event's own timestamp a `quality_frames` (e.g.
# the OCR tier's own denser/higher-res sample - see ocr_pipeline.OCR_FPS)
# candidate may be to be considered AT ALL for attach_reference_frames'
# sharpness-based pick below. Deliberately small - this is meant to break
# ties among frames already close enough in time to plausibly show the
# same moment, not to widen the search for "a frame showing this event"
# in general (that's still nearest_frame's job as the fallback).
QUALITY_FRAME_WINDOW_S = 1.5


def attach_reference_frames(events, frames, quality_frames=None, quality_window_s=QUALITY_FRAME_WINDOW_S):
    """Tags every event that has a timestamp with a reference_frame path.

    Base behavior (unchanged from before this parameter existed): with no
    `quality_frames`, this just tags the nearest-in-time frame from `frames`
    - the same single, low-res Gemini-facing battle sample as always.

    When `quality_frames` IS given (typically the OCR tier's own denser,
    higher-resolution sample - see ocr_pipeline.sample_ocr_frames - passed
    in by the caller once it's been sampled for OCR text reads anyway, at
    no extra cost), this instead:
      1. Gathers every quality_frames candidate within quality_window_s
         seconds of the event's own timestamp.
      2. If at least one exists, picks the SHARPEST one among them
         (frame_quality.pick_sharpest) rather than just the nearest - a
         nearby handful of higher-res candidates lets a blurry/mid-
         transition frame lose out to a clean one a fraction of a second
         away, which matters both for the human-reviewable reference photo
         and for every free accuracy_addons pixel cross-check that reads
         straight from this image (hp_bar_reader, icon_template_matcher,
         the OCR-visibility check - see run_accuracy_addons_checks).
      3. Falls back to the ORIGINAL nearest-frame-in-`frames` behavior for
         any event with no quality_frames candidate within the window (e.g.
         right at the very start/end of the sampled window, or when the
         caller has no quality_frames to offer at all).
    This can never make reference_frame WORSE than before calling code
    started passing quality_frames - it only replaces the single blind
    nearest-frame pick with a small local best-of vote when better material
    is available, and degrades gracefully to the exact previous behavior
    otherwise."""
    if not frames:
        return events
    for e in events:
        ts = e.get("timestamp")
        if ts is None:
            continue
        path = None
        if quality_frames:
            try:
                target = float(ts)
            except (TypeError, ValueError):
                target = None
            if target is not None:
                nearby = [p for p, t in quality_frames if abs(t - target) <= quality_window_s]
                if nearby:
                    path = frame_quality.pick_sharpest(nearby)
        if not path:
            path = nearest_frame(frames, ts)
        if path:
            e["reference_frame"] = path
    return events


def prune_unreferenced_frames(match_workdir, match_events):
    """Delete every sampled frame in match_workdir EXCEPT the ones actually
    kept as an event's reference_frame."""
    if not os.path.isdir(match_workdir):
        return
    keep = {os.path.normpath(e["reference_frame"]) for e in match_events if e.get("reference_frame")}
    removed = 0
    for name in os.listdir(match_workdir):
        full = os.path.join(match_workdir, name)
        if os.path.isfile(full) and os.path.normpath(full) not in keep:
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"  pruned {removed} unreferenced frame(s), kept {len(keep)} reference photo(s)")


def _atomic_write(path, write_fn):
    """Writes a file so it's never left half-written on disk: `write_fn(f)`
    writes into a temp file in the SAME directory as `path` (same
    filesystem, so the final os.replace() is one atomic rename, not a
    cross-device copy), and only once that completes without raising does
    the temp file get moved onto the real path. A crash, kill, or power
    loss mid-write leaves `path` holding either its old valid content or
    is untouched - never a half-written, corrupted result the way a plain
    open(path, "w") can. This exists because a real events.json (from a
    production run of this exact function) was found corrupted with a
    truncated string and a duplicated tail fragment - exactly the shape of
    damage an interrupted plain write leaves behind. See backend/
    job_files.py's identical helper (this script and the FastAPI server
    are two separate processes that both write events.json, so both need
    the same protection) and ARCHITECTURE_HANDOFF.md's data-retention note."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            write_fn(f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def default_events_paths(video):
    """events.json/events.csv default to sitting next to --video - the exact
    same real, previously-silent bug already fixed for --matches (see that
    flag's help text): bare "events.json" resolves relative to the CURRENT
    WORKING DIRECTORY the script happens to be run from, not the job folder.

    Found 2026-07-07, job 8c10092ac4a9: a --only 3,5 re-run to verify the
    summarize_roster_conflicts actor-filter fix showed CORRECT, already-
    corrected results in the terminal's own live prints (no Drampa in
    opponent_brought), but jobs/8c10092ac4a9/events.json - opened directly
    afterward to double check - still showed the pre-fix data untouched
    (likely_missed_opponent_species still listing Drampa, with
    apply_likely_missed_species_correction's own fix confirmed working in
    isolation - see the diagnostic run that ruled the function itself out).
    The run's own events.json read/write was resolving against whatever the
    CWD happened to be at the time, not jobs/8c10092ac4a9/ - so it never
    touched the file actually being inspected at all; every previous
    "--only N,M re-run" this session only ever looked consistent because the
    CWD happened to match the job folder by coincidence, not because the
    path was actually tied to --video."""
    d = os.path.dirname(os.path.abspath(video)) or "."
    return os.path.join(d, "events.json"), os.path.join(d, "events.csv")


def save_outputs(all_events, events_json_path="events.json"):
    events_csv_path = os.path.splitext(events_json_path)[0] + ".csv"
    _atomic_write(events_json_path, lambda f: json.dump(all_events, f, indent=2))
    if all_events:
        keys = []
        for e in all_events:
            for k in e.keys():
                if k not in keys:
                    keys.append(k)

        def _write_csv(f):
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for e in all_events:
                w.writerow(e)

        _atomic_write(events_csv_path, _write_csv)


def _read_rosters_and_winners_live(client, hard_model, args, matches, rules=None):
    """Phase 1 of batch mode: the live, cheap, low-volume reads every batch
    request downstream depends on. Returns {match_idx: state_dict}."""
    match_state = {}
    print(f"Phase 1/3: live roster + winner reads for {len(matches)} match(es) "
          f"(small, cheap - not what batch mode is optimizing)...")
    for idx, start, end in matches:
        match_workdir = os.path.join(args.workdir, f"match_{idx}")
        roster, roster_failed = read_roster(
            client, hard_model, args.model, find_ffmpeg(), args.video, start, match_workdir, args.hwaccel,
            rules=rules)
        pteam, pteam_rejected = reject_banned_species(roster.get("player_team") or [])
        oteam, oteam_rejected = reject_banned_species(roster.get("opponent_team") or [])
        winner, detail, winner_failed = read_winner(
            client, hard_model, args.model, find_ffmpeg(), args.video, end, match_workdir, args.hwaccel)
        if winner not in ("player", "opponent"):
            winner = "unknown"
        print(f"  match {idx}: rosters player[{len(pteam)}] opponent[{len(oteam)}]  winner: {winner}")
        match_state[idx] = {
            "start": start, "end": end, "roster": roster,
            "pteam": pteam, "oteam": oteam,
            "pteam_rejected": pteam_rejected, "oteam_rejected": oteam_rejected,
            "winner": winner, "detail": detail,
        }
    return match_state


def _sample_and_submit(client, args, schema, matches, match_state):
    """Phase 2 of batch mode: sample + de-duplicate battle frames for every
    match, build one prompt PER CHUNK, and submit everything as ONE batch
    job. Returns (job_name, chunk_counts, chunks_by_key)."""
    ffmpeg = find_ffmpeg()
    chunks_by_key = {}
    prompts_by_key = {}
    for idx, start, end in matches:
        roster = match_state[idx]["roster"]
        match_workdir = os.path.join(args.workdir, f"match_{idx}")
        frames_sampled = sample_window(ffmpeg, args.video, start, end - start, args.battle_fps,
                                       match_workdir, "b", args.hwaccel, scale_w=args.frame_width)
        frames = frame_dedup.dedupe_frames(frames_sampled, threshold=args.dedup_threshold)
        if len(frames) < len(frames_sampled):
            print(f"  match {idx}: dedup {len(frames_sampled)} -> {len(frames)} frames (free, local)")
        chunks = [frames[i:i + args.batch] for i in range(0, len(frames), args.batch)]
        for chunk_idx, chunk in enumerate(chunks):
            ts_list = [t for _, t in chunk]
            chunks_by_key[(idx, chunk_idx)] = chunk
            prompts_by_key[(idx, chunk_idx)] = build_event_prompt(schema, roster, ts_list)

    total_frames = sum(len(c) for c in chunks_by_key.values())
    print(f"  {len(chunks_by_key)} chunk(s), {total_frames} frame(s) total across all matches - "
          f"uploading and submitting as ONE batch job...")
    job_name = gemini_batch.submit_battle_batch(client, args.model, chunks_by_key, prompts_by_key)
    print(f"  Submitted: {job_name}")

    chunk_counts = {}
    for (idx, chunk_idx) in chunks_by_key:
        chunk_counts[idx] = max(chunk_counts.get(idx, 0), chunk_idx + 1)
    return job_name, chunk_counts, chunks_by_key


def _wait_and_finish(client, job_name, args, matches, match_state, chunk_counts, all_events,
                     chunks_by_key=None, rules=None):
    """Phases 2(wait)-3 shared by both a fresh run_batch_mode() call and a
    resumed one."""
    print(f"\nWaiting for batch job to finish (polling every {args.batch_poll_interval}s - "
          f"Google's target turnaround is 24h, usually much quicker)...")
    job = gemini_batch.wait_for_batch(
        client, job_name, poll_interval=args.batch_poll_interval,
        on_poll=lambda state: print(f"  ...{state}", flush=True))

    if job.state.name != "JOB_STATE_SUCCEEDED":
        sys.exit(f"\nBatch job ended in state {job.state.name}, not JOB_STATE_SUCCEEDED - no results "
                 f"to collect. Job name was {job_name}.")

    print("Phase 3/3: collecting results and building events.json...")
    results = gemini_batch.collect_battle_batch_results(client, job)

    for idx, start, end in matches:
        st = match_state[idx]
        n_chunks = chunk_counts.get(idx, 0)
        match_events = []
        n_errors = 0
        for chunk_idx in range(n_chunks):
            parsed, error = results.get((idx, chunk_idx), (None, "missing from batch results"))
            if error:
                n_errors += 1
                print(f"  match {idx} chunk {chunk_idx}: {error}")
                continue
            for e in parse_events(parsed):
                e["match"] = idx
                if "player_active" in e:
                    e["player_active"] = ", ".join(names_of(e.get("player_active")))
                if "opponent_active" in e:
                    e["opponent_active"] = ", ".join(names_of(e.get("opponent_active")))
                if isinstance(e.get("pokemon"), (list, dict)):
                    got = names_of(e.get("pokemon"))
                    e["pokemon"] = got[0] if got else ""
                match_events.append(e)
        flag_roster_conflicts(match_events)
        moveset_validator.flag_implausible_moves(match_events)
        if chunks_by_key:
            frames_for_match = []
            for chunk_idx in range(n_chunks):
                frames_for_match.extend(chunks_by_key.get((idx, chunk_idx), []))
            attach_reference_frames(match_events, frames_for_match)
            run_accuracy_addons_checks(args, match_events)
            prune_unreferenced_frames(os.path.join(args.workdir, f"match_{idx}"), match_events)

        print(f"  match {idx}: {len(match_events)} event(s)" +
              (f"  ({n_errors} chunk error(s) - see above)" if n_errors else ""))
        all_events.extend(match_events)

        pbrought, obrought, plead, olead = derive_brought(match_events, st["roster"], rules=rules)
        pmap = {_norm(n): n for n in st["pteam"]}
        omap = {_norm(n): n for n in st["oteam"]}
        pbrought, p_merge_rejected = merge_brought(pbrought, st["roster"].get("player_brought"), pmap)
        obrought, o_merge_rejected = merge_brought(obrought, st["roster"].get("opponent_brought"), omap)

        rejected = sorted(set(st["pteam_rejected"] + st["oteam_rejected"] + p_merge_rejected + o_merge_rejected))
        if rejected:
            print(f"  match {idx}: 🚫 REJECTED illegal species: {rejected}")

        team_preview_event = {
            "timestamp": round(start - 30, 1), "event": "team_preview", "actor": "both",
            "detail": (f"P1 team: {', '.join(st['pteam'])} | P2 team: {', '.join(st['oteam'])}  ||  "
                       f"P1 brought: {', '.join(pbrought)} | P2 brought: {', '.join(obrought)}"),
            "player_team": ", ".join(st["pteam"]), "opponent_team": ", ".join(st["oteam"]),
            "player_brought": ", ".join(pbrought), "opponent_brought": ", ".join(obrought),
            "player_lead": ", ".join(plead), "opponent_lead": ", ".join(olead),
            "illegal_species_detected": rejected,
            "confidence": 0.8, "match": idx}
        # Carry the free, supplementary type-badge hints computed inside
        # read_roster() (see attach_opponent_type_hints) through onto the
        # actual event written to events.json - it lives on the roster dict,
        # not on any of the named fields already copied above, so it has to
        # be threaded through explicitly or it's silently lost.
        if st["roster"].get("opponent_row_type_hints"):
            team_preview_event["opponent_row_type_hints"] = st["roster"]["opponent_row_type_hints"]
        if st["roster"].get("type_badge_overrides"):
            team_preview_event["type_badge_overrides"] = st["roster"]["type_badge_overrides"]
        summarize_roster_conflicts(match_events, team_preview_event)
        apply_likely_missed_species_correction(
            team_preview_event, opponent_team_cap=(rules or {}).get("team_size") or 6)
        all_events.append(team_preview_event)
        all_events.append({"timestamp": round(end, 1), "event": "battle_end", "actor": st["winner"],
                           "detail": st["detail"] or f"match {idx} result", "winner": st["winner"],
                           "confidence": 0.85, "match": idx})

    reconcile_player_rosters_across_matches(all_events)
    save_outputs(all_events, args.events_json)
    wins = sum(1 for idx, _, _ in matches if match_state[idx]["winner"] == "player")
    losses = sum(1 for idx, _, _ in matches if match_state[idx]["winner"] == "opponent")
    print("\n================= DONE (batch mode) =================")
    print(f"Matches analyzed: {len(matches)}   Record: {wins}-{losses}")
    print(f"Total events: {len(all_events)} -> events.json / events.csv")
    print("Next: py battle_record.py   and   py player_report.py")


def run_batch_mode(args, schema, ffmpeg, client, hard_model, matches, all_events):
    print(f"=== BATCH MODE: {len(matches)} match(es) - see ARCHITECTURE_HANDOFF.md section 2a ===")
    match_state = _read_rosters_and_winners_live(client, hard_model, args, matches, rules=schema.get("rules", {}))
    job_name, chunk_counts, chunks_by_key = _sample_and_submit(client, args, schema, matches, match_state)

    resume_state = {
        "job_name": job_name,
        "matches": [[idx, start, end] for idx, start, end in matches],
        "match_state": match_state,
        "chunk_counts": chunk_counts,
        "chunks_by_key": {gemini_batch.encode_key(i, c): frames for (i, c), frames in chunks_by_key.items()},
        "rules": schema.get("rules", {}),
    }
    with open(args.batch_state_file, "w", encoding="utf-8") as f:
        json.dump(resume_state, f, indent=2)
    print(f"  Saved job state to {args.batch_state_file} - if this run gets interrupted, resume with:\n"
          f"    py analyze_matches.py --video {args.video} --resume-batch-job {args.batch_state_file}")

    _wait_and_finish(client, job_name, args, matches, match_state, chunk_counts, all_events, chunks_by_key,
                     rules=schema.get("rules", {}))


def resume_batch_mode(args, hard_model):
    """Reconstructs everything phase 3 needs from a --batch-state-file saved
    by an earlier run_batch_mode() call, then waits/collects/finishes."""
    if _GENAI_IMPORT_ERROR:
        sys.exit(_GENAI_IMPORT_ERROR)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("No API key. Set GEMINI_API_KEY first.")
    if not os.path.exists(args.resume_batch_job):
        sys.exit(f"No such batch state file: {args.resume_batch_job}")

    with open(args.resume_batch_job, encoding="utf-8") as f:
        resume_state = json.load(f)

    client = genai.Client(api_key=api_key)
    matches = [(idx, start, end) for idx, start, end in resume_state["matches"]]
    match_state = {int(k): v for k, v in resume_state["match_state"].items()}
    chunk_counts = {int(k): v for k, v in resume_state["chunk_counts"].items()}
    chunks_by_key = {gemini_batch.decode_key(k): frames
                     for k, frames in resume_state.get("chunks_by_key", {}).items()}
    rules = resume_state.get("rules")

    args.events_json, args.events_csv = default_events_paths(args.video)
    print(f"Events file: {args.events_json}")

    all_events = []
    if os.path.exists(args.events_json):
        only_nums = {idx for idx, _, _ in matches}
        with open(args.events_json, encoding="utf-8") as f:
            existing = json.load(f)
        all_events = [e for e in existing if e.get("match") not in only_nums]

    print(f"Resuming batch job {resume_state['job_name']} for {len(matches)} match(es)...")
    _wait_and_finish(client, resume_state["job_name"], args, matches, match_state, chunk_counts, all_events,
                     chunks_by_key, rules=rules)


def main():
    ap = argparse.ArgumentParser(description="Analyze each match window from matches.csv.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--matches", default=None, help="Path to this job's matches.csv (from "
                    "structure_pass.py). Defaults to matches.csv sitting next to --video (e.g. "
                    "--video jobs/<id>/vod.mp4 -> jobs/<id>/matches.csv) rather than the current "
                    "working directory - a real, previously-silent bug: running this script from the "
                    "repo root with --video pointing into a job folder but no explicit --matches used "
                    "to fall back to whatever unrelated matches.csv (or none) happened to sit in the "
                    "CWD, e.g. an old leftover from a completely different, longer video - silently "
                    "sampling the WRONG time windows with no error at all (found 2026-07-07: a re-test "
                    "against job 8c10092ac4a9 read a stale root-level matches.csv from a different "
                    "video, so 'match 2' was actually some unrelated mid-battle window, not that job's "
                    "real match 2 - the roster read never had a chance since no team-preview screen "
                    "was anywhere in the wrong window it searched). Pass --matches explicitly to "
                    "override.")
    ap.add_argument("--schema", default="schema.json")
    ap.add_argument("--model", default="gemini-2.5-flash", help="cheap model for the bulk battle-event reads")
    ap.add_argument("--hard-model", default="", help="stronger model for the FEW hard reads (roster + winner). "
                                                     "Default = same as --model. Set gemini-3.5-flash to tier.")
    ap.add_argument("--battle-fps", type=float, default=0.33, help="frames/sec inside a battle (default ~1/3s)")
    ap.add_argument("--frame-width", type=int, default=640, help="battle frame width in px (lower = cheaper)")
    ap.add_argument("--dedup-threshold", type=float, default=2.0, help="skip battle frames that are near-"
                    "identical to the last KEPT frame (free, local, no API call) before they're ever sent "
                    "to Gemini - cuts image volume on the single biggest cost driver with no accuracy loss, "
                    "since a near-duplicate frame can't show a new event the last kept one didn't already "
                    "show. Set to 0 to disable (send every sampled frame, old behavior). See frame_dedup.py.")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="only analyze the first N matches (0 = all)")
    ap.add_argument("--only", default="", help="comma-separated match numbers (1-based, matching "
                    "matches.csv row order) to RE-analyze, e.g. --only 3,14,20. Leaves every other "
                    "match's existing events.json entries untouched - cheap way to redo just the "
                    "matches flagged as incomplete/unknown without reprocessing the whole video.")
    ap.add_argument("--hwaccel", default="", help="GPU decode, e.g. d3d11va")
    ap.add_argument("--workdir", default="match_frames")
    ap.add_argument("--regulation", default="m-b", help="Which Pokemon Champions regulation's "
                    "roster/legal-mechanics data to enforce (adapters/pokemon/regulations/<id>.json) - "
                    "e.g. m-b (current) or m-a (the game's launch regulation, superseded 2026-06-17). "
                    "This is what a wrong-format video (older footage, a future regulation) actually "
                    "needs changed - species legality is enforced against WHICHEVER regulation is named "
                    "here, not a single hardcoded roster. See ARCHITECTURE_HANDOFF.md section 3a.")
    ap.add_argument("--adapters", default="adapters", help="Adapters directory (default: adapters, "
                    "relative to the current directory - the backend passes an absolute path here "
                    "since a job's working directory has no adapters/ folder of its own).")
    ap.add_argument("--use-batch-api", action="store_true", help="run the bulk battle-frame event "
                    "extraction (the dominant cost driver) through Gemini's Batch API instead of live "
                    "calls - exactly 50%% off input/output tokens, same model, in exchange for not being "
                    "instant (Google's target turnaround is 24h, usually much quicker). Roster+winner "
                    "reads stay live (small, cheap, needed before batch prompts can be built anyway). "
                    "See gemini_batch.py and ARCHITECTURE_HANDOFF.md section 2a.")
    ap.add_argument("--batch-poll-interval", type=int, default=30, help="seconds between checking "
                    "whether the batch job has finished (--use-batch-api only)")
    ap.add_argument("--batch-state-file", default="batch_job_state.json", help="where to save the "
                    "submitted batch job's name + everything needed to finish processing later, so a "
                    "closed terminal / long wait doesn't lose the run (--use-batch-api only)")
    ap.add_argument("--resume-batch-job", default="", help="path to a --batch-state-file saved by a "
                    "previous --use-batch-api run - skips straight to waiting for/collecting that job "
                    "instead of submitting a new one. Use this if you Ctrl-C'd out or closed the "
                    "terminal while a batch job was still running.")
    ap.add_argument("--use-ocr-tier", dest="use_ocr_tier", action="store_true", default=True,
                    help="ON BY DEFAULT. LIVE MODE ONLY (not --use-batch-api yet - silently skipped "
                    "there, see the batch-mode check in main()). Before merging into the Gemini-derived "
                    "events, also read the bottom battle-text banner directly via local OCR "
                    "(ocr_battle_reader.py + battle_text_parser.py) and merge those in - deterministic "
                    "text beats a vision guess for the same moment. Any Pokemon nickname the banner text "
                    "names gets resolved against the match's known roster for free, falling back to ONE "
                    "small Gemini vision call per distinct nickname (not per frame) - see ocr_pipeline.py "
                    "and pokemon_identity.py. Requires pytesseract + a working Tesseract OCR install "
                    "(see requirements.txt); if either is missing, this now WARNS ONCE and continues in "
                    "pure-vision mode for the rest of the run, rather than exiting - it's the default "
                    "now, not something every environment can be assumed to have set up. Use "
                    "--no-ocr-tier to skip it outright without the warning.")
    ap.add_argument("--no-ocr-tier", dest="use_ocr_tier", action="store_false",
                    help="Disable the OCR tier (see --use-ocr-tier) - falls back to pure Gemini-vision "
                    "battle-event extraction, e.g. for an accuracy A/B comparison.")
    ap.add_argument("--use-accuracy-addons", dest="use_accuracy_addons", action="store_true", default=True,
                    help="ON BY DEFAULT. Works in both live and batch mode. Adds four free, local (no "
                    "extra API calls), no-cost cross-checks: (1) move-legality check against Showdown's "
                    "learnset data (accuracy_addons/) - flags an implausible species/move pairing (this "
                    "one part always runs regardless of this flag, since it's pure JSON lookup with no "
                    "image cost); (2) HP-bar pixel cross-check against the recorded hp_percent, for the "
                    "two plate positions that have been validated against real footage (player "
                    "bottom-left, opponent top-right); (3) a template-match pixel cross-check for "
                    "claimed opponent-side 'burn' status specifically (only status currently validated); "
                    "(4) a reference-frame VISIBILITY check (ocr_battle_reader.species_readable_in_frame) "
                    "- OCR-scans the photo attached to each event and flags when the named Pokemon isn't "
                    "legible anywhere in it, since a dynamically-moving battle camera (Pokemon Champions) "
                    "can point away from the relevant side at the exact instant an event's reference "
                    "photo was picked. (2), (3), and (4) open and scan the actual reference-frame image "
                    "per matching event - real, non-trivial local work, but still free/no-API, which is "
                    "why this now defaults on. If accuracy_addons/cv2 fail to import, this now WARNS ONCE "
                    "and disables itself for the rest of the run rather than crashing the whole job. "
                    "HONEST CURRENT SCOPE: template/data coverage is intentionally narrow right now (see "
                    "accuracy_addons/README.md and ARCHITECTURE_HANDOFF.md section 2e), and (4)'s scan "
                    "regions are an unvalidated first pass against real Pokemon Champions footage - these "
                    "will find little to flag (or occasionally over-flag) on most real jobs until refined "
                    "further; the plumbing is real and tested, the coverage/precision is not yet wide. "
                    "Use --no-accuracy-addons to skip all of (2)-(4) (move-legality still always runs).")
    ap.add_argument("--no-accuracy-addons", dest="use_accuracy_addons", action="store_false",
                    help="Disable the (2)-(4) accuracy_addons cross-checks (see --use-accuracy-addons).")
    args = ap.parse_args()
    hard_model = args.hard_model or args.model   # roster/winner use the stronger model if given

    reg_data = configure_regulation(args.adapters, args.regulation)
    print(f"Regulation: {reg_data.get('display_name', args.regulation)} "
          f"({len(ALLOWED_SPECIES)} legal species)")

    if args.use_ocr_tier and args.use_batch_api:
        print("Note: the OCR tier isn't wired into --use-batch-api yet - continuing without it "
              "(vision-only battle events, same as before this flag existed). Use live mode "
              "(drop --use-batch-api) for the OCR tier.")
        args.use_ocr_tier = False
    ocr_pipeline = None
    if args.use_ocr_tier:
        try:
            import ocr_pipeline
        except ImportError as e:
            print(f"Note: --use-ocr-tier is on by default but pytesseract/opencv-python/Tesseract "
                  f"aren't available here ({e}) - continuing in pure Gemini-vision mode for battle "
                  f"events (pass --no-ocr-tier to silence this check next time).")
            args.use_ocr_tier = False

    if args.resume_batch_job:
        resume_batch_mode(args, hard_model)
        return

    if _GENAI_IMPORT_ERROR:
        sys.exit(_GENAI_IMPORT_ERROR)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("No API key. Set GEMINI_API_KEY first.")
    if args.matches is None:
        # Default next to --video (e.g. jobs/<id>/vod.mp4 -> jobs/<id>/matches.csv) rather than
        # the current working directory - see --matches' own help text for the real, silent
        # wrong-file bug this replaces (2026-07-07, job 8c10092ac4a9).
        args.matches = os.path.join(os.path.dirname(os.path.abspath(args.video)), "matches.csv")
    print(f"Match windows: {args.matches}")
    if not os.path.exists(args.matches):
        sys.exit(f"No {args.matches}. Run structure_pass.py first, or pass --matches explicitly.")

    # events.json/events.csv default next to --video too, same as matches.csv above - see
    # default_events_paths' own docstring for the real, silent stale/wrong-file bug this replaces
    # (2026-07-07, job 8c10092ac4a9: a --only re-run's own correctness was invisible in the file
    # actually being inspected, because that read/write was resolving against the CWD, not the job).
    args.events_json, args.events_csv = default_events_paths(args.video)
    print(f"Events file: {args.events_json}")

    with open(args.schema, encoding="utf-8") as f:
        schema = json.load(f)
    check_regulation_staleness(schema.get("rules", {}), reg_data)
    with open(args.matches, newline="", encoding="utf-8") as f:
        all_windows = [(i, float(r["start_seconds"]), float(r["end_seconds"]))
                       for i, r in enumerate(csv.DictReader(f), 1)]   # (match_number, start, end)

    only_set = None
    if args.only.strip():
        only_set = {int(x) for x in args.only.split(",") if x.strip()}
        matches = [(i, s, e) for (i, s, e) in all_windows if i in only_set]
        missing = only_set - {i for i, _, _ in matches}
        if missing:
            sys.exit(f"--only referenced match number(s) not in {args.matches}: {sorted(missing)}")
    else:
        matches = all_windows
    if args.limit:
        matches = matches[:args.limit]

    all_events = []
    if only_set is not None and os.path.exists(args.events_json):
        with open(args.events_json, encoding="utf-8") as f:
            existing = json.load(f)
        all_events = [e for e in existing if e.get("match") not in only_set]
        print(f"Kept {len(all_events)} existing events from matches NOT in --only; "
              f"re-analyzing {sorted(only_set)}.")

    ffmpeg = find_ffmpeg()
    client = genai.Client(api_key=api_key)

    # Catches a match window with NO real footage in this video file at all
    # (e.g. matches.csv generated against a different/longer source) BEFORE
    # attempting it - see filter_matches_within_video_duration's own
    # docstring for the real production crash this replaces (a single
    # out-of-range match used to take down the ENTIRE multi-match run).
    matches = filter_matches_within_video_duration(matches, ffmpeg, args.video)
    if not matches:
        sys.exit("No requested matches fall within this video's actual length - nothing to do.")

    if args.use_batch_api:
        run_batch_mode(args, schema, ffmpeg, client, hard_model, matches, all_events)
        return

    summary = []
    consecutive_total_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3

    for idx, start, end in matches:
        print(f"\n--- Match {idx}/{len(matches)}  ({start:.0f}s–{end:.0f}s) ---", flush=True)
        match_workdir = os.path.join(args.workdir, f"match_{idx}")
        shutil.rmtree(match_workdir, ignore_errors=True)
        match_had_failure = False

        roster, roster_failed = read_roster(
            client, hard_model, args.model, ffmpeg, args.video, start, match_workdir, args.hwaccel,
            rules=schema.get("rules", {}))
        if roster_failed:
            match_had_failure = True
        pteam, pteam_rejected = reject_banned_species(roster.get("player_team") or [])
        oteam, oteam_rejected = reject_banned_species(roster.get("opponent_team") or [])
        print(f"  rosters: player[{len(pteam)}] opponent[{len(oteam)}]")

        frames_sampled = sample_window(ffmpeg, args.video, start, end - start, args.battle_fps,
                               match_workdir, "b", args.hwaccel, scale_w=args.frame_width)
        frames = frame_dedup.dedupe_frames(frames_sampled, threshold=args.dedup_threshold)
        if len(frames) < len(frames_sampled):
            print(f"  dedup: {len(frames_sampled)} sampled -> {len(frames)} sent to Gemini "
                  f"({len(frames_sampled) - len(frames)} near-duplicate frame(s) skipped, free)")
        jobs = [frames[i:i + args.batch] for i in range(0, len(frames), args.batch)]

        def work(chunk):
            ts = [t for _, t in chunk]
            data = call(client, args.model, build_event_prompt(schema, roster, ts), [p for p, _ in chunk])
            return parse_events(data)

        match_events = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            for fut in concurrent.futures.as_completed([ex.submit(work, c) for c in jobs]):
                try:
                    evs = fut.result()
                    for e in evs:
                        e["match"] = idx
                        if "player_active" in e:
                            e["player_active"] = ", ".join(names_of(e.get("player_active")))
                        if "opponent_active" in e:
                            e["opponent_active"] = ", ".join(names_of(e.get("opponent_active")))
                        if isinstance(e.get("pokemon"), (list, dict)):
                            got = names_of(e.get("pokemon"))
                            e["pokemon"] = got[0] if got else ""
                    match_events.extend(evs)
                except Exception as e:
                    print(f"  event batch error -> {str(e)[:80]}")

        # Sample the OCR tier's own (denser/higher-res) frame list ONCE,
        # BEFORE attach_reference_frames, so a reference-frame pick for
        # every event (not just OCR-sourced ones) can prefer a sharp OCR
        # frame nearby over the single blind nearest low-res Gemini frame -
        # see attach_reference_frames' own docstring. Reused below (via
        # frames=) for the actual OCR text extraction, so this samples the
        # match window exactly once regardless of --use-ocr-tier.
        ocr_frames = None
        if args.use_ocr_tier:
            ocr_frames = ocr_pipeline.sample_ocr_frames(
                sample_window, ffmpeg, args.video, start, end, match_workdir, args.hwaccel)

        attach_reference_frames(match_events, frames, quality_frames=ocr_frames)
        print(f"  battle frames: {len(frames)} | events: {len(match_events)}")

        if args.use_ocr_tier:
            resolver = ocr_pipeline.IdentityResolver(known_species=pteam + oteam)
            ocr_events = ocr_pipeline.extract_ocr_events(
                sample_window, ffmpeg, args.video, start, end, match_workdir, args.hwaccel,
                frames=ocr_frames)
            if ocr_events:
                vision_call = functools.partial(call, client, args.model)
                ocr_pipeline.resolve_ocr_pokemon_names(
                    ocr_events, resolver,
                    vision_call=lambda name, path: ocr_pipeline.identify_pokemon_species(
                        vision_call, name, path))
                for e in ocr_events:
                    e["match"] = idx
                match_events = ocr_pipeline.merge_ocr_and_vision_events(ocr_events, match_events)
                print(f"  OCR tier: {len(ocr_events)} text-derived event(s) merged in "
                      f"({len(match_events)} total after merge)")

        flag_roster_conflicts(match_events)
        moveset_validator.flag_implausible_moves(match_events)
        run_accuracy_addons_checks(args, match_events)

        all_events.extend(match_events)

        pbrought, obrought, plead, olead = derive_brought(match_events, roster, rules=schema.get("rules", {}))

        pmap = {_norm(n): n for n in pteam}
        omap = {_norm(n): n for n in oteam}

        pbrought, p_merge_rejected = merge_brought(pbrought, roster.get("player_brought"), pmap)
        obrought, o_merge_rejected = merge_brought(obrought, roster.get("opponent_brought"), omap)
        merge_rejected = p_merge_rejected + o_merge_rejected
        print(f"  brought: player {pbrought} | opponent {obrought}")

        rejected = sorted(set(pteam_rejected + oteam_rejected + merge_rejected))
        if rejected:
            print(f"  🚫 REJECTED illegal species (not legal in this format, excluded from results): {rejected}")

        team_preview_event = {
            "timestamp": round(start - 30, 1), "event": "team_preview", "actor": "both",
            "detail": (f"P1 team: {', '.join(pteam)} | P2 team: {', '.join(oteam)}  ||  "
                       f"P1 brought: {', '.join(pbrought)} | P2 brought: {', '.join(obrought)}"),
            "player_team": ", ".join(pteam), "opponent_team": ", ".join(oteam),
            "player_brought": ", ".join(pbrought), "opponent_brought": ", ".join(obrought),
            "player_lead": ", ".join(plead), "opponent_lead": ", ".join(olead),
            "illegal_species_detected": rejected,
            "confidence": 0.8, "match": idx}
        # Carry the free, supplementary type-badge hints computed inside
        # read_roster() (see attach_opponent_type_hints) through onto the
        # actual event written to events.json - it lives on the roster dict,
        # not on any of the named fields already copied above, so it has to
        # be threaded through explicitly or it's silently lost.
        if roster.get("opponent_row_type_hints"):
            team_preview_event["opponent_row_type_hints"] = roster["opponent_row_type_hints"]
        if roster.get("type_badge_overrides"):
            team_preview_event["type_badge_overrides"] = roster["type_badge_overrides"]
        summarize_roster_conflicts(match_events, team_preview_event)
        apply_likely_missed_species_correction(
            team_preview_event, opponent_team_cap=schema.get("rules", {}).get("team_size") or 6)
        all_events.append(team_preview_event)

        winner, detail, winner_failed = read_winner(
            client, hard_model, args.model, ffmpeg, args.video, end, match_workdir, args.hwaccel)
        if winner_failed:
            match_had_failure = True
        if winner not in ("player", "opponent"):
            winner = "unknown"

        prune_unreferenced_frames(match_workdir, match_events)

        if match_had_failure and not pteam and not oteam and winner == "unknown":
            consecutive_total_failures += 1
        else:
            consecutive_total_failures = 0
        if consecutive_total_failures >= MAX_CONSECUTIVE_FAILURES:
            save_outputs(all_events, args.events_json)
            sys.exit(f"\nStopped after {consecutive_total_failures} matches in a row with a fully "
                     f"failed roster+winner read - looks like a sustained Gemini API outage rather "
                     f"than a blip. Partial results saved. Wait a bit and re-run the same --only list "
                     f"(or just the remaining match numbers) once the API recovers.")
        all_events.append({"timestamp": round(end, 1), "event": "battle_end", "actor": winner,
                           "detail": detail or f"match {idx} result", "winner": winner,
                           "confidence": 0.85, "match": idx})
        print(f"  winner: {winner}")

        summary.append((idx, winner, len(pteam), len(match_events)))
        save_outputs(all_events, args.events_json)   # crash-safe after every match

    # Only meaningful once every match has actually been read - a single
    # match's roster is compared against ALL the others' agreement, so this
    # can't run mid-loop the way per-match save_outputs does.
    reconcile_player_rosters_across_matches(all_events)
    save_outputs(all_events, args.events_json)

    wins = sum(1 for _, w, _, _ in summary if w == "player")
    losses = sum(1 for _, w, _, _ in summary if w == "opponent")
    print("\n================= DONE =================")
    print(f"Matches analyzed: {len(summary)}   Record: {wins}-{losses}")
    print(f"Total events: {len(all_events)} -> events.json / events.csv")
    print("Next: py battle_record.py   and   py player_report.py")


if __name__ == "__main__":
    main()
