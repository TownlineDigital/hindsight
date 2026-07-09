"""
COACH CHAT - ask the AI about your games.

A conversational coach grounded in YOUR data: it reads events.json (match-tagged),
optionally transcript.json, builds a compact profile, and answers questions - pulling
in a specific match's full event log (and commentary) when you reference it.

  py coach_chat.py                       (interactive)
  py coach_chat.py --ask "what's my best lead and why?"
  py coach_chat.py --ask "what did I do wrong in game 12?"

Needs GEMINI_API_KEY. Text-only calls, so it's cheap.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("Run: pip install google-genai")

SYSTEM = (
    "You are an elite Pokemon VGC doubles coach analyzing THIS player's own match data. "
    "Use ONLY the data provided (format rules, meta, aggregate profile, match event logs, transcript). "
    "STRICTLY OBEY THE FORMAT RULES: never recommend a mechanic listed as ILLEGAL for this format "
    "(for example, do NOT suggest Terastallization if the rules say it isn't legal). "
    "Reference specific match numbers and turns/timestamps. If the data doesn't contain something, "
    "say so plainly rather than inventing it. Be concrete, honest, and actionable - point to the "
    "decision (lead, bring, switch, target, positioning) and what would have been better. "
    "If a SESSION-BY-SESSION PROGRESSION block is provided, that's this player's full upload history "
    "broken into separate practice sessions in chronological order - use it to answer questions about "
    "improvement, trends, or 'how have I changed' by comparing early sessions to recent ones, not just "
    "quoting one all-time average.")


def load_json(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def ev(e):
    return str(e.get("event", "")).strip()


def split(s):
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def by_match(events):
    g = defaultdict(list)
    for e in events:
        if e.get("match") is not None:
            g[e["match"]].append(e)
    return g


def load_meta_context(schema_path="schema.json", meta_dir="meta"):
    """Load the format rules + meta knowledge base as a grounding block for the coach."""
    rules = {}
    if os.path.exists(schema_path):
        try:
            rules = json.load(open(schema_path, encoding="utf-8")).get("rules", {})
        except Exception:
            pass
    fmt = re.sub(r"[^a-z0-9]+", "_", (rules.get("format_name") or "format").lower()).strip("_")
    meta = {}
    mp = os.path.join(meta_dir, fmt + ".json")
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp, encoding="utf-8"))
        except Exception:
            pass
    rules = meta.get("rules") or rules

    lines = []
    if rules:
        lines.append(f"FORMAT: {rules.get('format_name','?')} — "
                     f"{rules.get('active_per_side','?')} active/side, bring {rules.get('bring_count','?')} "
                     f"of {rules.get('team_size','?')}.")
        illegal = [k.replace('_no', '').replace('_', ' ').strip()
                   for k in rules.get('legal_mechanics', []) if str(k).endswith('_no')]
        if illegal:
            lines.append(f"ILLEGAL in this format (NEVER recommend): {', '.join(illegal)}.")
        if rules.get('format_notes'):
            lines.append("Rules: " + rules['format_notes'])
    om = meta.get("own_meta", {})
    if om.get("opponent_threats"):
        worst = sorted(om['opponent_threats'].items(), key=lambda kv: kv[1].get('win_pct', 0))[:6]
        lines.append("Your worst matchups (your win% vs opponent Pokemon): "
                     + ", ".join(f"{k} {v['win_pct']}%" for k, v in worst))
    if meta.get("pokedex"):
        lines.append(f"(Type/ability data available for {len(meta['pokedex'])} Pokemon; use it for type matchups.)")
    # THE WIDER FIELD (task #130) - real official Smogon usage stats for this
    # exact game+regulation (see meta_build.py's fetch_external_meta() for the
    # full "why this source" writeup). This is what own_meta above structurally
    # CANNOT provide: what everyone else is actually playing this month, so the
    # coach can warn about a likely-to-be-faced Pokemon even if this specific
    # player has never once seen it in their own uploaded matches.
    xm = meta.get("external_meta")
    if xm and xm.get("pokemon_usage_pct"):
        top = sorted(xm["pokemon_usage_pct"].items(), key=lambda kv: -kv[1])[:10]
        lines.append(
            f"FIELD-WIDE META (Smogon official stats, {xm.get('tier','?')}, {xm.get('month','?')}, "
            f"{xm.get('total_battles','?')} real battles - this is what OTHER players are using this "
            f"month, not just this player's own matches): "
            + ", ".join(f"{k} {v}%" for k, v in top)
        )
    return ("META & RULES:\n" + "\n".join(lines)) if lines else ""


def profile_summary(events):
    """Compact aggregate context (small token footprint)."""
    g = by_match(events)
    rec_w = rec_l = 0
    leads = Counter()
    lead_wins = Counter()
    bring = Counter()
    bring_w = Counter()
    tera_w = tera_n = notera_w = notera_n = 0
    for m, evs in g.items():
        tp = next((e for e in evs if ev(e) == "team_preview"), {})
        be = next((e for e in evs if ev(e) == "battle_end"), {})
        winner = str(be.get("winner") or be.get("actor") or "").lower()
        won = winner == "player"
        if winner in ("player", "opponent"):
            rec_w += won
            rec_l += (winner == "opponent")
        lead = " + ".join(sorted(split(tp.get("player_lead"))))
        if lead:
            leads[lead] += 1
            lead_wins[lead] += won
        for mon in set(split(tp.get("player_brought"))):
            bring[mon] += 1
            bring_w[mon] += won
        tera = any(ev(e) == "terastallized" and str(e.get("actor", "")).lower() == "player" for e in evs)
        if winner in ("player", "opponent"):
            if tera:
                tera_n += 1
                tera_w += won
            else:
                notera_n += 1
                notera_w += won
    n = rec_w + rec_l
    lines = [f"RECORD: {rec_w}-{rec_l} ({(rec_w/n*100 if n else 0):.0f}%) over {n} matches."]
    lines.append("LEADS (win rate): " + "; ".join(
        f"{k} {lead_wins[k]}/{v}" for k, v in leads.most_common(6)) or "n/a")
    lines.append("BRINGS (wins/brought): " + "; ".join(
        f"{k} {bring_w[k]}/{v}" for k, v in bring.most_common(10)))
    lines.append(f"TERA: with {tera_w}/{tera_n}, without {notera_w}/{notera_n}.")
    return "\n".join(lines)


def _format_session_date(value):
    """created_at may be a unix-epoch float (local dev mode) or an ISO-8601
    string (real Supabase timestamptz) - see backend/career.py's
    _created_at_key for the same normalization problem on the sorting side.
    Renders either as a plain YYYY-MM-DD for the coach's context, falling
    back to a placeholder rather than crashing on a genuinely missing/
    unparseable value."""
    if value is None:
        return "unknown date"
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return "unknown date"


def session_progression_summary(events, sessions):
    """Session-by-session profile blocks, oldest to newest - the piece that
    actually lets the coach talk about IMPROVEMENT rather than only one
    blended all-time average. A flat merged event list alone can't answer
    "have I gotten better" - the model has no way to tell an early match from
    a recent one without an explicit boundary, which is exactly what this
    adds.

    Deliberately reuses profile_summary() per session slice (same "one
    source of truth for how we count a win" principle backend/analytics.py
    already applies by reusing coach_report.py's functions) rather than
    re-deriving win rates/leads/brings from scratch for each session.

    `events` is the already-merged, session-tagged list from
    backend/career.py's merge_user_events() (each event carries a "session"
    field); `sessions` is that same function's session metadata list
    ({"session", "job_id", "created_at", "matches_in_session", ...})."""
    blocks = []
    for s in sessions:
        idx = s.get("session")
        session_events = [e for e in events if e.get("session") == idx]
        if not session_events:
            continue
        date = _format_session_date(s.get("created_at"))
        n_matches = s.get("matches_in_session", "?")
        header = f"SESSION {idx} ({date}, {n_matches} match{'es' if n_matches != 1 else ''}, job {s.get('job_id', '?')}):"
        blocks.append(header + "\n" + profile_summary(session_events))
    if not blocks:
        return ""
    return "SESSION-BY-SESSION PROGRESSION (oldest to newest - use this to answer questions about " \
           "improvement/trends over time, not just an all-time average):\n\n" + "\n\n".join(blocks)


def match_block(events, transcript, m):
    evs = sorted([e for e in by_match(events).get(m, [])], key=lambda e: float(e.get("timestamp", 0) or 0))
    if not evs:
        return f"(no data for match {m})"
    out = [f"--- MATCH {m} EVENT LOG ---"]
    for e in evs:
        bits = [f"{float(e.get('timestamp',0) or 0):.0f}s", ev(e), str(e.get('actor', ''))]
        for k in ("pokemon", "detail", "player_active", "opponent_active", "player_brought",
                  "opponent_brought", "winner", "turn"):
            if e.get(k):
                bits.append(f"{k}={e[k]}")
        out.append("  " + " | ".join(b for b in bits if b))
    if transcript:
        segs = [t for t in transcript if t.get("match") == m]
        if segs:
            out.append(f"--- MATCH {m} COMMENTARY ---")
            for s in segs[:60]:
                out.append(f"  {s['start']:.0f}s: {s['text']}")
    return "\n".join(out)


def referenced_matches(text, available):
    nums = set(int(x) for x in re.findall(r"(?:match|game|g)\s*#?\s*(\d+)", text, re.I))
    return [m for m in nums if m in available]


def answer(client, model, history, profile, extra_context, question):
    ctx = f"PLAYER PROFILE:\n{profile}\n"
    if extra_context:
        ctx += "\n" + extra_context + "\n"
    convo = "\n".join(f"{role}: {msg}" for role, msg in history[-6:])
    prompt = f"{SYSTEM}\n\n{ctx}\n\nConversation so far:\n{convo}\n\nPlayer: {question}\nCoach:"
    r = client.models.generate_content(
        model=model, contents=[prompt],
        config=types.GenerateContentConfig(temperature=0.4))
    return (r.text or "").strip()


def main():
    ap = argparse.ArgumentParser(description="Conversational VGC coach over your match data.")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--transcript", default="transcript.json")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--schema", default="schema.json")
    ap.add_argument("--meta-dir", default="meta")
    ap.add_argument("--ask", default="", help="ask a single question and exit")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY first.")
    events = load_json(args.events)
    if not events:
        sys.exit(f"No {args.events}. Run analyze_matches.py first.")
    transcript = load_json(args.transcript)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    meta_ctx = load_meta_context(args.schema, args.meta_dir)
    profile = (meta_ctx + "\n\n" if meta_ctx else "") + profile_summary(events)
    available = set(by_match(events).keys())
    history = []

    def handle(q):
        refs = referenced_matches(q, available)
        extra = "\n".join(match_block(events, transcript, m) for m in refs[:2])
        a = answer(client, args.model, history, profile, extra, q)
        history.append(("Player", q))
        history.append(("Coach", a))
        return a

    if args.ask:
        print(handle(args.ask))
        return

    print("VGC Coach ready. Ask about your games (e.g. 'what's my best lead?', "
          "'what went wrong in game 12?'). Type 'quit' to exit.\n")
    print("Profile loaded:\n" + profile + "\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            break
        print("\ncoach> " + handle(q) + "\n")


if __name__ == "__main__":
    main()
