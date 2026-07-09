"""
SKILL SCORES - the 4 progression scores that power the "leveling up" experience.

No AI. Reads events.json and computes four 0-100 scores plus a confidence tier based on
how many matches back them. Writes skill_scores.json (for the app/dashboard to render).

The four scores:
  - TEMPO         : do you take and keep the initiative? (KO differential + first-KO rate)
  - ADAPTABILITY  : do you vary your approach vs different opponents? (lead/bring variety)
  - EXECUTION     : do you trade cleanly and not misplay? (KO efficiency + few throws)
  - CLOSING       : do you finish won positions? (conversion when ahead + winning margin)

Confidence tier (by matches analyzed): <25 provisional, 25 good, 50 strong, 100 exceptional.

NOTE: the 0-100 scalings are HEURISTIC anchors for now. Once you have population data
across many users (the flywheel), recalibrate them to real percentiles. Keep the inputs
(the raw metrics) stable so historical scores stay comparable.

Run after analysis:
  py skill_scores.py
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict


def load_events(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    sys.exit(f"No {path}. Run analyze_matches.py first.")


def ev(e):
    return str(e.get("event", "")).strip()


def actor(e):
    return str(e.get("actor", "")).strip().lower()


def ts(e):
    try:
        return float(e.get("timestamp"))
    except (TypeError, ValueError):
        return 0.0


def split(s):
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def scale(x, lo, hi):
    """Map x in [lo, hi] to 0..100 (clamped)."""
    if hi == lo:
        return 50.0
    return clamp((x - lo) / (hi - lo) * 100.0)


def entropy_pct(counter):
    """Normalized Shannon entropy 0..100. 0 = always the same choice (predictable),
    100 = evenly varied across the options used."""
    total = sum(counter.values())
    k = len(counter)
    if total <= 1 or k <= 1:
        return 0.0
    h = -sum((c / total) * math.log(c / total) for c in counter.values())
    return clamp(h / math.log(k) * 100.0)


def by_match(events):
    g = defaultdict(list)
    for e in events:
        if e.get("match") is not None:
            g[e["match"]].append(e)
    return g


def per_match(evs):
    tp = next((e for e in evs if ev(e) == "team_preview"), {})
    be = next((e for e in evs if ev(e) == "battle_end"), {})
    winner = str(be.get("winner") or be.get("actor") or "").lower()
    if winner not in ("player", "opponent"):
        winner = "unknown"
    faints = sorted([e for e in evs if ev(e) == "pokemon_fainted"], key=ts)
    p_faints = sum(1 for e in faints if actor(e) == "player")
    o_faints = sum(1 for e in faints if actor(e) == "opponent")
    ko_seq = ["player" if actor(e) == "opponent" else "opponent" for e in faints]  # who SCORED it
    brought = split(tp.get("player_brought"))
    # was the player ever ahead in KOs?
    p = o = 0
    was_ahead = False
    for who in ko_seq:
        if who == "player":
            p += 1
        else:
            o += 1
        if p > o:
            was_ahead = True
    return {
        "winner": winner,
        "lead": " + ".join(sorted(split(tp.get("player_lead")))),
        "brought": frozenset(brought),
        "p_faints": p_faints,
        "o_faints": o_faints,
        "first_ko": ko_seq[0] if ko_seq else None,
        "was_ahead": was_ahead,
        "margin": max(0, len(brought or [0, 0, 0, 0]) - p_faints) if winner == "player" else 0,
        "brought_n": len(brought) or 4,
    }


def tier(n):
    if n >= 100:
        return "Exceptional", None
    if n >= 50:
        return "Strong", 100 - n
    if n >= 25:
        return "Good understanding", 50 - n
    return "Provisional (building)", 25 - n


def compute_skill_scores(events):
    """The importable core: events.json (already-loaded list) -> the skill_scores.json
    dict. Pulled out of main() so backend/analytics.py can call this directly instead
    of shelling out - same "one source of truth" pattern as battle_record.py /
    player_report.py / coach_report.py (see backend/analytics.py's docstring)."""
    sums = [per_match(g) for g in by_match(events).values()]
    decided = [s for s in sums if s["winner"] in ("player", "opponent")]
    n = len(decided)
    if n == 0:
        return None   # caller decides how to represent "no decided matches yet"

    # ---- raw metrics ----
    avg_ko_diff = sum(s["o_faints"] - s["p_faints"] for s in decided) / n
    first_blood_rate = sum(1 for s in decided if s["first_ko"] == "player") / n
    tot_o = sum(s["o_faints"] for s in decided)
    tot_p = sum(s["p_faints"] for s in decided)
    ko_efficiency = tot_o / (tot_o + tot_p) if (tot_o + tot_p) else 0.5
    losses = [s for s in decided if s["winner"] == "opponent"]
    throws = sum(1 for s in losses if s["was_ahead"])
    throw_rate = throws / len(losses) if losses else 0.0
    ahead = [s for s in decided if s["was_ahead"]]
    conversion = (sum(1 for s in ahead if s["winner"] == "player") / len(ahead)) if ahead else 0.0
    wins = [s for s in decided if s["winner"] == "player"]
    avg_margin_norm = (sum(s["margin"] / s["brought_n"] for s in wins) / len(wins)) if wins else 0.0
    lead_entropy = entropy_pct(Counter(s["lead"] for s in decided if s["lead"]))
    bring_entropy = entropy_pct(Counter(s["brought"] for s in decided if s["brought"]))

    # ---- 0-100 scores ----
    tempo = clamp(0.5 * scale(avg_ko_diff, -2, 2) + 0.5 * first_blood_rate * 100)
    adaptability = clamp(0.5 * lead_entropy + 0.5 * bring_entropy)
    execution = clamp(0.7 * ko_efficiency * 100 + 0.3 * (1 - throw_rate) * 100)
    closing = clamp(0.6 * conversion * 100 + 0.4 * avg_margin_norm * 100)
    overall = round((tempo + adaptability + execution + closing) / 4, 1)

    t_name, to_next = tier(n)

    return {
        "matches_analyzed": n,
        "confidence": {"tier": t_name, "matches_to_next_tier": to_next},
        "scores": {
            "tempo": round(tempo, 1),
            "adaptability": round(adaptability, 1),
            "execution": round(execution, 1),
            "closing": round(closing, 1),
        },
        "overall": overall,
        "drivers": {
            "tempo": f"avg KO diff {avg_ko_diff:+.2f}/match, first-KO {first_blood_rate*100:.0f}%",
            "adaptability": f"lead variety {lead_entropy:.0f}/100, bring variety {bring_entropy:.0f}/100",
            "execution": f"KO efficiency {ko_efficiency*100:.0f}%, throws {throws}/{len(losses)} losses",
            "closing": f"convert-when-ahead {conversion*100:.0f}%, avg margin {avg_margin_norm*100:.0f}%",
        },
        "note": "Heuristic 0-100 scores; recalibrate to population percentiles once enough users exist.",
    }


def main():
    ap = argparse.ArgumentParser(description="Compute the 4 skill scores from events.json")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--out", default="skill_scores.json")
    args = ap.parse_args()

    events = load_events(args.events)
    out = compute_skill_scores(events)
    if out is None:
        sys.exit("No decided matches found in events.json.")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    n, t_name, to_next = out["matches_analyzed"], out["confidence"]["tier"], out["confidence"]["matches_to_next_tier"]
    print("===============  SKILL SCORES  ===============")
    print(f"Matches: {n}   Confidence: {t_name}"
          + (f" ({to_next} more to next tier)" if to_next else ""))
    for k, v in out["scores"].items():
        print(f"  {k.capitalize():13} {v:5.1f}/100   — {out['drivers'][k]}")
    print(f"  {'Overall':13} {out['overall']:5.1f}/100")
    print("==============================================")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
