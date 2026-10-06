# -*- coding: utf-8 -*-
"""v3.76.0 TAIEX stale guard 修復測試

背景 (2026-08-28 稽核):
  _fetch_taiex_index 的 stale guard 寫 data[0].get('Date'),
  但 TWSE MI_INDEX 是**中文欄位「日期」**.
  → response_date 永遠 '' → `if expected_roc and response_date and ...` 短路
  → guard 自 v3.27.3 起從未執行過一次.

  後果: TWSE 未更新當日資料時 API 回前一交易日, 卻被寫入
  history["market"][trade_date] → 55 筆中 43 筆 (78%) 慢一天.
  連帶 temp_history.next_day_change_pct 60 筆中 47 筆記成「訊號當日」漲跌,
  Q5 一直在拿今天已發生的漲跌當明天的預測結果評分.

  這個 bug 能存活這麼久, 是因為沒有任何測試檢查 quote_date 有沒有值.

本測試鎖住三件事:
  1. 欄位名讀對 (中文「日期」優先, 英文 'Date' 為 fallback)
  2. 日期不符 → 回 None (擋住 stale)
  3. 完全拿不到日期 → 也回 None (fail-safe, 不寫無法驗證的資料)
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from unittest.mock import patch
import src.fetchers.history as hist

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1


class FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)
        self.encoding = 'utf-8'


def row(date_key='日期', d='1150828', close='46331.45', sign='+', pct='0.77'):
    return {date_key: d, '指數': '發行量加權股價指數',
            '收盤指數': close, '漲跌': sign, '漲跌點數': '356.23',
            '漲跌百分比': pct, '特殊處理註記': ''}


def run(payload, expected):
    """⚠️ 必須同時 patch safe_fetch.safe_get 與 requests.get —
    _fetch_taiex_index 優先走 safe_fetch, 只 patch requests 會漏網打到真實 API."""
    resp = FakeResp(payload)
    with patch.object(hist, 'requests') as rq,          patch('safe_fetch.safe_get', return_value=resp, create=True):
        rq.get.return_value = resp
        return hist._fetch_taiex_index(expected_trade_date=expected, max_retries=1)


# ─── 1. 中文欄位名讀得到 ───
print("\n[1] 中文欄位「日期」正確解析 (原 bug: 寫成英文 'Date')")
r = run([row()], '20260828')
check("日期相符 → 回傳資料", r is not None)
check("quote_date 有值 (原本永遠是空字串)", r and r.get('quote_date') == '1150828',
      f"got {r.get('quote_date')!r}" if r else 'None')
check("index 正確", r and r['index'] == 46331.45)

# ─── 2. stale 擋得住 ───
print("\n[2] 日期不符 → 擋下 (這是 v3.27.3 原本想做但從未生效的事)")
r = run([row(d='1150827')], '20260828')      # API 回前一交易日
check("回前一交易日 → None", r is None, f"got {r}")
r = run([row(d='1150828')], '20260901')      # 我們要 9/1, API 只有 8/28
check("API 落後多日 → None", r is None, f"got {r}")

# ─── 3. 英文 Date 仍相容 (若 TWSE 改欄位名) ───
print("\n[3] 英文 'Date' fallback (防 TWSE 未來改欄位名)")
r = run([row(date_key='Date')], '20260828')
check("英文 Date 也讀得到", r is not None and r.get('quote_date') == '1150828')

# ─── 4. fail-safe: 拿不到日期不可放行 ───
print("\n[4] fail-safe — 無日期欄位時不可寫入無法驗證的資料")
bad = {'指數': '發行量加權股價指數', '收盤指數': '46331.45',
       '漲跌': '+', '漲跌百分比': '0.77'}
r = run([bad], '20260828')
check("無日期欄位 + 有 expected → None (不放行)", r is None, f"got {r}")
r = run([bad], None)
check("無日期欄位 + 無 expected → 仍可回傳 (backfill 等場景)", r is not None)

# ─── 5. 迴歸: 不可再出現 quote_date 全空 ───
print("\n[5] 迴歸 — production 資料的 quote_date 必須有值")
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'data', 'stock_history.json')
if os.path.exists(p):
    mk = json.load(open(p, encoding='utf-8')).get('market') or {}
    empty = [d for d, v in mk.items() if not (v or {}).get('quote_date')]
    check(f"stock_history.market {len(mk)} 筆 quote_date 皆有值",
          len(empty) == 0, f"{len(empty)} 筆為空: {empty[:5]}")
    # 日期標籤 vs quote_date 必須一致
    bad_align = []
    for d, v in mk.items():
        q = str((v or {}).get('quote_date') or '')
        if len(q) == 7 and f'{int(q[:3]) + 1911}{q[3:]}' != d:
            bad_align.append(d)
    check("key 日期與 quote_date 一致 (無錯位)",
          len(bad_align) == 0, f"{len(bad_align)} 筆錯位: {bad_align[:5]}")
else:
    print("  (跳過 — 無 production 資料)")

print(f"\n{'=' * 58}")
print(f"test_v3760_taiex_stale_guard: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
