"""
Resolves the ambiguity a Pokemon nickname creates for OCR-based reading: a
Pokemon's on-screen name plate shows whatever the player NAMED it (a
nickname, e.g. "Big Red") just as often as it shows the species itself -
there's no way to tell which from text alone, and no Pokemon/Showdown/
PokeAPI database can look up an arbitrary player-chosen nickname (unlike
movesets or type data, a nickname isn't in any database at all - it's
whatever the player typed in). See ARCHITECTURE_HANDOFF.md's nickname
discussion for the full reasoning.

The fix doesn't need a fresh vision call per frame, just ONE per Pokemon:
the first time a given display name is seen (team preview, or its first
send-out in battle), a single Gemini vision call identifies the actual
species by appearance, and that mapping is reused for every subsequent OCR
read of that same display name for the rest of the match - a nickname
doesn't change mid-battle, so this only needs solving once per Pokemon,
not once per frame it appears in.

Most Pokemon aren't nicknamed at all, though, and that common case should
stay free - `resolve_or_flag()` first tries a cheap, local fuzzy-text match
against the match's own known roster (the same "is this just a misspelling
of a real roster name" check `analyze_matches._canon()` already does for
event text) before ever asking the caller to spend a real vision call. Only
a display name that doesn't resemble ANY known roster member at all - a
genuine nickname - gets flagged as needing one.
"""

import re


def _norm(name):
    """Same normalization analyze_matches.py's _norm() uses - lowercase,
    letters/digits only - so "Sp. Def", "Mr. Mime", etc. compare sanely."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _fuzzy_match(display_name, known_species):
    """A local, free, deterministic check for "is this display name just a
    plausible misread/partial read of a real roster species" - NOT a
    nickname resolver. Returns the matched species, or None if nothing in
    known_species resembles it closely enough to be worth trusting without
    a real vision call."""
    key = _norm(display_name)
    if not key:
        return None
    for species in known_species:
        species_key = _norm(species)
        if not species_key:
            continue
        if key == species_key:
            return species
        # Partial/prefix overlap only - NOT used for a full nickname like
        # "BigRed" vs "Charizard" (those share no meaningful substring), so
        # this stays safely narrow rather than accidentally "resolving" an
        # actual nickname through a coincidental short overlap.
        if len(key) >= 4 and (species_key.startswith(key) or key.startswith(species_key)):
            return species
    return None


class IdentityResolver:
    """One instance per match. Tracks the mapping from whatever display
    name appears on screen to the actual resolved species, scoped to one
    match (a nickname is only ever consistent within the match it's used
    in - a fresh IdentityResolver should be created per match, the same
    way analyze_matches.py already scopes rosters per match)."""

    def __init__(self, known_species=None):
        """`known_species`: the match's own known roster (player_team +
        opponent_team) - used for the free fuzzy-match path before ever
        asking for a real vision call. Optional; an empty/omitted roster
        just means every display name will need an explicit learn() call."""
        self._map = {}  # normalized display name -> resolved species
        self._known_species = set(known_species or [])

    def resolve_or_flag(self, display_name):
        """The main entry point. Returns (species, needs_vision_call):
          - (species, False) - already resolved (either learned earlier
            this match, or matched cheaply against the known roster just
            now) - no vision call needed.
          - (None, True) - this display name doesn't match anything known;
            a real vision call is needed to identify it, then learn() must
            be called with the result so it's never asked for again.
        Returns (None, False) for a blank/missing display name - nothing
        useful to resolve, and nothing worth spending a vision call on."""
        if not display_name:
            return None, False

        key = _norm(display_name)
        if key in self._map:
            return self._map[key], False

        fuzzy = _fuzzy_match(display_name, self._known_species)
        if fuzzy:
            self._map[key] = fuzzy   # cache so repeats skip even this cheap check
            return fuzzy, False

        return None, True

    def learn(self, display_name, species):
        """Records a display_name -> species mapping - call this once,
        right after resolving a flagged (needs_vision_call=True) display
        name via an actual vision call, so it's never flagged again this
        match. Also widens known_species so future fuzzy-matches (e.g. a
        second, differently-cased OCR read of the same nickname) can hit
        the cheap path too."""
        if not display_name or not species:
            return
        self._map[_norm(display_name)] = species
        self._known_species.add(species)

    def known_display_names(self):
        """Every display name resolved so far this match (nicknames and
        plain species names alike) - useful for a caller that wants to
        know what's already been handled without re-deriving it."""
        return set(self._map.keys())
