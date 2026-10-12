"""v3.96.5 spec section 10: one stock's main-force profile (owner 2026-10-12: 「今天搜尋2059川湖，我要立即知道董事長是
(林聰吉)、他的分點是(第一金-路竹)，他的買賣超狀況是?操作手法?勝率?期望值?短中長線來看分別?」). Test case 2059.

  1 who:     chairman and every insider with holdings - TWSE OpenAPI t187ap03_L / t187ap11_L (data/research/roster/)
  2 trades:  insiders' monthly change from the IRB110 summary (data/insider_monthly) + per-person pages if fetched
  3 branches: Fubon per-stock page per month 2023-09..2026-08 (data/insider_branch_raw/, fetched here if missing;
             only the stock asked for - MoneyDJ terms)
  4 each top branch: monthly net, months net buy / net sell, cumulative lots, local (same district) or not
  5 follow:  a month the branch net-bought -> buy at the close of the first trading day after that month;
             5 / 20 / 60 trading days (short / mid / long), after costs 0.585 %: n, hit rate, mean (= expectancy)
  6 style:   from the monthly pattern only (day trading / next-day flips need daily data - said so)
Evidence level of "the chairman's branch": A timing match (needs insider trades) / B owner label / C local and
long-term dominant / D none. Output: data/research/profile_<code>.md (branch data is private, not in git).
    python scripts/stock_profile.py --code 2059 [--owner-branch 第一金-路竹] [--max-requests 40]
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

from scripts.backfill_prices import months  # noqa: E402
from scripts.run_insider_radar import prices  # noqa: E402
from src.analyzers.insider_radar import COST_PCT  # noqa: E402
from src.core.fubon_codec import decode_fubon  # noqa: E402
from src.core.fubon_pacing import FUBON_MIN_GAP_S, note_request  # noqa: E402
from src.fetchers import stock_branch_ranking as S  # noqa: E402

URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}&e={y}-{m}-1&f={y}-{m}-{last}"
RAW = ROOT / "data" / "insider_branch_raw"
OUT = ROOT / "data" / "research"
GAP_S, SPAN, HS = max(5.0, FUBON_MIN_GAP_S), ("202309", "202608"), (5, 20, 60)


def roster(code):
    d = ROOT / "data" / "research" / "roster"
    base = next((x for x in json.loads((d / "t187ap03_L.json").read_text(encoding="utf-8")) if x.get("公司代號") == code), {})
    raw = (d / "t187ap11_L.json").read_bytes().decode("utf-8", "ignore")
    try:
        rows = json.loads(raw)
    except ValueError:                       # the API cut the download off (2026-10-12): keep the complete rows
        rows = json.loads(raw[:raw.rfind("},") + 1] + "]")
    return base, [x for x in rows if x.get("公司代號") == code]


def fetch_pages(code, max_requests):
    s, last, n = S._get_session(), 0.0, 0
    for ym in months(*SPAN):
        f = RAW / f"{code}_{ym}.html"
        if f.exists() or n >= max_requests:
            continue
        y, m = int(ym[:4]), int(ym[4:])
        wait = GAP_S - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        n += 1
        note_request()
        try:
            r = s.get(URL.format(code=code, y=y, m=m, last=calendar.monthrange(y, m)[1]), timeout=20)
        except requests.RequestException as x:
            print(f"[profile] stopped: {type(x).__name__} at {ym}", flush=True)
            break
        last = time.monotonic()
        if r.status_code in (403, 429) or r.status_code >= 500:
            print(f"[profile] stopped: HTTP {r.status_code} at {ym}", flush=True)
            break
        t = decode_fubon(r.content)
        if f"{y}/{m}/1" not in t:
            print(f"[profile] stopped: {ym} page does not show the month range", flush=True)
            break
        f.write_text(t, encoding="utf-8")
    return n


def follow(code, buy_months, closes, index):
    """Entry: close of the first trading day after each buy month; -> {h: (n, hit %, mean %)} after costs."""
    c, days = closes.get(code, {}), sorted(index)
    out = {}
    for h in HS:
        rs = []
        for ym in buy_months:
            y, m = int(ym[:4]), int(ym[4:])
            want = f"{y + (m == 12):04d}{m % 12 + 1:02d}"
            nxt = [d for d in days if d[:6] > ym]
            if not nxt or nxt[0][:6] != want or nxt[0] not in c:   # no price for that month: not counted (was: jumped to 2024-10)
                continue
            i = days.index(nxt[0])
            if i + h < len(days) and days[i + h] in c:
                rs.append((c[days[i + h]] / c[nxt[0]] - 1) * 100 - COST_PCT)
        out[h] = (len(rs), round(sum(r > 0 for r in rs) / len(rs) * 100) if rs else None,
                  round(statistics.mean(rs), 2) if rs else None)
    return out


def style(series):
    b = sum(1 for v in series.values() if v > 0)
    s = sum(1 for v in series.values() if v < 0)
    tot = sum(series.values())
    if b >= 3 and s <= b // 3 and tot > 0:
        return "囤貨（多數月份淨買、很少賣）"
    if s >= 3 and b <= s // 3 and tot < 0:
        return "出貨（多數月份淨賣）"
    if b >= 2 and s >= 2:
        return "波段（買賣月份交替）"
    return "偶爾進出（月份太少，看不出手法）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--owner-branch", default="", help="the owner's label for the chairman's branch (evidence B)")
    ap.add_argument("--max-requests", type=int, default=40)
    a = ap.parse_args()
    base, people = roster(a.code)
    n = fetch_pages(a.code, a.max_requests)
    pages = {}
    for ym in months(*SPAN):
        f = RAW / f"{a.code}_{ym}.html"
        if f.exists():
            pages[ym] = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), a.code) or {"buys": [], "sells": []}
    br = {}
    for ym, p in pages.items():
        for r in p["buys"] + p["sells"]:
            b = br.setdefault(r["bno"], {"name": r["name"], "series": {}})
            b["series"][ym] = b["series"].get(ym, 0) + int(r["net"] or 0)
    geo = json.loads((ROOT / "data" / "branch_geo.json").read_text(encoding="utf-8"))
    home = geo["companies"].get(a.code) or {}
    closes, index, _ = prices()
    ins = {}
    for f in sorted((ROOT / "data" / "insider_monthly").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))["companies"].get(a.code)
        if r and (r["dir_inc"] or r["dir_dec"]):
            ins[f.stem] = (r["dir_inc"], r["dir_dec"])
    ranked = sorted(br.items(), key=lambda kv: -sum(abs(v) for v in kv[1]["series"].values()))[:8]
    L = [f"# {a.code} {base.get('公司簡稱', '')} 主力檔案（{time.strftime('%Y-%m-%d %H:%M')}，dev 試做）", "",
         f"- 董事長：{base.get('董事長', '—')}；總經理：{base.get('總經理', '—')}；公司地址：{base.get('住址', '—')}",
         f"- 分點資料：{len(pages)} 個月（{SPAN[0]}～{SPAN[1]}），本次請求 {n} 次；股價只有 2024-10 起，之前的月份不算報酬", "",
         "## 1. 內部人與持股（證交所公開資料）", "", "| 身分 | 姓名 | 目前持股（股） | 關係人持股 |", "|---|---|---:|---:|"]
    L += [f"| {x['職稱']} | {x['姓名']} | {int(x['目前持股']):,} | {int(x['內部人關係人目前持股合計'] or 0):,} |" for x in people]
    L += ["", "## 2. 董監每月持股增減（彙總表，含所有原因，股）", ""]
    L += [f"- {ym[:4]}-{ym[4:]}：增 {i:,}、減 {d:,}" for ym, (i, d) in sorted(ins.items())] or ["- 這段期間沒有變動"]
    L += ["", "## 3. 這檔股票的主要分點（依 36 個月買賣量排序，張）", "",
          "| 分點 | 地緣 | 淨買月 | 淨賣月 | 累計淨買 | 手法（月資料） | 跟單 5 日 | 20 日 | 60 日 |", "|---|---|---:|---:|---:|---|---|---|---|"]
    base_fw = follow(a.code, [ym for ym in months(*SPAN)], closes, index)   # any month: the stock's own drift
    cell = lambda t: "—" if not t[0] else (f"{t[0]} 件 樣本不足" if t[0] < 10 else f"{t[0]} 件 勝率 {t[1]}% 平均 {t[2]:+.2f}%")
    L.append(f"| **基準：任一個月都進場** | | | | | | {cell(base_fw[5])} | {cell(base_fw[20])} | {cell(base_fw[60])} |")
    own_name = a.owner_branch
    if own_name and all(b["name"] != own_name for _, b in ranked):
        ranked = ranked + [kv for kv in br.items() if kv[1]["name"] == own_name]
    for bno, b in ranked:
        g = geo["branches"].get(bno) or {}
        local = "同區" if home.get("dist") and g.get("dist") == home.get("dist") else ("同市" if home.get("city") and g.get("city") == home.get("city") else "")
        buy_m = [ym for ym, v in b["series"].items() if v > 0]
        fw = follow(a.code, buy_m, closes, index)
        L.append(f"| {b['name']}{'（負責人標註）' if b['name'] == own_name else ''} | {local} | {len(buy_m)} | {sum(1 for v in b['series'].values() if v < 0)} | "
                 f"{sum(b['series'].values()):,} | {style(b['series'])} | {cell(fw[5])} | {cell(fw[20])} | {cell(fw[60])} |")
    own = next(((bno, b) for bno, b in br.items() if a.owner_branch and b["name"] == a.owner_branch), None)
    L += ["", "## 4. 董事長的分點", ""]
    if own:
        bno, b = own
        lots = " ".join(f"{ym[2:]}:{b['series'].get(ym, 0)}" for ym in months(*SPAN) if ym in pages)
        L += [f"- 負責人標註（證據 B）：{a.owner_branch}；在前 15 名出現 {len(b['series'])} 個月", f"- 每月淨買賣（張）：{lots}"]
    else:
        L += [f"- 負責人標註：{a.owner_branch or '—'}；36 個月的前 15 名裡沒有出現"]
    if own:
        hits = []
        for ym, (i, d) in sorted(ins.items()):
            net, v = (i - d) / 1000, own[1]["series"].get(ym, 0)
            if net and v and 0.5 <= v / net <= 1.5:
                hits.append(f"{ym[:4]}-{ym[4:]}：董監 {net:+,.0f} 張、{a.owner_branch} {v:+,} 張（{v / net:.0%}）")
        L += [f"- 時間比對（證據 A，量差在 50～150%）：{'；'.join(hits) if hits else '沒有吻合的月份'}"
              f"（董監變動 {len(ins)} 個月，彙總表含所有原因，不只集中市場）"]
    L += ["", "> 讀法：跟單欄是「那個月淨買 → 下個月第一個交易日收盤進場」扣成本 0.585% 後的結果；要和最上面的基準比，"
          "高出基準的部分才是分點的本事。件數少於 10 件寫「樣本不足」。手法只看月資料，看不出當沖／隔日沖。"]
    out = OUT / f"profile_{a.code}.md"
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[profile] {a.code}: requests {n}, months {len(pages)}, branches {len(br)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
