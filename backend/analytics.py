"""
Turns events.json into the structured JSON that /record and /report return.

This deliberately imports the same functions coach_report.py and
player_report.py use to build their .md files (per_match, group_by_match,
winrate_table, pct, record_from_previews, ...) instead of re-deriving win
rates / KO diffs / flags from scratch. That keeps ONE source of truth for
"how do we count a win" etc. - the .md reports and the JSON API can never
silently disagree. Only the *shaping* into JSON is new code.
"""

import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import coach_report as _cr        # noqa: E402  (renamed from 6_coach_report.py)
import decision_windows as _dw    # noqa: E402
import player_report as _pr       # noqa: E402  (renamed from 5_player_report.py)
import skill_scores as _ss        # noqa: E402
import strategic_analysis as _sa  # noqa: E402
from . import type_synergy         # noqa: E402


def _table_to_json(tbl: dict) -> dict:
    return {k: {"wins": w, "total": t, "win_pct": round(_cr.pct(w, t), 1)} for k, (w, t) in tbl.items()}


def compute_record(events: list) -> dict:
    groups = _cr.group_by_match(events)
    sums = [_cr.per_match(g) for g in groups.values()]
    sums = [s for s in sums if s["winner"] != "unknown" or s["player_brought"]]
    decided = [s for s in sums if s["winner"] in ("player", "opponent")]
    undetermined = len(sums) - len(decided)

    wins = sum(1 for s in decided if s["winner"] == "player")
    losses = sum(1 for s in decided if s["winner"] == "opponent")
    n = wins + losses

    lead_pairs = [(" + ".join(s["player_lead"]) or "(unknown)", s["winner"] == "player")
                  for s in decided if s["player_lead"]]
    bring_pairs = [(mon, s["winner"] == "player")
                   for s in decided for mon in set(s["player_brought"])]

    return {
        "matches": n,
        "total_games": len(sums),
        "undetermined": undetermined,
        "wins": wins,
        "losses": losses,
        "win_rate": round(_cr.pct(wins, n), 1),
        "by_lead": _table_to_json(_cr.winrate_table(lead_pairs)),
        "by_bring": _table_to_json(_cr.winrate_table(bring_pairs)),
    }


def compute_match_list(events: list) -> list:
    """One row per match: result, lead, brought, opponent brought - the stuff
    that actually tells you something at a glance, unlike raw start/end
    timestamps. Callers merge in duration from matches.csv (see main.py)."""
    groups = _cr.group_by_match(events)
    rows = []
    for m in sorted(groups.keys()):
        evs = groups[m]
        s = _cr.per_match(evs)
        # Doubles brings 4 of 6 per side. Our OWN team preview is our own UI - reading
        # fewer than 4 there should never happen and is a real extraction bug worth
        # fixing/re-running. The OPPONENT's reveal is a harder read (their screen, their
        # network conditions) and it's normal to sometimes only catch 2-3 of their 4 -
        # that's not flagged as "incomplete" the same way. See ARCHITECTURE_HANDOFF.md /
        # this chat for the analyze_matches.py fixes aimed at the player-side gap.
        player_team_known = len(s["player_brought"]) >= 4
        opponent_team_known = len(s["opponent_brought"]) >= 4

        # illegal_species_detected is written directly onto the team_preview event by
        # analyze_matches.py (species that can't legally exist in this format - see
        # BANNED_SPECIES there - almost always a misread, not a real occurrence).
        # per_match() doesn't carry this field through, so pull it straight off the
        # event; older events.json files predating this check just won't have it.
        tp = next((e for e in evs if e.get("event") == "team_preview"), {})
        illegal_species = tp.get("illegal_species_detected") or []

        rows.append({
            "match": m,
            "winner": s["winner"],
            "player_lead": list(s["player_lead"]),
            "player_brought": s["player_brought"],
            "opponent_brought": s["opponent_brought"],
            # Full 6-mon team preview for both sides (added 2026-07-09) - see
            # coach_report.per_match's own comment for where these come from.
            "player_team": s["player_team"],
            "opponent_team": s["opponent_team"],
            "p_faints": s["p_faints"],
            "o_faints": s["o_faints"],
            "player_team_known": player_team_known,
            "opponent_team_known": opponent_team_known,
            "illegal_species_detected": illegal_species,
            "complete_data": player_team_known and not illegal_species,
        })
    return rows


def compute_opponent_strength(events: list, min_resolved: int = 2) -> dict:
    """"How good was their team-preview pick?" - scores each opponent's brought 4 on
    type-overlap risk (type_synergy.py), then checks whether that score actually
    correlates with match outcomes in THIS player's own results. min_resolved is the
    minimum number of the 4 Pokemon we need a type-chart entry for before trusting a
    match's score at all (partial-coverage scores are still returned, just marked)."""
    groups = _cr.group_by_match(events)
    per_match = []
    for m in sorted(groups.keys()):
        s = _cr.per_match(groups[m])
        if s["winner"] not in ("player", "opponent") or not s["opponent_brought"]:
            continue
        risk = type_synergy.team_risk(s["opponent_brought"])
        # Full rosters + brought-vs-brought type matchup (added 2026-07-09,
        # direct user request: "we need to know all of the pokemon available
        # to the opponent, and all pokemon we had available, what pokemon we
        # both brought and how it was advantageous or disadvantageous to
        # us"). Keyed as "team_preview_evaluation" (not just "matchup") on
        # purpose - this is the OBJECTIVE TEAM PREVIEW EVALUATION layer the
        # user explicitly split out from OUTCOME EVALUATION (see
        # type_synergy.team_matchup's docstring): compares what actually got
        # brought using only typing, with zero knowledge of `winner` - never
        # let this branch read s["winner"] before computing it, or it stops
        # being a "before the result" evaluation.
        team_preview_evaluation = type_synergy.team_matchup(s["player_brought"], s["opponent_brought"])
        per_match.append({
            "match": m,
            "player_brought": s["player_brought"],
            "opponent_brought": s["opponent_brought"],
            "player_team": s["player_team"],
            "opponent_team": s["opponent_team"],
            "team_preview_evaluation": team_preview_evaluation,
            "winner": s["winner"],
            "player_won": s["winner"] == "player",
            **risk,
        })

    scored = [r for r in per_match if len(r["resolved"]) >= min_resolved]
    correlation = None
    if len(scored) >= 4:   # need a handful of points before a split says anything at all
        scores = sorted(r["risk_score"] for r in scored)
        mid = len(scores) // 2
        median = scores[mid] if len(scores) % 2 else (scores[mid - 1] + scores[mid]) / 2
        weaker_built = [r for r in scored if r["risk_score"] > median]   # opponent's team, more overlap
        tighter_built = [r for r in scored if r["risk_score"] <= median]
        correlation = {
            "median_risk_score": median,
            "sample_size": len(scored),
            "win_rate_vs_weaker_built_teams": round(
                _cr.pct(sum(1 for r in weaker_built if r["player_won"]), len(weaker_built)), 1)
                if weaker_built else None,
            "vs_weaker_built_n": len(weaker_built),
            "win_rate_vs_tighter_built_teams": round(
                _cr.pct(sum(1 for r in tighter_built if r["player_won"]), len(tighter_built)), 1)
                if tighter_built else None,
            "vs_tighter_built_n": len(tighter_built),
            "note": ("Small sample - treat as a lead worth tracking as more matches are added, "
                     "not a proven effect." if len(scored) < 15 else
                     "Enough matches to take this split more seriously."),
        }

    return {"matches": per_match, "correlation": correlation}


def compute_report(events: list, min_sample: int = 3, rules: dict = None) -> dict:
    """Everything coach_report.md / player_report.md contain, as JSON.

    `rules` is schema.json's "rules" block for this job's format (see
    compose_schema.py) - passed in so mechanics the format doesn't even have
    (e.g. Terastallization isn't legal in Pokemon Champions) don't show up as
    a misleading stat. See the "tera" field below: it's None, not 0%/fake
    data, when the format doesn't support it."""
    tera_legal = True if rules is None else bool(rules.get("terastallization", True))
    groups = _cr.group_by_match(events)
    sums = [_cr.per_match(g) for g in groups.values()]
    sums = [s for s in sums if s["winner"] != "unknown" or s["player_brought"]]
    decided = [s for s in sums if s["winner"] in ("player", "opponent")]
    wins = sum(1 for s in decided if s["winner"] == "player")
    losses = sum(1 for s in decided if s["winner"] == "opponent")
    n = wins + losses

    bring_pairs = [(mon, s["winner"] == "player") for s in decided for mon in set(s["player_brought"])]
    bring_tbl = _cr.winrate_table(bring_pairs)
    bogey_pairs = [(mon, s["winner"] == "player") for s in decided for mon in set(s["opponent_brought"])]
    bogey_tbl = _cr.winrate_table(bogey_pairs)

    tera_matches = [s for s in decided if s["tera"]] if tera_legal else []
    notera = [s for s in decided if not s["tera"]] if tera_legal else []
    tera_win = _cr.pct(sum(1 for s in tera_matches if s["winner"] == "player"), len(tera_matches))
    notera_win = _cr.pct(sum(1 for s in notera if s["winner"] == "player"), len(notera))
    tera_mon = Counter(m for s in decided for m in s["tera"]) if tera_legal else Counter()

    ko_diff = sum(s["o_faints"] - s["p_faints"] for s in decided) / len(decided) if decided else 0
    avg_margin = (sum(s["margin"] for s in decided if s["winner"] == "player") / wins) if wins else 0
    fb = [s for s in decided if s["first_ko"] == "player"]
    fb_win = _cr.pct(sum(1 for s in fb if s["winner"] == "player"), len(fb))

    lead_counts = Counter(" + ".join(s["player_lead"]) for s in decided if s["player_lead"])
    top_lead, top_lead_n = (lead_counts.most_common(1)[0] if lead_counts else ("(n/a)", 0))
    lead_predictability = _cr.pct(top_lead_n, sum(lead_counts.values()))

    throws = 0
    for s in decided:
        if s["winner"] != "opponent":
            continue
        p = o = 0
        ahead = False
        for who in s["ko_seq"]:
            p += (who == "player")
            o += (who == "opponent")
            ahead = ahead or p > o
        throws += int(ahead)

    flags = []
    if n >= min_sample and lead_predictability >= 50:
        flags.append(f"Predictable leads - {lead_predictability:.0f}% of games open with {top_lead}.")
    if tera_legal and len(tera_matches) >= min_sample and len(notera) >= min_sample and tera_win < notera_win - 10:
        flags.append(f"Tera not helping - {tera_win:.0f}% win with Tera vs {notera_win:.0f}% without.")
    for m, (w, t) in bring_tbl.items():
        if t >= min_sample and _cr.pct(w, t) < 40:
            flags.append(f"Low-value bring: {m} - {_cr.pct(w,t):.0f}% win across {t} brings.")
    for m, (w, t) in bring_tbl.items():
        if 2 <= t < max(2, n * 0.3) and _cr.pct(w, t) >= 65:
            flags.append(f"Underused asset: {m} - {_cr.pct(w,t):.0f}% win but only brought {t}x.")
    if throws:
        flags.append(f"{throws} likely thrown game(s) - lost after being ahead in KOs.")
    if not flags:
        flags.append("No strong patterns yet - need more matches for confident coaching signals.")

    # usage stats (mirrors player_report.py's Counters)
    moves, mons_by_move, field_mons = Counter(), Counter(), Counter()
    tera_player = 0
    for e in events:
        a = str(e.get("actor", "")).strip().lower()
        if _pr.is_(e, "move_used") and a == "player":
            if e.get("detail"):
                moves[str(e["detail"]).strip()] += 1
            if e.get("pokemon"):
                mons_by_move[str(e["pokemon"]).strip()] += 1
        if _pr.is_(e, "terastallized") and a == "player":
            tera_player += 1
    player_faints = sum(1 for e in events if _pr.is_(e, "pokemon_fainted") and _pr.actor_of(e) == "player")
    opp_faints = sum(1 for e in events if _pr.is_(e, "pokemon_fainted") and _pr.actor_of(e) == "opponent")

    return {
        "record": {"matches": n, "wins": wins, "losses": losses, "win_rate": round(_cr.pct(wins, n), 1)},
        "combat": {
            "kos_landed": opp_faints, "pokemon_lost": player_faints,
            "ko_differential_avg": round(ko_diff, 2),
            "avg_winning_margin": round(avg_margin, 1),
            "first_ko_win_rate": round(fb_win, 1),
        },
        "tera": ({
            "win_rate_with": round(tera_win, 1), "matches_with": len(tera_matches),
            "win_rate_without": round(notera_win, 1), "matches_without": len(notera),
            "most_tera_d": tera_mon.most_common(5),
            "player_terastallizations": tera_player,
        } if tera_legal else None),
        "leads": {"most_common": top_lead, "predictability_pct": round(lead_predictability, 1)},
        "toughest_matchups": [
            {"pokemon": m, "wins": w, "total": t, "win_pct": round(_cr.pct(w, t), 1)}
            for m, (w, t) in sorted(bogey_tbl.items(), key=lambda kv: _cr.pct(*kv[1]))
            if t >= min_sample
        ][:8],
        "most_used_pokemon": mons_by_move.most_common(8),
        "most_used_moves": moves.most_common(8),
        "flags": flags,
    }


def compute_skill_scores(events: list) -> dict:
    """The 4 progression scores (tempo/adaptability/execution/closing) + confidence
    tier, from skill_scores.py's compute_skill_scores() (see ARCHITECTURE_HANDOFF.md
    section 4 - this was written but never wired into the API/dashboard until now).
    Pure arithmetic over events.json, no AI call, so it's cheap to compute on every
    request rather than caching a skill_scores.json file."""
    result = _ss.compute_skill_scores(events)
    if result is None:
        return {"matches_analyzed": 0, "confidence": {"tier": "No data yet", "matches_to_next_tier": 25},
                "scores": None, "overall": None, "drivers": None,
                "note": "No decided matches yet - play/analyze at least one full match to see scores."}
    return result


def compute_decision_windows(events: list) -> list:
    """One entry per turn per match: what each side had available (board,
    alive roster, switch options, moves already revealed this match) and
    what it actually chose (move or switch) - see decision_windows.py's own
    module docstring for the full scope/limitations (most notably: returns
    [] for a match with no field_state/turn events, which is currently true
    of every Showdown-imported match). Pure arithmetic over events.json, no
    AI call - same "cheap enough to compute on every request" reasoning as
    compute_skill_scores above."""
    return _dw.build_decision_windows_for_job(events)


def compute_strategic_analysis(events: list) -> list:
    """One entry per match: a per-turn advantage-score/momentum timeline
    (with plain-language reasons), a resource-tracking summary (alive-
    Pokemon counts), and conservative mistake-candidate flags - see
    strategic_analysis.py's own module docstring for the load-bearing
    caveat that none of this is a calibrated model, only a bounded
    heuristic. Built directly on decision_windows.py, so it inherits the
    same "[] for a match with no field_state/turn events" limitation
    (currently every Showdown-imported match before the 2026-07-04 turn-
    tracking fix - see ARCHITECTURE_HANDOFF.md section 8c). Pure
    arithmetic over events.json, no AI call - same "cheap enough to
    compute on every request" reasoning as compute_decision_windows."""
    return _sa.analyze_job(events)


def compute_job_battle_profile(events: list) -> dict | None:
    """Job-wide rollup of compute_strategic_analysis's per-match/per-turn six
    reports (added 2026-07-09, tasks #234-237) into a single "overall skill
    set" profile: Position Score trend/band distribution, Speed Control/
    Threat Pressure favorability, screen uptime, momentum event tallies, Risk
    Management posture distribution, recurring mistake/win-condition
    patterns, and loss patterns - see strategic_analysis.compute_job_
    battle_profile's own docstring for exactly what is (and, to avoid
    double-counting, is NOT) rolled up from each report, and how this
    differs from compute_skill_scores' separate, coarser tempo/adaptability/
    execution/closing heuristic above. Returns None if the job has no
    successfully-analyzed match with any turns recorded (e.g. an all-
    Showdown-pre-2026-07-04 job, or a job whose every match errored) -
    same "nothing to report yet, not a zero" discipline as compute_
    skill_scores' own None case. Pure arithmetic over events.json (via
    analyze_job), no AI call."""
    return _sa.compute_job_battle_profile(_sa.analyze_job(events))
