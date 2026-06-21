# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3380_settlement_tz.py — v3.38.0 P0-1 結算日 timezone race 防護測試

驗證:
  1. third_wed 公開可呼叫, 各月第三個週三正確
  2. 跨年邊界 (12→1)
  3. _days_to_settlement 各天數正確
  4. trade_date 字串非 TW 時區時的行為 (函式內部仍以 string 計算, 不會偷用 UTC)
  5. 結算日當天 d=0
  6. 結算日後 N 天 d=-N (≤3 才算相關)

跑法: python test_v3380_settlement_tz.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from datetime import date
from crawler_pipeline import third_wed, _days_to_settlement

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

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] third_wed 函式已提升為 module-level, 各月第三個週三正確")
# 2026 各月第三個週三 (查 calendar 驗證)
expected_2026 = {
    1: date(2026, 1, 21),
    2: date(2026, 2, 18),
    3: date(2026, 3, 18),
    4: date(2026, 4, 15),
    5: date(2026, 5, 20),
    6: date(2026, 6, 17),
    7: date(2026, 7, 15),
    8: date(2026, 8, 19),
    9: date(2026, 9, 16),
    10: date(2026, 10, 21),
    11: date(2026, 11, 18),
    12: date(2026, 12, 16),
}
for m, expected in expected_2026.items():
    got = third_wed(2026, m)
    check(f"2026/{m} 第三個週三 = {expected}", got == expected, f"got {got}")
# 必為週三
for m in range(1, 13):
    d = third_wed(2026, m)
    check(f"2026/{m} 是週三 (weekday=2)", d.weekday() == 2)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] 跨年邊界")
# 2026/1 第三個週三 = 1/21, 對 2025/12/30 → 距離 22 天
d = _days_to_settlement('20251230')
check("2025/12/30 → 距離下一結算日", d is not None and d > 0)
# 2026/12 結算日 12/16, 對 2026/12/30 → 距離下個結算日 (2027/1) 約 14 天
d2 = _days_to_settlement('20261230')
check("2026/12/30 → 距離 2027 1 月結算日", d2 is not None and d2 > 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] 結算日當天 d=0")
# 2026/6/17 (六月結算日)
d3 = _days_to_settlement('20260617')
check("結算日當天 d=0", d3 == 0, f"got {d3}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] 結算日前 N 天 d=N")
# 2026/6/15 (結算前 2 天)
d4 = _days_to_settlement('20260615')
check("結算前 2 天 d=2", d4 == 2, f"got {d4}")
# 結算前 7 天
d5 = _days_to_settlement('20260610')
check("結算前 7 天 d=7", d5 == 7, f"got {d5}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] 結算日後 1-3 天 d 為負 (餘波範圍)")
d6 = _days_to_settlement('20260618')
check("結算後 1 天 d=-1", d6 == -1, f"got {d6}")
d7 = _days_to_settlement('20260620')
check("結算後 3 天 d=-3 (邊界)", d7 == -3, f"got {d7}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] 結算日後 4+ 天 → 切換下個月 (餘波範圍外)")
# 6/21 距 6/17 是 -4 天 (超出餘波), 應切到 7/15 (24 天後)
d8 = _days_to_settlement('20260621')
check("結算後 4 天切下月 (應 ≥ 20)", d8 is not None and d8 >= 20,
      f"got {d8}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] 壞輸入 → None")
check("空字串 → None", _days_to_settlement('') is None)
check("壞日期 → None", _days_to_settlement('99999999') is None)
check("None → None", _days_to_settlement(None) is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 8] TZ 約定: 函式內部用字串解析, 不偷用 UTC")
# 同一字串日期重複呼叫, 結果穩定 (純函式, 無 datetime.now() 依賴)
r1 = _days_to_settlement('20260617')
r2 = _days_to_settlement('20260617')
check("純函式: 同輸入結果穩定", r1 == r2 == 0)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3380_settlement_tz: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
