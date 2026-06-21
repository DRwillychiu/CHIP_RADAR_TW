# v3.52.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""
test_v3520_consecutive_accumulation.py — v3.52.0 Sprint 14 長4

驗證 master_profile._compute_consecutive_accumulation_metrics:
  1. 連續 5 天買 2330 → max_consecutive_days = 5
  2. 連續 3 天買 < 5 天門檻 → 不入榜
  3. 分散買 5 天 (中間斷掉) → max_consecutive_days < 5
  4. is_active: 最後一天還在連續
  5. has_active_accumulation summary
  6. compute_operation_metrics 注入 consecutive_accumulation 欄位
  7. labels 觸發 📦 連續囤貨
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from master_profile import (
    _compute_consecutive_accumulation_metrics,
    compute_operation_metrics,
    compute_timing_metrics,
    generate_labels,
)

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


def _make_trade(date, code, amt=10000, **kwargs):
    base = {
        'date': date, 'stock_code': code, 'stock_name': f'股{code}',
        'buy_lot': 10, 'buy_amt': amt, 'sell_lot': 0, 'sell_amt': 0,
        'is_limit_up': False, 'trade_style': 'overnight',
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1-2] 連續 5 天買 2330 → 入榜")
trades = [
    _make_trade('20260615', '2330'),
    _make_trade('20260616', '2330'),
    _make_trade('20260617', '2330'),
    _make_trade('20260618', '2330'),
    _make_trade('20260619', '2330'),
]
r = _compute_consecutive_accumulation_metrics(trades, min_consecutive_days=5)
check("accumulation_stocks 非空", len(r['accumulation_stocks']) == 1)
check("2330 連續 5 天", r['accumulation_stocks'][0]['max_consecutive_days'] == 5)
check("2330 is_active = True (今天還在)", r['accumulation_stocks'][0]['is_active'])
check("has_active_accumulation = True", r['has_active_accumulation'])

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] 連續 3 天 (< 5 門檻) → 不入榜")
trades2 = [
    _make_trade('20260617', '2454'),
    _make_trade('20260618', '2454'),
    _make_trade('20260619', '2454'),
]
r2 = _compute_consecutive_accumulation_metrics(trades2, min_consecutive_days=5)
check("3 天 → 不入榜", len(r2['accumulation_stocks']) == 0)
check("has_active_accumulation = False", not r2['has_active_accumulation'])

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] 分散買 (中間斷 ≥4 天) → streak 重置")
# 連續定義: 自然日相差 ≤ 3 天 (跟 timing streaks 一致, 6/19→6/24 = 5 天 → 算斷)
trades3 = [
    _make_trade('20260615', '6505'),
    _make_trade('20260616', '6505'),
    _make_trade('20260617', '6505'),
    # 6/18-6/23 斷 6 天
    _make_trade('20260624', '6505'),
    _make_trade('20260625', '6505'),
]
r3 = _compute_consecutive_accumulation_metrics(trades3, min_consecutive_days=5)
check("斷掉 ≥4 天 → 不入榜 (max=3, 不到 5)",
      len(r3['accumulation_stocks']) == 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] is_active: 不是最後一天買就 inactive")
trades4 = [
    _make_trade('20260612', '1234'),
    _make_trade('20260613', '1234'),
    _make_trade('20260614', '1234'),
    _make_trade('20260615', '1234'),
    _make_trade('20260616', '1234'),
    # 後面 6/17-6/19 都沒買 1234 (但要有買其他股 → overall_latest = 20260619)
    _make_trade('20260619', '9999'),
]
r4 = _compute_consecutive_accumulation_metrics(trades4, min_consecutive_days=5)
matching = [s for s in r4['accumulation_stocks'] if s['stock_code'] == '1234']
check("1234 連 5 天 → 入榜", len(matching) == 1 and matching[0]['max_consecutive_days'] == 5)
check("1234 is_active = False (整體 latest 是 6/19 但 1234 最後是 6/16)",
      not matching[0]['is_active'])
check("has_active_accumulation = False (沒有 active)", not r4['has_active_accumulation'])

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] compute_operation_metrics 注入 consecutive_accumulation")
trades5 = trades  # 用 case 1 的 5 天連買
op = compute_operation_metrics(trades5)
check("op 含 consecutive_accumulation 欄位", 'consecutive_accumulation' in op)
ca = op['consecutive_accumulation']
check("min_threshold = 5", ca['min_threshold'] == 5)
check("2330 連 5 天確認", ca['accumulation_stocks'][0]['stock_code'] == '2330')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] _generate_labels 觸發 📦 連續囤貨")
timing = compute_timing_metrics(trades5, total_days=10)
declared_styles = ['overnight']
labels = generate_labels(op, timing, declared_styles)
check("📦 連續囤貨 in labels", '📦 連續囤貨' in labels,
      f"got {labels}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 8] 多檔同時連續囤貨 排序")
trades6 = [
    # 2330 連 6 天
    _make_trade('20260614', '2330'),
    _make_trade('20260615', '2330'),
    _make_trade('20260616', '2330'),
    _make_trade('20260617', '2330'),
    _make_trade('20260618', '2330'),
    _make_trade('20260619', '2330'),
    # 2454 連 5 天
    _make_trade('20260615', '2454'),
    _make_trade('20260616', '2454'),
    _make_trade('20260617', '2454'),
    _make_trade('20260618', '2454'),
    _make_trade('20260619', '2454'),
]
r6 = _compute_consecutive_accumulation_metrics(trades6, min_consecutive_days=5)
check("兩檔皆入榜", len(r6['accumulation_stocks']) == 2)
check("Top 1 = 2330 (6 天)", r6['accumulation_stocks'][0]['stock_code'] == '2330')
check("Top 1 = 6 天", r6['accumulation_stocks'][0]['max_consecutive_days'] == 6)
check("max_consecutive_days_overall = 6", r6['max_consecutive_days_overall'] == 6)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3520_consecutive_accumulation: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
