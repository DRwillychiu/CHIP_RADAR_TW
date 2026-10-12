"""v3.96.0 insider radar 5.1: link each signal-size insider trade (company-month) to that stock's top
15 buying / selling branches over the same month, and tag the geographic ones (spec section 9).
Owner 2026-10-11: 「今天發現有內部人的進出動作，可以去連到對應的分點變化，同時去觀察這分點到底是不是地緣分點」.

Source: Fubon DJ per-stock branch page with a date range (verified 2026-10-11 on 2515 2025-10: the
page shows 2025/10/1 - 2025/10/31 and its top buyer 統一-仁愛 +105,877 lots matches the > 10 %
holder's 101,683,000-share buy). Only signal stocks are queried (MoneyDJ terms: no whole-market crawl).
Raw pages: data/insider_branch_raw/ and the links file are third-party branch data - not in git.

Events: from data/insider_people, a company-month whose person-level market net is >= 0.2 % of the
shares or >= 1 億 (buy or sell). Geography: data/branch_geo.json (six municipalities for now):
same_dist = same city and district as the company, same_city = same city only.
Polite: one thread, >= 5 s between requests, stop at 403 / 429 / 5xx; cached pages are never refetched.
    python scripts/fetch_insider_branches.py --max-requests 200
"""
import argparse
import calendar
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.core.fubon_codec import decode_fubon  # noqa: E402
from src.core.fubon_pacing import FUBON_MIN_GAP_S, note_request  # noqa: E402  (every Fubon request is measured)
from src.fetchers import stock_branch_ranking as S  # noqa: E402

URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}&e={y}-{m}-1&f={y}-{m}-{last}"
RAW = ROOT / "data" / "insider_branch_raw"
OUT = ROOT / "data" / "insider_branch_links.json"
GAP_S, PCT, YI = max(5.0, FUBON_MIN_GAP_S), 0.2, 1.0


def events():
    issued, px = {}, {}
    for f in sorted((ROOT / "data" / "insider_monthly").glob("*.json")):
        for c, r in json.loads(f.read_text(encoding="utf-8"))["companies"].items():
            issued[(c, f.stem)] = r["issued"]
    for f in sorted((ROOT / "data" / "price_history").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for c, v in d["close"].items():
            if v:
                px[(c, d["month"])] = statistics.mean(v.values())
    out = []
    for f in sorted((ROOT / "data" / "insider_people").glob("*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        net = {}
        for r in m["people"]:
            net[r["code"]] = net.get(r["code"], 0) + r["market_buy"] - r["market_sell"]
        for c, n in net.items():
            iss, p = issued.get((c, m["ym"])) or 0, px.get((c, m["ym"]))
            if n and ((iss and abs(n) / iss * 100 >= PCT) or (p and abs(n) * p >= YI * 1e8)):
                out.append({"code": c, "ym": m["ym"], "net_shares": n})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=50)
    ap.add_argument("--candidates", action="store_true",
                    help="5.3b level 2: every month 2025-09..2026-08 of the stocks with a repeat carrier branch")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    geo = json.loads((ROOT / "data" / "branch_geo.json").read_text(encoding="utf-8"))
    ev = events()
    if a.candidates:     # also the months WITHOUT insider trades: a true insider branch is quiet there
        from scripts.backfill_prices import months
        stats = json.loads((ROOT / "data" / "insider_branch_stats.json").read_text(encoding="utf-8"))
        codes = sorted({x["code"] for x in stats["repeat_branches"]})
        have = {(e["code"], e["ym"]) for e in ev}
        ev = ev + [{"code": c, "ym": ym, "net_shares": 0} for c in codes for ym in months("202509", "202608")
                   if (c, ym) not in have]
    todo = [e for e in ev if not (RAW / f"{e['code']}_{e['ym']}.html").exists()]
    print(f"[branches] {time.strftime('%H:%M:%S')} events {len(ev)}, cached {len(ev) - len(todo)}, to fetch {len(todo)}", flush=True)
    s, n, last = S._get_session(), 0, 0.0
    for e in todo:
        if n >= a.max_requests:
            print(f"[branches] max requests {a.max_requests} reached; rerun resumes", flush=True)
            break
        y, m = int(e["ym"][:4]), int(e["ym"][4:])
        wait = GAP_S - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        n += 1
        note_request()
        try:
            r = s.get(URL.format(code=e["code"], y=y, m=m, last=calendar.monthrange(y, m)[1]), timeout=20)
        except requests.RequestException as x:   # 2026-10-12 15:12 a read timeout ended the run: cool down, try once more
            print(f"[branches] {time.strftime('%H:%M:%S')} {type(x).__name__} at {e['code']} {e['ym']} - cooling down 5 min", flush=True)
            time.sleep(300)
            note_request()
            try:
                r = s.get(URL.format(code=e["code"], y=y, m=m, last=calendar.monthrange(y, m)[1]), timeout=20)
            except requests.RequestException as x2:
                print(f"[branches] stopped: {type(x2).__name__} twice at {e['code']} {e['ym']}", flush=True)
                break
        last = time.monotonic()
        if r.status_code in (403, 429) or r.status_code >= 500:
            print(f"[branches] stopped: HTTP {r.status_code} at {e['code']} {e['ym']}", flush=True)
            break
        t = decode_fubon(r.content)
        if f"{y}/{m}/1" not in t:            # the range was not applied: never store a wrong period
            print(f"[branches] stopped: {e['code']} {e['ym']} page does not show the month range", flush=True)
            break
        (RAW / f"{e['code']}_{e['ym']}.html").write_text(t, encoding="utf-8")
    links = {}
    for e in [e for e in ev if e["net_shares"]]:
        f = RAW / f"{e['code']}_{e['ym']}.html"
        p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), e["code"]) if f.exists() else None
        if not p:
            continue
        home = geo["companies"].get(e["code"]) or {}

        def tag(b):
            g = geo["branches"].get(b["bno"]) or {}
            same_city = bool(home.get("city")) and g.get("city") == home.get("city")
            return {**b, "city": g.get("city"), "dist": g.get("dist"), "same_city": same_city,
                    "same_dist": same_city and bool(home.get("dist")) and g.get("dist") == home.get("dist")}
        links[f"{e['code']}_{e['ym']}"] = {**e, "home": home, "buys": [tag(b) for b in p["buys"]],
                                           "sells": [tag(b) for b in p["sells"]]}
    OUT.write_text(json.dumps(links, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[branches] {time.strftime('%H:%M:%S')} requests {n}, linked {len(links)}/{len(ev)} events -> {OUT.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
