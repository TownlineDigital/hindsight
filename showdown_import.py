"""
POKEMON SHOWDOWN REPLAY IMPORTER - converts a Showdown replay (a saved .html
replay page, a saved .json file, or a live replay URL) directly into this
project's events.json format. NO video and NO Gemini call needed at all.

Why this is worth having: a Showdown replay is a complete, EXACT record of
everything that happened in a battle - there's no "the AI might have misread
the roster" step the video pipeline has to work around. Every event below is
parsed directly from Showdown's own battle log (its real, documented protocol -
see https://github.com/smogon/pokemon-showdown/blob/master/sim/SIM-PROTOCOL.md,
verified against a real fetched [Gen 9 Champions] VGC 2026 replay while building
this). Showdown also enforces format legality server-side - you cannot even
select a banned Pokemon in a real ladder/tournament game in this tier - so
Showdown-sourced matches are inherently ground truth for species legality too,
unlike a video read.

Both this script and analyze_matches.py write the exact same events.json shape
(see ARCHITECTURE_HANDOFF.md section 4), so every downstream tool -
battle_record.py, player_report.py, coach_report.py, skill_scores.py,
backend/analytics.py, the whole dashboard - works on Showdown-sourced matches
with ZERO changes. This is the source-agnostic design V1_SUMMARY.md flagged
Showdown integration as depending on.

Run, from poc-starter/:
  py showdown_import.py --file replay.html --player p1
  py showdown_import.py --url https://replay.pokemonshowdown.com/gen9... --player Geordivgc
  py showdown_import.py --files replay1.html replay2.html replay3.json --player p1 --out events.json
  py showdown_import.py --urls https://replay.pokemonshowdown.com/a https://replay.pokemonshowdown.com/b --player p1

--player identifies which side is "you" (player vs opponent) - either a
Showdown username (case-insensitive) or a raw side ID ("p1"/"p2"). A replay
file has no built-in notion of "the player" the way a video of your own POV
does, so this is the one thing that has to be told explicitly. Defaults to
"p1" if not given.
"""

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

# Reuse the exact same species-legality allowlist, Mega/regional-form
# normalization, and appearance-based "brought 4" derivation the video
# pipeline uses - one set of rules, whichever source produced the match.
import analyze_matches as am


# --------------------------------------------------------------------------
# Getting the raw log text, from whatever shape the source came in
# --------------------------------------------------------------------------

def read_source(file=None, url=None):
    """Returns raw text content from a local file or a live replay URL."""
    if file:
        return Path(file).read_text(encoding="utf-8", errors="replace")
    if url:
        # Prefer Showdown's own .json API - the cleanest possible source.
        # Any public replay is served at the same URL with ".json" appended.
        json_url = url if url.endswith(".json") else url.rstrip("/") + ".json"
        req = urllib.request.Request(json_url, headers={"User-Agent": "vgc-coach-importer/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    sys.exit("Provide --file or --url.")


def extract_log_text(raw):
    """Pulls the actual `|`-delimited battle log out of whatever shape the
    source came in - a raw .json API response, a full saved .html replay
    page, or (as a last resort) plain log text someone pasted directly.
    Tries each in order and uses the first that produces real protocol
    lines, rather than depending on knowing Showdown's exact HTML markup
    (which can change without notice - this is the same "don't be brittle
    about one exact assumed shape" approach the video pipeline's roster/
    winner retry logic already uses)."""
    raw = raw.strip()

    # 1) A straight JSON response (the .json API, or a saved .json file) -
    # has a top-level "log" string field.
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("log"), str):
            return data["log"]
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) A JSON object embedded somewhere inside a saved .html replay page
    # (e.g. a <script type="application/json">...</script> block). Find a
    # {...} chunk containing a "log" field and parse just that.
    for match in re.finditer(r"\{.*?\"log\"\s*:\s*\".*?(?<!\\)\"[^{}]*\}", raw, re.DOTALL):
        try:
            data = json.loads(match.group(0))
            if isinstance(data.get("log"), str):
                return data["log"]
        except (json.JSONDecodeError, ValueError):
            continue

    # 3) Fallback: the log's own lines are highly distinctive ("|move|...",
    # "|switch|...", "|win|...") - scan the raw text directly for anything
    # that looks like a protocol line, regardless of what HTML or JSON
    # escaping wraps it. Un-escape the common JSON string escapes first
    # (targeted, not a blanket codec - safer against mangling real unicode
    # text like Pokemon names/accents elsewhere on the page).
    candidate = raw
    if "\\n" in candidate:
        candidate = candidate.replace("\\n", "\n").replace("\\/", "/").replace('\\"', '"')
    lines = [ln.strip() for ln in candidate.splitlines()]
    protocol_lines = [ln for ln in lines if re.match(r"^\|[a-zA-Z:-]", ln)]
    if protocol_lines:
        return "\n".join(protocol_lines)

    sys.exit("Could not find a Showdown battle log in this source - expected "
              "a .json replay, an .html replay page, or raw log text.")


# --------------------------------------------------------------------------
# Parsing the log into this project's event schema
# --------------------------------------------------------------------------

def species_from_details(details):
    """"Farigiraf, L50, M" -> "Farigiraf". "Charizard-Mega-Y, L50, F" ->
    "Charizard-Mega-Y" (still has the Mega suffix here - normalization for
    legality/dedup purposes happens later via analyze_matches._species_base_norm,
    same as the video pipeline; this function only strips the level/gender/
    shininess/tera parts that DETAILS always carries, not the forme itself)."""
    return (details or "").split(",")[0].strip()


def _position_id(pokemon_id):
    """"p1a: Salazzle" -> "p1a" (the FULL position id, doubles slot letter
    included when present). Deliberately NOT sliced down to 2 characters -
    see BattleParser.active's docstring for the real bug that used to cause."""
    return pokemon_id.split(":")[0].strip()


def _side_of_position(position_id):
    """"p1a" -> "p1". "p1" -> "p1" (a rare no-letter singles id)."""
    return position_id[:2]


# Showdown's own |-boost|/|-unboost| stat abbreviations -> the exact display
# names battle_text_parser.py's OCR-tier stat_change regex already uses (see
# its own _STATS constant) - matching that vocabulary means a single shared
# parser (strategic_analysis.py's _parse_stat_change) works on stat_change
# events from EITHER source, not two source-specific formats.
_STAT_NAMES = {
    "atk": "Attack", "def": "Defense", "spa": "Sp. Atk", "spd": "Sp. Def",
    "spe": "Speed", "accuracy": "Accuracy", "evasion": "Evasiveness",
}

# Showdown's own |-weather|/|-fieldstart|/|-fieldend|/|-sidestart|/|-sideend|
# condition names -> the vocabulary adapters/pokemon/game.json's fields spec
# already documents for field_state's weather/terrain fields ("sun/rain/sand/
# snow/none", "electric/grassy/psychic/misty/none") - the video pipeline's
# Gemini-derived field_state events already use this vocabulary; Showdown
# replays never populated it at all before this (a real gap found while
# building this project's VGC Battle Intelligence Manual reports, 2026-07-09:
# 3 of the 6 reports - Speed Control Advantage, Resource Advantage, and
# indirectly Position Score - need these fields to say anything on Showdown-
# sourced matches, which is most of them, since only the video pipeline ever
# populated these fields before now).
_WEATHER_NAMES = {
    "sunnyday": "sun", "desolateland": "sun",
    "raindance": "rain", "primordialsea": "rain",
    "sandstorm": "sand",
    "snow": "snow", "hail": "snow",  # Gen 9 renamed Hail's weather to Snow; both map the same
    "none": "none", "": "none",
}
_TERRAIN_NAMES = {
    "electric terrain": "electric", "grassy terrain": "grassy",
    "misty terrain": "misty", "psychic terrain": "psychic",
}
# Only the 3 real damage-reducing screens are tracked (matches
# game.json's "screens" field example) - entry hazards (Spikes, Stealth
# Rock, Toxic Spikes, Sticky Web) and other side conditions (Safeguard,
# Mist, Lucky Chant) aren't in this project's tracked vocabulary and are
# deliberately ignored, not guessed at.
_SCREEN_NAMES = {"Reflect", "Light Screen", "Aurora Veil"}


def _strip_move_prefix(raw):
    """Showdown's |-fieldstart|/|-fieldend|/|-sidestart|/|-sideend| condition
    text is usually "move: Trick Room" (the move that caused it) but
    sometimes a bare name with no prefix at all (e.g. "Spikes", which isn't
    caused by a single named move). Strips the prefix when present; returns
    the text unchanged otherwise - never guesses one is missing/present."""
    s = str(raw or "").strip()
    if s.lower().startswith("move:"):
        return s.split(":", 1)[1].strip()
    return s


def _parse_hp_fraction(hp_field):
    """Showdown's |-damage|/|-heal| lines report HP as "CURRENT/MAX", optionally
    followed by a status abbreviation ("82/100 par") - VGC replays always show
    this out of 100 (i.e. it's already a percent, not a raw stat fraction),
    confirmed against the real fetched replay used throughout this project's
    tests. A lethal hit is reported as "0 fnt" (no slash at all) immediately
    before the separate |faint| line - handled the same as any other bare
    integer. Returns a float in [0, 100], or None if this doesn't parse at
    all (a genuinely unrecognized format returns None rather than a guessed
    number - "skip, don't guess," the same rule this project holds itself to
    everywhere else)."""
    first = str(hp_field or "").strip().split(" ")[0] if str(hp_field or "").strip() else ""
    if not first:
        return None
    if "/" in first:
        num, _, denom = first.partition("/")
        try:
            num_f, denom_f = float(num), float(denom)
        except ValueError:
            return None
        if denom_f <= 0:
            return None
        return round(max(0.0, min(100.0, num_f / denom_f * 100)), 1)
    try:
        return round(max(0.0, min(100.0, float(first))), 1)
    except ValueError:
        return None


class BattleParser:
    """Parses one battle's log lines into events.json-shaped event dicts.
    One instance per battle/replay - create a fresh one for each file when
    combining several replays into one events.json."""

    def __init__(self, match_number, player_id="p1"):
        self.match_number = match_number
        self.player_id = player_id   # a raw side ("p1"/"p2") or a username, resolved once |player| lines are seen
        self.player_side = None      # resolved to "p1" or "p2" once known
        self.usernames = {}          # "p1" -> "Geordivgc", "p2" -> "JarlomenVGC"
        # "p1a"/"p1b"/"p2a"/"p2b" -> current species in THAT EXACT slot. Keyed
        # by the FULL position id (slot letter included) - a real bug fixed
        # 2026-07-04: this used to be keyed by side only (_position_side()
        # sliced the id down to 2 chars, dropping the a/b slot letter), so in
        # doubles the two active Pokemon on one side silently overwrote each
        # other's tracked species - a move/faint/status/ability/item read for
        # slot "b" could report whichever of the side's two Pokemon happened
        # to switch in more recently, not the one that actually acted. Fixed
        # by tracking the full slot id throughout (see _position_id/
        # _side_of_position) - this also happens to be exactly what's needed
        # to build a real field_state event with BOTH active Pokemon per side
        # (see _emit_field_state), which decision_windows.py's turn-bucketing
        # needs to work on Showdown-imported matches at all.
        self.active = {}
        # position_id -> index into self.events of that slot's most recent
        # pokemon_sent_out event. Exists solely to let a later |replace|
        # (Illusion ending - see feed_line's own "replace" branch) know
        # exactly which already-emitted events belong to the decoy identity
        # it needs to retroactively correct, without guessing from species
        # name or log position - see that branch's own comment for why a
        # name-based guess would be unsafe (Species Clause doesn't protect
        # against a decoy species that legitimately appeared earlier in the
        # SAME match under a different, non-illusioned Pokemon).
        self.slot_last_switch_index = {}
        self.gametype = None         # "singles"/"doubles"/etc, from the log's own |gametype| line -
                                      # ground truth for mode, more reliable than trusting a CLI flag
                                      # that could mismatch what this particular replay actually was
        self.team_preview = {"p1": [], "p2": []}   # side -> [species,...] from |poke| lines
        self.events = []
        self.winner = "unknown"
        self.winner_detail = ""
        self.start_ts = None         # first |t:| timestamp seen, for relative seconds
        self.last_ts = 0.0
        # The replay protocol's own |turn|N| line - exact ground truth for
        # turn number, unlike the video pipeline which has to read it off a
        # screen. Starts at 1 since the initial leads are always switched in
        # BEFORE the very first |turn|1| line appears (real protocol order:
        # |switch| x2 per side, THEN |turn|1|) - see _emit_field_state.
        self.current_turn = 1
        # Field-condition state, updated live as |-weather|/|-fieldstart|/
        # |-fieldend|/|-sidestart|/|-sideend| lines arrive, and read into
        # each turn's field_state event by _emit_field_state() below - see
        # the _WEATHER_NAMES/_TERRAIN_NAMES/_SCREEN_NAMES module constants
        # for the exact vocabulary this normalizes onto.
        self.weather = "none"
        self.terrain = "none"
        self.trick_room = False
        self.tailwind_sides = set()          # raw side ids ("p1"/"p2") currently under Tailwind
        self.screens = {"p1": set(), "p2": set()}   # raw side id -> set of active screen names

    def _side_for(self, side_id):
        """Resolve a raw side ("p1"/"p2") to "player" or "opponent". Defensive
        on-demand resolve in case an event somehow arrives before both
        |player| lines have been seen (shouldn't happen in a real Showdown
        log - both always appear before any switch/move - but this avoids
        silently mis-attributing every event to "opponent" if it ever did)."""
        if not self.player_side:
            self._resolve_player_side()
        return "player" if side_id == self.player_side else "opponent"

    def _resolve_player_side(self):
        """Deliberately does NOT lock in a "p1" default here - this gets
        called after EACH |player| line is seen, one side at a time, so if
        --player names the side-2 username, it wouldn't have been seen yet
        the first time this runs. A real bug caught while testing against a
        real replay: locking in a wrong default here made it permanent (see
        the `if self.player_side: return` guard above), silently attributing
        every single event to the wrong side whenever --player was the
        second username printed in the log. The actual "if still unresolved,
        default to p1" fallback only happens in finalize_player_side(),
        after the WHOLE log (both usernames) has been read."""
        if self.player_side:
            return
        if self.player_id in ("p1", "p2"):
            self.player_side = self.player_id
            return
        for side, name in self.usernames.items():
            if name.lower() == str(self.player_id).lower():
                self.player_side = side
                return

    def finalize_player_side(self):
        """Called once, after the entire log has been fed - only NOW is it
        safe to fall back to a default, since every username has definitely
        been seen by this point."""
        self._resolve_player_side()
        if not self.player_side:
            self.player_side = "p1"

    def _ts(self, unix_time=None):
        if unix_time is not None:
            if self.start_ts is None:
                self.start_ts = unix_time
            self.last_ts = float(unix_time - self.start_ts)
        return self.last_ts

    def _emit(self, event, actor, pokemon=None, detail="", confidence=1.0, **extra):
        row = {"timestamp": round(self._ts(), 1), "event": event, "actor": actor,
               "pokemon": pokemon, "detail": detail, "confidence": confidence,
               "match": self.match_number}
        row.update(extra)
        self.events.append(row)

    def _tailwind_value(self):
        """"player"/"opponent"/"both"/"none" - see game.json's field spec.
        Translates the raw p1/p2 side ids self.tailwind_sides tracks into
        this project's player-relative vocabulary, the same translation
        _emit_field_state already does for player_active/opponent_active."""
        opp_side = "p2" if self.player_side == "p1" else "p1"
        has_player = self.player_side in self.tailwind_sides
        has_opponent = opp_side in self.tailwind_sides
        if has_player and has_opponent:
            return "both"
        if has_player:
            return "player"
        if has_opponent:
            return "opponent"
        return "none"

    def _screens_value(self):
        """"player Reflect, opponent Light Screen" (comma-joined, one entry
        per active side+screen combination) or "none" - matches game.json's
        own documented example format ("player Reflect"), extended to list
        more than one active screen since either side can have up to 2 up
        (a screen + Aurora Veil don't stack, but Reflect + Light Screen do)."""
        opp_side = "p2" if self.player_side == "p1" else "p1"
        labels = []
        for side_id, label in ((self.player_side, "player"), (opp_side, "opponent")):
            for name in sorted(self.screens.get(side_id, ())):
                labels.append(f"{label} {name}")
        return ", ".join(labels) if labels else "none"

    def _emit_field_state(self):
        """One field_state event per real turn boundary (the exact |turn|N|
        protocol line - see feed_line's own comment), listing both sides'
        currently-active Pokemon - the SAME shape analyze_matches.py's video
        pipeline produces (player_active/opponent_active comma strings, a
        `turn` number - see adapters/pokemon/*.json's fields spec), so
        decision_windows.py's turn-bucketing (which keys ONLY off
        field_state events) works identically whether a match came from
        video or a Showdown replay. Sorted by position id (p1a before p1b)
        purely for a stable, predictable ordering - doubles has no
        meaningful "first slot" otherwise.

        Also carries weather/terrain/trick_room/tailwind/screens - see
        _WEATHER_NAMES/_TERRAIN_NAMES/_SCREEN_NAMES and the -weather/
        -fieldstart/-fieldend/-sidestart/-sideend handlers in feed_line for
        how this state is kept current. Added 2026-07-09 alongside this
        project's VGC Battle Intelligence Manual reports - previously these
        5 fields were only ever populated by the video pipeline's Gemini
        vision read, never by this deterministic Showdown parser."""
        self._resolve_player_side()
        opp_side = "p2" if self.player_side == "p1" else "p1"
        player_active = [sp for pos, sp in sorted(self.active.items()) if pos.startswith(self.player_side)]
        opponent_active = [sp for pos, sp in sorted(self.active.items()) if pos.startswith(opp_side)]
        self._emit("field_state", "both",
                    player_active=", ".join(player_active),
                    opponent_active=", ".join(opponent_active),
                    turn=self.current_turn,
                    weather=self.weather,
                    terrain=self.terrain,
                    trick_room=self.trick_room,
                    tailwind=self._tailwind_value(),
                    screens=self._screens_value(),
                    detail=f"Turn {self.current_turn}")

    def feed_line(self, line):
        if not line.startswith("|"):
            return
        parts = line.split("|")
        # line looks like "|TYPE|arg1|arg2|..." -> parts[0] is "" (before the leading |)
        msg_type = parts[1] if len(parts) > 1 else ""
        args = parts[2:]

        if msg_type == "gametype" and args:
            self.gametype = args[0].strip().lower()

        elif msg_type == "player" and len(args) >= 2 and args[1]:
            self.usernames[args[0]] = args[1]
            self._resolve_player_side()

        elif msg_type == "poke" and len(args) >= 2:
            side, details = args[0], args[1]
            self.team_preview.setdefault(side, []).append(species_from_details(details))

        elif msg_type == "t:" and args:
            try:
                self._ts(int(args[0]))
            except ValueError:
                pass

        elif msg_type == "turn" and args:
            # The real, exact turn boundary straight from the replay protocol
            # (see sim/SIM-PROTOCOL.md's |turn|N| line) - everything fed to
            # this parser AFTER this line belongs to turn N, same "assign
            # forward, not retroactively" convention decision_windows.py's
            # own field_state/turn bucketing uses for the video pipeline.
            # Emitting a field_state here is what finally lets Showdown-
            # imported matches produce real decision_windows - previously a
            # documented, honest gap (decision_windows.py's own docstring:
            # "currently true of EVERY Showdown-imported match").
            try:
                self.current_turn = int(args[0])
            except ValueError:
                pass
            self._emit_field_state()

        elif msg_type in ("switch", "drag", "detailschange") and len(args) >= 2:
            pokemon_id, details = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = species_from_details(details)
            self.active[position_id] = species
            self._resolve_player_side()
            actor = self._side_for(_side_of_position(position_id))
            self._emit("pokemon_sent_out", actor, pokemon=species,
                        detail=f"{'switched in' if msg_type in ('switch', 'drag') else 'transformed'}")
            self.slot_last_switch_index[position_id] = len(self.events) - 1

        elif msg_type == "replace" and len(args) >= 2:
            # Illusion has ended for this slot (see sim/SIM-PROTOCOL.md's
            # |replace| line: "everything you thought you knew about the
            # previous Pokemon is now wrong"). `details` carries the REAL
            # species (in practice always Zoroark/Zoroark-Hisui, Illusion's
            # only real users) - everything already emitted for this exact
            # slot since its last switch-in (pokemon_sent_out/move_used/
            # hp_change/status_inflicted/etc, all recorded under the decoy
            # species) was attributed to the wrong Pokemon and needs fixing
            # retroactively, not just corrected going forward.
            #
            # Found 2026-07-08 while reviewing a third-party Showdown-
            # replay-parsing script for ideas: that script does a similar
            # retroactive fix (backtracking to the slot's most recent
            # |-damage| line to identify the decoy). This is an independent
            # implementation of the same underlying idea - scoped by this
            # exact slot's own recorded switch-in EVENT INDEX
            # (slot_last_switch_index) rather than re-deriving position from
            # log text, so it can never bleed into an unrelated earlier
            # instance of the same species name on the same side (e.g. a
            # real teammate who happened to share a name with the decoy and
            # had already fainted/switched out earlier in the SAME match,
            # before this slot's own illusion-disguised switch-in) - only
            # events at or after this slot's own last switch-in are ever
            # touched.
            #
            # Before this fix: showdown_import.py treated |replace| exactly
            # like an ordinary switch, so only events AFTER the reveal used
            # the real species - every move/faint/status/HP event from
            # while the illusion was still up stayed mislabeled under the
            # decoy's name. Since Zoroark is legal and actually played in
            # Reg Champions VGC, any Showdown-imported match containing a
            # real Illusion reveal had genuinely wrong event data until now.
            pokemon_id, details = args[0], args[1]
            position_id = _position_id(pokemon_id)
            decoy_species = self.active.get(position_id)
            real_species = species_from_details(details)
            self._resolve_player_side()
            actor = self._side_for(_side_of_position(position_id))
            start_idx = self.slot_last_switch_index.get(position_id)
            if decoy_species and real_species != decoy_species and start_idx is not None:
                for row in self.events[start_idx:]:
                    if row.get("actor") == actor and row.get("pokemon") == decoy_species:
                        row["pokemon"] = real_species
            self.active[position_id] = real_species
            self._emit("pokemon_sent_out", actor, pokemon=real_species,
                        detail=(f"Illusion revealed (was disguised as {decoy_species})"
                                if decoy_species and decoy_species != real_species
                                else "Illusion revealed"))
            self.slot_last_switch_index[position_id] = len(self.events) - 1

        elif msg_type == "move" and len(args) >= 2:
            pokemon_id, move = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            self._emit("move_used", self._side_for(_side_of_position(position_id)), pokemon=species, detail=move)

        elif msg_type == "faint" and args:
            pokemon_id = args[0]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            self._emit("pokemon_fainted", self._side_for(_side_of_position(position_id)), pokemon=species,
                       detail="fainted", hp_percent=0)
            # This slot is empty until the next switch - drop it so a stale
            # species can't be misattributed to whatever eventually re-fills
            # it, and _emit_field_state()'s active-Pokemon listing doesn't
            # keep reporting a fainted mon as still on the field.
            self.active.pop(position_id, None)

        elif msg_type == "-status" and len(args) >= 2:
            pokemon_id, status = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            self._emit("status_inflicted", self._side_for(_side_of_position(position_id)),
                       pokemon=species, detail=status)

        elif msg_type in ("-boost", "-unboost") and len(args) >= 3:
            # A real gap found while building strategic_analysis.py's win-
            # condition inference (2026-07-04): this project never parsed
            # Showdown's own |-boost|/|-unboost| lines at all, so no
            # Showdown-imported match ever produced a stat_change event -
            # meaning nothing could ever detect a stat-boost-driven "sweep"
            # on Showdown data. Formats detail exactly like
            # battle_text_parser.py's OCR-tier stat_change text ("Attack
            # rose", "Speed sharply rose") so ONE shared parser
            # (strategic_analysis._parse_stat_change) works on both
            # sources; `stat`/`stages` are ALSO included as structured
            # extras (Showdown gives an exact integer stage count, unlike
            # OCR text) for anything that wants the precise number rather
            # than the fuzzy "sharply"/plain wording.
            pokemon_id, stat, amount = args[0], args[1], args[2]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            stat_name = _STAT_NAMES.get(stat.strip().lower(), stat.strip())
            try:
                n = int(amount)
            except ValueError:
                n = 1
            rising = msg_type == "-boost"
            stage_word = ("sharply rose" if n >= 2 else "rose") if rising else \
                         ("harshly fell" if n >= 2 else "fell")
            self._emit("stat_change", self._side_for(_side_of_position(position_id)),
                       pokemon=species, detail=f"{stat_name} {stage_word}",
                       stat=stat_name, stages=(n if rising else -n))

        elif msg_type in ("-damage", "-heal") and len(args) >= 2:
            # Another real gap found while building strategic_analysis.py's
            # HP-percent scoring (2026-07-05): this project never parsed
            # Showdown's own |-damage|/|-heal| lines, so no Showdown-imported
            # match ever produced an hp_change event - meaning HP-based
            # scoring had zero data to work with on Showdown replays, even
            # though the replay carries an EXACT HP fraction on every single
            # hit (unlike the video pipeline's best-effort, sometimes-missing
            # OCR/vision read - see strategic_analysis.py's own docstring for
            # that side's honest limitations). Emits the SAME "hp_change"
            # event shape/field name (`hp_percent`) the video pipeline's
            # Gemini-derived events already use (see adapters/pokemon/
            # game.json's fields spec), so one shared reader works on both
            # sources. Silently skips a line that doesn't parse to a real
            # number (_parse_hp_fraction) rather than emitting a guessed HP.
            pokemon_id, hp_field = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            hp_percent = _parse_hp_fraction(hp_field)
            if hp_percent is not None:
                self._emit("hp_change", self._side_for(_side_of_position(position_id)),
                           pokemon=species, detail=f"HP: {hp_field.strip()}",
                           hp_percent=hp_percent)
            # Item-reveal detection, added 2026-07-09 for item_inference.py
            # (see that module's docstring - direct user request: don't
            # assume the opponent has Life Orb/Choice Scarf/Focus Sash etc.
            # in a damage calculation until it's actually been confirmed).
            # Showdown attributes the CAUSE of damage/heal directly in the
            # protocol line itself (args[2], e.g. "[from] item: Life Orb")
            # rather than requiring any inference from HP math - a real
            # example (Life Orb recoil): "|-damage|p1a: Garchomp|88/100|
            # [from] item: Life Orb", the line immediately after the SAME
            # Pokemon's own move dealt damage that turn. Only fires on an
            # explicit "[from] item:" tag - "[from] move: ..."/"[from]
            # ability: ..." attributions (recoil moves, Rough Skin, etc.)
            # are a different, unrelated cause and are deliberately left
            # alone here, same "don't guess beyond what the protocol
            # actually says" discipline as everywhere else in this parser.
            if len(args) >= 3 and args[2].strip().lower().startswith("[from] item:"):
                item_name = args[2].split(":", 1)[1].strip()
                if item_name:
                    self._emit("item_or_ability_activated", self._side_for(_side_of_position(position_id)),
                               pokemon=species,
                               detail=f"item: {item_name} ({'recoil' if msg_type == '-damage' else 'heal'})",
                               item=item_name)

        elif msg_type in ("-ability", "-item") and len(args) >= 2 and not args[1].startswith("[from]"):
            pokemon_id, value = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            extra = {"item": value} if msg_type == "-item" else {"ability": value}
            self._emit("item_or_ability_activated", self._side_for(_side_of_position(position_id)),
                       pokemon=species, detail=f"{msg_type.lstrip('-')}: {value}", **extra)

        elif msg_type == "-activate" and len(args) >= 2 and args[1].strip().lower().startswith("item:"):
            # Real protocol example: "|-activate|p2a: Wynaut|item: Focus
            # Sash" - fires the instant Focus Sash (or a similar activated
            # item) actually does something, e.g. holding a Pokemon at 1 HP
            # instead of fainting it. This is Showdown's OWN confirmation,
            # not an inference from "it survived a hit that looked lethal"
            # (which could also be Sturdy, Endure, a berry, or simply not
            # having been lethal in the first place - no need to guess when
            # the protocol says exactly which one it was).
            pokemon_id, value = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            item_name = value.split(":", 1)[1].strip()
            if item_name:
                self._emit("item_or_ability_activated", self._side_for(_side_of_position(position_id)),
                           pokemon=species, detail=f"item: {item_name} (activated)", item=item_name)

        elif msg_type == "-enditem" and len(args) >= 2:
            # Real protocol example: "|-enditem|p2a: Wynaut|Sitrus Berry" -
            # the item is consumed/removed (a berry eaten, Air Balloon
            # popped, or Focus Sash used up - Focus Sash triggers BOTH
            # -activate and this line; item_or_ability_activated events are
            # deduplicated per-Pokemon-per-item by item_inference.py's
            # dict-shaped output, so seeing the same item twice from one
            # Pokemon is harmless, not double-counted).
            pokemon_id, item_name = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            item_name = item_name.strip()
            if item_name and not item_name.startswith("["):
                self._emit("item_or_ability_activated", self._side_for(_side_of_position(position_id)),
                           pokemon=species, detail=f"item: {item_name} (consumed)", item=item_name)

        elif msg_type == "-mega" and len(args) >= 2:
            pokemon_id, stone = args[0], args[1]
            position_id = _position_id(pokemon_id)
            self._emit("item_or_ability_activated", self._side_for(_side_of_position(position_id)),
                       pokemon=self.active.get(position_id), detail=f"Mega Evolved ({stone})")

        elif msg_type == "-terastallize" and len(args) >= 2:
            # A real, previously-unparsed protocol line found 2026-07-08
            # while reviewing a third-party Showdown-log-parsing script for
            # ideas (its own example line: "|-terastallize|p1b: Amoonguss|
            # Dark"). showdown_import.py had a handler for -mega but none
            # for -terastallize, so NO Showdown-imported match has ever
            # produced a "terastallized" event - even though this project
            # already has a full "terastallized" event type wired through
            # player_report.py, coach_report.py, coach_chat.py, and
            # backend/analytics.py (all built against the video pipeline's
            # Gemini-derived events, per adapters/pokemon/game.json's
            # event_types list). Detail phrasing ("Terastallized into the
            # X type") matches that adapter's own documented on-screen-text
            # convention, and `tera_type` is added as a structured extra
            # (same pattern as stat_change's `stat`/`stages`) for anything
            # that wants the exact type without parsing `detail` text.
            pokemon_id, tera_type = args[0], args[1]
            position_id = _position_id(pokemon_id)
            species = self.active.get(position_id, pokemon_id.split(":")[-1].strip())
            self._emit("terastallized", self._side_for(_side_of_position(position_id)),
                       pokemon=species, detail=f"Terastallized into the {tera_type} type",
                       tera_type=tera_type)

        elif msg_type == "-weather" and args:
            # Sent both when weather actually changes AND as a once-per-turn
            # |[upkeep]| reminder while it's still active - both cases are
            # handled identically (an idempotent set), so a same-value
            # upkeep line is a no-op. See _WEATHER_NAMES for the mapping
            # onto this project's "sun/rain/sand/snow/none" vocabulary.
            raw = args[0].strip()
            self.weather = _WEATHER_NAMES.get(raw.lower(), raw)

        elif msg_type == "-fieldstart" and args:
            condition = _strip_move_prefix(args[0]).lower()
            if condition == "trick room":
                self.trick_room = True
            elif condition in _TERRAIN_NAMES:
                self.terrain = _TERRAIN_NAMES[condition]
            # Anything else (Gravity, Magic Room, Wonder Room, etc.) isn't in
            # this project's tracked field_state vocabulary - ignored, not guessed.

        elif msg_type == "-fieldend" and args:
            condition = _strip_move_prefix(args[0]).lower()
            if condition == "trick room":
                self.trick_room = False
            elif condition in _TERRAIN_NAMES and self.terrain == _TERRAIN_NAMES[condition]:
                self.terrain = "none"

        elif msg_type == "-sidestart" and len(args) >= 2:
            side_id = args[0].split(":")[0].strip()
            condition = _strip_move_prefix(args[1])
            if condition == "Tailwind":
                self.tailwind_sides.add(side_id)
            elif condition in _SCREEN_NAMES:
                self.screens.setdefault(side_id, set()).add(condition)

        elif msg_type == "-sideend" and len(args) >= 2:
            side_id = args[0].split(":")[0].strip()
            condition = _strip_move_prefix(args[1])
            if condition == "Tailwind":
                self.tailwind_sides.discard(side_id)
            elif condition in _SCREEN_NAMES:
                self.screens.get(side_id, set()).discard(condition)

        elif msg_type == "win" and args:
            winner_name = args[0]
            self._resolve_player_side()
            player_name = self.usernames.get(self.player_side, "")
            self.winner = "player" if winner_name.lower() == player_name.lower() else "opponent"
            self.winner_detail = f"{winner_name} won"

        elif msg_type == "tie":
            self.winner = "unknown"
            self.winner_detail = "tied"

    def build_team_preview_event(self):
        """Mirrors analyze_matches.py's team_preview event shape exactly,
        including running the SAME species-legality allowlist check - for a
        real Showdown ladder/tournament battle this should always come back
        clean (Showdown enforces legality server-side), so a rejection here
        is a strong signal our OWN allowlist is stale, not that the replay
        is wrong."""
        self.finalize_player_side()
        opp_side = "p2" if self.player_side == "p1" else "p1"
        pteam_raw = self.team_preview.get(self.player_side, [])
        oteam_raw = self.team_preview.get(opp_side, [])
        pteam, pteam_rejected = am.reject_banned_species(pteam_raw)
        oteam, oteam_rejected = am.reject_banned_species(oteam_raw)

        roster = {"player_team": pteam, "opponent_team": oteam}
        # self.gametype comes straight from the replay log's own |gametype| line -
        # ground truth for mode, so brought/lead caps match what this particular
        # battle actually was rather than assuming doubles for everything.
        rules = ({"bring_count": None, "active_per_side": 1, "team_size_max": 6}
                  if self.gametype == "singles"
                  else {"bring_count": 4, "active_per_side": 2})
        pbrought, obrought, plead, olead = am.derive_brought(self.events, roster, rules=rules)

        rejected = sorted(set(pteam_rejected + oteam_rejected))
        return {
            "timestamp": 0.0, "event": "team_preview", "actor": "both",
            "detail": (f"P1 team: {', '.join(pteam)} | P2 team: {', '.join(oteam)}  ||  "
                       f"P1 brought: {', '.join(pbrought)} | P2 brought: {', '.join(obrought)}"),
            "player_team": ", ".join(pteam), "opponent_team": ", ".join(oteam),
            "player_brought": ", ".join(pbrought), "opponent_brought": ", ".join(obrought),
            "player_lead": ", ".join(plead), "opponent_lead": ", ".join(olead),
            "illegal_species_detected": rejected,
            "confidence": 1.0, "match": self.match_number,
            "source": "showdown",
        }

    def build_battle_end_event(self):
        return {"timestamp": round(self._ts(), 1), "event": "battle_end", "actor": self.winner,
                "detail": self.winner_detail or f"match {self.match_number} result",
                "winner": self.winner, "confidence": 1.0, "match": self.match_number}

    def parse(self, log_text):
        for line in log_text.splitlines():
            self.feed_line(line.strip())
        team_preview_event = self.build_team_preview_event()
        battle_end_event = self.build_battle_end_event()
        return [team_preview_event] + self.events + [battle_end_event]


def parse_replay(raw_source, match_number, player_id="p1"):
    """raw_source: the raw text content (already read from file/URL). Returns
    a list of event dicts in this project's events.json shape."""
    log_text = extract_log_text(raw_source)
    parser = BattleParser(match_number, player_id)
    return parser.parse(log_text)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def save_outputs(all_events, out_path):
    # am._atomic_write (analyze_matches.py) - reused rather than duplicated a
    # third time (backend/job_files.py has its own copy for the FastAPI
    # server's own writes) - see its docstring for why a plain open(path, "w")
    # is unsafe here: a real corrupted events.json in production was traced
    # to exactly this kind of interrupted, non-atomic write.
    am._atomic_write(out_path, lambda f: json.dump(all_events, f, indent=2))
    if all_events:
        keys = []
        for e in all_events:
            for k in e.keys():
                if k not in keys:
                    keys.append(k)
        csv_path = str(Path(out_path).with_suffix(".csv"))

        def _write_csv(f):
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for e in all_events:
                w.writerow(e)

        am._atomic_write(csv_path, _write_csv)


def build_sources(args):
    """Turns whichever mutually-exclusive CLI source option was given into a
    uniform list of (kind, source) tuples, kind being "url" or "file" - pulled
    out of main() so this bit of branching logic (which option implies what)
    is unit-testable without needing real files/network. Precedence mirrors
    the argparse mutually-exclusive group: exactly one of these is set."""
    if args.files:
        return [("file", f) for f in args.files]
    if args.urls:
        return [("url", u) for u in args.urls]
    if args.url:
        return [("url", args.url)]
    return [("file", args.file)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="a saved Showdown replay .html or .json file")
    src.add_argument("--url", help="a live replay URL (replay.pokemonshowdown.com/...)")
    src.add_argument("--files", nargs="+", help="multiple replay files, combined into one events.json "
                     "as consecutive matches (1, 2, 3, ...)")
    src.add_argument("--urls", nargs="+", help="multiple live replay URLs, combined into one events.json "
                     "as consecutive matches (1, 2, 3, ...) - same idea as --files but for URLs "
                     "instead of saved files (e.g. importing several ladder games from one session).")
    ap.add_argument("--player", default="p1", help="which side is 'you' - a Showdown username, or "
                    "'p1'/'p2'. Defaults to p1 (a replay has no built-in notion of 'the player').")
    ap.add_argument("--out", default="events.json")
    ap.add_argument("--append", action="store_true", help="merge into an existing --out file instead "
                    "of overwriting it, numbering new matches after the highest existing match number")
    ap.add_argument("--regulation", default="m-b", help="Which Pokemon Champions regulation's roster "
                    "to check species legality against (adapters/pokemon/regulations/<id>.json) - e.g. "
                    "m-b (current) or m-a (launch, superseded 2026-06-17). Showdown enforces format "
                    "legality server-side, so a real replay should never actually trip this - it mainly "
                    "guards against a replay being imported under the wrong regulation label. See "
                    "analyze_matches.configure_regulation.")
    ap.add_argument("--adapters", default="adapters", help="Adapters directory (default: adapters, "
                    "relative to the current directory - the backend passes an absolute path here).")
    args = ap.parse_args()

    am.configure_regulation(args.adapters, args.regulation)

    existing = []
    start_match_number = 1
    if args.append and Path(args.out).exists():
        with open(args.out, encoding="utf-8") as f:
            existing = json.load(f)
        existing_numbers = [e.get("match") for e in existing if isinstance(e.get("match"), int)]
        start_match_number = (max(existing_numbers) + 1) if existing_numbers else 1

    sources = build_sources(args)

    all_new_events = []
    for i, (kind, source) in enumerate(sources):
        match_number = start_match_number + i
        raw = read_source(url=source) if kind == "url" else read_source(file=source)
        events = parse_replay(raw, match_number, args.player)
        tp = events[0]
        be = events[-1]
        print(f"Match {match_number} ({source}): "
              f"player[{len(tp['player_team'].split(', ')) if tp['player_team'] else 0}] "
              f"opponent[{len(tp['opponent_team'].split(', ')) if tp['opponent_team'] else 0}]  "
              f"winner: {be['winner']}"
              + (f"  \U0001f6ab illegal: {tp['illegal_species_detected']}" if tp["illegal_species_detected"] else ""))
        all_new_events.extend(events)

    save_outputs(existing + all_new_events, args.out)
    print(f"\nWrote {len(existing) + len(all_new_events)} events -> {args.out} "
          f"({len(sources)} match(es) from this run).")
    print("Next: py battle_record.py   and   py player_report.py   (or open the dashboard)")


if __name__ == "__main__":
    main()
