# v3.96.1 insider radar 3.1: the S08 大股東動向 block on 今日總整理 + the public / private split - offline
import sys, pathlib, re, json, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Spec docs/specs/INSIDER_RADAR_SPEC.md 4 (3.1) and 5. Owner 2026-10-11: key facts in big type, details
only in the drawer, top 5; label = 職位 + 買 / 賣 in a red (buy) / green (sell) box. The repo is public:
nothing from our branch-master crawl (group B, branch_net_10d, 同向 / 反向) may sit in a plain file."""
from scripts import run_insider_radar as RR
from src.pipelines.crawler_output import decrypt_data

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.96.1 大股東動向區塊 + 公開 / 加密分檔 (離線)")
print("=" * 72)

print("\n[A] 分檔: 分點大戶衍生的東西只在加密檔")
doc = {"generated_at": "2026-10-11T00:00:00", "notes": ["推算金額", "分點大戶資料 20260421～20261008"],
       "signals": {"A": [{"code": "1111"}], "B": [{"code": "1111", "branch_net_10d": 5}]},
       "backtest": {"A": {"all": {}}, "B": {"all": {}}, "layers_A": {}}}
pub, priv = RR.split_private(doc, {"B": doc["signals"]["B"]}, {"B": doc["backtest"]["B"]}, ["分點大戶資料 20260421～20261008"])
txt = json.dumps(pub, ensure_ascii=False)
check("公開檔沒有 B、沒有 branch_net、沒有分點說明", "B" not in pub["signals"] and "B" not in pub["backtest"]
      and "branch_net" not in txt and "分點" not in txt, txt)
check("A / 回測 A / 分層留在公開檔", pub["signals"]["A"] == doc["signals"]["A"] and "layers_A" in pub["backtest"])
check("加密檔裝 B、B 的回測、B 的說明", priv["signals"]["B"][0]["branch_net_10d"] == 5 and "B" in priv["backtest"] and priv["notes"])
with tempfile.TemporaryDirectory() as td:
    p = pathlib.Path(td) / RR.PRIVATE_NAME
    wrote = RR.write_private(p, priv, "unit-test-pw")
    env = json.loads(p.read_text(encoding="utf-8"))
    raw = p.read_text(encoding="utf-8")
    check("寫成和 daily_summary.json 一樣的加密信封, 明文看不到內容", wrote and env["encrypted"] is True and env["algorithm"] == "AES-256-GCM"
          and "branch_net" not in raw and "分點" not in raw)
    check("用密碼解得回來", json.loads(decrypt_data(env["data"], "unit-test-pw", env["iterations"])) == priv)
    src = (ROOT / "scripts" / "run_insider_radar.py").read_text(encoding="utf-8")
    check("產生器只加密不解密 (每日檔只經 read_day 讀, 有隔離過濾)", "decrypt_data" not in src and "from src.exports.transfer_watch import read_day" in src)

print("\n[B] 逐人明細 (抽屜用)")
recs = [{"role": "董事長", "name": "王大明", "kind": "本人", "market_buy": 1000, "market_sell": 0, "other_buy": 0, "other_sell": 0, "end_shares": 5000},
        {"role": "董事長", "name": "王大明(他人名義)", "kind": "利用他人名義持有者", "market_buy": 2000, "market_sell": 0, "other_buy": 0, "other_sell": 0, "end_shares": 2000},
        {"role": "經理", "name": "李四", "kind": "本人", "market_buy": 0, "market_sell": 0, "other_buy": 0, "other_sell": 0, "end_shares": 10}]
moved, quiet = RR.person_detail(recs)
check("他人名義併回本人、股數相加、記下身分種類", len(moved) == 1 and moved[0]["market_buy"] == 3000 and moved[0]["end_shares"] == 7000
      and moved[0]["kinds"] == ["本人", "利用他人名義持有者"], moved)
check("沒有變動的人只算人數", quiet == 1)
# 7689 2026-08 (owner check 2026-10-12): 本人 170,000 + 他人名義 增鐽電子 441,000 = 611,000; each official row stays visible
recs = [{"role": "董事長", "name": "張再發", "kind": "本人", "holder": "張再發", "market_buy": 170000, "market_sell": 0,
         "other_buy": 0, "other_sell": 0, "end_shares": 13649015},
        {"role": "董事長", "name": "張再發(他人名義)", "kind": "利用他人名義持有者", "holder": "增鐽電子股份有限公司",
         "market_buy": 441000, "market_sell": 0, "other_buy": 0, "other_sell": 0, "end_shares": 18153500},
        {"role": "協理", "name": "翟傳福", "kind": "本人", "holder": "翟傳福", "market_buy": 0, "market_sell": 6000,
         "other_buy": 0, "other_sell": 0, "end_shares": 0}]
moved, _ = RR.person_detail(recs)
p0 = moved[0].get("parts") or []
check("7689: 合計 611,000 / 31,802,515, 拆成本人 170,000 與 增鐽電子 441,000 兩列",
      moved[0]["market_buy"] == 611000 and moved[0]["end_shares"] == 31802515 and len(p0) == 2
      and p0[0] == {"kind": "本人", "holder": "", "market_buy": 170000, "market_sell": 0, "end_shares": 13649015}
      and p0[1]["holder"] == "增鐽電子股份有限公司" and p0[1]["market_buy"] == 441000, moved[0])
check("只有本人一列: 不加身分標籤也不拆列", moved[1]["kinds"] == [] and "parts" not in moved[1], moved[1])

print("\n[C] 現在的公開檔 (repo 是公開的)")
f = ROOT / "data" / "insider_radar.json"
if f.exists():
    t = f.read_text(encoding="utf-8")
    d = json.loads(t)
    check("沒有分點大戶衍生欄位 / 字樣", not any(w in t for w in ("branch_net", "同向", "反向", "分點")),
          [w for w in ("branch_net", "同向", "反向", "分點") if w in t])
    check("沒有對照組 B", "B" not in d.get("signals", {}) and "B" not in d.get("backtest", {}))
    rows = d["signals"].get("A", []) + d.get("sells", [])
    check("每列有頁面要的欄位", all({"code", "name", "side", "role", "role_group", "net_yi_est", "detail", "published", "signal_day"} <= set(r) for r in rows))
else:
    print("  (沒有 data/insider_radar.json, 略過)")

print("\n[D] 今日總整理 S08 區塊 (index.html)")
h = (ROOT / "index.html").read_text(encoding="utf-8")
check("抽屜把同一人的各列分開寫 (本人 + 他人名義)", "ins-parts" in h and "pp.parts" in h)
ds = h[h.index("function renderDailySummary()"):h.index("// ========== v3.90.0 detail drawer")]
js = h[h.index("// ========== v3.96.1 S08"):h.index("// ========== v3.94.0 every page a board")]
check("區塊放在今日總整理 (S08), 用同一套色帶", 'id="ekIns">${_insInner()}' in ds and 'class="ek-blk k-stocks ek-ins"' in ds
      and '<span class="ek-code">S<small>08</small></span>大股東動向' in js)
check("公開檔明文讀, 加密檔用同一套解密 (有密碼才讀)", "insider_radar.json" in js and "decryptToken(env.data, pw, env.iterations)" in js
      and "if (pw && typeof priv === 'string'" in js)
check("頁面只放前 5 列, 其餘在抽屜", "rows.slice(0, 5)" in js and "function _insAll()" in js and "_dsDrawer('stocks', 'S', '08'" in js)
check("標籤 = 職位 + 買 / 賣, 紅框買、綠框賣", "(_insSide(x) === 'buy' ? '買' : '賣')" in js
      and ".ek-ins-lb{justify-self:start;border:1px solid currentColor" in h and ".ek-ins-lb.buy{color:var(--red)}.ek-ins-lb.sell{color:var(--green)}" in h)
check("金額 ≥ 1 億寫億、以下寫萬, 標推算", "v >= 1 ? `${v.toFixed(1)} 億`" in js and "萬`" in js and "推算</small>" in js)
check("主數字 20 日, 5 / 10 / 60 用下拉選單", "let _INS_H = 20;" in js and "const _INS_HS = [5, 10, 20, 60];" in js and "onchange=\"_insSetH(this.value)\"" in js)
check("抽屜: 逐人明細六欄、標題句、公開日與訊號日、同身分回測", all(c in js for c in ("<th>姓名</th>", ">身分</th>", "集中買", "集中賣", "其它原因", "月底持股"))
      and "escHtml(x.headline || '')" in js and "_insDay(x.published)" in js and "_insDay(x.signal_day)" in js and "layers_sells" in js)
check("沒有訊號: 一行安靜的字, 不是錯誤", "沒有達門檻的大股東、董監、經理人買賣申報" in js and '<li class="ek-sub">' in js)
uses = list(re.finditer(r'\b(?:x|pp)\.(?:name|code|role|headline)\b', js))
raw = [js[max(0, m.start() - 12):m.end() + 4] for m in uses if not re.search(r'escHtml\($', js[max(0, m.start() - 8):m.start()])
       and not js[m.end():m.end() + 4] == ' ===' and not js[max(0, m.start() - 4):m.start()] == '=== '
       and not js[max(0, m.start() - 13):m.start()] == '_insPanoDraw(']   # comparisons and the chart's lookup key are not HTML
check("從資料來的名稱 / 代號 / 身分 / 標題句一律 escape (比較式除外)", len(uses) >= 8 and not raw, raw)
check("對照組 B 的說明只在 B 的列顯示", "(inB ? (INSIDER_PRIV || {}).notes || [] : [])" in js)
check("鎖定時清掉解出來的 B", "INSIDER_RADAR = null; INSIDER_PRIV = null; _INS_LOADING = null;" in h)
check("手機: 一列分兩行, 抽屜從下方拉出 (沿用)", re.search(r"@media \(max-width:560px\)\{\.ek-ins li\{grid-template-columns:22px minmax\(0,1fr\) auto", h) is not None
      and re.search(r'@media \(max-width:560px\)\{\s*\.dr\{top:auto;width:100vw', h) is not None)

print("\n[E] 年份選單 (v3.96.2): 每年一個視窗, 訊號只落在自己月份的那一年")
W = RR.WINDOWS
check("視窗由新到舊、首尾相接不重疊, 第一個是近一年", W[0][1] == "近一年" and all(RR.next_ym(W[i + 1][3]) == W[i][2] for i in range(len(W) - 1))
      and all(w[2] <= w[3] for w in W), W)
sig = [{"code": "1111", "ym": ym} for ym in ("202608", "202509", "202508", "202410", "202409", "202309", "202308")]
homes = {s["ym"]: [w[0] for w in W if s in RR.in_window(sig, w[2], w[3])] for s in sig}
check("每筆訊號只在一個視窗 (邊界月份也一樣); 範圍外的不進任何一個",
      homes == {"202608": ["y1"], "202509": ["y1"], "202508": ["y2"], "202410": ["y2"], "202409": ["y3"], "202309": ["y3"], "202308": []}, homes)
built = {m: {"1111"} for m in RR.month_list("202410", "202608")}
q = [[1, "202509", "1111"], [1, "202510", "2222"], [0, "202410", "3333"]]
check("抓取狀態: 佇列裡還沒建好的頁 → 抓取中, 有幾頁", RR.fetch_state("202509", "202608", built, q) == (1, True))
check("佇列從較晚月份開始 → 這一年還沒排進來, 算抓取中 (不知道還有幾頁)", RR.fetch_state("202410", "202508", built, q) == (None, True))
check("缺月份的檔 → 抓取中", RR.fetch_state("202309", "202409", built, None) == (None, True))
check("全部建好 → 不是抓取中", RR.fetch_state("202509", "202608", built, [[1, "202509", "1111"]]) == (0, False))
if f.exists():
    ys = d.get("years") or []
    check("公開檔有 years[], 最新一年也留在最上層 (舊讀法不壞)", [y["key"] for y in ys] == [w[0] for w in W]
          and ys[0]["signals"]["A"] == d["signals"]["A"] and ys[0]["sells"] == d["sells"])
    check("每年的訊號都在自己的月份範圍內", all(y["since"] <= x["ym"] <= y["until"] for y in ys for x in y["signals"]["A"] + y["sells"]))
    check("每年的 scope 有頁數 / 公司月 / 是否抓取中", all({"pages", "company_months", "fetching", "pending_pages"} <= set(y["scope"]) for y in ys))
src_r = (ROOT / "scripts" / "run_insider_radar.py").read_text(encoding="utf-8")
check("「第一次大買」回看從逐人資料起點算 (不是視窗起點), 沒抓完的年不算", "big_buys_a(rows, years=1, data_start=data_start)" in src_r
      and "if fetch_state(since, until, built, queue)[1]:" in src_r)
check("加密檔也照年份分 B", 'priv["years"] = priv_years' in src_r)
check("頁面: 年份選單在持有天數旁邊, 切換後列表 / 全部 / 抽屜 / 回測都讀選的那一年",
      'aria-label="年份" onchange="_insSetY(this.value)"' in js and "${yopt}同身分訊號過去" in js
      and "const d = _insWin();" in js and "(((_insWin().backtest || {})[key]" in js and "win = _insWin(), bt = win.backtest" in js
      and "const privB = (pw.signals || {}).B || [];" in js)
check("頁面: 抓取中的年說「資料抓取中（已抓 N 頁）」, 不把 0 當結果", "資料抓取中（已抓 ${Number(sc.pages) || 0} 頁" in js
      and "fetching || `<li class=\"ek-sub\">${what}</li>`" in js)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
