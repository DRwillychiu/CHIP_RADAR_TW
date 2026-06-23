"""v3.63.2 Dashboard 完整交叉驗證 — 比對每一筆顯示值 vs 原始計算

策略:
  1. 用 6/18 真實 daily_trading_signals.json + master_profiles.json 構造輸入
  2. 用合成 branches_data (從 6/18 一個追蹤 master + 一個非追蹤 master 模擬)
  3. 渲染 Dashboard
  4. 逐 section 比對 Excel cell value vs 獨立計算的 ground truth
  5. 列出所有 mismatch (應為 0)
"""
import sys, json, re
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from src.exports.excel_report import (
    build_dashboard_sheet, TRACKED_MASTERS, MASTER_MAPPING,
    _is_tracked_master, _filter_tracked_branches, _round_safe, _severity_from_z,
)

errors = []
def err(section, expected, actual, note=''):
    errors.append((section, expected, actual, note))

def warn(section, msg):
    errors.append((section, '⚠️', msg, 'WARN'))

# === Load data ===
with open(ROOT/'data'/'daily_trading_signals.json', 'r', encoding='utf-8') as f:
    signals = json.load(f)
with open(ROOT/'data'/'master_profiles.json', 'r', encoding='utf-8') as f:
    profiles = json.load(f)

# === Synthetic branches_data — match real Excel display ===
# 用 5 個追蹤 master 各 1 branch + 1 個非追蹤 master 來驗 filter
branches_data = [
    {'code': '9B25', 'name': '台新-五權西', 'master': '民哥', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_lot': 100, 'sell_lot': 20,
         'buy_amt': 250000, 'sell_amt': 50000, 'net_lot': 80,
         'buy_avg': 2500.0, 'sell_avg': 2500.0, 'close_price': 2500.0,
         'change_pct': 1.0, 'is_limit_up': False},
        {'code': '2454', 'name': '聯發科', 'buy_lot': 30, 'sell_lot': 5,
         'buy_amt': 90000, 'sell_amt': 15000, 'net_lot': 25,
         'buy_avg': 3000.0, 'sell_avg': 3000.0, 'close_price': 3000.0,
         'change_pct': 9.9, 'is_limit_up': True},
    ], 'sells': []},
    # 民哥 第 2 分點也買 2330 — 驗證單一 master 多分點 = ≥2 分點
    {'code': '9666', 'name': '富邦-南屯', 'master': '民哥', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_lot': 60, 'sell_lot': 10,
         'buy_amt': 150000, 'sell_amt': 25000, 'net_lot': 50,
         'buy_avg': 2500.0, 'sell_avg': 2500.0, 'close_price': 2500.0,
         'change_pct': 1.0, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9658', 'name': '富邦-建國', 'master': '林滄海', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_lot': 50, 'sell_lot': 10,
         'buy_amt': 125000, 'sell_amt': 25000, 'net_lot': 40,
         'buy_avg': 2500.0, 'sell_avg': 2500.0, 'close_price': 2500.0,
         'change_pct': 1.0, 'is_limit_up': False},
        {'code': '2317', 'name': '鴻海', 'buy_lot': 200, 'sell_lot': 50,
         'buy_amt': 30000, 'sell_amt': 7500, 'net_lot': 150,
         'buy_avg': 150.0, 'sell_avg': 150.0, 'close_price': 150.0,
         'change_pct': 9.85, 'is_limit_up': True},
    ], 'sells': []},
    {'code': '779Z', 'name': '國票-安和', 'master': '張濬安(航海王)', 'buys': [
        {'code': '00919', 'name': '群益台灣精選高息', 'buy_lot': 10000, 'sell_lot': 0,
         'buy_amt': 200000, 'sell_amt': 0, 'net_lot': 10000,
         'buy_avg': 20.0, 'sell_avg': 0.0, 'close_price': 20.0,
         'change_pct': 0.5, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9217', 'name': '凱基-松山', 'master': '迷你哥/松山哥', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_lot': 20, 'sell_lot': 20,
         'buy_amt': 50000, 'sell_amt': 50000, 'net_lot': 0,
         'buy_avg': 2500.0, 'sell_avg': 2500.0, 'close_price': 2500.0,
         'change_pct': 1.0, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9B2a', 'name': '台新-松德', 'master': 'Tradow', 'buys': [
        {'code': '00919', 'name': '群益台灣精選高息', 'buy_lot': 5000, 'sell_lot': 0,
         'buy_amt': 100000, 'sell_amt': 0, 'net_lot': 5000,
         'buy_avg': 20.0, 'sell_avg': 0.0, 'close_price': 20.0,
         'change_pct': 0.5, 'is_limit_up': False},
    ], 'sells': []},
    # 非追蹤 master — 必須被過濾
    {'code': '888A', 'name': '國泰-館前', 'master': '江士勳', 'buys': [
        {'code': '9999', 'name': '不應出現股', 'buy_lot': 99999, 'sell_lot': 0,
         'buy_amt': 9999999, 'sell_amt': 0, 'net_lot': 99999,
         'buy_avg': 100.0, 'sell_avg': 0.0, 'close_price': 100.0,
         'change_pct': 0.0, 'is_limit_up': False},
    ], 'sells': []},
]

# v3.63.6: 構造 10+ 大戶共識個案 (TESTSTK 9988) 驗證 MIN_MASTER_COUNT=10 篩選
# 從 MASTER_MAPPING 取前 10 位每個各 1 個 branch 都買 9988
from src.exports.excel_report import MASTER_MAPPING
for idx, m in enumerate(MASTER_MAPPING[:10]):
    branch_code, branch_name = m['branches'][0]
    branches_data.append({
        'code': f'TEST{idx:02d}', 'name': branch_name, 'master': m['name'], 'buys': [
            {'code': '9988', 'name': '強共識股', 'buy_lot': 100, 'sell_lot': 10,
             'buy_amt': 100000 + idx * 1000, 'sell_amt': 10000, 'net_lot': 90,
             'buy_avg': 100.0, 'sell_avg': 100.0, 'close_price': 100.0,
             'change_pct': 1.0, 'is_limit_up': False},
            # v3.63.7: 同時加 ETF 00919, 10 大戶都買 -> 應該被 ETF filter 剔除
            {'code': '00919', 'name': '群益台灣精選高息', 'buy_lot': 1000, 'sell_lot': 0,
             'buy_amt': 200000, 'sell_amt': 0, 'net_lot': 1000,
             'buy_avg': 20.0, 'sell_avg': 0.0, 'close_price': 20.0,
             'change_pct': 0.5, 'is_limit_up': False},
        ], 'sells': []
    })

# === Render dashboard ===
wb = Workbook()
ws = wb.active
ws.title = 'Dashboard'
build_dashboard_sheet(ws, branches_data, '20260618', ROOT/'data')

# === Re-load for inspection ===
out_path = ROOT/'data'/'reports'/'_xvalidate_dashboard.xlsx'
wb.save(str(out_path))
wb2 = load_workbook(str(out_path))
ws2 = wb2['Dashboard']

print(f"Total rows rendered: {ws2.max_row}\n")

# Helper: get cell value by addr
def cell(addr):
    v = ws2[addr].value
    return v

# === Ground truth (independent calc, only tracked branches) ===
filtered = [b for b in branches_data if b['master'] in TRACKED_MASTERS]
assert len(filtered) == 16, f"filter should yield 16 (6 original + 10 high-consensus), got {len(filtered)}"

# A. 規模統計 — v3.64.1+ 三 bug 修復 + v3.64.2 Excel-native cell types
# GT 計算對齊 production 邏輯
gt_total_buy = sum(s.get('buy_amt', 0) for b in filtered for s in b.get('buys', []))
# Bug 1 fix: dedup by (branch_code, stock_code) — sell_amt 只算一次
_seen_sell = set()
gt_total_sell = 0
for _b in filtered:
    _bcode = _b.get('code', '')
    for _s in (_b.get('buys', []) or []) + (_b.get('sells', []) or []):
        _key = (_bcode, _s.get('code'))
        if _key in _seen_sell: continue
        _seen_sell.add(_key)
        gt_total_sell += _s.get('sell_amt', 0) or 0
gt_total_net = gt_total_buy - gt_total_sell
gt_master_active = len({b['master'] for b in filtered if b.get('buys')})
# Bug 3 fix: distinct stocks = buys ∪ sells
gt_distinct_stocks = len({s['code'] for b in filtered
                          for s in (b.get('buys', []) or []) + (b.get('sells', []) or [])
                          if s.get('code')})
gt_limit_up = sum(1 for b in filtered for s in (b.get('buys', []) or []) if s.get('is_limit_up'))
# Bug 2 fix: 分點覆蓋分母改用 MASTER_MAPPING unique branches
gt_active_branches = len({b['code'] for b in filtered if b.get('buys')})
gt_tracked_codes = {code for m in MASTER_MAPPING for code, _ in m['branches']}
gt_total_watched = len(gt_tracked_codes)
gt_coverage_ratio = gt_active_branches / gt_total_watched if gt_total_watched else 0

print(f"=== Section A: 規模統計 (v3.64.2 strict assertions) ===")
print(f"  GT 活躍 Master: {gt_master_active}")
print(f"  GT 個股涉及: {gt_distinct_stocks}")
print(f"  GT 分點覆蓋: {gt_active_branches}/{gt_total_watched} = {gt_coverage_ratio:.4f}")
print(f"  GT 總買進: {gt_total_buy/100000:.2f} 億 (cell={gt_total_buy/100000})")
print(f"  GT 總賣出: {gt_total_sell/100000:.2f} 億 (cell={gt_total_sell/100000})")
print(f"  GT 淨買差: {gt_total_net/100000:.2f} 億 (cell={gt_total_net/100000})")

# 找 Section A 的兩列 — _section_header「▍ A. 規模統計」之後的下 2 行
sec_a_start = None
for r in range(3, ws2.max_row + 1):
    v = cell(f'B{r}')
    if v and isinstance(v, str) and 'A. 規模統計' in v:
        sec_a_start = r + 1
        break

if sec_a_start is None:
    err('A', '找到 Section A', None, 'header missing')
else:
    # row1: 活躍 Master (C) / 個股涉及 (F) / 分點覆蓋 (I)
    # row2: 總買進 (C) / 總賣出 (F) / 淨買差 (I)
    r1, r2 = sec_a_start, sec_a_start + 1
    actual = {
        '活躍 Master':  cell(f'C{r1}'),
        '個股涉及':     cell(f'F{r1}'),
        '分點覆蓋':     cell(f'I{r1}'),
        '總買進':       cell(f'C{r2}'),
        '總賣出':       cell(f'F{r2}'),
        '淨買差':       cell(f'I{r2}'),
    }
    print(f"  Excel row {r1}: 活躍={actual['活躍 Master']!r}, 個股={actual['個股涉及']!r}, 覆蓋={actual['分點覆蓋']!r}")
    print(f"  Excel row {r2}: 買={actual['總買進']!r}, 賣={actual['總賣出']!r}, 淨={actual['淨買差']!r}")

    # === STRICT 數值比對 (cell value 為 native int/float) ===
    def _approx(a, b, tol=1e-6):
        if a is None or b is None: return a == b
        return abs(float(a) - float(b)) < tol

    if actual['活躍 Master'] != gt_master_active:
        err('A', gt_master_active, actual['活躍 Master'], '活躍 Master')
    if actual['個股涉及'] != gt_distinct_stocks:
        err('A', gt_distinct_stocks, actual['個股涉及'], '個股涉及')
    if not _approx(actual['分點覆蓋'], gt_coverage_ratio):
        err('A', gt_coverage_ratio, actual['分點覆蓋'], '分點覆蓋 ratio')
    if not _approx(actual['總買進'], gt_total_buy / 100000):
        err('A', gt_total_buy / 100000, actual['總買進'], '總買進 億')
    if not _approx(actual['總賣出'], gt_total_sell / 100000):
        err('A', gt_total_sell / 100000, actual['總賣出'], '總賣出 億')
    if not _approx(actual['淨買差'], gt_total_net / 100000):
        err('A', gt_total_net / 100000, actual['淨買差'], '淨買差 億')

    # === Excel-native 型別檢查 (v3.64.2: 必須是 numeric 不是字串) ===
    for label, val in actual.items():
        if val is not None and isinstance(val, str):
            err('A', 'int/float (Excel-native)', f'str: {val!r}', f'{label} 型別不是 numeric')

# Check Section B / C
print(f"\n=== Section B: Top 5 高手 ===")
gt_master_amt = {}
for b in filtered:
    m = b['master']
    amt = sum(s['buy_amt'] for s in b['buys'])
    gt_master_amt[m] = gt_master_amt.get(m, 0) + amt
gt_top_masters = sorted(gt_master_amt.items(), key=lambda x: -x[1])
gt_total_all = sum(gt_master_amt.values())
print(f"  GT total_all = {gt_total_all} 千元")
for i, (m, amt) in enumerate(gt_top_masters):
    pct = amt/gt_total_all*100
    print(f"  GT  #{i+1}: {m} = {amt} 千元 (= {round(amt/10,0)} 萬), {pct:.1f}%")

# Find Section B start (look for "Top 5 高手" header)
b_start = None
for r in range(4, 20):
    v = cell(f'B{r}')
    if v and isinstance(v, str) and 'Top 5 高手' in v:
        b_start = r + 2  # +1 hdr +1 col-header
        break
print(f"  Section B data starts at row {b_start}")
if b_start:
    for i in range(5):
        rank = cell(f'B{b_start+i}')
        name = cell(f'C{b_start+i}')
        amt_wan = cell(f'D{b_start+i}')
        pct = cell(f'E{b_start+i}')
        if name is None:
            print(f"  Excel #{i+1}: (empty)")
            continue
        # GT for this rank
        if i < len(gt_top_masters):
            gt_m, gt_a = gt_top_masters[i]
            gt_wan = round(gt_a / 10, 0)
            gt_pct_str = f"{gt_a/gt_total_all*100:.1f}%"
            ok_name = (name == gt_m)
            ok_amt = (amt_wan == gt_wan)
            ok_pct = (pct == gt_pct_str)
            print(f"  Excel #{i+1}: {name}={amt_wan}萬, {pct}")
            if not ok_name: err('B', gt_m, name, f'#{i+1} master')
            if not ok_amt: err('B', gt_wan, amt_wan, f'#{i+1} amt')
            if not ok_pct: err('B', gt_pct_str, pct, f'#{i+1} pct')

# v3.63.7: ETF (00919) 即使 10 大戶買也應被剔除
print(f"\n=== ETF 排除驗證 ===")
# 直接掃 ws2 整張 sheet 內容找 00919 字串
etf_text = []
for row_cells in ws2.iter_rows(values_only=True):
    for v in row_cells:
        if v is not None:
            etf_text.append(str(v))
sec0_text = []
for r in range(4, ws2.max_row+1):
    v = cell(f'B{r}')
    if v and isinstance(v, str) and '強共識買超' in v:
        # 從這行 +1 (col header) +1 開始, 到下個 section header 為止
        for rr in range(r+2, min(r+50, ws2.max_row+1)):
            for c in 'BCDEFGHIJKLMN':
                vv = cell(f'{c}{rr}')
                if vv is not None:
                    sec0_text.append(str(vv))
            # 偵測下個 section header (▍ 開頭)
            vv = cell(f'B{rr}')
            if vv and isinstance(vv, str) and vv.startswith('▍'):
                break
        break
sec0_str = ' | '.join(sec0_text)
if '00919' in sec0_str:
    err('ETF_FILTER', '不應出現', '00919', 'ETF 出現在 Section 0')
else:
    print(f"  ✓ 00919 群益台灣精選高息 (ETF) 已被 Section 0 排除")

# Check 江士勳 (non-tracked) does NOT appear anywhere
print(f"\n=== 非追蹤 master 過濾驗證 ===")
forbidden = ['江士勳', '何莎', '優式資本', '東億資本', 'Krenz(再多一位數本人)', '志誠資本',
             '林適中', '謝明彧大哥(華南永昌)', '宋福祥', '呂金發', '陳光裕', '謝孟恭(股癌)',
             '丁凌全', '江士勳', '劉子豪', '陳泊澔', '嘉義幫']
all_text = []
for row_cells in ws2.iter_rows(values_only=True):
    for v in row_cells:
        if v is not None:
            all_text.append(str(v))
all_str = ' | '.join(all_text)
for m in forbidden:
    if m in all_str:
        err('FILTER', '不應出現', m, '非追蹤大戶洩漏')
    else:
        print(f"  ✓ {m} 未出現")

# Section E: anomaly first row 比對
print(f"\n=== Section E: 異常警報資料正確性 ===")
tracked_anom = [s for s in (signals.get('anomalies') or [])
                if s.get('master') in TRACKED_MASTERS][:15]
if tracked_anom:
    first = tracked_anom[0]
    expected_amt = _round_safe(first.get('today_buy_amt_wan'))
    expected_desc = first.get('description', '—')
    expected_sev = _severity_from_z(first.get('z_score'))
    print(f"  GT first anomaly: master={first.get('master')}, today_buy_amt_wan={first.get('today_buy_amt_wan')} -> rounded={expected_amt}")
    print(f"  GT severity from z={first.get('z_score')}: {expected_sev}")
    # Find first 🔴 row
    for r in range(4, ws2.max_row+1):
        v = cell(f'B{r}')
        if v == '🔴 異常':
            actual_master = cell(f'C{r}')
            actual_sev = cell(f'D{r}')
            actual_desc = cell(f'E{r}')
            actual_amt = cell(f'F{r}')
            print(f"  Excel: master={actual_master}, sev={actual_sev}, desc={actual_desc[:60] if actual_desc else None}..., amt={actual_amt}")
            if actual_master != first.get('master'):
                err('E.anom', first.get('master'), actual_master, 'master')
            if actual_sev != expected_sev:
                err('E.anom', expected_sev, actual_sev, 'severity')
            if actual_desc != expected_desc:
                err('E.anom', expected_desc[:40], (actual_desc or '')[:40], 'description')
            if actual_amt != expected_amt:
                err('E.anom', expected_amt, actual_amt, 'amount')
            break

# Section E: accumulation 第一筆
tracked_acc = [s for s in (signals.get('accumulations') or [])
               if s.get('master') in TRACKED_MASTERS][:15]
if tracked_acc:
    first = tracked_acc[0]
    expected_master_stock = f"{first.get('master', '?')} → {first.get('stock_code', '?')}"
    expected_amt = _round_safe(first.get('total_buy_amt_wan'))
    expected_desc = first.get('description', '—')
    print(f"\n  GT first accumulation: {expected_master_stock}, total_buy_amt_wan={first.get('total_buy_amt_wan')} -> {expected_amt}")
    for r in range(4, ws2.max_row+1):
        v = cell(f'B{r}')
        if v == '🟢 連續加碼':
            actual_pair = cell(f'C{r}')
            actual_desc = cell(f'E{r}')
            actual_amt = cell(f'F{r}')
            print(f"  Excel: {actual_pair}, desc={actual_desc[:60] if actual_desc else None}..., amt={actual_amt}")
            if actual_pair != expected_master_stock:
                err('E.acc', expected_master_stock, actual_pair, 'master->stock')
            if actual_amt != expected_amt:
                err('E.acc', expected_amt, actual_amt, 'amount')
            if actual_desc != expected_desc:
                err('E.acc', expected_desc[:40], (actual_desc or '')[:40], 'description')
            break

# Section F: 第一筆 accumulation (top 30 sorted by consecutive_days)
print(f"\n=== Section F: 跨日連續囤貨資料正確性 ===")
all_acc_sorted = sorted(
    [s for s in (signals.get('accumulations') or []) if s.get('master') in TRACKED_MASTERS],
    key=lambda x: -x.get('consecutive_days', 0)
)
if all_acc_sorted:
    first = all_acc_sorted[0]
    print(f"  GT #1: master={first.get('master')}, code={first.get('stock_code')}, "
          f"days={first.get('consecutive_days')}, amt={_round_safe(first.get('total_buy_amt_wan'))}")
    # Find Section F start
    f_start = None
    for r in range(4, ws2.max_row+1):
        v = cell(f'B{r}')
        if v and isinstance(v, str) and '跨日連續囤貨' in v:
            f_start = r + 2  # +1 hdr +1 col-header
            break
    if f_start:
        actual_master = cell(f'B{f_start}')
        actual_code = cell(f'C{f_start}')
        actual_days = cell(f'D{f_start}')
        actual_amt = cell(f'E{f_start}')
        actual_desc = cell(f'F{f_start}')
        print(f"  Excel F top: master={actual_master}, code={actual_code}, days={actual_days}, amt={actual_amt}")
        if actual_master != first.get('master'):
            err('F', first.get('master'), actual_master, '#1 master')
        if actual_code != first.get('stock_code'):
            err('F', first.get('stock_code'), actual_code, '#1 stock_code')
        if actual_days != first.get('consecutive_days'):
            err('F', first.get('consecutive_days'), actual_days, '#1 days')
        if actual_amt != _round_safe(first.get('total_buy_amt_wan')):
            err('F', _round_safe(first.get('total_buy_amt_wan')), actual_amt, '#1 amt')

# Section J: Master × Top 3
print(f"\n=== Section J: Master × Top 3 cross-table 驗證 ===")
gt_master_stocks = {}
for b in filtered:
    m = b['master']
    for s in b['buys']:
        gt_master_stocks.setdefault(m, {})
        k = (s['code'], s['name'])
        gt_master_stocks[m][k] = gt_master_stocks[m].get(k, 0) + s['buy_amt']
gt_rows = []
for m, stocks in gt_master_stocks.items():
    sorted_s = sorted(stocks.items(), key=lambda kv: -kv[1])
    total = sum(stocks.values())
    gt_rows.append({'master': m, 'total': total, 'top': sorted_s[:3]})
gt_rows.sort(key=lambda x: -x['total'])
print(f"  GT top master in J: {gt_rows[0]['master']}, total={round(gt_rows[0]['total']/10,0)}萬")
print(f"    Top stocks: {[(f'{n}({c})', round(a/10,0)) for (c,n),a in gt_rows[0]['top']]}")

# Find J section
j_start = None
for r in range(4, ws2.max_row+1):
    v = cell(f'B{r}')
    if v and isinstance(v, str) and 'cross-table' in v:
        j_start = r + 2
        break
if j_start:
    actual_master = cell(f'B{j_start}')
    actual_total = cell(f'C{j_start}')
    print(f"  Excel J #1: master={actual_master}, total={actual_total}萬")
    if actual_master != gt_rows[0]['master']:
        err('J', gt_rows[0]['master'], actual_master, '#1 master')
    expected_total = round(gt_rows[0]['total']/10, 0)
    if actual_total != expected_total:
        err('J', expected_total, actual_total, '#1 total')

# === Section 0: 共同買超 (≥2 分點) verify ===
print(f"\n=== ★ Section 0: 共同買超 (≥2 分點) cross-validate ===")
# Ground truth: 從 filtered branches_data 獨立計算, 以分點為單位
gt_stock_map = {}
for b in filtered:
    m = b['master']
    b_code = b.get('code', '')
    for s in b['buys'] + b.get('sells', []):
        net = (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
        if net <= 0: continue
        e = gt_stock_map.setdefault(s['code'], {'name': s.get('name',''), 'branches': []})
        e['branches'].append({'branch_code': b_code, 'master': m, 'net_amt': net})
gt_consensus = []
MIN_MASTER_COUNT = 10  # v3.63.6
for code, info in gt_stock_map.items():
    # v3.63.7: 排除 ETF
    if code.startswith('00'):
        continue
    if len(info['branches']) < 2:
        continue
    master_set = {br['master'] for br in info['branches']}
    if len(master_set) < MIN_MASTER_COUNT:
        continue
    gt_consensus.append({
        'code': code, 'name': info['name'],
        'branch_count': len(info['branches']),
        'master_count': len(master_set),
        'masters': master_set,
        'total': sum(br['net_amt'] for br in info['branches']),
    })
gt_consensus.sort(key=lambda x: (-x['master_count'], -x['branch_count'], -x['total']))

print(f"  GT consensus count: {len(gt_consensus)}")
for i, c in enumerate(gt_consensus[:5]):
    print(f"  GT #{i+1}: {c['code']}({c['name']}), 分點{c['branch_count']}/大戶{c['master_count']}, "
          f"{int(round(c['total']/10))}萬, masters={c['masters']}")

# Find Section 0 in Excel
sec0_start = None
for r in range(4, ws2.max_row+1):
    v = cell(f'B{r}')
    # v3.63.6+: 標題含「強共識買超」或舊「共同買超」
    if v and isinstance(v, str) and ('強共識買超' in v or '共同買超' in v):
        # v3.63.9: 多了註腳 row → +1 hdr, +1 note, +1 col-header = +3
        sec0_start = r + 3
        break
print(f"  Section 0 data starts at row {sec0_start}")
if sec0_start and gt_consensus:
    # v3.63.8 Excel-native 13 欄佈局
    # B=#, C=代號, D=名稱, E=大戶數, F=分點數,
    # G=領頭大戶, H=領頭金額, I=#2 大戶, J=#2 金額, K=#3 大戶, L=#3 金額,
    # M=+更多, N=合計淨買
    def _short(m): return m.split('(')[0].split('/')[0]
    for i in range(min(3, len(gt_consensus))):
        r = sec0_start + i
        actual_rank = cell(f'B{r}')
        actual_code = cell(f'C{r}')
        actual_mc = cell(f'E{r}')
        actual_bc = cell(f'F{r}')
        actual_lead_name = cell(f'G{r}')
        actual_lead_amt = cell(f'H{r}')
        actual_2_name = cell(f'I{r}')
        actual_2_amt = cell(f'J{r}')
        actual_3_name = cell(f'K{r}')
        actual_3_amt = cell(f'L{r}')
        actual_tail = cell(f'M{r}')
        actual_total = cell(f'N{r}')
        gt = gt_consensus[i]
        gt_total = int(round(gt['total']/10))
        print(f"  Excel #{i+1}: code={actual_code}, 大戶={actual_mc}, 分點={actual_bc}, "
              f"領頭={actual_lead_name}({actual_lead_amt}萬), #2={actual_2_name}({actual_2_amt}萬), "
              f"#3={actual_3_name}({actual_3_amt}萬), +{actual_tail}, 合計={actual_total}萬")
        if actual_rank != i+1: err('0', i+1, actual_rank, f'#{i+1} rank')
        if actual_code != gt['code']: err('0', gt['code'], actual_code, f'#{i+1} code')
        if actual_bc != gt['branch_count']: err('0', gt['branch_count'], actual_bc, f'#{i+1} branch_count')
        if actual_mc != gt['master_count']: err('0', gt['master_count'], actual_mc, f'#{i+1} master_count')
        if actual_total != gt_total: err('0', gt_total, actual_total, f'#{i+1} total')
        # 領頭+#2+#3 名字必須都在 gt masters 內
        gt_short = {_short(m) for m in gt['masters']}
        for nm, label in [(actual_lead_name, 'lead'), (actual_2_name, '#2'), (actual_3_name, '#3')]:
            if nm and nm not in gt_short:
                err('0', f'in {gt_short}', nm, f'#{i+1} {label} master not in masters')
        # 領頭+#2+#3+tail 名額總和 = master_count
        visible = sum(1 for x in [actual_lead_name, actual_2_name, actual_3_name] if x)
        tail = actual_tail if isinstance(actual_tail, int) else 0
        if visible + tail != gt['master_count']:
            err('0', gt['master_count'], visible + tail,
                f'#{i+1} visible({visible}) + tail({tail}) != master_count')
        # 領頭金額 ≥ #2 金額 ≥ #3 金額 (排序正確性)
        amts = [a for a in [actual_lead_amt, actual_2_amt, actual_3_amt] if isinstance(a, int)]
        if amts != sorted(amts, reverse=True):
            err('0', 'desc sorted', amts, f'#{i+1} amount sort')

# === Result ===
print(f"\n{'='*60}")
if errors:
    print(f"❌ FAIL: {len(errors)} mismatches:")
    for sec, exp, act, note in errors:
        print(f"  [{sec}] {note}: expected={exp!r}, actual={act!r}")
else:
    print(f"✅ PASS: 全部 cross-validate 通過")
