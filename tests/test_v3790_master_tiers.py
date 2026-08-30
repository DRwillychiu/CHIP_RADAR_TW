# -*- coding: utf-8 -*-
"""v3.79.0 Master 分層單一真相來源 — 漂移守門

P2 稽核 (2026-08-30) 在 4 個檔案找到同一概念的 4 份定義, 已產生 3 個實際缺陷:

  ① PREMIUM_MASTERS 漂移到**零交集**
     bootstrap_multiday_backtest.py 硬寫 {陳律師,竹科主力分點,陳族元} (2026-06-26 凍結)
     vs excel_report 動態值 {巨人傑} (v3.75.0 起依實測 LOO)
  ② SNIPER_MASTERS 兩份不同 — crawler 1 人 / audit 4 人
  ③ '迷你哥' 這名字不存在 (正式名稱 '迷你哥/松山哥')
     → audit 的 `master in SNIPER_MASTERS` 對他永遠不成立, silent no-op

③ 是這陣子一直在抓的那類 bug: 不拋例外 / 不變紅 / 看起來正常, 只是沒作用.

本測試鎖住:
  A. 名稱驗證會擋下打錯的名字 (讓 ③ 不可能再發生)
  B. 兩個 sniper 概念保持分離 (它們語意不同, 合併會改行為)
  C. 所有消費端都指向同一來源, 不再各自持有副本
  D. 回測用的是**時點快照**而非動態值 (換成動態會製造 look-ahead)
"""
import sys, os, io, ast
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from src.core.master_tiers import (
    LIMIT_UP_SNIPERS, TOP_BUYER_HIGHLIGHT_MASTERS, SNIPER_MASTERS,
    PREMIUM_MASTERS, PREMIUM_MASTERS_SNAPSHOT, PREMIUM_SNAPSHOT_DATE,
    get_premium_masters, refresh_premium_masters, validate_master_names,
    check_snapshot_leakage,
)
from src.core.branches import MASTER_STYLES

# ─── A. 名稱驗證 ───
print("\n[A] 名稱驗證 — 打錯名字必須當場擋下 (原本是 silent no-op)")
try:
    validate_master_names({'迷你哥'}, 'test')
    check("'迷你哥' (簡寫) 應被擋下", False, "沒有 raise")
except ValueError as e:
    check("'迷你哥' (簡寫) 被擋下", True)
    check("錯誤訊息提示正式名稱", '迷你哥/松山哥' in str(e), str(e)[:80])
check("正式名稱通過", validate_master_names({'迷你哥/松山哥'}, 'test') == set())
check("strict=False 只回報不 raise",
      validate_master_names({'不存在的人'}, 'test', strict=False) == {'不存在的人'})

print("\n[A2] 所有靜態名單的名字都真的存在於 MASTER_STYLES")
for nm, s in (('LIMIT_UP_SNIPERS', LIMIT_UP_SNIPERS),
              ('TOP_BUYER_HIGHLIGHT_MASTERS', TOP_BUYER_HIGHLIGHT_MASTERS),
              ('PREMIUM_MASTERS_SNAPSHOT', PREMIUM_MASTERS_SNAPSHOT)):
    bad = s - set(MASTER_STYLES)
    check(f"{nm} 全部有效", not bad, f"未知: {sorted(bad)}")

# ─── B. 兩個 sniper 概念必須分離 ───
print("\n[B] 兩個 sniper 概念不可合併 (語意不同)")
check("LIMIT_UP_SNIPERS 是風格分類 (4 人)", len(LIMIT_UP_SNIPERS) == 4, sorted(LIMIT_UP_SNIPERS))
check("TOP_BUYER_HIGHLIGHT 是功能範圍 (蔣承翰)",
      TOP_BUYER_HIGHLIGHT_MASTERS == {'蔣承翰'}, sorted(TOP_BUYER_HIGHLIGHT_MASTERS))
check("兩者不相等 (合併會改變 Excel 呈現)", LIMIT_UP_SNIPERS != TOP_BUYER_HIGHLIGHT_MASTERS)
check("舊名 SNIPER_MASTERS 指向 highlight 那個 (crawler 行為不變)",
      SNIPER_MASTERS == TOP_BUYER_HIGHLIGHT_MASTERS)
check("迷你哥/松山哥 已納入風格分類 (原本永遠匹配不到)",
      '迷你哥/松山哥' in LIMIT_UP_SNIPERS)

# ─── C. 消費端不得再持有副本 ───
print("\n[C] 消費端必須 import, 不得各自硬寫")
def src_of(rel):
    return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()

crawler = src_of('crawler.py')
check("crawler.py 不再硬寫 SNIPER_MASTERS",
      'SNIPER_MASTERS = {"蔣承翰"}' not in crawler)
check("crawler.py 改 import master_tiers",
      'from src.core.master_tiers import TOP_BUYER_HIGHLIGHT_MASTERS' in crawler)

audit = src_of('src/audit/histock_branch_audit.py')
check("audit 不再硬寫 4 人名單",
      "SNIPER_MASTERS = {'蔣承翰', '迷你哥', 'Tradow', '巨人傑'}" not in audit)
check("audit 改 import LIMIT_UP_SNIPERS", 'LIMIT_UP_SNIPERS' in audit)

er = src_of('src/exports/excel_report.py')
check("excel_report 不再自己定義 _LazyPremiumSet",
      'class _LazyPremiumSet' not in er)
check("excel_report 改 import master_tiers", 'master_tiers import' in er)

bm = src_of('scripts/bootstrap_multiday_backtest.py')
check("bootstrap_multiday 不再硬寫凍結名單",
      "PREMIUM_MASTERS = {'陳律師', '竹科主力分點', '陳族元'}" not in bm)

# excel_report re-export 後行為必須跟 master_tiers 一致
import src.exports.excel_report as ER
check("excel_report.PREMIUM_MASTERS 與 master_tiers 同源",
      set(ER.PREMIUM_MASTERS) == set(PREMIUM_MASTERS))
check("雙向 & 都正確 (frozenset 子類陷阱)",
      ({'巨人傑', 'X'} & ER.PREMIUM_MASTERS) == (ER.PREMIUM_MASTERS & {'巨人傑', 'X'}))
check("非 frozenset 子類", not isinstance(ER.PREMIUM_MASTERS, frozenset))

# ─── D. 回測必須用時點快照 ───
print("\n[D] 回測用時點快照, 不可換成動態值 (否則 look-ahead)")
check("快照與動態值確實不同 (證明這個區分有實質意義)",
      PREMIUM_MASTERS_SNAPSHOT != set(PREMIUM_MASTERS),
      f"snapshot={sorted(PREMIUM_MASTERS_SNAPSHOT)} live={sorted(PREMIUM_MASTERS)}")
check("快照日已記錄", PREMIUM_SNAPSHOT_DATE == '20260626')
check("bootstrap 用的是 SNAPSHOT 不是動態",
      'PREMIUM_MASTERS_SNAPSHOT as PREMIUM_MASTERS' in bm)
check("bootstrap 輸出帶偏誤揭露", 'premium_selection' in bm and 'bias_note' in bm)

print("\n[D2] leakage 檢查")
check("OOS 起點早於快照日 → 出警告",
      check_snapshot_leakage('20260601') is not None)
check("OOS 起點晚於快照日 → 無警告",
      check_snapshot_leakage('20260701') is None)
check("無 cutoff → 無警告", check_snapshot_leakage(None) is None)

# 實際產出檔要有揭露欄位
import json
mp = os.path.join(ROOT, 'data', 'multiday_backtest.json')
if os.path.exists(mp):
    d = json.load(io.open(mp, encoding='utf-8'))
    ps = d.get('premium_selection') or {}
    check("multiday_backtest.json 含 premium_selection", bool(ps))
    check("含 snapshot_date", ps.get('snapshot_date') == '20260626', ps.get('snapshot_date'))
    check("含 bias_note", 'in-sample' in (ps.get('bias_note') or ''))

# ─── E. 動態計算門檻未被誤改 ───
print("\n[E] 動態 premium 門檻")
from src.core.master_tiers import PREMIUM_MIN_N, PREMIUM_MIN_HIT_PCT
check("PREMIUM_MIN_N = 20 (與 LOO 一致)", PREMIUM_MIN_N == 20)
check("PREMIUM_MIN_HIT_PCT = 60", PREMIUM_MIN_HIT_PCT == 60)
check("refresh 可清 cache 重算", isinstance(refresh_premium_masters('data'), set))
check("資料不存在 → 空集合而非報錯",
      get_premium_masters('/no/such/dir') == set())

print(f"\n{'=' * 58}")
print(f"test_v3790_master_tiers: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
