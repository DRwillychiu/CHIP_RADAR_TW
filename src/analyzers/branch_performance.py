"""v3.82.0 branch performance model (owner 2026-10-08: "losses and performance
must follow the most complete, generally accepted financial model").

Inputs per branch: daily rows (date, stock, buy_lots, sell_lots, buy_amt 仟元,
sell_amt 仟元) and daily closes (+ TAIEX). Model:

  Position accounting  FIFO lot matching per (branch, stock). Buy cost and sell
                       proceeds include transaction costs: commission
                       COMMISSION (both sides), securities transaction tax
                       TAX_SELL (sells). Sells beyond the known inventory are
                       "unmatched" (the shares were bought before the data
                       starts): excluded from PnL and reported.
  PnL                  realized (FIFO, net of costs) + unrealized (open lots
                       marked to the close). Total PnL over the window =
                       V_end - V_begin - net cash flow.
  Returns              Modified Dietz over the window (GIPS) and a daily
                       time-weighted return (TWR, flows at the start of day).
  Risk                 annualized volatility, Sharpe, Sortino (rf configurable),
                       max drawdown of the TWR index.
  Benchmark            beta / Jensen's alpha vs TAIEX daily returns (OLS);
                       information ratio; the same cash flows put into TAIEX
                       give the benchmark PnL -> excess PnL.
  Trade statistics     per stock position (all FIFO matches of one branch x
                       stock in the window): win rate, payoff, profit factor,
                       expectancy, PnL per NT$10M bought.
  Owner's legacy       sell_lots x (sell_avg - buy_avg) per stock, mean over
                       positions / mean buy amount x 1000 (每千萬期望值). That
                       product is 仟元, so the legacy number is 10x the 萬 value;
                       both are returned.

Limitation (stated in every result): only the stocks a branch has in its daily
top-50 net-buy / net-sell lists are visible, so a position's other days can be
missing. Coverage figures are returned with each branch.
"""
from collections import defaultdict, deque
from math import sqrt

COMMISSION = 0.001425        # 0.1425% each side, undiscounted (conservative)
TAX_SELL = 0.003             # 0.3% securities transaction tax on sells
SHARES_PER_LOT = 1000
TRADING_DAYS = 252
TEN_MILLION = 10_000_000


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _std(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


class Book:
    """FIFO lots of one (branch, stock). Money in NT$, quantity in shares."""

    def __init__(self, commission=COMMISSION, tax=TAX_SELL):
        self.lots = deque()          # [shares, cost per share incl. buy commission, buy day]
        self.commission, self.tax = commission, tax
        self.realized = 0.0
        self.unmatched_shares = 0
        self.sold_shares = 0
        self.holds = []              # v3.82.1: [(shares, holding trading days)] of matched sells
        self.matched_cost = 0.0      # cost of the shares sold out of inventory

    @property
    def shares(self):
        return sum(lot[0] for lot in self.lots)

    def buy(self, shares, price, day=None):
        """-> cash out (NT$, incl. commission). day: trading-day ordinal (holding periods)."""
        if shares <= 0:
            return 0.0
        cost = shares * price * (1 + self.commission)
        self.lots.append([shares, cost / shares, day])
        return cost

    def sell(self, shares, price, day=None):
        """-> cash in (NT$, net of commission + tax) for the matched part only."""
        if shares <= 0:
            return 0.0
        net_px = price * (1 - self.commission - self.tax)
        self.sold_shares += shares
        left, proceeds = shares, 0.0
        while left > 0 and self.lots:
            lot = self.lots[0]
            q = min(left, lot[0])
            proceeds += q * net_px
            self.realized += q * (net_px - lot[1])
            self.matched_cost += q * lot[1]
            if day is not None and lot[2] is not None:
                self.holds.append((q, day - lot[2]))
            lot[0] -= q
            left -= q
            if lot[0] == 0:
                self.lots.popleft()
        self.unmatched_shares += left
        return proceeds

    def value(self, close):
        return self.shares * close if close else 0.0

    def cost_basis(self):
        return sum(lot[0] * lot[1] for lot in self.lots)


def modified_dietz(v_begin, v_end, flows, n_days):
    """flows: [(day_index 0..n_days, amount)] external flows (+ in, - out)."""
    cf = sum(a for _, a in flows)
    denom = v_begin + sum(a * (n_days - d) / n_days for d, a in flows) if n_days else v_begin
    return (v_end - v_begin - cf) / denom if denom > 0 else None


def ols_beta_alpha(r, m):
    """Daily OLS r = alpha + beta*m -> (beta, alpha_daily)."""
    if len(r) < 10:
        return None, None
    mm, mr = _mean(m), _mean(r)
    var = sum((x - mm) ** 2 for x in m)
    if var == 0:
        return None, None
    beta = sum((x - mm) * (y - mr) for x, y in zip(m, r)) / var
    return beta, mr - beta * mm


def evaluate(rows, closes, index, dates, warmup_rows=(), rf_annual=0.0, min_value=1_000_000, day_index=None):
    """One branch.

    rows        [{date, code, buy_lots, sell_lots, buy_amt, sell_amt}] inside the window
    warmup_rows same shape, before the window: build the opening inventory only
    closes      {code: {date: close}};  index {date: TAIEX close}
    dates       window trading dates, ascending; dates[0] = valuation start
    min_value   days whose start value + inflow is below this (NT$) get no daily return
    """
    books = defaultdict(Book)
    di = day_index or {}
    for r in sorted(warmup_rows, key=lambda x: x["date"]):
        _apply(books[r["code"]], r, di.get(r["date"]))
    d0 = dates[0]
    v_begin = sum(b.value(closes.get(c, {}).get(d0)) for c, b in books.items())
    # GIPS period accounting: the opening inventory enters the window at its
    # beginning market value, so the window's PnL starts from the d0 close and
    # nothing realized during the warm-up counts.
    for c, b in books.items():
        px = closes.get(c, {}).get(d0)
        if px:
            for lot in b.lots:
                lot[1] = px
        b.realized, b.matched_cost, b.unmatched_shares, b.sold_shares = 0.0, 0.0, 0, 0
        b.holds = []
    by_day = defaultdict(list)
    for r in rows:
        if r["date"] in dates[1:]:
            by_day[r["date"]].append(r)
    n = len(dates) - 1
    flows, daily_r, daily_m, pnl_series = [], [], [], []
    v_prev, last_close = v_begin, {}
    pos = defaultdict(lambda: {"buy": 0.0, "sell_matched_cost": 0.0, "pnl": 0.0})
    bought_total = 0.0
    for i, d in enumerate(dates[1:], start=1):
        cf = 0.0
        for r in by_day.get(d, []):
            b = books[r["code"]]
            before_real, before_cost = b.realized, b.matched_cost
            out = _apply(b, r, di.get(d))
            cf += out
            p = pos[r["code"]]
            p["pnl"] += b.realized - before_real
            p["sell_matched_cost"] += b.matched_cost - before_cost
            if r.get("buy_lots"):
                spent = r["buy_lots"] * SHARES_PER_LOT * _px(r["buy_amt"], r["buy_lots"]) * (1 + COMMISSION)
                p["buy"] += spent
                bought_total += spent
        v = 0.0
        for c, b in books.items():
            px = closes.get(c, {}).get(d) or last_close.get(c)
            if px:
                last_close[c] = px
            v += b.value(px)
        if cf:
            flows.append((i, cf))
        pnl_t = v - v_prev - cf
        pnl_series.append(pnl_t)
        base = v_prev + max(cf, 0.0)
        if base >= min_value and index.get(d) and index.get(dates[i - 1]):
            daily_r.append(pnl_t / base)
            daily_m.append(index[d] / index[dates[i - 1]] - 1)
        v_prev = v
    v_end = v_prev
    total_pnl = v_end - v_begin - sum(a for _, a in flows)
    # unrealized PnL of the open lots at the end, per stock (for position stats)
    d_end = dates[-1]
    for c, b in books.items():
        px = closes.get(c, {}).get(d_end) or last_close.get(c)
        if px and b.shares and c in pos:
            pos[c]["pnl"] += b.value(px) - b.cost_basis()
    out = {"v_begin": v_begin, "v_end": v_end, "total_pnl": total_pnl,
           "realized_pnl": sum(b.realized for b in books.values()),
           "bought": bought_total, "days": n,
           "md_return": modified_dietz(v_begin, v_end, flows, n),
           "unmatched_shares": sum(b.unmatched_shares for b in books.values()),
           "sold_shares": sum(b.sold_shares for b in books.values())}
    out["unmatched_ratio"] = out["unmatched_shares"] / out["sold_shares"] if out["sold_shares"] else None
    # time-weighted return + risk
    twr, peak, mdd, idx = 1.0, 1.0, 0.0, 1.0
    for x in daily_r:
        idx *= 1 + x
        peak = max(peak, idx)
        mdd = min(mdd, idx / peak - 1)
    twr = idx - 1 if daily_r else None
    rf_d = rf_annual / TRADING_DAYS
    ex = [x - rf_d for x in daily_r]
    sd, down = _std(daily_r), [x for x in ex if x < 0]
    dd = sqrt(sum(x * x for x in down) / len(ex)) if ex and down else None
    beta, alpha_d = ols_beta_alpha(daily_r, daily_m)
    act = [x - y for x, y in zip(daily_r, daily_m)]
    out.update({
        "twr": twr, "return_days": len(daily_r),
        "vol_ann": sd * sqrt(TRADING_DAYS) if sd else None,
        "sharpe": (_mean(ex) / sd * sqrt(TRADING_DAYS)) if sd else None,
        "sortino": (_mean(ex) / dd * sqrt(TRADING_DAYS)) if dd else None,
        "max_drawdown": mdd if daily_r else None,
        "beta": beta, "alpha_ann": alpha_d * TRADING_DAYS if alpha_d is not None else None,
        "info_ratio": (_mean(act) / _std(act) * sqrt(TRADING_DAYS)) if _std(act) else None,
        "benchmark_pnl": _benchmark_pnl(flows, v_begin, index, dates),
    })
    out["excess_pnl"] = (total_pnl - out["benchmark_pnl"]) if out["benchmark_pnl"] is not None else None
    # position statistics
    pnls = [p["pnl"] for p in pos.values() if p["buy"] > 0 or p["sell_matched_cost"] > 0]
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    bought_shares = sum((r.get("buy_lots") or 0) * SHARES_PER_LOT for r in rows if r["date"] in dates[1:])
    out.update(style_metrics([h for bk in books.values() for h in bk.holds],
                             [r for r in rows if r["date"] in dates[1:]], bought_shares))
    out.update(chase_metrics([r for r in rows if r["date"] in dates[1:]], closes, dates))
    out.update(style_labels(out))
    out.update({
        "positions": len(pnls), "win_rate": len(wins) / len(pnls) if pnls else None,
        "avg_win": _mean(wins), "avg_loss": _mean(losses),
        "payoff": (_mean(wins) / -_mean(losses)) if wins and losses else None,
        "profit_factor": (sum(wins) / -sum(losses)) if losses else None,
        "expectancy": _mean(pnls),
        "pnl_per_10m": total_pnl / bought_total * TEN_MILLION if bought_total else None,
    })
    return out


def _px(amt_k, lots):
    return amt_k * 1000 / (lots * SHARES_PER_LOT) if lots else 0.0


def _apply(book, r, day=None):
    """Apply one daily row to a book -> external cash flow (+ buy cost, - sell proceeds)."""
    cf = 0.0
    if r.get("buy_lots"):
        cf += book.buy(r["buy_lots"] * SHARES_PER_LOT, _px(r["buy_amt"], r["buy_lots"]), day)
    if r.get("sell_lots"):
        cf -= book.sell(r["sell_lots"] * SHARES_PER_LOT, _px(r["sell_amt"], r["sell_lots"]), day)
    return cf


def style_metrics(holds, rows, bought_shares):
    """v3.82.1 owner 2026-10-08: judge performance together with the branch's style.

    holds: [(shares, holding trading days)] of FIFO-matched sells in the window
    rows : the window's daily rows (same-day two-sided trading = day-trade proxy;
           FIFO hides a same-day round trip behind older inventory)
    -> measured style + the evaluation horizon that fits it.
    """
    two = sum(min(r.get("buy_lots") or 0, r.get("sell_lots") or 0) for r in rows)
    buys = sum(r.get("buy_lots") or 0 for r in rows)
    two_sided = two / buys if buys else None
    matched = sum(q for q, _ in holds)
    out = {"two_sided_share": two_sided, "matched_share": (matched / bought_shares) if bought_shares else None,
           "hold_median": None, "hold_le1": None, "hold_le5": None, "hold_gt20": None}
    if matched:
        acc, med = 0, None
        for q, d in sorted(holds, key=lambda x: x[1]):
            acc += q
            if med is None and acc >= matched / 2:
                med = d
        out.update(hold_median=med,
                   hold_le1=sum(q for q, d in holds if d <= 1) / matched,
                   hold_le5=sum(q for q, d in holds if d <= 5) / matched,
                   hold_gt20=sum(q for q, d in holds if d > 20) / matched)
    if two_sided is not None and two_sided >= 0.5:
        style = "day_trader"
    elif out["hold_le1"] is not None and out["hold_le1"] >= 0.5:
        style = "next_day_flipper"
    elif out["hold_median"] is not None and out["hold_median"] <= 5:
        style = "short_term"
    elif out["hold_median"] is not None and out["hold_median"] <= 30 and (out["matched_share"] or 0) >= 0.3:
        style = "swing"
    elif out["matched_share"] is not None:
        style = "longterm"
    else:
        style = None
    out["style"] = style
    out["horizon"] = "recent" if style in ("day_trader", "next_day_flipper", "short_term") else "full"
    return out


def _benchmark_pnl(flows, v_begin, index, dates):
    """Same flows (and starting value) put into TAIEX at that day's close."""
    if not index.get(dates[0]) or not index.get(dates[-1]):
        return None
    units, cf_sum = v_begin / index[dates[0]], 0.0
    for d_i, a in flows:
        px = index.get(dates[d_i])
        if not px:
            return None
        units += a / px
        cf_sum += a
    return units * index[dates[-1]] - v_begin - cf_sum


def legacy_owner_metric(stock_rows):
    """Owner's sheet: stock_rows [(buy_lots, sell_lots, buy_wan, buy_avg, sell_avg)] aggregated
    per stock over the window. -> (legacy 每千萬期望值 as in the sheet, same in 萬)."""
    if not stock_rows:
        return None, None
    pnl = [s * (sa - ba) for _, s, _, ba, sa in stock_rows]       # 張 x 元 = 仟元
    ev = sum(pnl) / len(pnl)
    avg_order = sum(w for _, _, w, _, _ in stock_rows) / len(stock_rows)
    legacy = ev / avg_order * 1000 if avg_order else None
    return legacy, (legacy / 10 if legacy is not None else None)


STRONG_DAY = 0.05        # buy-day close change >= +5% counts as buying into strength


def chase_metrics(rows, closes, dates):
    """v3.82.2: next-day flippers buy into strength. Buy amount weighted: mean
    close-to-close change of the stock on the buy day, share bought on days with
    change >= +5%, share bought in limit-up stocks (row flag 'lu' when present)."""
    prev = {d: dates[i - 1] for i, d in enumerate(dates) if i}
    tot = wsum = strong = lu = 0.0
    for r in rows:
        amt = r.get("buy_amt") or 0
        if amt <= 0 or not r.get("buy_lots"):
            continue
        c = closes.get(r["code"], {})
        p0, p1 = c.get(prev.get(r["date"])), c.get(r["date"])
        if not p0 or not p1:
            continue
        chg = p1 / p0 - 1
        tot += amt
        wsum += amt * chg
        strong += amt if chg >= STRONG_DAY else 0.0
        lu += amt if r.get("lu") else 0.0
    if not tot:
        return {"buy_day_change": None, "strong_day_buy_share": None, "limit_up_buy_share": None}
    return {"buy_day_change": wsum / tot, "strong_day_buy_share": strong / tot, "limit_up_buy_share": lu / tot}


# v3.82.2 thresholds calibrated on the owner's labels (2026-10-08) - see the spec
SECONDARY_MIN = 0.37      # the other horizon is a second label when its share is >= 37%
FLIP_MIN = 0.30           # next-day flipper needs >= 30% of matched shares held <= 1 day ...
CHASE_MIN = None          # ... AND strong-day buying share >= CHASE_MIN (set after calibration)
DAY_TRADE_MIN = 0.75      # same-day two-sided share; 55% was a swing / short branch (新光-新竹)


def style_labels(m, secondary_min=None, flip_min=None, chase_min=None, day_trade_min=None):
    """Multi-label style: primary 波段 (swing, held > 5 days) or 短線 (short, <= 5),
    the other as secondary when large enough, plus 隔日沖 / 當沖 flags."""
    secondary_min = SECONDARY_MIN if secondary_min is None else secondary_min
    flip_min = FLIP_MIN if flip_min is None else flip_min
    chase_min = CHASE_MIN if chase_min is None else chase_min
    day_trade_min = DAY_TRADE_MIN if day_trade_min is None else day_trade_min
    labels = []
    short = m.get("hold_le5")
    if short is not None:
        swing = 1 - short
        primary, other, other_share = ("swing", "short_term", short) if swing >= short else \
            ("short_term", "swing", swing)
        labels.append(primary)
        if other_share >= secondary_min:
            labels.append(other)
    flip = m.get("hold_le1")
    chase = m.get("strong_day_buy_share")
    if flip is not None and flip >= flip_min and (chase_min is None or (chase is not None and chase >= chase_min)):
        labels.append("next_day_flipper")
    if (m.get("two_sided_share") or 0) >= day_trade_min:
        labels.append("day_trader")
    return {"style_labels": labels}
