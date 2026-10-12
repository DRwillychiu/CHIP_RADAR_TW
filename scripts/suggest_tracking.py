"""v3.96.6 spec section 10: the first 「建議加入追蹤」 list (owner 2026-10-12: 「同意，立即開始」).
Flow written in the spec: research candidates -> beats the stock's own baseline with enough cases -> the owner reviews
-> only approved branches join the nightly crawl (each one = its page fetched every night).

Candidates: the strict insider-branch list (data/insider_watch_branches.json, 89 pairs) and the local main-force /
地緣 branches of the profiled stocks (data/research/profile_<code>.json).
Rule, written down before the run (2026-10-12):
  - local branches only: no foreign broker, no 常客 (>= 30 % of the stocks); head offices allowed, tagged
  - month-level, like the profile: a month the branch net-BOUGHT the stock -> buy at the close of the first trading
    day of the next month, 20 trading days, after costs; baseline = the same for every month of that stock
  - buy side: n >= 6, mean beats the baseline, hit >= 51 %  -> 建議
    sell side: after its net-SELL months the stock does worse than the baseline (n >= 6)  -> 建議（賣壓警示）
  - already tracked branches (src/core/branches.py) are marked, not suggested again
Output: data/research/suggest_tracking.md (branch data: private, not in git).
    python scripts/suggest_tracking.py
"""
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import stock_profile as P  # noqa: E402
from scripts.run_insider_radar import prices  # noqa: E402
from src.core.branches import WATCHED_BRANCHES  # noqa: E402
from src.fetchers import stock_branch_ranking as S  # noqa: E402

N_MIN, HIT_MIN, H = 6, 51.0, 20


def series_of(code):
    out = {}
    for f in sorted(P.RAW.glob(f"{code}_*.html")):
        ym = f.stem.rsplit("_", 1)[1]
        p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {}
        for r in (p.get("buys") or []) + (p.get("sells") or []):
            out.setdefault((r["bno"], r["name"]), {})[ym] = out.get((r["bno"], r["name"]), {}).get(ym, 0) + int(r["net"] or 0)
    return out


def rets(code, yms, closes, index):
    """20-day after-cost returns from the first trading day after each month (no price -> skipped)."""
    c, days, out = closes.get(code, {}), sorted(index), []
    for ym in yms:
        y, m = int(ym[:4]), int(ym[4:])
        want = f"{y + (m == 12):04d}{m % 12 + 1:02d}"
        nxt = [d for d in days if d[:6] == want]
        if not nxt or nxt[0] not in c:
            continue
        i = days.index(nxt[0])
        if i + H < len(days) and days[i + H] in c:
            out.append((c[days[i + H]] / c[nxt[0]] - 1) * 100 - P.COST_PCT)
    return out


def main():
    closes, index, _ = prices()
    share = P.branch_share()
    tracked = {b["code"] for b in WATCHED_BRANCHES}
    cands = {}
    for x in json.loads((ROOT / "data" / "insider_watch_branches.json").read_text(encoding="utf-8"))["branches"]:
        cands[(x["code"], x["branch"])] = f"內部人分點（{x['side']}，{x['same_month_matches']} 個月吻合）"
    for f in sorted((ROOT / "data" / "research").glob("profile_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for key, why in (("accumulators", "本土主力（累計買）"), ("sellers", "本土主力（累計賣）"), ("near", "地緣"), ("far", "鄰近")):
            for b in d.get(key) or []:
                cands.setdefault((d["code"], b["branch"]), why)
    rows, cache = [], {}
    for (code, name), why in sorted(cands.items()):
        if P.kind(name) == "foreign" or share.get(name, 0) >= 30:
            continue
        ser = cache.setdefault(code, series_of(code))
        hit = next(((bno, s) for (bno, n), s in ser.items() if n == name), None)
        if not hit:
            continue
        bno, s = hit
        base = rets(code, sorted({ym for v in ser.values() for ym in v}), closes, index)
        if len(base) < N_MIN:
            continue
        b0 = statistics.mean(base)
        buy = rets(code, [ym for ym, v in s.items() if v > 0], closes, index)
        sell = rets(code, [ym for ym, v in s.items() if v < 0], closes, index)
        r = {"code": code, "name": name, "bno": bno, "why": why, "head": P.kind(name) == "head", "share": share.get(name, 0),
             "tracked": bno in tracked, "base": b0, "n_buy": len(buy), "n_sell": len(sell),
             "buy": statistics.mean(buy) if buy else None, "buy_hit": sum(v > 0 for v in buy) / len(buy) * 100 if buy else None,
             "sell": statistics.mean(sell) if sell else None}
        r["ok_buy"] = bool(len(buy) >= N_MIN and r["buy"] > b0 and r["buy_hit"] >= HIT_MIN)
        r["ok_sell"] = bool(len(sell) >= N_MIN and r["sell"] < b0)
        rows.append(r)
    sug = [r for r in rows if (r["ok_buy"] or r["ok_sell"]) and not r["tracked"]]
    edge = lambda r: max(r["buy"] - r["base"] if r["ok_buy"] else -1e9, r["base"] - r["sell"] if r["ok_sell"] else -1e9)
    sug.sort(key=lambda r: -edge(r))
    names = {}
    sh = json.loads((ROOT / "data" / "stock_history.json").read_text(encoding="utf-8"))["stocks"]
    L = [f"# 建議加入追蹤（第一份，{time.strftime('%Y-%m-%d %H:%M')}，待負責人審）", "",
         f"- 候選 {len(cands)} 組（內部人分點嚴格名單＋已做主力檔案的股票），排除外資與常客後可算的 {len(rows)} 組；"
         f"通過 {sum(1 for r in rows if r['ok_buy'] or r['ok_sell'])} 組，其中已在追蹤 {sum(1 for r in rows if (r['ok_buy'] or r['ok_sell']) and r['tracked'])} 組",
         f"- 規則（跑之前寫死）：月資料；那個月淨買 → 下個月第一個交易日收盤進場、{H} 日、扣成本；要贏過「任一個月都進場」基準、"
         f"件數 ≥ {N_MIN}、勝率 ≥ {HIT_MIN:.0f}%；賣方＝淨賣之後的報酬比基準差",
         "- 注意：單一檔股票只有月資料，件數少（6～12 件），只能當「值得每天盯」的依據，不是買賣訊號", "",
         "| 分點 | 股票 | 來源 | 類型 | 淨買後 20 日（件數、勝率） | 淨賣後 20 日（件數） | 基準 | 出現率 |", "|---|---|---|---|---|---|---:|---:|"]
    for r in sug:
        nm = (sh.get(r["code"]) or {}).get("name", "")
        b = f"{r['buy']:+.1f}%（{r['n_buy']} 件、{r['buy_hit']:.0f}%）" if r["buy"] is not None else "—"
        s_ = f"{r['sell']:+.1f}%（{r['n_sell']} 件）" if r["sell"] is not None else "—"
        kind = ("買方" if r["ok_buy"] else "") + ("、" if r["ok_buy"] and r["ok_sell"] else "") + ("賣壓警示" if r["ok_sell"] else "")
        L.append(f"| {r['name']}{'（總公司）' if r['head'] else ''} | {r['code']} {nm} | {r['why']} | {kind} | {b} | {s_} | {r['base']:+.1f}% | {r['share']}% |")
    L += ["", f"> 每加入 1 個分點，每晚多抓 1 頁富邦分點頁。已在追蹤、通過規則的：" +
          ("、".join(sorted({f"{r['name']}（{r['code']}）" for r in rows if (r['ok_buy'] or r['ok_sell']) and r['tracked']})) or "無")]
    out = ROOT / "data" / "research" / "suggest_tracking.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[suggest] candidates {len(cands)}, computable {len(rows)}, pass {sum(1 for r in rows if r['ok_buy'] or r['ok_sell'])}, "
          f"new suggestions {len(sug)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
