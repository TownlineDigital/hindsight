# Overnight report — 2026-07-03

Morning summary of the overnight pass on `accuracy_addons/`. Everything below
was tested against **real** project footage/data this session — nothing is
marked done unless I actually ran it and saw the result. All work stayed inside
`accuracy_addons/` (plus the one allowed note in `ARCHITECTURE_HANDOFF.md` §2e);
no pipeline files were touched.

## What got done (with real numbers)

**1. New burn status-condition icon — the strongest-tested template we have.**
Cropped an 18×18 burn badge (the flame on a burned Pokémon's plate) from a real
frame (`jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg`, a burned
Hydreigon) and wired it into `icon_template_matcher.py` under a new
`templates/status/` category. It doesn't just self-match its own frame (1.000) —
I ran it across all 38 battle frames of that match and it scored **0.94–0.98 on
the 10 other frames** where the burn badge is showing, vs **0.30–0.43** where
it isn't. Clean separation, real cross-frame generalization. (The 3 original
move-type templates were only ever self-match-tested, so this is a step up.)
No Tera crown was found in the frames reviewed — expected, since this format
has Terastallization off. I did not force one.

**2. Player's own HP bar (bottom-left plate) is now measured & validated.**
`hp_bar_reader.py` only had the opponent's top-right plate. I measured the
player's bottom-left plate from real pixels (not by assuming symmetry — the two
plates are laid out differently) and validated it at **two** real HP values:
Rotom at 157/157 → reads 100%, and Rotom at 69/157 (= 44% by the on-screen
text) → reads 51%. Both agree within the tool's ±8-point coarse tolerance. The
~7-point miss at 44% is consistent with the known ~1–2 HP%/pixel precision cap
at 640×360 — good for catching a badly-wrong read, not for exact numbers.

**3. Fixed a real staleness bug in `format_rules_validator.py`.** While
re-running the format cross-check I found it had quietly broken: the codebase's
regulation-layer refactor (§3a) moved the banned-species / Tera / regulation
facts out of `doubles.json` into `adapters/pokemon/regulations/m-b.json`, so the
validator was checking an empty spot and reporting a **false "mismatch"** on the
Mythical/Restricted-Legendary ban. I made it read the regulation layer where
those facts now live. Re-run against the real files, that check is back to a
correct **MATCH** — the ironic case of the staleness-checker itself going stale,
caught and fixed.

**4. Reg M-B re-fetch — still not in Showdown.** Re-fetched
`config/formats.ts` and searched specifically for Reg M-B. It's **still not
there** as its own Champions entry (only Reg M-A, Reg M-A Bo3, BSS Reg M-A). So
the exact-regulation check stays honestly "not confirmable" — no change to
upgrade it, and I didn't pretend otherwise.

## Still open / blocked (and why)

- **Full Showdown learnset export — still blocked, same as last night.** npm is
  still 403 in this sandbox, the 3.55 MB `learnsets.ts` comes back empty through
  the fetch tool, and per-species APIs (PokeAPI etc.) aren't reachable under the
  fetch tool's provenance rule (it only allows URLs that literally appear in
  search results). So `moveset_validator`'s coverage is **unchanged** — still
  the 15 starter species. Good news: 3 of those 15 (Charizard, Venusaur,
  Blastoise) actually do appear in your real match footage, and I re-confirmed
  the check works against them this session (Charizard+Flamethrower→True,
  Charizard+Thunderbolt→False+flagged, Hydreigon→None because it's not in the
  data yet). **I did not fabricate any learnsets from memory** to fake coverage —
  when you have a machine with normal npm access, running
  `tools/export_showdown_learnsets.js` is still the real fix.
- **HP-bar plates aren't pinned to a fixed screen position.** I found the
  opponent region reads 0% on a frame where its plate sits ~8px lower than in
  the frame it was measured from. Both HP regions are validated for the plate
  position they were measured against; a robust integration should locate the
  plate first (e.g. via a template anchor) rather than trust fixed coordinates.
  Documented in `hp_bar_reader.py`.

## Judgment calls I made while you were away

- Put the burn badge in a new `templates/status/` folder and a separate
  `VALIDATED_STATUS_TEMPLATES` registry rather than mixing it into the
  move-type set, to keep the two icon categories cleanly separable.
- Made `format_rules_validator.py` auto-load the regulation layer (defaulting
  to `m-b`) so existing callers keep working without code changes, while new
  callers can pass a specific regulation file. Kept a legacy fallback so it
  degrades gracefully instead of crashing.
- Chose to *fix* the validator's regulation-layer staleness rather than just
  report it, since it was inside `accuracy_addons/` (my safe-to-edit zone) and
  the fix is exactly the kind of thing this tool exists to do.

## One environment note (not a code problem)

This dev sandbox's Linux mount served **stale/truncated copies** of the Python
files right after I edited them (a sync lag that didn't recover on its own).
Your actual files on disk are complete and correct — the edits went through the
host, and I verified their full contents by reading them back host-side. Because
of that lag, I validated the two edited modules' end-to-end behaviour by running
their exact logic against the real files/frames in a scratch copy (e.g.
`identify_status_icon` → `('burn', 1.0)` / `('burn', 0.984)` / `None`, and the
format check → MATCH), rather than importing the just-edited files in the lagged
mount. Worth a 10-second sanity `import` on your end when you're back, but the
logic and data are confirmed.
