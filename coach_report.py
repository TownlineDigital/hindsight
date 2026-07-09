"""
STEP 6 - Coaching analytics from the event stream.

No AI calls. Reads events.json (match-tagged, from analyze_matches.py), rolls it up
into per-match metrics and a cross-match coaching profile: win rates by lead and bring,
KO differential, Tera usage, bogey Pokemon, style indices, and coaching flags
(predictable leads, low-win brings, "throws"). Writes coach_report.md.

Run after analyze_matches.py:
  py 6_coach_report.py
"""

import argparse
import json
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


def group_by_match(events):
    groups = defaultdict(list)
    if any("match" in e for e in events):
        for e in events:
            if e.get("match") is not None:
                groups[e["match"]].append(e)
        return groups
    # fallback: segment at each team_preview
    idx = 0
    for e in sorted(events, key=ts):
        if ev(e) == "team_preview":
            idx += 1
        groups[idx or 1].append(e)
    return groups


def per_match(evs):
    tp = next((e for e in evs if ev(e) == "team_preview"), {})
    be = next((e for e in evs if ev(e) == "battle_end"), {})
    winner = str(be.get("winner") or be.get("actor") or "unknown").lower()
    if winner not in ("player", "opponent"):
        winner = "unknown"
    faints = sorted([e for e in evs if ev(e) == "pokemon_fainted"], key=ts)
    p_faints = sum(1 for e in faints if actor(e) == "player")
    o_faints = sum(1 for e in faints if actor(e) == "opponent")
    # who SCORED each KO (your KO = opponent's Pokemon fainting)
    ko_seq = ["player" if actor(e) == "opponent" else "opponent" for e in faints]
    p_brought = split(tp.get("player_brought")) or split(tp.get("player_active"))
    return {
        "winner": winner,
        "player_lead": tuple(sorted(split(tp.get("player_lead")))),
        "player_brought": p_brought,
        "opponent_brought": split(tp.get("opponent_brought")) or split(tp.get("opponent_team")),
        "p_faints": p_faints,
        "o_faints": o_faints,
        "margin": max(0, len(p_brought or [0, 0, 0, 0]) - p_faints) if winner == "player" else 0,
        "tera": [e.get("pokemon") for e in evs if ev(e) == "terastallized"
                 and actor(e) == "player" and e.get("pokemon")],
        "first_ko": ko_seq[0] if ko_seq else None,
        "ko_seq": ko_seq,
    }


def pct(w, n):
    return (w / n * 100) if n else 0.0


def winrate_table(pairs):
    """pairs: list of (key, won_bool). returns {key: (wins, total)} sorted by total."""
    agg = defaultdict(lambda: [0, 0])
    for key, won in pairs:
        agg[key][1] += 1
        if won:
            agg[key][0] += 1
    return dict(sorted(agg.items(), key=lambda kv: -kv[1][1]))


def main():
    ap = argparse.ArgumentParser(description="Coaching analytics from events.json")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--out", default="coach_report.md")
    ap.add_argument("--min-sample", type=int, default=3, help="min matches before flagging a pattern")
    args = ap.parse_args()

    events = load_events(args.events)
    groups = group_by_match(events)
    sums = [per_match(g) for g in groups.values()]
    sums = [s for s in sums if s["winner"] != "unknown" or s["player_brought"]]  # keep real matches
    decided = [s for s in sums if s["winner"] in ("player", "opponent")]

    wins = sum(1 for s in decided if s["winner"] == "player")
    losses = sum(1 for s in decided if s["winner"] == "opponent")
    n = wins + losses

    # leads
    lead_tbl = winrate_table([(" + ".join(s["player_lead"]) or "(unknown)", s["winner"] == "player")
                              for s in decided if s["player_lead"]])
    # brings (per Pokemon brought)
    bring_pairs = []
    for s in decided:
        for mon in set(s["player_brought"]):
            bring_pairs.append((mon, s["winner"] == "player"))
    bring_tbl = winrate_table(bring_pairs)
    # tera
    tera_matches = [s for s in decided if s["tera"]]
    tera_win = pct(sum(1 for s in tera_matches if s["winner"] == "player"), len(tera_matches))
    notera = [s for s in decided if not s["tera"]]
    notera_win = pct(sum(1 for s in notera if s["winner"] == "player"), len(notera))
    tera_mon = Counter(m for s in decided for m in s["tera"])
    # KO diff / margin / first blood
    ko_diff = sum(s["o_faints"] - s["p_faints"] for s in decided) / len(decided) if decided else 0
    avg_margin = (sum(s["margin"] for s in decided if s["winner"] == "player") / wins) if wins else 0
    fb = [s for s in decided if s["first_ko"] == "player"]
    fb_win = pct(sum(1 for s in fb if s["winner"] == "player"), len(fb))
    # bogeys: opponent Pokemon you face, with YOUR win rate against them
    bogey_pairs = []
    for s in decided:
        for mon in set(s["opponent_brought"]):
            bogey_pairs.append((mon, s["winner"] == "player"))
    bogey_tbl = winrate_table(bogey_pairs)
    # predictability
    lead_counts = Counter(" + ".join(s["player_lead"]) for s in decided if s["player_lead"])
    top_lead, top_lead_n = (lead_counts.most_common(1)[0] if lead_counts else ("(n/a)", 0))
    lead_predictability = pct(top_lead_n, sum(lead_counts.values()))
    # throws: lost matches where you were ever ahead in KOs
    throws = 0
    for s in decided:
        if s["winner"] != "opponent":
            continue
        p = o = 0
        ahead = False
        for who in s["ko_seq"]:
            if who == "player":
                p += 1
            else:
                o += 1
            if p > o:
                ahead = True
        if ahead:
            throws += 1

    # ---------------- build report ----------------
    L = []
    L.append("# Coaching Report\n")
    L.append("## Record & performance")
    L.append(f"- Matches: **{n}**  |  Record: **{wins}-{losses}**  ({pct(wins,n):.0f}% win rate)")
    L.append(f"- Avg KO differential: **{ko_diff:+.2f}** per match")
    L.append(f"- Avg winning margin: **{avg_margin:.1f}** Pokémon left when you win")
    L.append(f"- Win rate when you get first KO: **{fb_win:.0f}%** ({len(fb)} matches)")
    L.append("")
    L.append("## Leads (your opening pair)")
    for key, (w, t) in list(lead_tbl.items())[:8]:
        L.append(f"- {key}: {w}-{t-w}  ({pct(w,t):.0f}%)")
    L.append(f"\n*Lead predictability:* your most common lead is **{top_lead}** "
             f"({lead_predictability:.0f}% of games).")
    L.append("")
    L.append("## Brings (win rate when this Pokémon is brought)")
    for mon, (w, t) in list(bring_tbl.items())[:12]:
        L.append(f"- {mon}: brought {t}×, {pct(w,t):.0f}% win")
    L.append("")
    L.append("## Terastallization")
    L.append(f"- Win rate WITH Tera: **{tera_win:.0f}%** ({len(tera_matches)} matches)  |  "
             f"WITHOUT: **{notera_win:.0f}%** ({len(notera)} matches)")
    if tera_mon:
        L.append("- Most Tera'd: " + ", ".join(f"{m} ({c})" for m, c in tera_mon.most_common(5)))
    L.append("")
    L.append("## Toughest matchups (your win rate vs opponent Pokémon faced)")
    hardest = sorted([(m, w, t) for m, (w, t) in bogey_tbl.items() if t >= args.min_sample],
                     key=lambda x: pct(x[1], x[2]))[:8]
    for mon, w, t in hardest:
        L.append(f"- vs {mon}: {pct(w,t):.0f}% win ({w}-{t-w})")
    L.append("")
    L.append("## Coaching flags")
    flags = []
    if n >= args.min_sample and lead_predictability >= 50:
        flags.append(f"**Predictable leads** — {lead_predictability:.0f}% of games open with {top_lead}; "
                     "an opponent can prep for it. Vary your lead.")
    if len(tera_matches) >= args.min_sample and len(notera) >= args.min_sample and tera_win < notera_win - 10:
        flags.append(f"**Tera not helping** — you win {tera_win:.0f}% with Tera vs {notera_win:.0f}% without; "
                     "reconsider when/what you Terastallize.")
    bad_brings = [(m, w, t) for m, (w, t) in bring_tbl.items() if t >= args.min_sample and pct(w, t) < 40]
    for m, w, t in bad_brings[:5]:
        flags.append(f"**Low-value bring: {m}** — only {pct(w,t):.0f}% win across {t} brings.")
    underused = [(m, w, t) for m, (w, t) in bring_tbl.items()
                 if t < max(2, n * 0.3) and t >= 2 and pct(w, t) >= 65]
    for m, w, t in underused[:5]:
        flags.append(f"**Underused asset: {m}** — {pct(w,t):.0f}% win but only brought {t}×; bring it more.")
    if throws:
        flags.append(f"**{throws} likely thrown game(s)** — lost after being ahead in KOs. "
                     "Closing out won positions is your biggest win-rate lever.")
    if not flags:
        flags.append("No strong patterns yet — need more matches for confident coaching signals.")
    for fl in flags:
        L.append(f"- {fl}")
    L.append("")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    # console summary
    print("===============  COACHING REPORT  ===============")
    print(f"Record: {wins}-{losses} ({pct(wins,n):.0f}%) over {n} matches")
    print(f"KO diff/match: {ko_diff:+.2f} | first-KO win rate: {fb_win:.0f}% | throws: {throws}")
    print(f"Most common lead: {top_lead} ({lead_predictability:.0f}% of games)")
    print(f"Tera win {tera_win:.0f}% vs no-Tera {notera_win:.0f}%")
    print(f"\nFlags ({len(flags)}):")
    for fl in flags:
        print("  - " + fl.replace("**", ""))
    print("=================================================")
    print(f"\nFull report -> {args.out}")


if __name__ == "__main__":
    main()
