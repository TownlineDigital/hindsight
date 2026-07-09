"""
Downloads the full Pokemon Champions "menusprite" set (species icons, as
actually rendered by the game itself - not generic Pokedex artwork) from
Bulbagarden Archives, including both normal AND shiny variants, and builds
a manifest mapping every file to its species name, national dex number,
form, and shiny status, for use as a future local icon-matcher's reference
template library.

WHY THIS EXISTS: analyze_matches.py's opponent-roster read is currently the
dominant source of misreads (see ARCHITECTURE_HANDOFF.md section 2g/2h) -
the opponent's team-preview panel shows icons only, with no name text,
unlike the player's own fully-labeled side. A real local icon/template
matcher against this closed ~212-species roster (accuracy_addons/
icon_template_matcher.py already does the same free/local pixel-matching
trick for status badges and move-type icons - see that file's docstring)
is the "deeper version" fix noted there, but it needs a reference image for
every legal species first - shiny included, since a real match can and
does show a shiny lead/Tera'd Pokemon on either side, and a matcher trained
only on non-shiny templates would badly misjudge those on color/pattern
alone. This script gets that reference set. It does NOT build the matcher
itself - see accuracy_addons/icon_template_matcher.py for that when it's
ready to be extended to species icons.

WHY THIS IS A STANDALONE SCRIPT YOU RUN ONCE, NOT SOMETHING
analyze_matches.py CALLS AT RUNTIME: this only needs to run occasionally
(once now, again if Champions adds new species/regulations), and it talks
to a public wiki + API that the actual video-analysis pipeline has no
business depending on mid-run. It was also written to run from your own
machine specifically because the sandboxed environment this was developed
in could not reach archives.bulbagarden.net at all (network allowlist) -
if you're seeing this note and everything below just works, that's why.

WHAT IT DOES:
  1. Fetches the MediaWiki category listing for BOTH "Champions menu
     sprites" (normal) AND "Champions Shiny menu sprites" (shiny) directly
     from Bulbagarden's own API (action=query&list=categorymembers) - the
     full, authoritative file lists (359 files each as of 2026-07, a true
     1:1 parallel set - every normal-form file has a shiny counterpart),
     not a guess at what forms/filenames might exist.
  2. Downloads each file via Special:FilePath/<filename>, which redirects
     to the real (MD5-hash-bucketed) media URL without needing to know that
     hash ahead of time.
  3. Parses each filename. Two real, DIFFERENT naming conventions were
     found in the wild here, not one: a form suffix is joined with a
     HYPHEN ("Menu_CP_0006-Mega_X.png"), but the shiny suffix is joined
     with an UNDERSCORE, always LAST, after any form ("Menu_CP_0003_shiny.png",
     "Menu_CP_0006-Mega_X_shiny.png"). parse_filename() strips a trailing
     "_shiny" first (setting a boolean), THEN parses dex number/form from
     whatever's left - trying to handle both in one combined regex was the
     first approach tried and it silently mis-split "Mega_shiny" as if
     "shiny" were part of the form name; splitting the shiny suffix off
     first avoids that ambiguity entirely.
  4. Maps the dex number to a species name via CHAMPIONS_DEX_MAP below - a
     static, already-fetched copy of PokeAPI's own Champions-specific
     Pokedex (https://pokeapi.co/api/v2/pokedex/champions, id 36).
     Confirmed by direct spot-check that this Pokedex's entry_number IS the
     real national dex number (Charizard = 6 in both) - not a separate
     Champions-only renumbering. Embedded as a static dict (rather than
     fetched live here too) so this script depends on ONE external site at
     runtime, not two; re-fetch pokeapi.co/api/v2/pokedex/champions by hand
     if Champions adds a new species and this map needs extending (a real
     run already found one gap this way - see the "923: pawmot" entry below).
  5. Cross-checked against this project's own adapters/pokemon/regulations/
     m-b.json species list: this map covers 208 of that file's 212 species
     exactly - the 4 gaps are precisely m-b.json's own "provisional_species"
     (basculin, duraludon, girafarig, glimmet), the ones that file already
     flags as "not independently source-confirmed". Nothing was missed by
     accident.
  6. Writes every PNG into accuracy_addons/templates/species/ (normal and
     shiny files side by side - their filenames never collide, the "_shiny"
     suffix already makes them unique), plus a manifest.json in that same
     folder mapping filename -> species name, dex number, form (None for
     the default/base form), and shiny (True/False).

USAGE (from poc-starter/):
  python accuracy_addons/tools/fetch_species_sprites.py

Only needs the Python standard library (urllib, json, re, time, os) - no
pip install required. Deliberately polite: single-threaded, small delay
between requests, ~720 total requests to a public wiki (both categories
combined) - don't put this in a loop or a CI job.

LICENSING: Bulbagarden Archives tags these as fair-use sprite extractions
from the actual game (see e.g. https://archives.bulbagarden.net/wiki/
File:Menu_CP_0006.png); the Archives' own general content license is
CC BY-NC-SA 2.5. Fine for this project's own internal, non-commercial
accuracy tooling - don't redistribute the image files themselves outside
this project.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

API_URL = "https://archives.bulbagarden.net/w/api.php"
FILEPATH_BASE = "https://archives.bulbagarden.net/wiki/Special:FilePath/"
CATEGORIES = [
    "Category:Champions menu sprites",
    "Category:Champions Shiny menu sprites",
]
USER_AGENT = "poc-starter-sprite-fetch/1.0 (internal accuracy tooling; see accuracy_addons/tools/fetch_species_sprites.py)"
REQUEST_DELAY_SECONDS = 0.5

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "species")

# Static copy of PokeAPI's "champions" Pokedex (id 36), fetched 2026-07-06 -
# see module docstring point 4/5 above for provenance and the 4 known gaps.
CHAMPIONS_DEX_MAP = {
    3: "venusaur", 6: "charizard", 9: "blastoise", 15: "beedrill", 18: "pidgeot",
    24: "arbok", 25: "pikachu", 26: "raichu", 36: "clefable", 38: "ninetales",
    45: "vileplume", 59: "arcanine", 65: "alakazam", 68: "machamp", 71: "victreebel",
    80: "slowbro", 94: "gengar", 115: "kangaskhan", 121: "starmie", 127: "pinsir",
    128: "tauros", 130: "gyarados", 132: "ditto", 134: "vaporeon", 135: "jolteon",
    136: "flareon", 142: "aerodactyl", 143: "snorlax", 149: "dragonite", 154: "meganium",
    157: "typhlosion", 160: "feraligatr", 168: "ariados", 181: "ampharos", 184: "azumarill",
    186: "politoed", 196: "espeon", 197: "umbreon", 199: "slowking", 205: "forretress",
    208: "steelix", 211: "qwilfish", 212: "scizor", 214: "heracross", 227: "skarmory",
    229: "houndoom", 248: "tyranitar", 254: "sceptile", 257: "blaziken", 260: "swampert",
    279: "pelipper", 282: "gardevoir", 302: "sableye", 303: "mawile", 306: "aggron",
    308: "medicham", 310: "manectric", 319: "sharpedo", 323: "camerupt", 324: "torkoal",
    334: "altaria", 350: "milotic", 351: "castform", 354: "banette", 358: "chimecho",
    359: "absol", 362: "glalie", 376: "metagross", 389: "torterra", 392: "infernape",
    395: "empoleon", 398: "staraptor", 405: "luxray", 407: "roserade", 409: "rampardos",
    411: "bastiodon", 428: "lopunny", 442: "spiritomb", 445: "garchomp", 448: "lucario",
    450: "hippowdon", 454: "toxicroak", 460: "abomasnow", 461: "weavile", 464: "rhyperior",
    470: "leafeon", 471: "glaceon", 472: "gliscor", 473: "mamoswine", 475: "gallade",
    478: "froslass", 479: "rotom", 497: "serperior", 500: "emboar", 503: "samurott",
    505: "watchog", 510: "liepard", 512: "simisage", 514: "simisear", 516: "simipour",
    518: "musharna", 530: "excadrill", 531: "audino", 534: "conkeldurr", 545: "scolipede",
    547: "whimsicott", 553: "krookodile", 560: "scrafty", 563: "cofagrigus", 569: "garbodor",
    571: "zoroark", 579: "reuniclus", 584: "vanilluxe", 587: "emolga", 604: "eelektross",
    609: "chandelure", 614: "beartic", 618: "stunfisk", 623: "golurk", 635: "hydreigon",
    637: "volcarona", 652: "chesnaught", 655: "delphox", 658: "greninja", 660: "diggersby",
    663: "talonflame", 666: "vivillon", 668: "pyroar", 670: "floette", 671: "florges",
    675: "pangoro", 676: "furfrou", 678: "meowstic", 681: "aegislash", 683: "aromatisse",
    685: "slurpuff", 687: "malamar", 689: "barbaracle", 691: "dragalge", 693: "clawitzer",
    695: "heliolisk", 697: "tyrantrum", 699: "aurorus", 700: "sylveon", 701: "hawlucha",
    702: "dedenne", 706: "goodra", 707: "klefki", 709: "trevenant", 711: "gourgeist",
    713: "avalugg", 715: "noivern", 724: "decidueye", 727: "incineroar", 730: "primarina",
    733: "toucannon", 740: "crabominable", 745: "lycanroc", 748: "toxapex", 750: "mudsdale",
    752: "araquanid", 758: "salazzle", 763: "tsareena", 765: "oranguru", 766: "passimian",
    778: "mimikyu", 780: "drampa", 784: "kommo-o", 823: "corviknight", 841: "flapple",
    842: "appletun", 844: "sandaconda", 855: "polteageist", 858: "hatterene", 861: "grimmsnarl",
    866: "mr. rime", 867: "runerigus", 869: "alcremie", 870: "falinks", 877: "morpeko",
    887: "dragapult", 899: "wyrdeer", 900: "kleavor", 902: "basculegion", 903: "sneasler",
    904: "overqwil", 908: "meowscarada", 911: "skeledirge", 914: "quaquaval",
    923: "pawmot",  # added 2026-07 after a live run found this dex# missing (roster grew since research)
    925: "maushold",
    934: "garganacl", 936: "armarouge", 937: "ceruledge", 939: "bellibolt", 952: "scovillain",
    956: "espathra", 959: "tinkaton", 964: "palafin", 968: "orthworm", 970: "glimmora",
    972: "houndstone", 979: "annihilape", 981: "farigiraf", 983: "kingambit",
    1000: "gholdengo", 1013: "sinistcha", 1018: "archaludon", 1019: "hydrapple",
}

FILENAME_RE = re.compile(r"^Menu_CP_(\d{4})(?:-(.+))?\.png$")
SHINY_SUFFIX_RE = re.compile(r"^(.*)_shiny\.png$")


def _api_get(params):
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{API_URL}?{qs}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def normalize_title(title):
    """MediaWiki's API returns file titles in their "display" form, with
    plain spaces ("Menu CP 0003-Mega X.png") - NOT the underscore form used
    in URLs/most examples on the site itself ("Menu_CP_0003-Mega_X.png").
    MediaWiki treats the two forms as interchangeable for a title (a
    space-based title and its underscore equivalent name the exact same
    page/file), so converting every space to an underscore here is always
    safe and makes the rest of this script (FILENAME_RE, the saved-on-disk
    filename, the Special:FilePath request) consistent no matter which form
    the API happened to hand back. Confirmed to matter for real: without
    this, a real run against the live category listing parsed ZERO of 359
    files (every title still had its original spaces, so FILENAME_RE's
    literal underscores never matched anything - see
    tests/test_fetch_species_sprites.py's regression test for this exact
    case)."""
    return title.replace(" ", "_")


def list_category_files(category):
    """Returns every file title in ONE category, e.g. "Menu_CP_0006.png"
    (already underscore-normalized - see normalize_title) - the real,
    authoritative list, paginated via `cmcontinue` (MediaWiki's own
    continuation token) rather than guessing a page size that covers
    everything in one shot."""
    titles = []
    params = {
        "action": "query", "list": "categorymembers", "cmtitle": category,
        "cmlimit": "500", "cmtype": "file", "format": "json",
    }
    while True:
        data = _api_get(params)
        for member in data.get("query", {}).get("categorymembers", []):
            title = member["title"]
            if title.startswith("File:"):
                title = title[len("File:"):]
            titles.append(normalize_title(title))
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        params["cmcontinue"] = cont
        time.sleep(REQUEST_DELAY_SECONDS)
    return sorted(titles)


def list_all_category_files(categories=CATEGORIES):
    """Union of list_category_files() over every category in `categories` -
    currently the normal-form category plus the shiny one (see CATEGORIES).
    A file's shiny-ness is recovered later from its OWN filename (see
    parse_filename), not tracked separately here - the two categories are
    just where the full file list comes from, nothing more."""
    all_titles = []
    for category in categories:
        all_titles.extend(list_category_files(category))
    return sorted(set(all_titles))


def parse_filename(filename):
    """"Menu_CP_0059-Hisui.png" -> (59, "Hisui", False); "Menu_CP_0006.png"
    -> (6, None, False); "Menu_CP_0003_shiny.png" -> (3, None, True);
    "Menu_CP_0006-Mega_X_shiny.png" -> (6, "Mega_X", True).

    Bulbagarden joins a FORM suffix with a hyphen ("-Mega_X") but the SHINY
    suffix with an underscore, always last ("_shiny") - two different
    conventions, not one. This strips a trailing "_shiny" first (setting
    the boolean) and only THEN runs FILENAME_RE on whatever's left, rather
    than trying to match both in one combined pattern - a single regex
    attempt at this mis-split "Mega_shiny" as if "shiny" were part of the
    form name, since FILENAME_RE's form group is naturally greedy and had
    no way to know where the real form name ended and the shiny suffix
    began without being told separately.

    Returns None if the filename doesn't match the expected pattern at all
    (so a future unrelated file added to either category doesn't silently
    corrupt the manifest)."""
    shiny = False
    m_shiny = SHINY_SUFFIX_RE.match(filename)
    if m_shiny:
        shiny = True
        filename = m_shiny.group(1) + ".png"
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    dex_number = int(m.group(1))
    form = m.group(2)
    return dex_number, form, shiny


def download_file(filename, dest_path):
    url = FILEPATH_BASE + urllib.request.quote(filename)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Fetching file lists from {len(CATEGORIES)} categor{'y' if len(CATEGORIES) == 1 else 'ies'}: "
          f"{CATEGORIES}...")
    filenames = list_all_category_files()
    print(f"  {len(filenames)} file(s) listed (normal + shiny combined).")

    manifest = []
    unmapped_dex_numbers = set()
    skipped_unparsed = []
    downloaded, failed, already_had = 0, 0, 0

    for i, filename in enumerate(filenames, 1):
        parsed = parse_filename(filename)
        if parsed is None:
            skipped_unparsed.append(filename)
            continue
        dex_number, form, shiny = parsed
        species = CHAMPIONS_DEX_MAP.get(dex_number)
        if species is None:
            unmapped_dex_numbers.add(dex_number)

        dest_path = os.path.join(OUT_DIR, filename)
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            already_had += 1
        else:
            try:
                size = download_file(filename, dest_path)
                downloaded += 1
                print(f"  [{i}/{len(filenames)}] {filename} ({size} bytes)")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                failed += 1
                print(f"  [{i}/{len(filenames)}] FAILED {filename}: {e}")
                continue
            time.sleep(REQUEST_DELAY_SECONDS)

        manifest.append({
            "filename": filename,
            "national_dex_number": dex_number,
            "species": species,   # None if dex_number isn't in CHAMPIONS_DEX_MAP yet
            "form": form,         # None means the default/base form
            "shiny": shiny,
        })

    manifest.sort(key=lambda e: (e["national_dex_number"], e["form"] or "", e["shiny"]))
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    shiny_count = sum(1 for e in manifest if e["shiny"])
    print("\n================= DONE =================")
    print(f"Downloaded: {downloaded}   Already had: {already_had}   Failed: {failed}")
    print(f"Manifest entries: {len(manifest)} ({shiny_count} shiny) -> {manifest_path}")
    if unmapped_dex_numbers:
        print(f"Dex numbers with no species mapping (game added something new since "
              f"this script's CHAMPIONS_DEX_MAP was written - re-fetch "
              f"https://pokeapi.co/api/v2/pokedex/champions and extend the map): "
              f"{sorted(unmapped_dex_numbers)}")
    if skipped_unparsed:
        print(f"Filenames that didn't match the expected pattern (skipped, not "
              f"downloaded): {skipped_unparsed}")
    if failed:
        print("Some downloads failed - just re-run this script; it skips files "
              "it already has and will only retry the missing ones.")


if __name__ == "__main__":
    main()
