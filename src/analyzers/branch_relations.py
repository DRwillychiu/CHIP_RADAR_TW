"""v3.83.0 R2 co-trading between branches (owner 2026-10-08: "when a branch buys
a stock big, do other branches trade it together?").

cells       {(date, code): {bno: net_amt}} - net buy amount (仟元, > 0 = net buy) of
            every visible branch row (daily top-50 lists).
big buy     (date, code) where branch X's net buy is in X's own top BIG_Q of its
            net-buy amounts (and >= MIN_BIG_K 仟元).
co-buy      branch Y net-buys the same stock on date + lag (lag 0 = same day,
            lag 1 = next trading day -> Y follows X).
lift        observed co-buys / expected co-buys. v3.83.1: the expectation is
            crowdedness-adjusted - on a target cell with k other buyers, Y is
            expected there with probability min(1, k * w_Y), w_Y = Y's share of all
            buy incidences. Hot stocks that everyone buys therefore do not create
            links (the first real-DB run with a marginal base rate linked all 83
            branches into one cluster).
p_value     Poisson upper tail P(K >= co | mean = expected) (Poisson-binomial
            approximation).
Only visible rows exist, so co-buys are undercounted: lifts are conservative.
"""
from collections import defaultdict
from math import exp, lgamma, log

BIG_Q = 0.9
MIN_BIG_K = 10_000          # NT$10m: a "big buy" is at least this
MIN_CO = 5
MIN_OVERLAP_DAYS = 20     # v3.83.3: both branches visible on >= 20 common days
MAX_Q = 1e-3              # v3.83.3: Benjamini-Hochberg FDR threshold for a relation
MAX_EVENTS = 60            # co-buy events kept per notable edge (x date, y date, stock)


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


def _poisson_sf(k, lam):
    """P(K >= k) for K ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    term = exp(-lam)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, 1.0 - cdf)


def co_trading(cells, dates, masters=None, lags=(0, 1), big_q=BIG_Q, min_big_k=MIN_BIG_K, min_co=MIN_CO):
    """-> [{x, y, lag, n_big, co, expected, lift, p_value, same_master}] sorted by lift."""
    masters = masters or {}
    pos = {d: i for i, d in enumerate(dates)}
    buys_by_cell = {k: {b for b, a in row.items() if a > 0} for k, row in cells.items()}
    active = defaultdict(set)                # v3.83.3: days each branch is visible at all
    for (d, _), row in cells.items():
        for b in row:
            active[b].add(d)
    n_inc = defaultdict(int)
    for bs in buys_by_cell.values():
        for b in bs:
            n_inc[b] += 1
    total_inc = sum(n_inc.values())
    bigs = big_buys(cells, big_q, min_big_k)
    out = []
    for x, xs in bigs.items():
        if not xs:
            continue
        rest = total_inc - n_inc.get(x, 0)
        if rest <= 0:
            continue
        w = {y: n / rest for y, n in n_inc.items() if y != x}
        for lag in lags:
            counts, expected, n = defaultdict(int), defaultdict(float), 0
            events = defaultdict(list)       # v3.83.2: which (date, stock) the co-buys were
            for d, c in xs:
                i = pos.get(d)
                if i is None or i + lag >= len(dates):
                    continue
                n += 1
                buyers = buys_by_cell.get((dates[i + lag], c), set()) - {x}
                k = len(buyers)
                if k:
                    for y, wy in w.items():
                        expected[y] += min(1.0, k * wy)
                for y in buyers:
                    counts[y] += 1
                    if len(events[y]) < MAX_EVENTS:
                        events[y].append((d, dates[i + lag], c))
            for y, co in counts.items():
                e = expected[y]
                if co < min_co or e <= 0:
                    continue
                lift, pv = co / e, _poisson_sf(co, e)
                out.append({"x": x, "y": y, "lag": lag, "n_big": n, "co": co, "expected": e,
                            "lift": lift, "p_value": pv,
                            "same_master": bool(set(masters.get(x, ())) & set(masters.get(y, ()))),
                            "overlap_days": len(active[x] & active[y]),
                            "events": events[y] if (lift >= 2 and pv <= 1e-2) else []})
    # v3.83.3: ~13k pairs x lags are tested at once -> Benjamini-Hochberg q-values
    m = len(out)
    ranked = sorted(out, key=lambda e: e["p_value"])
    prev = 1.0
    for rank in range(m, 0, -1):                 # step-up: q_i = min_{j >= i} p_j * m / j
        e = ranked[rank - 1]
        prev = min(prev, e["p_value"] * m / rank)
        e["q_value"] = prev
    out.sort(key=lambda e: -e["lift"])
    return out


def is_relation(e, min_lift=3.0, max_q=MAX_Q, min_overlap=MIN_OVERLAP_DAYS):
    """A real relation: strong, FDR-significant, enough common days, not the same master."""
    return (e["lift"] >= min_lift and e.get("q_value", 1.0) <= max_q
            and e.get("overlap_days", 0) >= min_overlap and not e["same_master"])


def clusters(edges, min_lift=3.0, max_q=MAX_Q, lag=0, min_overlap=MIN_OVERLAP_DAYS):
    """Connected groups of branches linked by same-day relations (is_relation)."""
    adj = defaultdict(set)
    for e in edges:
        if e["lag"] == lag and is_relation(e, min_lift, max_q, min_overlap):
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
