"""v3.83.0 R2 co-trading between branches (owner 2026-10-08: "when a branch buys
a stock big, do other branches trade it together?").

cells       {(date, code): {bno: net_amt}} - net buy amount (仟元, > 0 = net buy) of
            every visible branch row (daily top-50 lists).
big buy     (date, code) where branch X's net buy is in X's own top BIG_Q of its
            net-buy amounts (and >= MIN_BIG_K 仟元).
co-buy      branch Y net-buys the same stock on date + lag (lag 0 = same day,
            lag 1 = next trading day -> Y follows X).
lift        P(Y co-buys | X big-buys) / P(Y net-buys a random visible cell of that
            lag's dates). Base rate over all visible (date, code) cells.
p_value     exact binomial upper tail P(K >= co | n = X's big buys, p = base).
Only visible rows exist, so co-buys are undercounted: lifts are conservative.
"""
from collections import defaultdict
from math import exp, lgamma, log

BIG_Q = 0.9
MIN_BIG_K = 10_000          # NT$10m: a "big buy" is at least this
MIN_CO = 5


def _binom_sf(k, n, p):
    """P(K >= k) for K ~ Binomial(n, p), in log space."""
    if k <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lp, lq = log(p), log(1 - p)
    total = 0.0
    for i in range(k, n + 1):
        total += exp(lgamma(n + 1) - lgamma(i + 1) - lgamma(n - i + 1) + i * lp + (n - i) * lq)
    return min(1.0, total)


def big_buys(cells, big_q=BIG_Q, min_big_k=MIN_BIG_K):
    """-> {bno: [(date, code), ...]} each branch's own top-quantile net buys."""
    per = defaultdict(list)
    for (d, c), row in cells.items():
        for b, amt in row.items():
            if amt > 0:
                per[b].append((amt, d, c))
    out = {}
    for b, xs in per.items():
        xs.sort()
        cut = xs[min(len(xs) - 1, int(len(xs) * big_q))][0] if xs else 0
        out[b] = [(d, c) for amt, d, c in xs if amt >= max(cut, min_big_k)]
    return out


def co_trading(cells, dates, masters=None, lags=(0, 1), big_q=BIG_Q, min_big_k=MIN_BIG_K, min_co=MIN_CO):
    """-> [{x, y, lag, n_big, co, cond, base, lift, p_value, same_master}] sorted by lift."""
    masters = masters or {}
    pos = {d: i for i, d in enumerate(dates)}
    buys_by_cell = {k: {b for b, a in row.items() if a > 0} for k, row in cells.items()}
    n_cells = len(cells) or 1
    base = defaultdict(float)
    for k, bs in buys_by_cell.items():
        for b in bs:
            base[b] += 1 / n_cells
    bigs = big_buys(cells, big_q, min_big_k)
    out = []
    for x, xs in bigs.items():
        if not xs:
            continue
        for lag in lags:
            counts = defaultdict(int)
            n = 0
            for d, c in xs:
                i = pos.get(d)
                if i is None or i + lag >= len(dates):
                    continue
                n += 1
                for y in buys_by_cell.get((dates[i + lag], c), ()):
                    if y != x:
                        counts[y] += 1
            for y, co in counts.items():
                if co < min_co or base[y] <= 0 or n == 0:
                    continue
                cond = co / n
                out.append({"x": x, "y": y, "lag": lag, "n_big": n, "co": co, "cond": cond, "base": base[y],
                            "lift": cond / base[y], "p_value": _binom_sf(co, n, base[y]),
                            "same_master": bool(set(masters.get(x, ())) & set(masters.get(y, ())))})
    out.sort(key=lambda e: -e["lift"])
    return out


def clusters(edges, min_lift=3.0, max_p=1e-3, lag=0):
    """Connected groups of branches linked by strong same-day co-trading edges."""
    adj = defaultdict(set)
    for e in edges:
        if e["lag"] == lag and e["lift"] >= min_lift and e["p_value"] <= max_p and not e["same_master"]:
            adj[e["x"]].add(e["y"])
            adj[e["y"]].add(e["x"])
    seen, groups = set(), []
    for start in adj:
        if start in seen:
            continue
        stack, g = [start], set()
        while stack:
            v = stack.pop()
            if v in g:
                continue
            g.add(v)
            stack.extend(adj[v] - g)
        seen |= g
        groups.append(sorted(g))
    return sorted(groups, key=len, reverse=True)
