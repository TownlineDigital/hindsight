"""
Deterministic parser for POKEMON on-screen battle text - the scrolling
banner that narrates every action ("X used Y!", "It's super effective!",
"X fainted!", ability/item activations, stat changes, status conditions,
weather/terrain). Converts one line of transcribed text (from OCR, or
anywhere else text might come from) into the SAME event schema
analyze_matches.py already produces via Gemini vision.

Why this exists: adapters/pokemon/game.json's "notes" field already
documents this exact text -> event mapping as an instruction TO the vision
model ("'X used [Move]!' = move_used; 'A critical hit!' = critical_hit; ...").
That's the tell that this was always a text-parsing problem wearing a
vision-AI costume - the battle text box is authoritative, exact, and
already tells you what happened in plain language. This module does the
same mapping deterministically instead of asking an LLM to interpret
instructions probabilistically over pixels. See ARCHITECTURE_HANDOFF.md's
OCR write-up for the full reasoning and the real Staraptor/Charizard bug
that motivated it.

Two things this module deliberately does NOT do, by design:

1. Resolve species identity from a nickname. `pokemon` here is whatever
   display name literally appears on screen (a nickname or the species
   name, no way to tell from text alone) - resolving that to an actual
   species is pokemon_identity.py's job, using visual/roster context this
   module doesn't have.
2. Guess. `actor` (player/opponent) is only set when the text ITSELF makes
   it unambiguous - Pokemon's own UI convention marks anything on the
   opponent's side with "The opposing ..." and never does for the
   player's own side, so that prefix is a hard, reliable signal. Anything
   else is left as None for the caller to resolve against known rosters
   (which pokemon_identity.py / the roster read already track).

`parse_line()` returns None for a line that doesn't match any known
pattern - that's the signal for the caller to fall back to the existing
Gemini vision read for that moment, not to guess at a shape that isn't
there. This is intentionally NOT an exhaustive grammar of every possible
Pokemon battle string (that space is enormous and grows with every new
mechanic) - it covers the high-frequency, well-documented patterns
robustly and safely defers anything else, rather than mis-parsing it.
"""

import re


# Every OCR-derived event gets a HIGH, mostly-fixed confidence - this came
# from deterministically matching exact on-screen text against a known
# pattern, not from a model's visual judgment call the way a Gemini vision
# read's confidence is. Some patterns intentionally use a slightly lower
# value where the text itself is inherently a bit less specific (see
# per-pattern comments below).
DEFAULT_CONFIDENCE = 0.95


def _event(event_type, detail, confidence=DEFAULT_CONFIDENCE, **fields):
    """Every field the shared Pokemon schema (adapters/pokemon/*.json)
    defines, defaulted to None so each parse function only has to set
    what it actually determined from the text."""
    out = {
        "event": event_type, "detail": detail, "confidence": confidence,
        "pokemon": None, "actor": None, "hp_percent": None, "winner": None,
        "turn": None, "weather": None, "terrain": None, "trick_room": None,
        "tailwind": None, "screens": None, "field_status": None,
        "player_active": None, "opponent_active": None,
    }
    out.update(fields)
    return out


def _clean(name):
    """Trailing punctuation/whitespace OCR commonly leaves behind."""
    return name.strip().strip(".,!'\"").strip()


# Order matters throughout this module: patterns are tried in the order
# they're registered, first match wins, so a MORE SPECIFIC pattern must
# come before a more GENERAL one it could otherwise be swallowed by (e.g.
# "X's Attack rose!" must be tried before a generic "X's <anything>" - an
# ability/item activation pattern - or the stat-change case would never
# get a chance to match).

_STATS = r"(?:Attack|Defense|Sp\. Atk|Sp\. Def|Speed|Accuracy|Evasiveness)"
_STAGES = r"(?:sharply rose|sharply fell|harshly fell|rose|fell|won't go any higher|won't go any lower)"

_PATTERNS = []


def _register(regex, handler):
    _PATTERNS.append((re.compile(regex, re.IGNORECASE), handler))


# --- fainting -----------------------------------------------------------
# Pokemon's own UI convention: the OPPONENT's side is always prefixed "The
# opposing ..."; the player's own side never is. That prefix is the one
# place this module can determine `actor` from text alone - checked first
# since it's the more specific of the two fainting patterns.
_register(
    r"^The opposing (.+?) fainted\.?!?$",
    lambda m: _event("pokemon_fainted", f"{_clean(m.group(1))} fainted",
                      pokemon=_clean(m.group(1)), actor="opponent", hp_percent=0),
)
_register(
    r"^(.+?) fainted\.?!?$",
    lambda m: _event("pokemon_fainted", f"{_clean(m.group(1))} fainted",
                      pokemon=_clean(m.group(1)), actor="player", hp_percent=0),
)

# --- move effectiveness / crits ------------------------------------------
# These don't name a Pokemon at all - they're a one-line reaction to
# whatever move_used event immediately preceded them, so the caller is
# expected to associate this with "the most recent move_used" itself.
_register(r"^It'?s super effective!?$",
           lambda m: _event("super_effective_hit", "It's super effective!"))
_register(r"^It'?s not very effective\.*!?$",
           lambda m: _event("not_very_effective_hit", "It's not very effective..."))
_register(
    r"^It doesn'?t affect (.+?)\.*!?$",
    lambda m: _event("not_very_effective_hit", f"No effect on {_clean(m.group(1))}",
                      pokemon=_clean(m.group(1))),
)
_register(r"^A critical hit!?$", lambda m: _event("critical_hit", "A critical hit!"))

# --- stat changes (must precede the generic ability/item pattern below) --
_register(
    rf"^(.+?)'s ({_STATS}) ({_STAGES})\.?!?$",
    lambda m: _event("stat_change", f"{_clean(m.group(2))} {m.group(3)}",
                      pokemon=_clean(m.group(1))),
)

# --- status conditions ----------------------------------------------------
_STATUS_PHRASES = (
    r"was poisoned|is paralyzed|was paralyzed|was burned|fell asleep|"
    r"was frozen solid|became confused|was confused|flinched|is confused"
)
_register(
    rf"^(.+?) ({_STATUS_PHRASES})[\.\!]*.*$",
    lambda m: _event("status_inflicted", f"{_clean(m.group(1))} {m.group(2)}",
                      pokemon=_clean(m.group(1))),
)

# --- move usage (including the "but it failed" variant) ------------------
_register(
    r"^(.+?) used ([A-Za-z][\w' \-]*?), but it failed\.?!?$",
    lambda m: _event("move_used", f"{m.group(2).strip()} (failed)",
                      pokemon=_clean(m.group(1)), confidence=0.9),
)
_register(
    r"^(.+?) used ([A-Za-z][\w' \-]*?)!?$",
    lambda m: _event("move_used", m.group(2).strip(), pokemon=_clean(m.group(1))),
)

# --- sending a Pokemon out -------------------------------------------------
_register(
    r"^Go[!,] ?(.+?)!?$",
    lambda m: _event("pokemon_sent_out", f"{_clean(m.group(1))} sent out",
                      pokemon=_clean(m.group(1)), actor="player"),
)
_register(
    r"^(.+?) sent out (.+?)!?$",
    lambda m: _event("pokemon_sent_out", f"{_clean(m.group(2))} sent out",
                      pokemon=_clean(m.group(2))),
)

# --- weather / terrain ------------------------------------------------------
_WEATHER_KEYWORDS = r"rain|sunlight|sandstorm|snow|hail"
_register(
    rf"^.*(?:{_WEATHER_KEYWORDS}).*[\.\!]$",
    lambda m: _event("weather_or_terrain_set", m.group(0).strip()),
)
_TERRAIN_KEYWORDS = r"Electric Terrain|Grassy Terrain|Misty Terrain|Psychic Terrain"
_register(
    rf"^.*(?:{_TERRAIN_KEYWORDS}).*[\.\!]$",
    lambda m: _event("weather_or_terrain_set", m.group(0).strip()),
)

# --- item/ability activation - deliberately LAST among the "X's ..."
# patterns since it's the most permissive one and would otherwise swallow
# the more specific stat-change pattern above. Two variants: an explicit
# "activated" suffix (very safe), and the short callout style seen in real
# footage during this project's own testing ("Scrafty's Intimidate", no
# verb at all) - lower confidence since the short form is more easily
# confused with an unrelated possessive phrase this parser hasn't seen yet.
_register(
    r"^(.+?)'s (.+?) activated\.?!?$",
    lambda m: _event("item_or_ability_activated", f"{_clean(m.group(2))} activated",
                      pokemon=_clean(m.group(1))),
)
_register(
    r"^(.+?)'s ([A-Z][\w \-]*?)!?$",
    lambda m: _event("item_or_ability_activated", _clean(m.group(2)),
                      pokemon=_clean(m.group(1)), confidence=0.75),
)

# --- battle end -------------------------------------------------------------
_register(
    r"^(?:You won the battle!|Congratulations! You won!)$",
    lambda m: _event("battle_end", m.group(0), winner="player", confidence=0.98),
)
_register(
    r"^(?:You lost the battle!|.+ defeated you!)$",
    lambda m: _event("battle_end", m.group(0), winner="opponent", confidence=0.98),
)


def parse_line(text):
    """Parses ONE line of on-screen battle text into an event dict matching
    the schema in adapters/pokemon/game.json, or None if it doesn't match
    any known pattern (the caller should fall back to a vision read for
    that moment rather than guess). `text` should already be whitespace-
    normalized (a single line) - callers doing OCR should split multi-line
    output themselves and call this once per line."""
    text = (text or "").strip()
    if not text:
        return None
    for pattern, handler in _PATTERNS:
        m = pattern.match(text)
        if m:
            return handler(m)
    return None


def parse_lines(lines):
    """Parses each line in `lines` (a list of strings, or one multi-line
    string) via parse_line(), returning only the ones that matched -
    silently drops unrecognized lines rather than erroring, since OCR
    output routinely includes junk (partial words, background noise) mixed
    in with the real text."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    results = []
    for line in lines:
        event = parse_line(line)
        if event:
            results.append(event)
    return results
