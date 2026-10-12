"""v3.96.6 research on the tracked research branches (owner 2026-10-12: 「然後針對這九個繼續進行研究」). Offline.
For each (stock, branch) pair:
  1 who: the insiders whose own market net matched the branch's month (per-person pages, within 20 %)
  2 robustness: the month-level follow at 5 / 20 / 60 days against the stock's baseline, and the two halves of the
    months separately (an edge carried by one half only is not trusted)
  3 the branch elsewhere: the other stocks where it was in a month's top 15 with the biggest cumulative net
    (a branch that trades a few stocks heavily looks like one person; hundreds of small ones look like a crowd)
Output: data/research/research_branches.md (branch data: private, not in git).
    python scripts/research_branches.py
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
from src.fetchers import stock_branch_ranking as S  # noqa: E402

PAIRS = (("2460", "元大-路竹", -1), ("3008", "凱基-永和", -1), ("8042", "台新-三重", -1), ("6274", "永豐金-匯立", -1),
         ("6823", "永豐金-中正", -1), ("3691", "台新-新竹", -1), ("6669", "台新-台北", 1), ("6274", "台新-台北", -1),
         ("2474", "台新-府城", 1))


def rets(code, yms, h, closes, index):
    c, days, out = closes.get(code, {}), sorted(index), []
    for ym in yms:
        y, m = int(ym[:4]), int(ym[4:])
        want = f"{y + (m == 12):04d}{m % 12 + 1:02d}"
        nxt = [d for d in days if d[:6] == want]
        if nxt and nxt[0] in c:
            i = days.index(nxt[0])
            if i + h < len(days) and days[i + h] in c:
                out.append((c[days[i + h]] / c[nxt[0]] - 1) * 100 - P.COST_PCT)
    return out


def main():
    closes, index, _ = prices()
    allp = {}
    for f in P.RAW.glob("*_*.html"):
        code, ym = f.stem.rsplit("_", 1)
        p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {}
        for r in (p.get("buys") or []) + (p.get("sells") or []):
            allp.setdefault(r["name"], {}).setdefault(code, {})[ym] = int(r["net"] or 0)
    persons = {}
    for f in sorted((ROOT / "data" / "insider_people").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d["people"]:
            if r["market_buy"] or r["market_sell"]:
                persons.setdefault((r["code"], d["ym"]), []).append((r["name"], r["role"], r["market_buy"] - r["market_sell"]))
    sh = json.loads((ROOT / "data" / "stock_history.json").read_text(encoding="utf-8"))["stocks"]
    nm = lambda c: (sh.get(c) or {}).get("name", "")
    L = [f"# 9 組追蹤分點研究（{time.strftime('%Y-%m-%d %H:%M')}，月資料，扣成本；只給負責人）", ""]
    for code, name, side in PAIRS:
        ser = allp.get(name, {}).get(code, {})
        months = sorted({ym for b in allp.values() for ym in (b.get(code) or {})})
        act = sorted(ym for ym, v in ser.items() if v * side > 0)
        L += [f"## {name} × {code} {nm(code)}（{'淨買' if side > 0 else '淨賣'}訊號）", ""]
        who = {}
        for ym in act:
            for n, role, net in persons.get((code, ym), []):
                if net and 0.8 <= ser[ym] * 1000 / net <= 1.2:
                    who.setdefault(f"{n}（{role}）", []).append(ym[2:])
        L.append("- 對上的內部人：" + ("；".join(f"{k} {'、'.join(v)}" for k, v in who.items()) or "沒有（不是內部人的量，或那幾個月沒有逐人明細）"))
        L.append(f"- 訊號月份 {len(act)} 個：" + "、".join(f"{ym[2:4]}/{ym[4:]}（{ser[ym]:+,} 張）" for ym in act))
        L.append("- 和基準比（訊號後 − 任一個月都進場，百分點）：")
        half = len(act) // 2
        for h in P.HS:
            base = rets(code, months, h, closes, index)
            sig = rets(code, act, h, closes, index)
            a1, a2 = rets(code, act[:half], h, closes, index), rets(code, act[half:], h, closes, index)
            if not base or not sig:
                L.append(f"  - {h} 日：資料不足")
                continue
            g = lambda xs: (statistics.mean(xs) - statistics.mean(base)) * side if xs else None
            fmt = lambda v: "—" if v is None else f"{v:+.1f}"
            L.append(f"  - {h} 日：全部 {fmt(g(sig))}（{len(sig)} 件）；前半 {fmt(g(a1))}、後半 {fmt(g(a2))}")
        other = sorted(((c, sum(v.values()), len(v)) for c, v in allp.get(name, {}).items() if c != code), key=lambda t: -abs(t[1]))
        L.append(f"- 這個分點出現過的股票共 {len(allp.get(name, {}))} 檔；量最大的其他 5 檔：" +
                 "、".join(f"{c} {nm(c)} {cum:+,} 張（{n} 月）" for c, cum, n in other[:5]))
        L.append("")
    L.append("> 「和基準比」正數＝這個訊號有用（買方：之後比平常好；賣方：之後比平常差）。前後半同號才算穩。")
    out = ROOT / "data" / "research" / "research_branches.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[research] {len(PAIRS)} pairs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
