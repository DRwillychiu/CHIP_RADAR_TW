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
import html
import json
import re
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


def _load(f):
    raw = html.unescape(f.read_bytes().decode("utf-8", "ignore"))   # 6669: the API writes 洪麗寗 as &#23511;
    try:
        return json.loads(raw)
    except ValueError:                       # the API cut a download off (2026-10-12): keep the complete rows
        return json.loads(raw[:raw.rfind("},") + 1] + "]")


def roster(code):
    """TWSE (listed) or TPEx (OTC) OpenAPI: company basics + every insider with holdings."""
    d = ROOT / "data" / "research" / "roster"
    base = next((x for x in _load(d / "t187ap03_L.json") if x.get("公司代號") == code), None)
    if base is None and (d / "t187ap03_O.json").exists():
        o = next((x for x in _load(d / "t187ap03_O.json") if x.get("SecuritiesCompanyCode") == code), {})
        base = {"公司簡稱": o.get("CompanyAbbreviation", ""), "董事長": o.get("Chairman", ""),
                "總經理": o.get("GeneralManager", ""), "住址": o.get("Address", "")}
    people = [x for x in _load(d / "t187ap11_L.json") if x.get("公司代號") == code]
    if not people and (d / "t187ap11_O.json").exists():
        people = [x for x in _load(d / "t187ap11_O.json") if x.get("公司代號") == code]
    return base or {}, people


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
        except requests.RequestException as x:   # 3008 2026-10-12 18:58: cool down 5 min, try once more
            print(f"[profile] {type(x).__name__} at {ym} - cooling down 5 min", flush=True)
            time.sleep(300)
            note_request()
            try:
                r = s.get(URL.format(code=code, y=y, m=m, last=calendar.monthrange(y, m)[1]), timeout=20)
            except requests.RequestException as x2:
                print(f"[profile] stopped: {type(x2).__name__} twice at {ym}", flush=True)
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


# owner 2026-10-12: 「主力，多半會看台灣本土分點為主。然後那種綜合的統稱:國泰證券、永豐金證券這種，其實就當作是潛在可能
# 匯撥以及藏分點買賣的真正市場高手」 -> three kinds: foreign brokers / a broker's head office (no branch suffix) / local branch
FOREIGN = ("美商", "港商", "新加坡商", "英商", "瑞士商", "法商", "德商", "日商", "台灣摩根士丹利", "摩根大通", "美林", "花旗",
           "瑞銀", "高盛", "麥格理", "野村", "大和", "匯豐", "法銀", "德意志", "瑞士信貸", "摩根士丹利")


def kind(name):
    if any(k in name for k in FOREIGN):
        return "foreign"
    return "local" if "-" in name else "head"


PARKS = (("新竹科學", ("新竹市", "東區")), ("Hsinchu Science", ("新竹市", "東區")), ("南部科學", ("臺南市", "新市區")),
         ("TAINAN SCIENCE", ("臺南市", "新市區")), ("Tainan Science", ("臺南市", "新市區")), ("中部科學", ("臺中市", "西屯區")))
EN_CITY = (("New Taipei", "新北市"), ("Taipei", "臺北市"), ("Taoyuan", "桃園市"), ("Taichung", "臺中市"), ("Tainan", "臺南市"),
           ("Kaohsiung", "高雄市"), ("Hsinchu Hsien", "新竹縣"), ("Hsinchu County", "新竹縣"), ("Hsinchu", "新竹市"),
           ("Miaoli", "苗栗縣"), ("Changhua", "彰化縣"), ("Nantou", "南投縣"), ("Yunlin", "雲林縣"), ("Chiayi", "嘉義縣"),
           ("Pingtung", "屏東縣"), ("Yilan", "宜蘭縣"), ("Hualien", "花蓮縣"), ("Taitung", "臺東縣"), ("Keelung", "基隆市"))
EN_DIST = (("Chupei", "竹北市"), ("Zhubei", "竹北市"), ("Sanchong", "三重區"), ("Hsinchuang", "新莊區"), ("Xinzhuang", "新莊區"),
           ("Tucheng", "土城區"), ("Zhonghe", "中和區"), ("Chung Ho", "中和區"), ("Banqiao", "板橋區"), ("Neihu", "內湖區"),
           ("Xizhi", "汐止區"), ("Hsichih", "汐止區"), ("Taishan", "泰山區"), ("Wugu", "五股區"), ("Luzhu", "蘆竹區"),
           ("Guishan", "龜山區"), ("Zhongli", "中壢區"), ("Chungli", "中壢區"), ("Pingzhen", "平鎮區"), ("Yangmei", "楊梅區"),
           ("Hukou", "湖口鄉"), ("Xinfeng", "新豐鄉"), ("Zhunan", "竹南鎮"), ("Toufen", "頭份市"), ("Daya", "大雅區"),
           ("Xitun", "西屯區"), ("Nantun", "南屯區"), ("Rende", "仁德區"), ("Yongkang", "永康區"), ("Anping", "安平區"),
           ("Gangshan", "岡山區"), ("Luzhu Dist., Kaohsiung", "路竹區"), ("Qianzhen", "前鎮區"), ("Nanzi", "楠梓區"))


def home_of(code, base, geo):
    """(city, district) of the company: data/branch_geo.json when it has one, else the roster address
    (Chinese for listed; TPEx gives English - city always, district from a short table). 台 -> 臺 like the branch table."""
    h = geo["companies"].get(code) or {}
    if h.get("city") and h.get("dist"):
        return h["city"], h["dist"], "address"
    addr = base.get("住址") or ""
    for k, v in PARKS:
        if k in addr:
            return v[0], v[1], "science park"
    m = re.match(r"^(.{2}[市縣])(.{1,3}?[區鄉鎮市])", addr.replace("台", "臺"))
    if m:
        return m.group(1), m.group(2), "address"
    city = next((zh for en, zh in EN_CITY if en.lower() in addr.lower()), None)
    dist = next((zh for en, zh in EN_DIST if en.lower() in addr.lower()), None)
    return city, dist, "english address"


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
    hc, hd, hsrc = home_of(a.code, base, geo)
    home = {"city": hc, "dist": hd}
    closes, index, _ = prices()
    ins = {}
    for f in sorted((ROOT / "data" / "insider_monthly").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))["companies"].get(a.code)
        if r and (r["dir_inc"] or r["dir_dec"]):
            ins[f.stem] = (r["dir_inc"], r["dir_dec"])
    cum = lambda kv: sum(kv[1]["series"].values())
    loc = [kv for kv in br.items() if kind(kv[1]["name"]) == "local"]
    head = sorted((kv for kv in br.items() if kind(kv[1]["name"]) == "head"), key=lambda kv: -abs(cum(kv)))[:4]
    ranked = sorted(loc, key=cum, reverse=True)[:4] + sorted(loc, key=cum)[:4]   # local branches: 4 biggest accumulators + 4 sellers
    L = [f"# {a.code} {base.get('公司簡稱', '')} 主力檔案（{time.strftime('%Y-%m-%d %H:%M')}，dev 試做）", "",
         f"- 董事長：{base.get('董事長', '—')}；總經理：{base.get('總經理', '—')}；公司地址：{base.get('住址', '—')}",
         f"- 公司位置：{hc or '—'}{hd or ''}（{hsrc}）",
         f"- 分點資料：{len(pages)} 個月（{SPAN[0]}～{SPAN[1]}），本次請求 {n} 次；股價只有 2024-10 起，之前的月份不算報酬", "",
         "## 1. 內部人與持股（證交所公開資料）", "", "| 身分 | 姓名 | 目前持股（股） | 關係人持股 |", "|---|---|---:|---:|"]
    L += [f"| {x['職稱']} | {x['姓名']} | {int(x.get('目前持股') or 0):,} | {int(x.get('內部人關係人目前持股合計') or 0):,} |" for x in people]
    L += ["", "## 2. 董監每月持股增減（彙總表，含所有原因，股）", ""]
    L += [f"- {ym[:4]}-{ym[4:]}：增 {i:,}、減 {d:,}" for ym, (i, d) in sorted(ins.items())] or ["- 這段期間沒有變動"]
    L += ["", "## 3. 主力分點：本土分點（36 個月累計淨買最多 4 家＋淨賣最多 4 家，張；外資與總公司另列）", "",
          "| 分點 | 地緣 | 淨買月 | 淨賣月 | 累計淨買 | 手法（月資料） | 跟單 5 日 | 20 日 | 60 日 |", "|---|---|---:|---:|---:|---|---|---|---|"]
    base_fw = follow(a.code, [ym for ym in months(*SPAN)], closes, index)   # any month: the stock's own drift
    cell = lambda t: "—" if not t[0] else (f"{t[0]} 件 樣本不足" if t[0] < 10 else f"{t[0]} 件 勝率 {t[1]}% 平均 {t[2]:+.2f}%")
    L.append(f"| **基準：任一個月都進場** | | | | | | {cell(base_fw[5])} | {cell(base_fw[20])} | {cell(base_fw[60])} |")
    own_name = a.owner_branch
    if own_name and all(b["name"] != own_name for _, b in ranked):
        ranked = ranked + [kv for kv in br.items() if kv[1]["name"] == own_name]
    for bno, b in ranked:
        g = geo["branches"].get(bno) or {}
        local = "同區" if home.get("dist") and g.get("dist") == home.get("dist") and g.get("city") == home.get("city") else ("同市" if home.get("city") and g.get("city") == home.get("city") else "")
        buy_m = [ym for ym, v in b["series"].items() if v > 0]
        fw = follow(a.code, buy_m, closes, index)
        L.append(f"| {b['name']}{'（負責人標註）' if b['name'] == own_name else ''} | {local} | {len(buy_m)} | {sum(1 for v in b['series'].values() if v < 0)} | "
                 f"{sum(b['series'].values()):,} | {style(b['series'])} | {cell(fw[5])} | {cell(fw[20])} | {cell(fw[60])} |")
    strict = [x for x in json.loads((ROOT / "data" / "insider_watch_branches.json").read_text(encoding="utf-8"))["branches"] if x["code"] == a.code]
    persons = {}                                  # ym -> [(name, role, market net shares)] from the per-person pages
    for f in sorted((ROOT / "data" / "insider_people").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rows = [(r["name"], r["role"], r["market_buy"] - r["market_sell"]) for r in d["people"] if r["code"] == a.code and (r["market_buy"] or r["market_sell"])]
        if rows:
            persons[d["ym"]] = rows

    def who(series):
        """'韓顯福（副董事長）賣 2606、2608' - the people whose own market net is within 20 % of the branch's month."""
        got = {}
        for ym, rows in persons.items():
            v = series.get(ym)
            for n, role, sh in rows:
                if v and sh and 0.8 <= v * 1000 / sh <= 1.2:
                    got.setdefault((n, role, "買" if sh > 0 else "賣"), []).append(ym[2:])
        return "；".join(f"{n}（{role}）{side} {'、'.join(m)}" for (n, role, side), m in got.items())

    matches = []
    for tier in ("local", "head", "foreign"):     # owner: local branches first; foreign only when no local branch matches
        for bno, b in br.items():
            if kind(b["name"]) != tier:
                continue
            hit = [ym for ym, (i, d) in ins.items() if (i - d) and b["series"].get(ym) and 0.8 <= b["series"][ym] * 1000 / (i - d) <= 1.2]
            if len(hit) >= 2:
                matches.append((b["name"], hit))
        if matches:
            break
    def same(kv, lvl):
        g = geo["branches"].get(kv[0]) or {}
        return bool(home.get("city")) and g.get("city") == home.get("city") and (lvl == "city" or (home.get("dist") and g.get("dist") == home.get("dist")))
    near = sorted((kv for kv in br.items() if same(kv, "dist")), key=lambda kv: -abs(cum(kv)))
    L += ["", "### 地緣分點（和公司同一區；36 個月有進前 15 名的全部列出）", ""]
    L += [f"- {kv[1]['name']}：累計 {cum(kv):+,} 張，出現 {len(kv[1]['series'])} 個月" for kv in near] or ["- 同一區沒有分點進過前 15 名"]
    L += ["", "### 總公司（綜合統稱：可能匯撥、藏分點的市場高手）", ""]
    L += [f"- {kv[1]['name']}：36 個月累計 {cum(kv):+,} 張，淨買 {sum(1 for v in kv[1]['series'].values() if v > 0)} 月、淨賣 {sum(1 for v in kv[1]['series'].values() if v < 0)} 月" for kv in head] or ["- 無"]
    fr = sorted((kv for kv in br.items() if kind(kv[1]["name"]) == "foreign"), key=lambda kv: -abs(cum(kv)))[:3]
    L += ["", "### 外資券商（參考）", ""] + [f"- {kv[1]['name']}：36 個月累計 {cum(kv):+,} 張" for kv in fr]
    own = next(((bno, b) for bno, b in br.items() if a.owner_branch and b["name"] == a.owner_branch), None)
    L += ["", "## 4. 董事長／內部人的分點", ""]
    sb = {b["name"]: b for b in br.values()}
    L += [f"- 嚴格名單（證據 A，近一年逐人申報 ±20% 吻合、時間對照通過）：" + ("；".join(
        f"{x['branch']}＝{who(sb[x['branch']]['series']) or '對上董監合計'}" for x in strict if x["branch"] in sb) or "無")]
    L += [f"- 36 個月彙總表比對（董監每月增減含所有原因，量差 ±20% 吻合 ≥ 2 個月）：" + ("；".join(f"{n}（{'、'.join(m[2:] for m in h)}）" for n, h in matches) or "無")]
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
    br_by_name = {b["name"]: b for b in br.values()}

    def brief(kv):
        g = geo["branches"].get(kv[0]) or {}
        return {"branch": kv[1]["name"], "cum_lots": sum(kv[1]["series"].values()),
                "local": bool(home.get("dist")) and g.get("dist") == home.get("dist")}
    (OUT / f"profile_{a.code}.json").write_text(json.dumps({
        "code": a.code, "name": base.get("公司簡稱", ""), "chairman": base.get("董事長", ""),
        "big_holders": [x["姓名"] for x in people if str(x.get("職稱", "")).startswith("大股東")],
        "strict": [{"branch": x["branch"], "side": x["side"], "months": x["same_month_matches"],
                    "who": who(br_by_name[x["branch"]]["series"]) if x["branch"] in br_by_name else ""} for x in strict],
        "home": f"{hc or ''}{hd or ''}",
        "matches": [{"branch": n, "months": h} for n, h in matches],
        "accumulators": [brief(kv) for kv in sorted(loc, key=cum, reverse=True)[:3]],
        "sellers": [brief(kv) for kv in sorted(loc, key=cum)[:3]],
        "head_offices": [brief(kv) for kv in head[:3]],
        "near": [{"branch": kv[1]["name"], "cum_lots": cum(kv), "months": len(kv[1]["series"])} for kv in near[:3]],
        "baseline_20d": base_fw[20], "insider_change_months": len(ins)}, ensure_ascii=False), encoding="utf-8")
    out = OUT / f"profile_{a.code}.md"
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[profile] {a.code}: requests {n}, months {len(pages)}, branches {len(br)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
