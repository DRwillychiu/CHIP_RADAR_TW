# -*- coding: utf-8 -*-
"""
test_v3400_manipulation.py — v3.40.0 B6 機構級操縱偵測測試

驗證:
  1. 規則 A 拉抬: daytrade>70% + is_limit_up + amt>=median×3 → 觸發
  2. 規則 A 不觸發: daytrade=50% 或 非漲停 或 amt<median×3
  3. 規則 B 對敲: A 買 B 賣量級匹配 → 觸發; 同 master 嚴重度=high
  4. 規則 B 不觸發: 同分點 / 量級不匹配 / 太小
  5. 規則 C 出貨: sell ≥ 30d 均 × 5 且近 5 天漲停 ≥ 2 → 觸發
  6. 規則 C 不觸發: 無 history / 近期沒漲停 / 量級正常
  7. compute_all_flags 主入口 + summary 計數
  8. red_flags.json 寫出 + disclaimer

跑法: python test_v3400_manipulation.py
"""
import sys, io, json, tempfile
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import manipulation_flags as mf

PASS = 0
FAIL = 0

def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")

def mk_stock(code, name='', buy_lot=0, sell_lot=0, buy_amt=0, sell_amt=0, is_lu=False):
    return {'code': code, 'name': name or f'股{code}',
            'buy_lot': buy_lot, 'sell_lot': sell_lot,
            'buy_amt': buy_amt, 'sell_amt': sell_amt,
            'is_limit_up': is_lu}

def mk_branch(code, master='', buys=None, sells=None):
    return {'code': code, 'name': code, 'master': master, 'co_masters': [],
            'buys': buys or [], 'sells': sells or []}


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] 規則 A 拉抬: 觸發")
# 1234 是漲停, 9A 分點 daytrade 100% (買=賣) 且金額 50000 仟元 (= 5000 萬)
# 其他 5 個分點都買 1000 仟元小金額 → median = 1000, 9A 金額 50× median = 觸發
branches_a = [
    mk_branch('9A00', '甲', buys=[mk_stock('1234', buy_lot=200, sell_lot=200,
                                             buy_amt=50000, is_lu=True)]),
    mk_branch('9B00', '乙', buys=[mk_stock('1234', buy_lot=20, buy_amt=1000, is_lu=True)]),
    mk_branch('9C00', '丙', buys=[mk_stock('1234', buy_lot=20, buy_amt=1000, is_lu=True)]),
    mk_branch('9D00', '丁', buys=[mk_stock('1234', buy_lot=20, buy_amt=1000, is_lu=True)]),
    mk_branch('9E00', '戊', buys=[mk_stock('1234', buy_lot=20, buy_amt=1000, is_lu=True)]),
    mk_branch('9F00', '己', buys=[mk_stock('1234', buy_lot=20, buy_amt=1000, is_lu=True)]),
]
pump = mf.detect_pump_suspicion(branches_a)
check("9A00 拉抬 1234 觸發", any(f['branch_code']=='9A00' and f['stock_code']=='1234' for f in pump))
flag = next(f for f in pump if f['branch_code']=='9A00')
check("severity = high (daytrade>85%)", flag['severity'] == 'high')
check("reasoning 含當沖比 + 漲停 + 金額", '當沖' in flag['reasoning'] and '漲停' in flag['reasoning'])

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] 規則 A 不觸發")
# 非漲停
branches_a2 = [mk_branch('9A', '甲', buys=[mk_stock('5678', buy_lot=200, sell_lot=200, buy_amt=50000, is_lu=False)])]
pump2 = mf.detect_pump_suspicion(branches_a2)
check("非漲停 → 不觸發", len(pump2) == 0)
# 當沖比 50%
branches_a3 = [mk_branch('9A', '甲', buys=[mk_stock('1234', buy_lot=200, sell_lot=100, buy_amt=50000, is_lu=True)])]
pump3 = mf.detect_pump_suspicion(branches_a3)
check("當沖比 50% → 不觸發", len(pump3) == 0)
# 量太小
branches_a4 = [mk_branch('9A', '甲', buys=[mk_stock('1234', buy_lot=30, sell_lot=30, buy_amt=5000, is_lu=True)])]
pump4 = mf.detect_pump_suspicion(branches_a4)
check("買 30 張 < 50 → 不觸發", len(pump4) == 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] 規則 B 對敲: 觸發 + 同 master 高 severity")
branches_b = [
    mk_branch('9X', '甲', buys=[mk_stock('2222', buy_lot=300, buy_amt=30000)]),
    mk_branch('9Y', '甲', sells=[mk_stock('2222', sell_lot=290, sell_amt=29000)]),  # 同 master!
]
wash = mf.detect_wash_trade(branches_b)
check("2222 對敲觸發", any(f['stock_code']=='2222' for f in wash))
flag_b = next(f for f in wash if f['stock_code']=='2222')
check("same_master = True", flag_b['same_master'] is True)
check("severity = high (同 master)", flag_b['severity'] == 'high')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] 規則 B 不觸發")
# 同分點 (不算 wash)
branches_b2 = [mk_branch('9X', '甲',
                          buys=[mk_stock('3333', buy_lot=300, buy_amt=30000)],
                          sells=[mk_stock('3333', sell_lot=290, sell_amt=29000)])]
wash2 = mf.detect_wash_trade(branches_b2)
check("同分點 → 不觸發", len(wash2) == 0)
# 量級不匹配
branches_b3 = [
    mk_branch('9X', '甲', buys=[mk_stock('4444', buy_lot=300, buy_amt=30000)]),
    mk_branch('9Y', '乙', sells=[mk_stock('4444', sell_lot=50, sell_amt=5000)]),  # 50/300 = 0.17
]
wash3 = mf.detect_wash_trade(branches_b3)
check("量級不匹配 (0.17 < 0.7) → 不觸發", len(wash3) == 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] 規則 C 出貨: 觸發")
# 30 天 history: 9X 分點賣 5555, 每天 10 張, 但今天賣 200 張 (20× 均)
# 且近 5 天該股有 2+ 次漲停
history_c = []
for i, d in enumerate(['20260520', '20260521', '20260522', '20260523', '20260524']):
    history_c.append({'date': d, 'data': {'branches': [
        mk_branch('9X', '甲', sells=[mk_stock('5555', sell_lot=10, sell_amt=1000)])
    ]}})
# 近 5 天 (≡ recent_lu) 加 2 次漲停
for d in ['20260618', '20260619']:
    history_c.append({'date': d, 'data': {'branches': [
        mk_branch('9Z', '丙', buys=[mk_stock('5555', buy_lot=100, buy_amt=10000, is_lu=True)])
    ]}})
branches_c = [mk_branch('9X', '甲', sells=[mk_stock('5555', sell_lot=200, sell_amt=20000)])]
dist = mf.detect_distribution(branches_c, history_c)
check("5555 出貨觸發", any(f['stock_code']=='5555' for f in dist))
flag_c = next(f for f in dist if f['stock_code']=='5555')
check("sell_vs_avg_x 高", flag_c['sell_vs_avg_x'] >= 10)
check("recent 5d limit_up = 2", flag_c['recent_5d_limit_up_count'] == 2)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] 規則 C 不觸發")
# 無 history → 不觸發
dist_no_hist = mf.detect_distribution(branches_c, None)
check("無 history → 不觸發", len(dist_no_hist) == 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] compute_all_flags + summary")
with tempfile.TemporaryDirectory() as td:
    all_flags = mf.compute_all_flags(branches_a, '20260619', history=history_c, data_dir=td)
    s = all_flags['summary']
    check("summary 含 pump_count + total", 'pump_count' in s and 'total' in s)
    check("disclaimer 含「嫌疑」", '嫌疑' in all_flags.get('disclaimer', ''))
    # 確認 red_flags.json 寫出
    out_file = Path(td) / 'red_flags.json'
    check("red_flags.json 寫出", out_file.exists())
    written = json.loads(out_file.read_text(encoding='utf-8'))
    check("寫出檔含 trade_date", written.get('trade_date') == '20260619')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 8] format_summary 視覺輸出")
out = mf.format_summary(all_flags)
check("含 [Red Flags] header", '[Red Flags]' in out)
empty_result = {'summary': {'pump_count':0, 'wash_count':0, 'distribution_count':0, 'total':0}}
empty_out = mf.format_summary(empty_result)
check("空時顯示 ✓ 無嫌疑", '✓' in empty_out and '無' in empty_out)

print(f"\n{'='*60}")
print(f"test_v3400_manipulation: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
