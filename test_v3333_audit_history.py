# -*- coding: utf-8 -*-
"""
test_v3333_audit_history.py — v3.33.3 (M5) audit_history 趨勢化測試

驗證:
  1. append 新 entry + 欄位正確
  2. 同日重跑 dedup (兜底排程 22:37/23:47 不會重複)
  3. 180 筆上限裁切
  4. 壞檔自救 (JSON 壞掉重建不炸)
  5. save_audit_report 整合 (寫 daily_audit.json 同時 append history)
  6. 排序 (按 date 升冪)

跑法: python test_v3333_audit_history.py  (免密碼, tmp dir fixture)
"""
import sys
import io
import json
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from auto_audit import (
    append_audit_history,
    save_audit_report,
    HISTORY_MAX_ENTRIES,
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


def mk_report(sheet, verdict='PASS', total_real=400, net_sell=0):
    return {
        'audit_run_at': f'2026-06-11T21:30:00',
        'sheet': sheet,
        'overall_verdict': verdict,
        'summary': f'{verdict} test',
        'stats': {'total_real': total_real, 'net_sell': net_sell,
                  'net_zero': 1, 'reverse_est': 3},
        'branches_audited': 42,
    }


with tempfile.TemporaryDirectory() as td:
    data_dir = Path(td)

    # ────────────────────────────────────────────────────────────────
    print("\n[Case 1] append 新 entry + 欄位正確")
    append_audit_history(data_dir, mk_report('20260609'))
    hist = json.loads((data_dir / 'audit_history.json').read_text(encoding='utf-8'))
    check("1 筆 entry", len(hist) == 1)
    e = hist[0]
    check("date = sheet", e['date'] == '20260609')
    check("verdict 帶到", e['verdict'] == 'PASS')
    check("stats 摘要帶到", e['total_real'] == 400 and e['net_sell'] == 0)
    check("不存 examples (防膨脹)", 'anomalies' not in e and 'net_sell_examples' not in e)

    # ────────────────────────────────────────────────────────────────
    print("\n[Case 2] 同日重跑 dedup (兜底排程)")
    append_audit_history(data_dir, mk_report('20260609', verdict='WARN', total_real=500))
    hist = json.loads((data_dir / 'audit_history.json').read_text(encoding='utf-8'))
    check("仍只有 1 筆 (同日覆蓋)", len(hist) == 1, f"got {len(hist)}")
    check("內容是最新那次 (WARN/500)", hist[0]['verdict'] == 'WARN' and hist[0]['total_real'] == 500)

    # ────────────────────────────────────────────────────────────────
    print("\n[Case 3] 多日累積 + 排序")
    append_audit_history(data_dir, mk_report('20260611'))
    append_audit_history(data_dir, mk_report('20260610'))
    hist = json.loads((data_dir / 'audit_history.json').read_text(encoding='utf-8'))
    check("3 筆", len(hist) == 3)
    check("按 date 升冪", [h['date'] for h in hist] == ['20260609', '20260610', '20260611'])

    # ────────────────────────────────────────────────────────────────
    print(f"\n[Case 4] {HISTORY_MAX_ENTRIES} 筆上限裁切")
    for i in range(HISTORY_MAX_ENTRIES + 30):
        append_audit_history(data_dir, mk_report(f'2025{i:04d}'))
    hist = json.loads((data_dir / 'audit_history.json').read_text(encoding='utf-8'))
    check(f"裁到 {HISTORY_MAX_ENTRIES} 筆", len(hist) == HISTORY_MAX_ENTRIES,
          f"got {len(hist)}")
    check("留最新 (最大 date 還在)", any(h['date'] == '20260611' for h in hist))

    # ────────────────────────────────────────────────────────────────
    print("\n[Case 5] 壞檔自救")
    (data_dir / 'audit_history.json').write_text('{{{not json', encoding='utf-8')
    append_audit_history(data_dir, mk_report('20260612'))
    hist = json.loads((data_dir / 'audit_history.json').read_text(encoding='utf-8'))
    check("壞檔重建為 1 筆, 不炸", len(hist) == 1 and hist[0]['date'] == '20260612')

with tempfile.TemporaryDirectory() as td2:
    data_dir2 = Path(td2)
    # ────────────────────────────────────────────────────────────────
    print("\n[Case 6] save_audit_report 整合 (主入口自動 append)")
    save_audit_report(data_dir2, mk_report('20260611', verdict='PASS'))
    check("daily_audit.json 寫出", (data_dir2 / 'daily_audit.json').exists())
    check("audit_history.json 同步生成", (data_dir2 / 'audit_history.json').exists())
    hist = json.loads((data_dir2 / 'audit_history.json').read_text(encoding='utf-8'))
    check("history 有該日 entry", len(hist) == 1 and hist[0]['date'] == '20260611')

# ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3333_audit_history: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
