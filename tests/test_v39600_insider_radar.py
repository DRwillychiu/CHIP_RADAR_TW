# v3.96.0 insider radar stage 2: merge, change, rule A / B, signal day, event returns - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Spec docs/specs/INSIDER_RADAR_SPEC.md section 5. Synthetic data only; the owner's real cases
(考題) are added when stage 1 delivers real records."""
from src.analyzers import insider_radar as R

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.96.0 大股東籌碼雷達 第 2 階段 (離線)")
print("=" * 72)
print("\n[A] 歸戶")
check("「他人名義」併回本人", R.base_name("王大明(他人名義)") == "王大明" and R.base_name("王大明（他人名義）") == "王大明")
rec = [
    {"code": "1111", "ym": "202609", "role": "董事長", "name": "王大明", "delta_shares": 1_000_000, "end_shares": 5_000_000, "declared_on": "20261005"},
    {"code": "1111", "ym": "202609", "role": "董事長", "name": "王大明(他人名義)", "delta_shares": 2_000_000, "end_shares": 2_000_000, "declared_on": "20261008"},
    {"code": "1111", "ym": "202609", "role": "董事", "name": "李小華", "delta_shares": 500_000, "end_shares": 900_000},
    {"code": "1111", "ym": "202609", "role": "經理人", "name": "張三", "delta_shares": -100_000, "end_shares": 0},
]
ppl = R.merge_people(rec)
wang = [p for p in ppl if p["name"] == "王大明"]
check("同人同月合成一列, 股數相加、取最晚申報日", len(wang) == 1 and wang[0]["delta_shares"] == 3_000_000 and wang[0]["declared_on"] == "20261008" and wang[0]["nominee"], wang)
check("標籤: 董事長(他人名義) 等 2 人 / 賣方 經理人", R.role_label(ppl, 1) == "董事長(他人名義) 等 2 人" and R.role_label(ppl, -1) == "經理人", (R.role_label(ppl, 1), R.role_label(ppl, -1)))

print("\n[B] 變化與推算金額")
cm = R.company_months(ppl, {("1111", "202609"): 40.0}, {"1111": 1_000_000_000})[("1111", "202609")]
check("淨買股數 = 3,400,000; 推算金額 = 股數 × 月均價 (億)", cm["net_shares"] == 3_400_000 and cm["net_yi_est"] == 1.36, cm)
check("占股本 %", cm["pct_of_shares"] == 0.34, cm["pct_of_shares"])
check("沒有月均價就不推算 (不亂填)", R.company_months(ppl, {}, None)[("1111", "202609")]["net_yi_est"] is None)

print("\n[C] 訊號日 = 資料公開後第一個交易日 (不偷看未來)")
td = ["20261001", "20261002", "20261005", "20261006", "20261007", "20261008", "20261013", "20261014", "20261015", "20261016",
      "20261019", "20270104", "20270115", "20270118"]
check("有申報日: 申報日的下一個交易日", R.signal_day("202609", "20261008", td) == "20261013")
check("沒申報日: 次月 15 日截止後的下一個交易日", R.signal_day("202609", None, td) == "20261016")
check("12 月 → 隔年 1 月 15 日後", R.signal_day("202612", None, td) == "20270118")
check("絕不用月底當訊號日", R.signal_day("202609", None, td) > "20260930")

print("\n[D] 對照組 A (參考網站規則)")
def row(ym, net, yi, pct):
    return {"code": "2222", "ym": ym, "net_shares": net, "net_yi_est": yi, "pct_of_shares": pct}
hist = [row(f"{2024 + (m - 1) // 12}{(m - 1) % 12 + 1:02d}", 0, 0.0, 0.0) for m in range(8, 32)]   # 2024-08 .. 2026-07, no buys
a = R.big_buys_a(hist + [row("202609", 1, 0.3, 0.25)])
check("2 年來第一次大買且 ≥ 0.2% → 入選", [x["ym"] for x in a] == ["202609"] and a[0]["why"] == "2 年來第一次大買", a)
a2 = R.big_buys_a(hist + [row("202608", 1, 0.3, 0.25), row("202609", 1, 0.3, 0.25)])
check("2 年內已經大買過 → 第二次不算「第一次」", [x["ym"] for x in a2 if x["why"] == "2 年來第一次大買"] == ["202608"], [x["ym"] for x in a2])
check("歷史不滿 2 年 → 不能判「第一次」", R.big_buys_a([row("202608", 0, 0, 0), row("202609", 1, 0.3, 0.25)]) == [])
check("資料起點滿 1 年、該公司只有這一個月 → 1 年來第一次", [x["why"] for x in R.big_buys_a([row("202609", 1, 0.3, 0.25)], years=1, data_start="202509")] == ["1 年來第一次大買"])
check("資料起點不滿 1 年 → 不判「第一次」", R.big_buys_a([row("202609", 1, 0.3, 0.25)], years=1, data_start="202510") == [])
check("淨買 ≥ 1 億 → 入選 (不看歷史)", [x["why"] for x in R.big_buys_a([row("202609", 1, 1.2, 0.01)])] == ["淨買 ≥ 1 億"])
check("淨賣不算大買", R.big_buys_a([row("202609", -5, -3.0, -1.0)]) == [])

print("\n[E] 對照組 B (加上我們的分點大戶)")
sig = [{"code": "2222", "ym": "202609", "signal_day": "20261016"}]
check("訊號日前 10 個交易日大戶淨買 > 0 → 入選", len(R.group_b(sig, {("2222", "20261014"): 500}, trading_days=td)) == 1)
check("大戶淨賣 → 不入選", R.group_b(sig, {("2222", "20261014"): -500}, trading_days=td) == [])
check("訊號日當天的大戶買進不算 (只看之前)", R.group_b(sig, {("2222", "20261016"): 500}, trading_days=td) == [])

print("\n[F] 事件報酬 (超額 = 個股 − 大盤)")
days = [f"2026{m:02d}{d:02d}" for m in (10, 11) for d in range(1, 29)]
idx = {d: 100.0 for d in days}
px = {"2222": {d: (100.0 if i <= 3 else 110.0) for i, d in enumerate(days)}}
res = R.event_returns([{"code": "2222", "ym": "202609", "signal_day": days[3]}], px, idx, horizons=(5,))
check("訊號日收盤買、5 日後 +10%、大盤 0% → 超額 +10", res and res[0].get("ex5") == 10.0, res)
check("跟單實際報酬扣成本 0.585% → +9.42", res and res[0].get("r5") == 10.0 and res[0].get("n5") == 9.42, res)
s = R.summarize(res + [{"code": "x", "ym": "202610", "signal_day": "20261120", "ex5": -2.0}], horizons=(5,), split_day="20261101")
check("樣本內 / 樣本外分開算", s["in"]["n"] == 1 and s["out"]["n"] == 1 and s["all"]["ex5"]["hit"] == 50.0, s)

print("\n[G] 逐人明細篩選 (彙總表只篩選)")
from src.fetchers import insider_monthly as IM
mo = {"companies": {
    "1111": {"issued": 100_000_000, "dir_inc": 200_000, "dir_dec": 0},          # 0.2 % -> buy side
    "2222": {"issued": 100_000_000, "dir_inc": 0, "dir_dec": 300_000},          # 0.3 % -> sell side
    "3333": {"issued": 10_000_000_000, "dir_inc": 200_000, "dir_dec": 0},       # 0.002 % but 200k x 600 = 1.2 億
    "4444": {"issued": 100_000_000, "dir_inc": 100_000, "dir_dec": 100_000},    # small, but in IRB140
    "5555": {"issued": 100_000_000, "dir_inc": 199_999, "dir_dec": 0}},         # just under -> out
    "transfers": [{"code": "4444"}]}
got = dict((c, p) for p, c in IM.screen(mo, {"3333": 600.0, "5555": 10.0}))
check("買方 / 賣方 / ≥1 億 / 只在大額轉讓表 / 未達門檻", got == {"1111": 1, "2222": 2, "3333": 1, "4444": 3}, got)

prev = {"companies": {"6666": {"issued": 100_000_000, "big10_held": 30_000_000, "mgr_held": 0}}}
cur = {"companies": {"6666": {"issued": 100_000_000, "dir_inc": 0, "dir_dec": 0, "big10_held": 36_600_000, "mgr_held": 0}}}
check("董監沒動、大股東持股變 6.6% → 優先序 4 (2515 2025-10 抽查漏網)", IM.screen(cur, {}, prev) == [(4, "6666")], IM.screen(cur, {}, prev))
check("沒給上個月 → 不判優先序 4", IM.screen(cur, {}) == [])
check("非 4 位數代號不進篩選 (負責人：台灣公司代碼只有 4 位)", IM.screen({"companies": {"674191": {"issued": 100_000_000, "dir_inc": 5_000_000, "dir_dec": 0}}}, {}) == [])

print("\n[I] 逐人明細去重 (2540 2024-10 同一筆持股列在兩種身分)")
def _row(role, name, inc, dec, end):
    return (f"<tr><td>{role}</td><td>{name}</td><td>普通股</td><td>0</td><td>{inc[0]:,} {inc[1]:,} 0 0 0</td>"
            f"<td>{dec[0]:,} {dec[1]:,} 0 0 0</td><td>{end:,} 0 0 0</td></tr>")
pg = ("<table>" + _row("董事本人", "仰山林廣告有限公司", (2024000, 0), (0, 0), 86602972)
      + _row("董事法人代表人利用他人名義持有者", "仰山林廣告有限公司", (2024000, 0), (0, 0), 86602972)
      + _row("大股東本人", "仰山林廣告有限公司", (2024000, 0), (0, 0), 86602972) + "</table>")
rs = IM.parse_query6_1(pg, "2540", "202410")
check("同名同數字的三列只算一次 (官方註：勿重複累計)", sum(r["market_buy"] for r in rs) == 2024000, [(r["role"], r["kind"], r["market_buy"]) for r in rs])

print("\n[H] 抓取時遇到的正常答案 (16:08 4130、16:15 2884 踩到的坑)")
from scripts import fetch_insider_people as FP
check("「不繼續公開發行」是答案不是錯誤", FP.page_ok("<h2>該 4130 公開發行公司不繼續公開發行！</h2>".encode()))
check("沒有表格的其他頁面 → 當錯誤停下", not FP.page_ok(b"<html>502 Bad Gateway</html>"))
pick = ("<h2>請點選欲查詢之公司：</h2><form name='fm1'><input type='hidden' name='co_id' value='2884'>"
        "<input type='hidden' name='KIND' value='1'></form><form name='fm1'><input type='hidden' name='co_id' value='28840001'></form>").encode()
check("金控選單 → 接著查控股公司本身", FP.picker_form(pick, "2884") == {"co_id": "2884", "KIND": "1"}, FP.picker_form(pick, "2884"))
check("一般明細頁不是選單", FP.picker_form("<th>身份別</th>".encode(), "8114") is None)
check("空的公司選單 (674191 2026-03) 是「沒資料」的答案，不是錯誤", FP.page_ok("<h2>請點選欲查詢之公司：</h2><BR><BR></div>".encode()))

print("\n[J] 抓取節奏 (負責人 2026-10-12：白天每 90 秒 7 頁，30 分鐘內錯 2 次或 21:30 以後 120 秒)")
check("白天沒出錯 → 90 秒", FP.pick_cycle(90, 120, [], 5000.0, "10:05") == (90, False))
check("30 分鐘內只錯 1 次 → 還是 90 秒", FP.pick_cycle(90, 120, [4000.0], 5000.0, "10:05") == (90, False))
check("30 分鐘內錯 2 次 → 120 秒", FP.pick_cycle(90, 120, [3300.0, 4900.0], 5000.0, "10:05") == (120, True))
check("兩次錯隔超過 30 分鐘 → 90 秒", FP.pick_cycle(90, 120, [1000.0, 4900.0], 5000.0, "10:05") == (90, False))
check("因為出錯退回後，整個執行都維持 120 秒", FP.pick_cycle(90, 120, [], 99999.0, "13:00", slowed=True) == (120, True))
check("21:30 以後 → 120 秒，早上 07:00 回到 90 秒", FP.pick_cycle(90, 120, [], 0.0, "21:30")[0] == 120
      and FP.pick_cycle(90, 120, [], 0.0, "06:59")[0] == 120 and FP.pick_cycle(90, 120, [], 0.0, "07:00")[0] == 90)
ch = (pathlib.Path(__file__).resolve().parent.parent / "scripts" / "fetch_insider_chain.sh").read_text(encoding="utf-8")
check("三年的抓取都帶 --slow-cycle", ch.count('--slow-cycle "$S"') == 3)

print("\n[K] 持股等式檢查 (scripts/check_insider_identity.py, 驗證關卡 1)")
from scripts import check_insider_identity as CI
def _row6(prev, inc, dec, end):
    return (f"<tr><td>董事本人</td><td>甲</td><td>普通股</td><td>0 {prev:,} 0 0 0</td><td>{inc[0]:,} {inc[1]:,} {inc[2]:,} 0 0</td>"
            f"<td>{dec[0]:,} {dec[1]:,} {dec[2]:,} 0 0</td><td>{end:,} 0 0 0 0</td></tr>")
ok_pg = "<table>" + _row6(13479015, (170000, 0, 0), (0, 0, 0), 13649015) + _row6(6000, (0, 0, 0), (6000, 0, 0), 0) + "</table>"
check("加得起來的列 (7689 張再發、翟傳福 2026-08) → 0 錯", CI.check_page(ok_pg) == (2, []), CI.check_page(ok_pg))
bad_pg = "<table>" + _row6(13479015, (170000, 0, 0), (0, 0, 0), 13649000) + "</table>"
check("差 15 股也抓得到", CI.check_page(bad_pg)[0] == 1 and len(CI.check_page(bad_pg)[1]) == 1, CI.check_page(bad_pg))
print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
