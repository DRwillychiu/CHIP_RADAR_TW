"""v3.86.0 今日總整理: one small summary per night for the site's first page.

Owner 2026-10-09: "登錄後的第一頁，絕對就是當日的總整理…能夠人在1分鐘讀完的資訊".
Layout = the approved mock-up (CHIP_RADAR_LOCAL/mock_summary.png): 4 sentences,
8 KPIs, strong chips top 5, what changed, domestic masters top 5, foreign
brokers on their own, disposal lane.

Strong chips = rule #1 (owner 2026-10-08, docs/specs/DAILY_SUMMARY_SPEC.md §3): per branch-stock
over the last W trading days, net >= NT$30m, >= 5 buy days, buy days >= 2.5x
sell days, cumulative net still >= 80% of its window high; a stock counts when
>= 3 distinct masters qualify. Foreign brokers (region us / eu / asia) are
never inside the tracked-master total (owner 2026-10-09: "要排除外資大戶，
直接獨立列出外資的追蹤大戶就好").

Pure functions; no file or network access here (scripts/build_daily_summary.py
does the I/O).
"""
import datetime as dt
from collections import defaultdict

W = 10                    # trading days in the window
MIN_NET_K = 30000         # NT$30m in 仟元 (same unit as net_amt)
MIN_BUY_DAYS = 5
BUY_SELL_RATIO = 2.5
KEEP_HIGH = 0.8
MIN_MASTERS = 3
FOREIGN_REGIONS = ("us", "eu", "asia")
SURGE = 3                 # masters added since yesterday to call it a surge
TREND_DAYS = 20           # v3.89.0 sparklines on the page (owner 2026-10-10)
BROKEN = "�"
WEEKDAY = "一二三四五六日"


def is_common(code):
    """Ordinary listed / OTC shares only: 4 digits, not 0xxx (ETFs, warrants)."""
    return len(code) == 4 and code.isdigit() and code[0] != "0"


def day_rows(day):
    """{bno: {code: (net_lot, net_amt_k, name)}}; first row per code, buys before sells."""
    out = {}
    for b in day.get("branches") or []:
        rs = {}
        for r in (b.get("buys") or []) + (b.get("sells") or []):
            c = str(r.get("code") or "")
            if c and c not in rs:
                rs[c] = (r.get("net_lot") or 0, r.get("net_amt") or 0, r.get("name") or "")
        out[b.get("code")] = rs
    return out


def qualifies(win):
    """win = [(net_lot, net_amt_k), ...] for the days the pair shows up in the window.
    Returns the window net (仟元) when the pair passes rule #1, else None."""
    if len(win) < MIN_BUY_DAYS:
        return None
    amt = sum(a for _, a in win)
    buy = sum(1 for lot, _ in win if lot > 0)
    sell = sum(1 for lot, _ in win if lot < 0)
    if amt < MIN_NET_K or buy < MIN_BUY_DAYS or (sell > 0 and buy < BUY_SELL_RATIO * sell):
        return None
    cum = high = 0
    for _, a in win:
        cum += a
        high = max(high, cum)
    return amt if cum >= KEEP_HIGH * high else None


def strong_chips(rows_by_day, masters, end):
    """{code: {master: net_k}} for the W trading days ending at index `end`."""
    pairs = defaultdict(list)
    for u in range(max(0, end - W + 1), end + 1):
        for b, rs in rows_by_day[u].items():
            for c, (lot, amt, _) in rs.items():
                if is_common(c):
                    pairs[(b, c)].append((lot, amt))
    out = defaultdict(dict)
    for (b, c), win in pairs.items():
        a = qualifies(win)
        if a:
            m = masters.get(b) or b
            out[c][m] = out[c].get(m, 0) + a
    return dict(out)


def ranked(hold):
    """Stocks with >= MIN_MASTERS masters, most masters first, then biggest net."""
    return sorted(((c, m) for c, m in hold.items() if len(m) >= MIN_MASTERS),
                  key=lambda x: (-len(x[1]), -sum(x[1].values())))


def _yi(k):
    return None if k is None else round(k / 1e5, 1)


def day_flows(rs, foreign):
    """(domestic, foreign) net of one day in 仟元, ordinary shares only."""
    dom = frn = 0
    for b, r in rs.items():
        tot = sum(a for c, (_, a, _) in r.items() if is_common(c))
        if b in foreign:
            frn += tot
        else:
            dom += tot
    return dom, frn


def _clean(name):
    return name if name and BROKEN not in name else ""


def build_summary(days, stock_history=None, attstock=None, official_names=None):
    """days: [{'date': 'YYYYMMDD', 'data': <decrypted day>}, ...] ascending, the
    last one is tonight. Returns the dict written to data/daily_summary.json."""
    if not days:
        raise ValueError("no day files")
    sh = stock_history or {}
    att = attstock or {}
    official = official_names or {}
    rows = [day_rows(d["data"]) for d in days]
    masters, region = {}, {}
    for d in days:
        for b in d["data"].get("branches") or []:
            masters[b.get("code")] = b.get("master") or masters.get(b.get("code")) or b.get("code")
            region[b.get("code")] = b.get("region") or region.get(b.get("code"))
    foreign = {b for b, r in region.items() if r in FOREIGN_REGIONS}
    T = len(days) - 1
    date, today = days[T]["date"], days[T]["data"]
    prev_day = days[T - 1]["data"] if T >= 1 else {}

    names = {}
    for rs in rows:
        for b_rows in rs.values():
            for c, (_, _, nm) in b_rows.items():
                if _clean(nm):
                    names[c] = nm
    for c, st in (sh.get("stocks") or {}).items():
        if _clean(st.get("name")):
            names[c] = st["name"]
    names.update({c: n for c, n in official.items() if _clean(n)})

    def name(c):
        return names.get(c) or c

    def px(c):
        return (((sh.get("stocks") or {}).get(c) or {}).get("daily") or {}).get(date) or {}

    now = strong_chips(rows, masters, T)
    prev = strong_chips(rows, masters, T - 1) if T >= 1 else {}
    top = ranked(now)
    prev3 = {c for c, _ in ranked(prev)}
    new3 = [c for c, _ in top if c not in prev3]
    gone3 = sorted(prev3 - {c for c, _ in top})
    in_disp = set(att.get("codes_in_disposal") or [])
    pend = list(att.get("codes_pending_1d") or [])

    # tonight per master, domestic and foreign apart
    pm = defaultdict(lambda: {"amt": 0, "stocks": defaultdict(int), "bnos": set()})
    for b, rs in rows[T].items():
        m = masters.get(b) or b
        for c, (_, amt, _) in rs.items():
            if is_common(c):
                pm[m]["amt"] += amt
                pm[m]["stocks"][c] += amt
                pm[m]["bnos"].add(b)
    fpm = {m: v for m, v in pm.items() if v["bnos"] & foreign}
    dpm = {m: v for m, v in pm.items() if m not in fpm}

    def player(m, v):
        side = 1 if v["amt"] >= 0 else -1      # biggest flow on the side of the net
        best = max(v["stocks"].items(), key=lambda x: side * x[1]) if v["stocks"] else (None, 0)
        return {"master": m, "net_yi": _yi(v["amt"]), "branches": len(v["bnos"]),
                "best_code": best[0], "best_name": name(best[0]) if best[0] else "", "best_yi": _yi(best[1])}

    dom = [player(m, v) for m, v in sorted(dpm.items(), key=lambda x: -x[1]["amt"])]
    frn = [player(m, v) for m, v in sorted(fpm.items(), key=lambda x: -x[1]["amt"])]
    dom_net = _yi(sum(v["amt"] for v in dpm.values()))
    frn_net = _yi(sum(v["amt"] for v in fpm.values()))

    mk = (sh.get("market") or {}).get(date) or {}
    fut = (today.get("futures_data") or {}).get("summary") or {}
    fut0 = (prev_day.get("futures_data") or {}).get("summary") or {}
    mg = today.get("margin_market_aggregate") or {}
    mg0 = prev_day.get("margin_market_aggregate") or {}
    oi, oi0 = fut.get("foreign_equivalent_net_oi"), fut0.get("foreign_equivalent_net_oi")
    pc, pc0 = fut.get("pc_ratio_oi"), fut0.get("pc_ratio_oi")
    kpis = {
        "taiex": mk.get("index"), "taiex_chg_pct": mk.get("change_pct"),
        "fut_foreign_oi": oi, "fut_foreign_oi_chg": (oi - oi0) if oi is not None and oi0 is not None else None,
        "pc_ratio": pc, "pc_ratio_chg": round(pc - pc0, 2) if pc is not None and pc0 is not None else None,
        "margin_chg_yi": mg.get("margin_amt_change_yi"), "margin_chg_yi_prev": mg0.get("margin_amt_change_yi"),
        "margin_balance_yi": mg.get("margin_amt_balance_yi"),
        "domestic_net_yi": dom_net, "domestic_masters": len(dpm), "domestic_branches": sum(len(v["bnos"]) for v in dpm.values()),
        "foreign_net_yi": frn_net, "foreign_brokers": len(fpm),
        "strong_count": len(top), "strong_prev": len(prev3), "strong_new": len(new3),
        "disposal_in": len(in_disp), "disposal_pending": len(pend),
    }

    def risk_of(c):
        return "處置中" if c in in_disp else ("明日恐處置" if c in pend else "")

    def strong_row(c, m):
        return {"code": c, "name": name(c), "masters": len(m), "net10_yi": _yi(sum(m.values())),
                "chg_pct": px(c).get("change_pct"), "risk": risk_of(c), "new": c in new3,
                "who": [w for w, _ in sorted(m.items(), key=lambda x: -x[1])[:3]]}

    top_rows = [strong_row(c, m) for c, m in top[:5]]
    strong_all = [strong_row(c, m) for c, m in top]          # v3.90.0 the drawer lists every one

    changes = []
    if new3:
        changes.append({"tag": f"新進強籌 {len(new3)}", "kind": "up",
                        "text": "、".join(name(c) for c in new3[:4]) + ("…" if len(new3) > 4 else "")})
    if gone3:
        changes.append({"tag": f"跌出 {len(gone3)}", "kind": "flat",
                        "text": "、".join(name(c) for c in gone3[:4]) + ("…" if len(gone3) > 4 else "")})
    surge = [c for c, m in top if len(m) - len(prev.get(c, {})) >= SURGE][:3]
    if surge:
        changes.append({"tag": "主力暴增", "kind": "up",
                        "text": "、".join(f"{name(c)} {len(prev.get(c, {}))}→{len(now[c])} 位" for c in surge)})
    risk_top = [c for c, _ in top if risk_of(c)]
    if risk_top:
        changes.append({"tag": "強籌∩風險", "kind": "risk",
                        "text": "、".join(f"{name(c)}（{risk_of(c)}）" for c in risk_top[:3])})
    if oi is not None and oi0 is not None:
        d = oi - oi0
        changes.append({"tag": "期貨", "kind": "flat",
                        "text": f"外資台指期淨{'空' if oi < 0 else '多'}單 {'增加' if (d < 0) == (oi < 0) else '減少'} "
                                f"{abs(d):,} 口（{abs(oi):,} 口）"})

    # four sentences; **x** = emphasis (the page escapes HTML first, then bolds)
    s = []
    if top:
        lead = "、".join(f"{name(c)} {len(m)} 位" for c, m in top[:2])
        s.append(f"**{len(top)}** 檔正被 3 位以上追蹤大戶同時布局（昨 {len(prev3)}；新進 {len(new3)}、跌出 {len(gone3)}）。最集中：{lead}。")
    else:
        s.append(f"今晚沒有股票被 3 位以上追蹤大戶同時布局（昨 {len(prev3)} 檔）。")
    if dom:
        lead = dom[0]
        txt = f"本土追蹤大戶今晚合計淨買 **{_fmt_yi(dom_net)} 億**；"
        if lead["net_yi"] is not None and lead["net_yi"] > 0:
            buys = sorted(dpm[lead["master"]]["stocks"].items(), key=lambda x: -x[1])[:2]
            txt += (f"最大買方 {lead['master']} {_fmt_yi(lead['net_yi'])} 億，主要買 "
                    + "、".join(name(c) for c, _ in buys if c) + "。")
        else:
            txt += f"沒有大戶淨買，賣最多 {dom[-1]['master']} {_fmt_yi(dom[-1]['net_yi'])} 億。"
        if frn:
            low, high = frn[-1], frn[0]
            pick = (f"賣最多 {low['master']} {_fmt_yi(low['net_yi'])} 億" if (low["net_yi"] or 0) < 0
                    else f"買最多 {high['master']} {_fmt_yi(high['net_yi'])} 億")
            txt += f"外資 {len(frn)} 家合計 **{_fmt_yi(frn_net)} 億**（{pick}）。"
        s.append(txt)
    if oi is not None:
        txt = f"外資台指期淨{'空' if oi < 0 else '多'}單 **{abs(oi):,} 口**"
        if oi0 is not None:
            d = oi - oi0
            txt += f"，比昨天{'增加' if (d < 0) == (oi < 0) else '減少'} {abs(d):,} 口"
        if mk.get("change_pct") is not None:
            txt += f"；加權 {mk['change_pct']:+.2f}%"
        s.append(txt + "。")
    if mg.get("margin_amt_change_yi") is not None:
        c0 = mg0.get("margin_amt_change_yi")
        txt = (f"融資{'增加' if mg['margin_amt_change_yi'] >= 0 else '減少'} {abs(mg['margin_amt_change_yi']):.0f} 億"
               + (f"（昨 {c0:+.0f} 億）" if c0 is not None else "") + f"；明日恐處置 **{len(pend)}** 檔")
        if risk_top:
            txt += f"，其中 {len(risk_top)} 檔在強籌名單"
        s.append(txt + "。")

    # v3.87.0 one headline + one note under each big number (owner 2026-10-09:
    # Japanese-ad style, "簡潔，卻又非常清楚重點"); the page only displays them
    if len(top) >= 2:
        headline = f"{name(top[0][0])}、{name(top[1][0])}被最多大戶同時布局"
    elif top:
        headline = f"{name(top[0][0])}被最多大戶同時布局"
    else:
        headline = "今晚沒有 3 位以上大戶同時布局的股票"
    if frn and frn_net is not None:
        headline += f"；外資券商合計{'賣超' if frn_net < 0 else '買超'} {abs(frn_net):,.1f} 億"

    def pick(rows):
        if not rows:
            return ""
        if (rows[0]["net_yi"] or 0) > 0:
            return f"買最多 {rows[0]['master']} {_fmt_yi(rows[0]['net_yi'])}"
        return f"賣最多 {rows[-1]['master']} {_fmt_yi(rows[-1]['net_yi'])}"

    def pick_foreign(rows):
        if not rows:
            return ""
        if (rows[-1]["net_yi"] or 0) < 0:
            return f"賣最多 {rows[-1]['master']} {_fmt_yi(rows[-1]['net_yi'])}"
        return f"買最多 {rows[0]['master']} {_fmt_yi(rows[0]['net_yi'])}"

    notes = {
        "strong": f"昨 {len(prev3)}・新進 {len(new3)}",
        "domestic": f"{len(dpm)} 位合計" + (f"・{pick(dom)}" if dom else ""),
        "foreign": f"{len(frn)} 家合計" + (f"・{pick_foreign(frn)}" if frn else ""),
        "risk": ("・".join(name(c) for c in sorted(pend)) or "無") + f"（處置中 {len(in_disp)}）",
    }

    # v3.89.0 20-day trends for the sparklines; the strong count of each day uses its
    # own full 10-day window (scripts/build_daily_summary.py loads TREND_DAYS + W + 1 days)
    span = range(max(0, T - TREND_DAYS + 1), T + 1)
    flows = [day_flows(rows[u], foreign) for u in span]

    def fut(u, key):
        # 0 means the futures fetch failed that day (20260917 stored 0 net OI): a gap, not a value
        v = ((days[u]["data"].get("futures_data") or {}).get("summary") or {}).get(key)
        return v if v else None

    trends = {
        "dates": [days[u]["date"] for u in span],
        "strong": [len(ranked(strong_chips(rows, masters, u))) for u in span],
        "domestic": [_yi(f[0]) for f in flows],
        "foreign": [_yi(f[1]) for f in flows],
        "taiex": [(((sh.get("market") or {}).get(days[u]["date"]) or {}).get("index")) for u in span],
        "fut_oi": [fut(u, "foreign_equivalent_net_oi") for u in span],
        "margin": [(days[u]["data"].get("margin_market_aggregate") or {}).get("margin_amt_change_yi") for u in span],
        "pc": [fut(u, "pc_ratio_oi") for u in span],
    }

    crawled = str(today.get("crawled_at") or "")
    d0 = dt.date(int(date[:4]), int(date[4:6]), int(date[6:]))
    return {
        "version": 1,
        "date": date,
        "weekday": WEEKDAY[d0.weekday()],
        "crawled_at": crawled[11:16] if len(crawled) >= 16 else "",
        "window_days": min(W, len(days)),
        "fubon": {"ok": today.get("success") or 0, "total": (today.get("success") or 0) + (today.get("failed") or 0)},
        "headline": headline,
        "notes": notes,
        "trends": trends,
        "sentences": s,
        "kpis": kpis,
        "strong_top": top_rows,
        "changes": changes[:5],
        "domestic_top": dom[:5],
        "strong_all": strong_all,
        "domestic_all": dom,
        "foreign": frn,
        "risk": {"in_disposal": len(in_disp),
                 "pending": [{"code": c, "name": name(c), "strong_masters": len(now.get(c, {}))} for c in sorted(pend)],
                 "fetched_at": att.get("fetched_at") or ""},
    }


def _fmt_yi(v):
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):,.1f}"
