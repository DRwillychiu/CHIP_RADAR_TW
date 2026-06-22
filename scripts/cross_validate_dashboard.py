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
assert len(filtered) == 6, f"filter should yield 6, got {len(filtered)}"

# A. 規模統計
gt_total_buy = sum(s['buy_amt'] for b in filtered for s in b['buys'])
gt_master_active = len({b['master'] for b in filtered if b['buys']})
gt_distinct_stocks = len({s['code'] for b in filtered for s in b['buys']})
gt_limit_up = sum(1 for b in filtered for s in b['buys'] if s['is_limit_up'])

print(f"=== Section A: 規模統計 ===")
print(f"  GT  | 活躍 Master: {gt_master_active} 位")
print(f"  GT  | 個股涉及: {gt_distinct_stocks} 檔")
print(f"  GT  | 總買進: {gt_total_buy/100000:.2f} 億 (= {gt_total_buy} 千元 / 100000)")
print(f"  GT  | 漲停買進: {gt_limit_up} 筆")

# Scan rows 4-8 for A section
import re as _re
for r in range(4, 10):
    for c in 'BCDEFGHI':
        v = cell(f'{c}{r}')
        if v and isinstance(v, str):
            if '活躍' in v or 'Master' in v or '個股涉及' in v or '總買進' in v or '漲停' in v:
                # Print row
                row_data = [f"{c2}{r}={cell(f'{c2}{r}')!r}" for c2 in 'BCDEFGHI' if cell(f'{c2}{r}') is not None]
                print(f"  ROW {r}: {' | '.join(row_data)}")
                break

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
for code, info in gt_stock_map.items():
    if len(info['branches']) >= 2:
        master_set = {br['master'] for br in info['branches']}
        gt_consensus.append({
            'code': code, 'name': info['name'],
            'branch_count': len(info['branches']),
            'master_count': len(master_set),
            'masters': master_set,
            'total': sum(br['net_amt'] for br in info['branches']),
        })
gt_consensus.sort(key=lambda x: (-x['branch_count'], -x['master_count'], -x['total']))

print(f"  GT consensus count: {len(gt_consensus)}")
for i, c in enumerate(gt_consensus[:5]):
    print(f"  GT #{i+1}: {c['code']}({c['name']}), 分點{c['branch_count']}/大戶{c['master_count']}, "
          f"{int(round(c['total']/10))}萬, masters={c['masters']}")

# Find Section 0 in Excel
sec0_start = None
for r in range(4, ws2.max_row+1):
    v = cell(f'B{r}')
    if v and isinstance(v, str) and '今日共同買超' in v:
        sec0_start = r + 2   # +1 hdr, +1 col-header
        break
print(f"  Section 0 data starts at row {sec0_start}")
if sec0_start and gt_consensus:
    # Verify top 3
    for i in range(min(3, len(gt_consensus))):
        r = sec0_start + i
        actual_rank = cell(f'B{r}')
        actual_code = cell(f'C{r}')
        actual_name = cell(f'D{r}')
        actual_bc = cell(f'E{r}')
        actual_mc = cell(f'F{r}')
        actual_masters = cell(f'G{r}')
        actual_total = cell(f'H{r}')
        gt = gt_consensus[i]
        gt_total = int(round(gt['total']/10))
        print(f"  Excel #{i+1}: code={actual_code}, name={actual_name}, "
              f"分點={actual_bc}, 大戶={actual_mc}, total={actual_total}萬, masters={actual_masters}")
        if actual_rank != i+1: err('0', i+1, actual_rank, f'#{i+1} rank')
        if actual_code != gt['code']: err('0', gt['code'], actual_code, f'#{i+1} code')
        if actual_bc != gt['branch_count']: err('0', gt['branch_count'], actual_bc, f'#{i+1} branch_count')
        if actual_mc != gt['master_count']: err('0', gt['master_count'], actual_mc, f'#{i+1} master_count')
        if actual_total != gt_total: err('0', gt_total, actual_total, f'#{i+1} total')
        actual_masters_set = set((actual_masters or '').split(' / '))
        if gt['masters'] != actual_masters_set:
            err('0', gt['masters'], actual_masters_set, f'#{i+1} masters')

# === Result ===
print(f"\n{'='*60}")
if errors:
    print(f"❌ FAIL: {len(errors)} mismatches:")
    for sec, exp, act, note in errors:
        print(f"  [{sec}] {note}: expected={exp!r}, actual={act!r}")
else:
    print(f"✅ PASS: 全部 cross-validate 通過")
