# -*- coding: utf-8 -*-
"""v3.77.0 資料自我一致性守門 + API 欄位漂移稽核 測試

背景 (2026-08-29 → 08-30 P0 掃尾):
  v3.76.0 揭穿 stock_history.market 有 78% 紀錄日期慢一天.
  該 bug 的致命特徵是**完全靜默** — 不拋例外、workflow 不變紅、
  資料看起來正常, 錯的只有「保護沒生效」.

  用戶目標是「一個月不去動他, 讓他自動更新」,
  所以真正該補的不是修一次資料, 而是讓同類錯誤下次會自己叫.

本測試鎖住兩道新防線:
  A. heartbeat check_data_integrity — 每日兩次, 純本機, 抓日期錯位
  B. audit_api_fields registry      — 每週一次, 打真 API, 抓上游欄位改名
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

import heartbeat_check as hb

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1


def write_sh(market, stocks=None):
    fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'market': market, 'stocks': stocks or {}}, f, ensure_ascii=False)
    return path


def roc(d):
    return f'{int(d[:4]) - 1911}{d[4:]}'


# ─── A1. 乾淨資料 → PASS ───
print("\n[A1] 乾淨資料")
clean = {d: {'index': 46000.0, 'quote_date': roc(d)}
         for d in ['20260826', '20260827', '20260828']}
p = write_sh(clean)
r = hb.check_data_integrity(p)
check("全部對齊 → PASS", r['verdict'] == 'PASS', r['issues'])
check("stats 筆數正確", r['stats']['market_records'] == 3)
os.unlink(p)

# ─── A2. 日期錯位 → FAIL (這正是 v3.76.0 前的真實狀態) ───
print("\n[A2] 日期錯位 — v3.76.0 前 43/55 筆的狀態")
bad = dict(clean)
bad['20260828'] = {'index': 45900.0, 'quote_date': roc('20260827')}   # 慢一天
p = write_sh(bad)
r = hb.check_data_integrity(p)
check("錯位 → FAIL", r['verdict'] == 'FAIL', r['verdict'])
check("錯位筆數計為 1", r['stats']['misaligned'] == 1, r['stats'])
check("issue 訊息點名 key ≠ quote_date",
      any('錯位' in i for i in r['issues']), r['issues'])
os.unlink(p)

# ─── A3. 缺 quote_date → FAIL (bug 存活一年的原始狀態) ───
print("\n[A3] 缺 quote_date — guard 從未執行時的狀態 (55 筆全空)")
noqd = {d: {'index': 46000.0} for d in ['20260827', '20260828']}
p = write_sh(noqd)
r = hb.check_data_integrity(p)
check("缺 quote_date → FAIL", r['verdict'] == 'FAIL', r['verdict'])
check("缺漏筆數 = 2", r['stats']['missing_quote_date'] == 2, r['stats'])
check("issue 說明「無法驗證新鮮度」",
      any('無法驗證新鮮度' in i for i in r['issues']), r['issues'])
os.unlink(p)

# ─── A4. 大盤落後個股 → WARN (軟性, 不擋但要叫) ───
print("\n[A4] 大盤最新日落後個股最新日")
stocks = {'2330': {'daily': {'20260827': {'close': 1000},
                             '20260828': {'close': 1010}}}}
lag = {d: {'index': 46000.0, 'quote_date': roc(d)} for d in ['20260826', '20260827']}
p = write_sh(lag, stocks)
r = hb.check_data_integrity(p)
check("大盤落後 → WARN (非 FAIL)", r['verdict'] == 'WARN', r['verdict'])
check("issue 點名 TWSE 未更新",
      any('落後個股' in i for i in r['issues']), r['issues'])
os.unlink(p)

# 大盤與個股同日 → 不該 WARN
same = {d: {'index': 46000.0, 'quote_date': roc(d)} for d in ['20260827', '20260828']}
p = write_sh(same, stocks)
check("大盤與個股同日 → PASS", hb.check_data_integrity(p)['verdict'] == 'PASS')
os.unlink(p)

# ─── A5. 退化保護 ───
print("\n[A5] 退化保護")
check("檔案不存在 → PASS 不誤報",
      hb.check_data_integrity('data/__no_such_file__.json')['verdict'] == 'PASS')
p = write_sh({})
check("market 空 → PASS 不誤報", hb.check_data_integrity(p)['verdict'] == 'PASS')
os.unlink(p)

# ─── A6. 迴歸: production 現況必須 PASS ───
print("\n[A6] 迴歸 — production stock_history 現況")
prod = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'data', 'stock_history.json')
if os.path.exists(prod):
    r = hb.check_data_integrity(prod)
    check(f"production PASS ({r['stats'].get('market_records')} 筆)",
          r['verdict'] == 'PASS', r['issues'])
else:
    print("  (跳過 — 無 production 資料)")

# ─── B. API 欄位 registry 完整性 (不打網路, 只驗結構) ───
print("\n[B] audit_api_fields registry 結構")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'scripts'))
import audit_api_fields as af

check("REGISTRY 非空", len(af.REGISTRY) >= 8, len(af.REGISTRY))
check("REGISTRY_RWD 非空", len(af.REGISTRY_RWD) >= 4, len(af.REGISTRY_RWD))
crit = [x for x in af.REGISTRY if x[4]]
check("至少 5 個 critical endpoint", len(crit) >= 5, len(crit))

# 三個曾出過事 / 最容易搞混的必須在 registry 內且列為 critical
names = ' '.join(x[0] for x in af.REGISTRY)
for must in ['MI_INDEX', 'STOCK_DAY_ALL', 'MI_MARGN', 'margin_balance']:
    check(f"{must} 在 registry 內", must in names)

# ⚠️ TWSE 融資是中文欄位 / TPEx 融資是英文欄位 — 第一版 registry 寫反並誤報 CRITICAL.
# 這裡把「哪邊是哪種語言」釘死, 避免下次再搞混.
twse_m = next(x for x in af.REGISTRY if 'MI_MARGN' in x[0])
tpex_m = next(x for x in af.REGISTRY if 'margin_balance' in x[0])
check("TWSE 融資 registry 用中文欄位",
      all(any('\u4e00' <= c <= '\u9fff' for c in f) for f in twse_m[3]), twse_m[3])
check("TPEx 融資 registry 用英文欄位",
      all(f.isascii() for f in tpex_m[3]), tpex_m[3])

# MI_INDEX 的日期欄位必須是中文「日期」— 這就是 v3.76.0 的 bug 本體
mi = next(x for x in af.REGISTRY if 'MI_INDEX' in x[0])
check("MI_INDEX 日期欄釘為中文「日期」(v3.76.0 bug 本體)", mi[5] == '日期', mi[5])
sda = next(x for x in af.REGISTRY if 'STOCK_DAY_ALL' in x[0])
check("STOCK_DAY_ALL 日期欄釘為英文 'Date' (此處原本就對)", sda[5] == 'Date', sda[5])

print(f"\n{'=' * 58}")
print(f"test_v3770_data_integrity_guard: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
