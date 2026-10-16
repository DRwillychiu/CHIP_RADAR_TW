# v3.96.3 insider radar 3.3 個股全景圖: the chart series match the data files - offline
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Spec docs/specs/INSIDER_RADAR_SPEC.md 4 item 3.3 and the owner-approved draft
docs/diagrams/insider_radar/panorama_v3_draft.html. The page draws only what data/insider_radar.json
pano holds, so the series are checked against the files they come from, for one real stock."""
from scripts import run_insider_radar as RR

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "data"
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


print("=" * 72)
print("  v3.96.3 個股全景圖 (離線)")
print("=" * 72)

print("\n[A] 成本帶與「N 人同買」")
ins = {"202601": {"buy_sh": 1000, "avg": 10.0, "ppl": [["董事", "甲", 1000, 0]]},
       "202602": {"buy_sh": 3000, "avg": 20.0, "ppl": [["董事", "乙", 3000, 0], ["經理", "丙", -500, 0]]},
       "202603": {"buy_sh": 0, "avg": 30.0, "ppl": [["董事", "甲", 0, 2000]]}}
ms = ["202601", "202602", "202603"]
check("成本 = 集中市場買進的股數加權均價 (賣出、贈與不算)", RR.pano_cost(ins, ms, "202603") == 17.5, RR.pano_cost(ins, ms, "202603"))
check("沒有人買 → 沒有成本帶", RR.pano_cost({"202601": {"buy_sh": 0, "avg": 9.0}}, ["202601"], "202601") is None)
check("只算到最新申報月為止的近 12 個月", RR.pano_cost(ins, ms, "202601") == 10.0)
check("3 個月內不到 3 人買 → 沒有旗標 (賣方、贈與不算人數)", RR.pano_clusters(ins, ms) == [])
ins["202603"]["ppl"].append(["協理", "丁", 10, 0])
check("3 個月內 3 個不同的人買 → 「3 人同買」", RR.pano_clusters(ins, ms) == [["202601", "202603", 3]], RR.pano_clusters(ins, ms))
ins6 = {f"2026{m:02d}": {"ppl": [["董事", f"人{m}", 1, 0]]} for m in range(1, 7)}
check("旗標不重疊", RR.pano_clusters(ins6, [f"2026{m:02d}" for m in range(1, 7)]) == [["202601", "202603", 3], ["202604", "202606", 3]])

print("\n[B] 一檔真實股票: 圖上的序列 = 資料檔")
f = D / "insider_radar.json"
if not f.exists() or not (D / "insider_people").exists():
    print("  (沒有 data/insider_radar.json 或逐人資料, 略過)")
else:
    doc = load(f)
    P = doc.get("pano") or {}
    st_all = P.get("stocks") or {}
    code = "1712" if "1712" in st_all else (sorted(st_all, key=lambda c: -len(st_all[c]["ins"])) or [None])[0]
    st, M = st_all.get(code) or {}, P.get("months") or []
    check(f"有全景圖序列 ({code}), 月份連續", bool(st) and M == RR.month_list(M[0], M[-1]), (code, M[:1], M[-1:]))
    # monthly close = the month's last stored close (price_history, then the 60-day stock_history)
    days = {}
    for pf in sorted((D / "price_history").glob("*.json")):
        days.update(load(pf)["close"].get(code, {}))
    for day, row in ((load(D / "stock_history.json")["stocks"].get(code) or {}).get("daily") or {}).items():
        if row.get("close"):
            days.setdefault(day, row["close"])
    want = [days[max(d for d in days if d[:6] == m)] if any(d[:6] == m for d in days) else None for m in M]
    check("月收盤 = 該月最後一個交易日收盤", st["close"] == want, [(m, a, b) for m, a, b in zip(M, st["close"], want) if a != b][:3])
    # insider months = person rows with any market / other change; sums in shares
    exp = {}
    for pf in sorted((D / "insider_people").glob("*.json")):
        mo = load(pf)
        if mo["ym"] not in M:
            continue
        rs = [r for r in mo["people"] if r["code"] == code]
        if any(r["market_buy"] or r["market_sell"] or r["other_buy"] or r["other_sell"] for r in rs):
            exp[mo["ym"]] = (sum(r["market_buy"] - r["market_sell"] for r in rs), sum(r["other_buy"] - r["other_sell"] for r in rs),
                             sum(r["market_buy"] for r in rs))
    got = {m: (e["net_sh"], e["oth_sh"], e["buy_sh"]) for m, e in st["ins"].items()}
    check("內部人月份與淨股數 / 其它原因 / 買進股數 = 逐人資料加總", got == exp, sorted(set(got.items()) ^ set(exp.items()))[:3])
    check("每月的人: 淨股數加總 = 公司淨股數", all(sum(p[2] for p in e["ppl"]) == e["net_sh"] and sum(p[3] for p in e["ppl"]) == e["oth_sh"] for e in st["ins"].values()))
    tw = []
    for tf in sorted((D / "tdcc_history").glob("*.json")):
        t = load(tf)
        h = (t.get("holdings") or {}).get(code)
        if h and h.get("mega1000_pct") is not None:
            tw.append([t.get("effective_date") or tf.stem, h["mega1000_pct"]])
    check("千張大戶 % = 集保週資料", st["tdcc"] == tw, (len(st["tdcc"]), len(tw)))
    pubs = [p.stem for p in (D / "insider_monthly").glob("*.json") if load(p).get("published")]
    check("尚未申報 = 最新已公開月份之後", P.get("published_until") == max(pubs), (P.get("published_until"), max(pubs)))
    codes = {x["code"] for y in doc.get("years", []) for x in y["signals"]["A"] + y["sells"]}
    check("只給出現在任一年份的股票", set(st_all) == codes, len(set(st_all) ^ codes))
    t = json.dumps(P, ensure_ascii=False)
    check("全景圖公開資料沒有分點大戶的東西", not any(w in t for w in ("branch", "分點", "同向", "反向")))

print("\n[C] 頁面 (index.html)")
h = (ROOT / "index.html").read_text(encoding="utf-8")
js = h[h.index("// ========== v3.96.3 3.3 個股全景圖"):h.index("function _insOpen(i) {")]
op = h[h.index("function _insOpen(i) {"):h.index("function _insAll() {")]
check("抽屜一打開最上面就是五格重點 + 全景圖", 'const body = _insCells(x) + `<div class="dr-pano" id="insPano" onclick="_insPanoClick(event)"></div>`' in op and "_insPanoDraw(x.code);" in op)
check("分點大戶副圖只讀解密後的私密部分", "(INSIDER_PRIV || {}).pano" in js and "if (brs) {" in js and "INSIDER_RADAR || {}).pano" in js)
check("圖上只有「職位＋買/賣」框 (名字、金額在小框)", "`${st.ins[M[i]].role || ''}${st.ins[M[i]].net_sh > 0 ? '買' : '賣'}`" in js
      and "escHtml(label(p.i))" in js and "${escHtml(p[0])}(${escHtml(p[1])})" in js)
check("標籤不壓標籤也不壓圓圈 (壓到就拿掉, 圓圈仍可點)", "if (circles.some(c => hitC(b, c)) || obst.some(o => hit(b, o)) || boxes.some(o => hit(b, o.b))) continue;" in js
      and "box.dataset.overlaps = bad" in js)
check("贈與・信託是灰色空心圈、不算買賣", "fill: rn ? 'none' : BG, stroke: TX3" in js and "贈與・信託（不算買賣）" in js)
check("手機少放標籤 (買 2、賣 1)", "slice(0, side ? (mob ? 2 : 3) : (mob ? 1 : 2))" in js)
check("尚未申報、成本帶、N 人同買、月柱、千張大戶都有", all(k in js for k in ("尚未申報", "內部人買進成本", "人同買", "內部人每月買賣金額", "千張大戶持股 %")))

print("\n[D] 五格重點、身分 / 期間切換、檢查更新 (v3.96.4)")
cj = h[h.index("function _insCells(x) {"):h.index("function _insOpen(i) {")]
check("五格: 誰在買 / 買多少 / 內部人成本 / 分點大戶 / 這類訊號過去 N 日, 放在圖的上面",
      all(k in cj for k in ("'誰在買'", "'買多少'", "'內部人成本'", "'分點大戶'", "這類訊號過去 ${H} 日")) and "const body = _insCells(x) + `<div class=\"dr-pano\"" in op)
check("分點大戶格只讀解密後的部分, 沒解鎖寫「需解鎖」", "const pv = INSIDER_PRIV, br = pv && pv.br10" in cj and "cell('分點大戶', '—', '需解鎖')" in cj)
src_r = (ROOT / "scripts" / "run_insider_radar.py").read_text(encoding="utf-8")
check("10 日分點淨額只寫進加密檔", 'priv["br10"] = br10' in src_r and '"br10"' not in json.dumps(load(f)) if f.exists() else 'priv["br10"] = br10' in src_r)
check("身分 / 1 年・2 年 切換一起改圓圈、標籤、月柱 (圖從同一個 view 畫)", "const st = st0 && { ...st0, close: (st0.close || []).slice(keep), ins: _insPanoView(st0.ins || {}, f.role) };" in js
      and "_INS_ROLES = ['全部', '董事長', '董事', '經理人', '大股東']" in js and "_insPanoSet('span',${y})" in js)
sj = h[h.index("let _INS_CHECK = null;"):h.index("function _insSide(x)")]
check("檢查更新: 繞過快取重讀、寫資料到哪個月與下次公告日", "_INS_LOADING = null;" in sj and "資料到 ${u.slice(0, 4)}-${u.slice(4)}；下一次約 ${nx.label} 公告" in sj
      and "{cache: 'no-store'}" in h[h.index("function _insLoad() {"):h.index("let _INS_CHECK = null;")])
# 2026-10-16 owner: complete from the 16th (filed by the 15th, 證交法 §25) - the red line comes 2 days later, on the 18th (was 20th / 22nd)
check("過了公告日 + 2 天還沒新資料 → 紅字", "overdue: now > new Date(py, pm - 1, 18, 23, 59, 59)" in sj and "官方應已公告，資料未更新" in sj)
check("頁面不放任何 token / key", not re.search(r"ghp_|github_pat_|Authorization|api[_-]?key", sj + cj, re.I))
if f.exists():
    check("公開檔寫了資料到哪個月 (data_until)", bool(load(f).get("data_until")))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
