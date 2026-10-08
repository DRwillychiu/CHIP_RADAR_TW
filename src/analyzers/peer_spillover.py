"""v3.84.0 R3 peer spillover (owner 2026-10-08: "when a stock is bought big, are its
peers in the same group, or its runner-up, bought too?").

Event   branch X big-buys stock S on day t (branch_relations.big_buys: X's own top
        10% net buys, >= NT$10m).
Peers   the other stocks of S's sub-industry (groups of >= 3 stocks). Runner-up:
        when S is its group's #1 by market value, the #2.
Window  days t .. t+H (H = 3 trading days).
Measure share of events where (a) X itself, (b) any OTHER tracked branch net-buys a
        peer / the runner-up inside the window, against a baseline: the same
        branch(es) and the same group over every possible window start
        (lift = observed rate / baseline rate). Only visible rows (daily top-50
        lists) exist, so both rates are lower bounds.
"""
from collections import defaultdict

HORIZON = 3
MIN_GROUP = 3


def _window(dates, i, h):
    return dates[i:i + h + 1]


def spillover(cells, dates, groups, rank, events, horizon=HORIZON):
    """cells {(date, code): {bno: net}}, groups {code: group}, rank {code: rank in group (1 = top)},
    events [(bno, date, code)] -> summary dict."""
    members = defaultdict(set)
    for c, g in groups.items():
        members[g].add(c)
    members = {g: m for g, m in members.items() if len(m) >= MIN_GROUP}
    top = {}
    for c, g in groups.items():
        if g in members:
            top.setdefault(g, {})[rank.get(c, 99)] = c
    pos = {d: i for i, d in enumerate(dates)}
    buyers = defaultdict(set)                       # (date, group) -> {(bno, code)}
    for (d, c), row in cells.items():
        g = groups.get(c)
        if g in members:
            for b, amt in row.items():
                if amt > 0:
                    buyers[(d, g)].add((b, c))

    def hit(i, g, exclude_code, who, only_code=None):
        for d in _window(dates, i, horizon):
            for b, c in buyers.get((d, g), ()):
                if c == exclude_code or (only_code and c != only_code):
                    continue
                if who(b):
                    return True
        return False

    starts = range(len(dates) - horizon)
    base_cache = {}

    def base(g, who_key, who, exclude_code, only_code=None):
        # same group, same buyer set, the event stock itself excluded (as in the observation)
        k = (g, who_key, exclude_code, only_code)
        if k not in base_cache:
            base_cache[k] = sum(hit(i, g, exclude_code, who, only_code) for i in starts) / max(1, len(starts))
        return base_cache[k]

    stats = defaultdict(lambda: {"n": 0, "obs": 0, "base": 0.0})
    per_group = defaultdict(lambda: {"n": 0, "obs": 0, "base": 0.0})     # (kind, group)
    per_branch = defaultdict(lambda: {"n": 0, "obs": 0, "base": 0.0})
    examples = []
    for x, d, c in events:
        g = groups.get(c)
        i = pos.get(d)
        if g not in members or i is None or i + horizon >= len(dates):
            continue
        same = (lambda b, x=x: b == x)
        other = (lambda b, x=x: b != x)
        for key, who in (("same_branch_peer", same), ("other_branch_peer", other)):
            o = hit(i, g, c, who)
            bv = base(g, (key, x), who, c)
            for s in (stats[key], per_group[(key, g)]):
                s["n"] += 1
                s["obs"] += o
                s["base"] += bv
            if key == "same_branch_peer":
                pb = per_branch[x]
                pb["n"] += 1
                pb["obs"] += o
                pb["base"] += base(g, (key, x), who, c)
        if rank.get(c) == 1 and 2 in top.get(g, {}):
            r2 = top[g][2]
            for key, who in (("same_branch_runner_up", same), ("other_branch_runner_up", other)):
                o = hit(i, g, c, who, only_code=r2)
                bv = base(g, (key, x), who, c, only_code=r2)
                for s in (stats[key], per_group[(key, g)]):
                    s["n"] += 1
                    s["obs"] += o
                    s["base"] += bv
                if o and len(examples) < 80:
                    examples.append({"x": x, "date": d, "leader": c, "runner_up": r2, "group": g, "kind": key})
    out = {}
    for k, s in stats.items():
        rate, b = (s["obs"] / s["n"]) if s["n"] else None, (s["base"] / s["n"]) if s["n"] else None
        out[k] = {"events": s["n"], "rate": rate, "baseline": b, "lift": (rate / b) if rate is not None and b else None}
    branches = {}
    for x, s in per_branch.items():
        if s["n"] >= 10:
            rate, b = s["obs"] / s["n"], s["base"] / s["n"]
            branches[x] = {"events": s["n"], "rate": rate, "baseline": b, "lift": rate / b if b else None}
    groups_out = []
    for (kind, g), s in per_group.items():
        if s["n"] >= 3:
            rate, b = s["obs"] / s["n"], s["base"] / s["n"]
            groups_out.append({"kind": kind, "group": g, "events": s["n"], "rate": rate, "baseline": b,
                               "lift": rate / b if b else None})
    groups_out.sort(key=lambda e: -(e["lift"] or 0))
    return {"overall": out, "per_branch_same_peer": branches, "per_group": groups_out,
            "runner_up_examples": examples,
            "groups_used": len(members), "horizon": horizon}
