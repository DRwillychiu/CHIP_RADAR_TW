"""v3.96.0 insider radar 2.2-2.4 on real data -> data/insider_radar.json, the file the web page reads
in stage 3 (owner 2026-10-11: everything computed here must end up on the page).
Spec: docs/specs/INSIDER_RADAR_SPEC.md 5 (defaults approved 2026-10-11).

Trades = each person's market buys - market sells (5.1); 其它原因 is kept apart as other_net_shares.
Signal day = the first trading day after the month's publish date (IRB110 資料日期).
Group A: net buy >= 1 億, or the first big buy in 1 year with >= 0.2 % of the shares.
Group B: A and the tracked branch masters net buying in the 10 trading days before the signal day;
the daily branch data starts 2026-04-21, so A_cov (A with branch coverage) is the fair comparison.
Excess return = stock - TAIEX (the OTC index is not stored yet; noted in the output).
v3.96.1 (spec 3.1, the 今日總整理 block): the repo is public, so the output is split in two.
  data/insider_radar.json          public MOPS data only (A, sells, their backtests, per-person detail)
  data/insider_radar_private.json  everything from our branch-master crawl (group B, branch_net_10d,
                                   同向 / 反向, B's backtest), AES-GCM envelope like daily_summary.json
v3.96.2 year windows (WINDOWS): the same blocks per year in doc['years'] (the latest one also at the top level);
  the private part gets the same split for B.
    CHIP_RADAR_PASSWORD=... python scripts/run_insider_radar.py
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analyzers import insider_radar as R  # noqa: E402

SELL_YI, SELL_PCT = -1.0, -0.2     # the risk list: net sell <= -1 億 or <= -0.2 % of the shares
IN_SAMPLE_UNTIL = "202604"         # in-sample 2025-09..2026-04, out-of-sample 2026-05..2026-08
PRIVATE_NAME = "insider_radar_private.json"
DETAIL_FIELDS = ("market_buy", "market_sell", "other_buy", "other_sell", "end_shares")
# v3.96.2 owner 2026-10-11 「設置一個可以下拉選年份的選單」: the year windows, newest first, the first one ending
# at the latest published month. (key, label, first ym, last ym); a signal belongs to the window of its ym.
WINDOWS = (
    ("y1", "近一年", "202509", "202608"),
    ("y2", "2024-10～2025-08", "202410", "202508"),
    ("y3", "2023-09～2024-09", "202309", "202409"),
)


def in_window(items, since, until):
    """The signals of one year window, by the signal's month (ym)."""
    return [s for s in items if since <= s["ym"] <= until]


def next_ym(ym):
    y, m = int(ym[:4]), int(ym[4:])
    return f"{y + m // 12:04d}{m % 12 + 1:02d}"


def month_list(since, until):
    out, y, m = [], int(since[:4]), int(since[4:])
    while f"{y:04d}{m:02d}" <= until:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def open_queue(queue, raw_dir):
    """The queue entries that still mean a per-person page to come (2026-10-12: year 1 showed 「抓取中」 after it
    finished): the t56 jobs are saved elsewhere and are not person pages, and a company that answered
    「不繼續公開發行」 is skipped for all its months by the fetcher."""
    if not queue:
        return queue
    gone = {f.stem.split("_")[0] for f in Path(raw_dir).glob("*.html")
            if f.stat().st_size < 5000 and "不繼續公開發行" in f.read_bytes().decode("utf-8", errors="replace")}
    return [x for x in queue if not str(x[2]).startswith("T56:") and x[2] not in gone]


# v3.96.6 owner 2026-10-12: 「這 5 組穩定的，做成每晚的賣壓／買進警示」 (research pairs) and v3.96.7 owner 2026-10-13:
# 「要，同時記錄到網頁正式版中」 (the 12 pairs found in both years, with the person). Everything computed from them goes
# to the ENCRYPTED part only. 2026-10-13: the pairs themselves are research conclusions from branch data, so they live
# in data/research/alert_pairs.json (not in git; this repo is public) - a build without that file has no alerts.
_PAIRS_FILE = ROOT / "data" / "research" / "alert_pairs.json"
_PAIRS = json.loads(_PAIRS_FILE.read_text(encoding="utf-8")) if _PAIRS_FILE.exists() else {}
ALERT_PAIRS = tuple(tuple(p) for p in _PAIRS.get("research", []))
TWO_YEAR_PAIRS = tuple(tuple(p) for p in _PAIRS.get("two_year", []))
A_LEVEL_PAIRS = tuple(tuple(p) for p in _PAIRS.get("a_level", []))   # v3.96.9: the market-cap >= 100 億 A-level watch list


def branch_alerts(password, days):
    """-> [{code, branch, side, tier, person, last_month, last_net, today, n, gap20, half1, half2}] or [] when the raw pages
    are absent. tier A級 (A_LEVEL_PAIRS, v3.96.9) first, then 兩年都找到 (TWO_YEAR_PAIRS, with the person), then 研究
    (ALERT_PAIRS); a stock x branch appears once."""
    from scripts import research_branches as RB
    from src.exports.transfer_watch import read_day
    from src.fetchers import stock_branch_ranking as S
    raw = ROOT / "data" / "insider_branch_raw"
    closes, index, _ = prices()
    out = []
    names = {c: (v or {}).get("name", "") for c, v in load_json(ROOT / "data" / "stock_history.json")["stocks"].items()}
    recent = days[-5:]
    nightly = {}
    for day in recent:
        d = read_day(ROOT / "data", day, password) or {}
        for b in d.get("branches") or []:
            for side in ("buys", "sells"):
                for x in b.get(side) or []:
                    if isinstance(x, dict):
                        nightly[(b.get("code"), x.get("code"), day)] = int(x.get("net_lot") or 0)
    pairs = [(c, b, n, s, "A級", who) for c, b, n, s, who in A_LEVEL_PAIRS]
    pairs += [(c, b, n, s, "兩年都找到", who) for c, b, n, s, who in TWO_YEAR_PAIRS] + [(c, b, n, s, "研究", "") for c, b, n, s in ALERT_PAIRS]
    seen, uniq = set(), []                       # v3.96.9: a stock x branch once, the strongest tier first
    for x in pairs:
        if (x[0], x[1].upper()) not in seen:
            seen.add((x[0], x[1].upper()))
            uniq.append(x)
    pairs = uniq
    # v3.96.13 owner 2026-10-14 「這區塊是可不可以點入查看」: each alert carries the branch's own record in the stock
    # (scripts/branch_pnl.py) and the one-day-late fair copy result (scripts/copy_trade.py, next open, recent year)
    from scripts import branch_pnl as BP
    rp = ROOT / "data" / "research"
    pnl_rec = {(q["code"], q["branch"]): q for q in (json.loads((rp / "branch_pnl.json").read_text(encoding="utf-8"))
                                                     if (rp / "branch_pnl.json").exists() else [])}
    ctj = json.loads((rp / "copy_trade_open.json").read_text(encoding="utf-8")) if (rp / "copy_trade_open.json").exists() else {}
    fair_rec = {(r["code"], r["branch"]): r for g_ in ("chosen", "not_chosen") for r in ((ctj.get("A") or {}).get(g_) or {}).get("per_pair", [])}
    for code, bno, name, side, tier, who in pairs:
        ser = {}
        for f in sorted(raw.glob(f"{code}_*.html")):
            p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {}
            ser[f.stem.rsplit("_", 1)[1]] = sum(int(r["net"] or 0) for r in (p.get("buys") or []) + (p.get("sells") or []) if r["bno"] == bno)
        if not ser:
            continue
        months = sorted(ser)
        act = [ym for ym in months if ser[ym] * side > 0]
        half = len(act) // 2
        base = RB.rets(code, months, 20, closes, index)
        g = lambda yms: round((statistics.mean(RB.rets(code, yms, 20, closes, index)) - statistics.mean(base)) * side, 1)             if base and RB.rets(code, yms, 20, closes, index) else None
        today = [{"day": d, "net": nightly[(bno, code, d)]} for d in recent if (bno, code, d) in nightly]
        if not today:                            # v3.96.13 the nightly watch rows (zco0) - the page said 「等每晚資料」 for most
            z = BP.rows_all(code, bno)
            cut = sorted(index)[-7] if len(index) >= 7 else ""
            today = [{"day": d, "net": z[d]} for d in sorted(z) if d >= cut and z[d]][-3:]
        rec = (pnl_rec.get((code, name)) or {}).get("all") or {}
        fm = (fair_rec.get((code, name)) or {}).get("matched") or {}
        out.append({"code": code, "name": names.get(code, ""), "branch": name, "side": "買" if side > 0 else "賣", "tier": tier,
                    "person": who, "last_month": months[-1],
                    "last_net": ser[months[-1]], "last_act": [act[-1], ser[act[-1]]] if act else None, "today": today, "n": len(RB.rets(code, act, 20, closes, index)),
                    "gap20": g(act), "half1": g(act[:half]), "half2": g(act[half:]),
                    "rec": [rec.get("n"), rec.get("win"), rec.get("ev")] if rec else None,
                    "fair": [fm.get("n"), fm.get("mean"), fm.get("beat")] if fm else None})
    return out


def fetch_state(since, until, built_pages, queue):
    """Is the person-level data of a window complete? built_pages = {ym: {code, ...}} from data/insider_people,
    queue = [[priority, ym, code]] of the running fetch (data/insider_people_queue.json, None if absent).
    -> (pending pages or None when the queue does not cover the window, fetching)."""
    months = month_list(since, until)
    missing = [m for m in months if m not in built_pages]
    if queue is None:
        return None, bool(missing)
    q_since = min((ym for p, ym, _ in queue if p > 0), default=None)   # priority 0 = control pages only
    if q_since is None or q_since > since:      # the queue was built for a later start: this window is not queued yet
        return None, True
    pending = sum(1 for _, ym, code in queue if since <= ym <= until and code not in built_pages.get(ym, ()))
    return pending, bool(pending or missing)


def person_detail(records):
    """The drawer's per-person table for one company-month (spec 5: 他人名義 joins the person).
    -> (people with any change, biggest market net first; number of people without a change)."""
    acc = {}
    for r in records:
        k = (r.get("role") or "", R.base_name(r.get("name")))
        a = acc.setdefault(k, {"role": k[0], "name": k[1], "kinds": [], **{f: 0 for f in DETAIL_FIELDS}})
        for f in DETAIL_FIELDS:
            a[f] += int(r.get(f) or 0)
        kind = r.get("kind") or "本人"
        moved_row = any(r.get(f) for f in DETAIL_FIELDS[:4])
        if moved_row:               # 2061 2026-07: an unchanged spouse row must not label 陳福得's own sale
            if kind not in a["kinds"]:
                a["kinds"].append(kind)
            # 7689 2026-08 (owner check): 本人 170,000 + 他人名義 增鐽電子 441,000 were shown as one 611,000 line
            # labelled only 他人名義; keep each official row so the drawer can show the split
            a.setdefault("parts", []).append({"kind": kind, "holder": r.get("holder") if kind != "本人" else "",
                                              **{f: int(r.get(f) or 0) for f in ("market_buy", "market_sell", "end_shares")}})
        if kind in ("本人", "之法人代表人", "利用他人名義持有者") and moved_row:
            a["self_moved"] = True
    for a in acc.values():          # only the spouse / children traded: say so, do not show it as the insider's own trade
        if "本人之配偶及未成年子女" in a["kinds"] and not a.pop("self_moved", False):
            a["name"] += "之配偶"
        a.pop("self_moved", None)
        if a["kinds"] == ["本人"]:  # the plain case needs no label
            a["kinds"] = []
        if len(a.get("parts", ())) < 2:
            a.pop("parts", None)
    moved = [a for a in acc.values() if any(a[f] for f in DETAIL_FIELDS[:4])]
    moved.sort(key=lambda a: -abs(a["market_buy"] - a["market_sell"]))
    return moved, len(acc) - len(moved)


def pano_cost(ins, months, until):
    """3.3 insider cost band: the weighted average price of the market buys in the last 12 months up to
    `until` (the latest published month). ins[ym] = {"buy_sh", "avg", ...}. None when nobody bought."""
    last = [m for m in months if m <= until][-12:]
    got = [(ins[m]["buy_sh"], ins[m]["avg"]) for m in last if m in ins and ins[m].get("avg") and ins[m]["buy_sh"] > 0]
    sh = sum(s for s, _ in got)
    return round(sum(s * p for s, p in got) / sh, 2) if sh else None


def pano_clusters(ins, months, min_people=3, span=3):
    """3.3 「N 人同買」: 3-month windows with >= 3 distinct people buying in the market (ppl rows
    [role, name, net_sh, other_sh]); the best first, never overlapping. -> [[first ym, last ym, n]]."""
    cand = []
    for i in range(len(months) - span + 1):
        names = {p[1] for m in months[i:i + span] for p in (ins.get(m) or {}).get("ppl", []) if p[2] > 0}
        if len(names) >= min_people:
            cand.append((len(names), i))
    out, used = [], set()
    for n, i in sorted(cand, key=lambda c: (-c[0], -c[1])):
        if used.isdisjoint(range(i, i + span)):
            used.update(range(i, i + span))
            out.append([months[i], months[i + span - 1], n])
    return sorted(out)


def split_private(doc, private_signals, private_backtest, private_notes):
    """-> (public doc, private doc). Nothing derived from the branch crawl may stay in the public one."""
    pub = {**doc, "signals": {k: v for k, v in doc["signals"].items() if k not in private_signals},
           "backtest": {k: v for k, v in doc["backtest"].items() if k not in private_backtest},
           "notes": [x for x in doc["notes"] if x not in private_notes]}
    priv = {"generated_at": doc["generated_at"], "signals": private_signals, "backtest": private_backtest,
            "notes": list(private_notes)}
    return pub, priv


def write_private(path, priv, password):
    """Encrypted envelope (same as daily_summary.json). Rewritten on every run (new salt): reading the
    old file back would make this script a day-file decryptor under tests/test_v3803_quarantine.py."""
    from src.pipelines.crawler_output import encrypt_data, PBKDF2_ITERATIONS
    plaintext = json.dumps(priv, ensure_ascii=False, sort_keys=True)
    env = {"encrypted": True, "algorithm": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iterations": PBKDF2_ITERATIONS,
           "generated_at": priv["generated_at"], "data": encrypt_data(plaintext, password)}
    Path(path).write_text(json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def prices():
    closes, index, avg = defaultdict(dict), {}, {}
    for f in sorted((ROOT / "data" / "price_history").glob("*.json")):
        d = load_json(f)
        index.update(d["taiex"])
        for code, v in d["close"].items():
            closes[code].update(v)
            if v:
                avg[(code, d["month"])] = statistics.mean(v.values())
    sh = load_json(ROOT / "data" / "stock_history.json")      # the last 60 days, for the newest signals
    for day, m in sh["market"].items():
        index.setdefault(day, m["index"])
    for code, s in sh["stocks"].items():
        for day, row in (s.get("daily") or {}).items():
            if row.get("close"):
                closes[code].setdefault(day, row["close"])
    return closes, index, avg


def branch_net(codes, password):
    """{(code, day): net amount of all tracked branches} from the stored daily crawls."""
    from src.exports.transfer_watch import read_day
    days = sorted({p.name[:8] for p in (ROOT / "data").glob("2026????.json")} |
                  {p.name[:8] for p in (ROOT / "data" / "archive").glob("2026????.json*")})
    out = defaultdict(int)
    for day in days:
        d = read_day(ROOT / "data", day, password) or {}
        for b in d.get("branches") or []:
            for side in ("buys", "sells"):
                for s in b.get(side) or []:
                    if isinstance(s, dict) and s.get("code") in codes:
                        out[(s["code"], day)] += int(s.get("net_amt") or 0)
    return out, days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=min(w[2] for w in WINDOWS), help="first month loaded (default: the oldest window)")
    ap.add_argument("--out", default=str(ROOT / "data" / "insider_radar.json"))
    a = ap.parse_args()
    monthly = {f.stem: load_json(f) for f in sorted((ROOT / "data" / "insider_monthly").glob("*.json"))}
    trades, other = [], defaultdict(int)
    raw = defaultdict(list)            # (code, ym) -> the person rows, for the drawer's detail table
    built, n_pages, n_ctrl, n_people = {}, defaultdict(int), defaultdict(int), defaultdict(int)   # per month, for each window's scope
    for f in sorted((ROOT / "data" / "insider_people").glob("*.json")):
        m = load_json(f)
        if m["ym"] < a.since:
            continue
        built[m["ym"]] = set(m["pages"])
        n_pages[m["ym"]] = len(m["pages"])
        n_ctrl[m["ym"]] = sum(1 for p in m["pages"].values() if p == 0)
        n_people[m["ym"]] = len(m["people"])
        for r in m["people"]:
            trades.append({**r, "delta_shares": r["market_buy"] - r["market_sell"], "declared_on": None})
            other[(r["code"], r["ym"])] += r["other_buy"] - r["other_sell"]
            raw[(r["code"], r["ym"])].append(r)
    qf = ROOT / "data" / "insider_people_queue.json"
    queue = open_queue(load_json(qf) if qf.exists() else None, ROOT / "data" / "insider_q61_raw")
    # v3.96.2 the 1-year 「第一次大買」 look-back starts at the first month of person-level data, not at a window
    # start: the latest window, plus each older window once its fetch has finished. A partly fetched year does
    # not count (2024-10..2025-08 holds 101 sample pages tonight; counting them made A 57 -> 168, most of them
    # "first big buys" only because the earlier buys were not fetched yet).
    data_start = WINDOWS[0][2]
    for _, _, since, until in WINDOWS[1:]:
        if fetch_state(since, until, built, queue)[1]:
            break
        data_start = since
    closes, index, avg = prices()
    tdays = sorted(index)
    have = {d[:6] for d in tdays}
    issued = {}
    for ym in sorted(monthly):
        for code, c in monthly[ym]["companies"].items():
            issued[code] = c["issued"]
    rows = list(R.company_months(R.merge_people(trades), avg, issued).values())
    short = {k: v.get("name") for k, v in load_json(ROOT / "data" / "stock_history.json")["stocks"].items()}
    for r in rows:
        c = monthly.get(r["ym"], {}).get("companies", {}).get(r["code"], {})
        pub = monthly.get(r["ym"], {}).get("published", {}).get(c.get("market", "sii"))
        nxt = next_ym(r["ym"])   # the publish month needs stored prices, else the signal day would slide
        r.update(name=short.get(r["code"]) or re.sub(r"(股份有限公司|股份有限|股份有|股份)$", "", c.get("name") or ""), market=c.get("market"), published=pub,   # IRB110 cuts names at 8 characters
                 other_net_shares=other[(r["code"], r["ym"])],
                 signal_day=R.signal_day(r["ym"], pub, tdays) if nxt in have else None)
    sig_a = R.big_buys_a(rows, years=1, data_start=data_start)
    sells = [r for r in rows if r["net_shares"] < 0 and ((r["net_yi_est"] or 0) <= SELL_YI or (r["pct_of_shares"] or 0) <= SELL_PCT)]
    notes = ["推算金額＝集中市場淨股數 × 當月平均收盤價", "超額報酬以加權指數計（上櫃股暫未改用櫃買指數）",
             f"「1 年來第一次大買」要回看滿 1 年，資料從 {data_start} 起，滿 1 年前的月份不判斷"]
    pw = os.environ.get("CHIP_RADAR_PASSWORD")
    sig_b, a_cov, bdays, priv_notes, br10 = [], [], [], [], {}
    # v3.96.3 3.3 個股全景圖: a compact monthly series for every stock that appears in a window
    pano_codes = sorted({s["code"] for w in WINDOWS for s in in_window(sig_a + sells, w[2], w[3])})
    bn = {}
    if pw:
        bn, bdays = branch_net({s["code"] for s in sig_a} | set(pano_codes), pw)
        first_ok = tdays[tdays.index(bdays[0]) + 10] if bdays and bdays[0] in tdays else None
        a_cov = [s for s in sig_a if first_ok and s["signal_day"] and s["signal_day"] >= first_ok]
        sig_b = R.group_b(a_cov, bn, 10, tdays)
        # v3.96.4 the drawer's 分點大戶 cell: our masters' net in the 10 trading days before every covered signal
        # (buys and sells; B only keeps the positive buys) -> encrypted part only
        for s in sig_a + sells:
            d0 = s.get("signal_day")
            if first_ok and d0 and d0 >= first_ok and d0 in tdays:
                i0 = tdays.index(d0)
                br10[f"{s['code']}:{s['ym']}"] = round(sum(bn.get((s['code'], d), 0) for d in tdays[max(0, i0 - 10):i0]) / 1e5, 4)
        priv_notes.append(f"分點大戶資料 {bdays[0]}～{bdays[-1]}（{len(bdays)} 天）；B 只和同期間的 A（A_cov）比")
        notes.extend(priv_notes)
    else:
        notes.append("沒有提供密碼，對照組 B 未計算")
    split = R.signal_day(f"{int(IN_SAMPLE_UNTIL[:4])}{int(IN_SAMPLE_UNTIL[4:]) + 1:02d}",
                         monthly.get("202605", {}).get("published", {}).get("sii"), tdays)
    rets = {(x["code"], x["ym"]): x for x in R.event_returns(sig_a + sells, closes, index)}

    # layers (spec 5: results only count when they hold per layer); owner 2026-10-11: 大股東買進 on its own
    def role_group(s):
        r = (s["buyers"] if s["net_shares"] > 0 else s["sellers"]).split(" 等 ")[0]
        return ("大股東" if "大股東" in r else "董事長" if "董事長" in r else
                "董事監察人" if any(k in r for k in ("董事", "監察人")) else "經理人")

    def amount_band(s):
        v = abs(s["net_yi_est"] or 0)
        return "10 億以上" if v >= 10 else "1–10 億" if v >= 1 else "1 億以下"

    def cap_band(s):
        cap = (issued.get(s["code"]) or 0) * (s["avg_price"] or 0) / 1e8
        return "大型 500 億以上" if cap >= 500 else "中型 100–500 億" if cap >= 100 else "小型 100 億以下"
    def backtest(sa, sc, sb, ss):
        """One window's backtest: A / A_cov / B / sells, and the layers of A and of the sells."""
        bt = {k: R.summarize(R.event_returns(v, closes, index), split_day=split)
              for k, v in (("A", sa), ("A_cov", sc), ("B", sb), ("sells", ss))}
        for key, sigs in (("layers_A", sa), ("layers_sells", ss)):   # v3.96.1 sells too (the drawer's layer line)
            layers = {}
            for name, fn in (("身分", role_group), ("金額", amount_band), ("市值", cap_band)):
                groups = defaultdict(list)
                for x in sigs:
                    groups[fn(x)].append(x)
                layers[name] = {g: R.summarize(R.event_returns(v, closes, index), split_day=split) for g, v in groups.items()}
            bt[key] = layers
        return bt

    def headline(s):
        """2.5 one line per stock (owner: labels = role + 買/賣; amounts are estimates)."""
        buy = s["net_shares"] > 0
        who = (s["buyers"] if buy else s["sellers"]).split(" 等 ")[0].replace("(他人名義)", "")
        amt = abs(s["net_yi_est"] or 0)
        amt_s = f"{amt:.1f} 億" if amt >= 1 else f"{amt * 1e4:,.0f} 萬"
        br = s.get("branch_net_10d")
        tail = "" if br is None else ("，分點大戶同向" if (br > 0) == buy else "，分點大戶反向")
        return (f"{who}{'買' if buy else '賣'} {amt_s}（股本 {abs(s['pct_of_shares'] or 0):.2f}%），"
                f"均 {s['avg_price']:.0f}（推算）{tail}" if s.get("avg_price") else f"{who}{'買' if buy else '賣'}")

    def pack(v):
        out = []
        for s in sorted(v, key=lambda s: (s["signal_day"] or "", s["code"]), reverse=True):
            buy = s["net_shares"] > 0
            moved, quiet = person_detail(raw[(s["code"], s["ym"])])
            out.append({**s, "headline": headline(s), **{k: rets.get((s["code"], s["ym"]), {}).get(k) for k in tuple(f"{k}{h}" for k in ("ex", "r", "n") for h in R.HORIZONS)},
                        "side": "buy" if buy else "sell",          # v3.96.1 the page label = role + 買 / 賣
                        "role": (s["buyers"] if buy else s["sellers"]).split(" 等 ")[0].replace("(他人名義)", ""),
                        "role_group": role_group(s), "detail": moved, "quiet": quiet})
        return out
    # v3.96.2 one block per year window (signals by their ym); the scope says whether the window's
    # person-level data is still being fetched, so the page does not show an empty window as a result
    years, priv_years = [], []
    for key, label, since, until in WINDOWS:
        sa, sc, sb, ss = (in_window(v, since, until) for v in (sig_a, a_cov, sig_b, sells))
        bt = backtest(sa, sc, sb, ss)
        ms = month_list(since, until)
        pending, fetching = fetch_state(since, until, built, queue)
        scope = {"since": since, "until": until, "data_start": data_start, "split_day": split,
                 "pages": sum(n_pages[m] for m in ms), "control_pages": sum(n_ctrl[m] for m in ms),
                 "people_rows": sum(n_people[m] for m in ms), "company_months": len(in_window(rows, since, until)),
                 "months": len(ms), "months_with_data": sum(1 for m in ms if m in built),
                 "pending_pages": pending, "fetching": fetching,
                 "price_gap": [m for m in ms if next_ym(m) not in have]}   # months whose signal day cannot be dated yet
        years.append({"key": key, "label": label, "since": since, "until": until, "signals": {"A": pack(sa)}, "sells": pack(ss),
                      "backtest": {k: v for k, v in bt.items() if k != "B"}, "scope": scope})
        priv_years.append({"key": key, "signals": {"B": pack(sb)}, "backtest": {"B": bt["B"]}})
    y0, p0 = years[0], priv_years[0]   # the latest window also stays in the top-level fields (old readers)
    doc = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "scope": y0["scope"], "notes": notes,
           "signals": {"A": y0["signals"]["A"], "B": p0["signals"]["B"]}, "sells": y0["sells"],
           "backtest": {**y0["backtest"], "B": p0["backtest"]["B"]}, "years": years}
    # v3.96.1 split: B (our branch masters) goes into the encrypted file only
    pub, priv = split_private(doc, {"B": p0["signals"]["B"]}, {"B": p0["backtest"]["B"]}, priv_notes)
    priv["years"] = priv_years
    # v3.96.3 3.3 個股全景圖 (spec 4 item 3.3, docs/diagrams/insider_radar/panorama_v3_draft.html): per stock the
    # monthly close, the insider months (company net / other-reason net / people, in shares; the page
    # multiplies by the month's average price), the cost band, 「N 人同買」 and the TDCC 1000-lot %.
    # Our branch masters' monthly net goes into the encrypted part only.
    latest = tdays[-1][:6] if tdays else data_start
    first_px = tdays[0][:6] if tdays else data_start
    pm = month_list(first_px, latest)[-26:]
    pmset = set(pm)
    max_pub = max((ym for ym, mo in monthly.items() if mo.get("published")), default=None)
    rows_by = {(r["code"], r["ym"]): r for r in rows}
    tdcc = defaultdict(list)
    for f in sorted((ROOT / "data" / "tdcc_history").glob("*.json")):
        t = load_json(f)
        for code in pano_codes:
            h = (t.get("holdings") or {}).get(code)
            if h and h.get("mega1000_pct") is not None:
                tdcc[code].append([t.get("effective_date") or f.stem, h["mega1000_pct"]])
    # v3.96.11 owner 2026-10-14 (toalpha 申報資料 page): 36 months of 董監持股比 = IRB110 dir_pct (all directors' and
    # supervisors' holdings / issued shares) and 質押比 = pledged shares on the directors' own person-page rows /
    # IRB110 dir_held; a month without a person page of that company = None (not guessed)
    pano_set = set(pano_codes)
    pledged = defaultdict(dict)
    for f in sorted((ROOT / "data" / "insider_people").glob("2*.json")):
        pdoc = load_json(f)
        acc = defaultdict(int)
        for r in pdoc["people"]:
            if r["code"] in pano_set and r["kind"] == "本人" and ("董事" in r["role"] or "監察" in r["role"]):
                acc[r["code"]] += r.get("pledge_shares") or 0
        for c in set(pdoc.get("pages") or {}) & pano_set:
            pledged[c][pdoc["ym"]] = acc.get(c, 0)
    dirs = defaultdict(list)
    for ym in sorted(monthly)[-36:]:
        comp = monthly[ym].get("companies") or {}
        for code in pano_codes:
            x = comp.get(code)
            if x and x.get("dir_pct") is not None:
                pl = pledged[code].get(ym)
                dirs[code].append([ym, x["dir_pct"], round(pl / x["dir_held"] * 100, 1) if pl is not None and x.get("dir_held") else None])
    stocks = {}
    for code in pano_codes:
        mc = {}
        for day, v in closes.get(code, {}).items():
            if day[:6] in pmset and (day[:6] not in mc or day > mc[day[:6]][0]):
                mc[day[:6]] = (day, v)
        ins = {}
        for ym in pm:
            moved, _ = person_detail(raw.get((code, ym), []))
            if not moved:
                continue
            net = sum(p["market_buy"] - p["market_sell"] for p in moved)
            r0 = rows_by.get((code, ym), {})
            ins[ym] = {"net_sh": net, "oth_sh": sum(p["other_buy"] - p["other_sell"] for p in moved),
                       "buy_sh": sum(p["market_buy"] for p in moved),
                       "avg": round(avg[(code, ym)], 2) if avg.get((code, ym)) else None,
                       "role": ((r0.get("buyers") if net > 0 else r0.get("sellers")) or "").split(" 等 ")[0].replace("(他人名義)", ""),
                       "ppl": [[p["role"], p["name"], p["market_buy"] - p["market_sell"], p["other_buy"] - p["other_sell"]] for p in moved]}
        stocks[code] = {"close": [mc[m][1] if m in mc else None for m in pm], "ins": ins,
                        "cost": pano_cost(ins, pm, max_pub or latest),
                        "clusters": pano_clusters(ins, [m for m in pm if m <= (max_pub or latest)]), "tdcc": tdcc.get(code, []),
                        "dirs": dirs.get(code, [])}
    pub["pano"] = {"months": pm, "published_until": max_pub, "stocks": stocks}
    pub["data_until"] = max_pub      # v3.96.4 the 「檢查更新」 line: 資料到 YYYY-MM；下一次約 MM/20 公告
    if pw:
        priv["br10"] = br10              # {code:ym: 億}, from the first covered day on
    if pw and bdays:
        bm = defaultdict(lambda: defaultdict(int))
        for (code, day), v in bn.items():
            if code in stocks and day[:6] in pmset:
                bm[code][day[:6]] += v
        priv["pano"] = {"from": bdays[0], "until": bdays[-1],   # net_amt is in 仟元 -> 億
                        "stocks": {c: {m: round(v / 1e5, 3) for m, v in sorted(ms.items())} for c, ms in bm.items()}}
    if pw:
        priv["alerts"] = branch_alerts(pw, bdays or [])
        # v3.96.9 owner 2026-10-14: the stock of the day (scripts/insider_dossier.py), newest file; private like the pairs
        dz = sorted((ROOT / "data" / "research" / "dossier").glob("*_2*.json"), key=lambda f: f.stat().st_mtime)   # the newest written
        if dz:
            priv["dossier"] = json.loads(dz[-1].read_text(encoding="utf-8"))
        # v3.96.11 owner 2026-10-14: 「人對應分點的重點!要列在哪?」 - every matched insider -> branch with 12 months of
        # declared vs branch lots (scripts/build_who_branch.py); private like the pairs
        wb = ROOT / "data" / "research" / "who_branch.json"
        if wb.exists():
            priv["who_branch"] = json.loads(wb.read_text(encoding="utf-8")).get("stocks", {})
        # v3.96.13 owner 2026-10-14: 「累積的實績就是去複製…從0至1」「在隔天開盤就買」「可以設計下拉選單就是收盤前買或者盤中
        # 1100點買」 - the copy test by entry price (scripts/copy_trade.py) and the paper record (scripts/copy_forward.py)
        cp = {}
        for mode, fn in (("open", "copy_trade_open.json"), ("avg", "copy_trade_avg.json"), ("close", "copy_trade.json")):
            f = ROOT / "data" / "research" / fn
            if f.exists():
                ct = json.loads(f.read_text(encoding="utf-8"))
                cp[mode] = {t: {"pass": ct[t]["pass"],
                                **{g: {"pairs": ct[t][g]["pairs"], "m": ct[t][g].get("matched"), "fx": ct[t][g].get("matched_fixed"),
                                       "top": [[r["code"], r["who"], r["branch"], (r["matched"] or {}).get("n"), (r["matched"] or {}).get("beat"),
                                                (r["matched"] or {}).get("mean")] for r in ct[t][g]["per_pair"]
                                               if (r.get("matched") or {}).get("n", 0) >= 5][:5] if g == "chosen" else []}
                                   for g in ("chosen", "not_chosen")}} for t in ("A", "B")}
        fz = sorted((ROOT / "data" / "research" / "copy_forward").glob("2*.json"))
        if fz:
            fw = json.loads(fz[-1].read_text(encoding="utf-8"))
            cp["forward"] = {"day": fw["day"], "start": fw["start"], "pairs": fw["chosen_pairs"], "record": fw["record"],
                             "verdict": fw["verdict"],
                             "signals": [[s["code"], s["who"], s["branch"], s["lots"], s["amt"]] for s in fw["signals"][:10]]}
        if cp:
            priv["copy"] = cp
    priv_path = Path(a.out).with_name(PRIVATE_NAME)
    if pw:
        pub["private"] = PRIVATE_NAME       # the page fetches the encrypted part only when it exists
        write_private(priv_path, priv, pw)
        print(f"[radar] private part (encrypted) -> {priv_path.name}")
    Path(a.out).write_text(json.dumps(pub, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")   # compact: the page downloads it (704 KB indented -> 344 KB)
    print(f"[radar] data from {data_start}, people rows {len(trades)}, company-months {len(rows)}, all A {len(sig_a)}, "
          f"A_cov {len(a_cov)}, B {len(sig_b)}, sells {len(sells)}, split {split}")
    for y, p in zip(years, priv_years):
        sc = y["scope"]
        print(f"  {y['key']} {y['label']} {y['since']}-{y['until']}: A {len(y['signals']['A'])}, sells {len(y['sells'])}, "
              f"B {len(p['signals']['B'])} | pages {sc['pages']}, company-months {sc['company_months']}, months {sc['months_with_data']}/{sc['months']}, "
              f"pending {sc['pending_pages']}, fetching {sc['fetching']}" + (f", price gap {sc['price_gap']}" if sc["price_gap"] else ""))
        for name, groups in y["backtest"]["layers_A"].items():
            print(f"     A by {name}: " + "; ".join(f"{g} n={v['all']['n']} ex20={v['all']['ex20']['mean']}" for g, v in groups.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
