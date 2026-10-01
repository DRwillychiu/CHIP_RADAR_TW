# -*- coding: utf-8 -*-
"""v3.80.5 大盤缺口自我修復 + temp_history 對齊 + heartbeat 中間缺口

背景 (2026-10-01 稽核):
  v3.79.5 (09/22 23:45) 用 FMTQIK 把 8/31~9/21 的大盤缺口補到 60/60,
  13 分鐘後被一個並行的 daily-full 用舊版 stock_history 蓋掉
  (push 衝突走 `git pull --rebase -X theirs`). 之後 9 天:
    · market 60 天缺 14 天 → Quad 失效歸因出現「TAIEX 資料缺, 歸因不全」
    · 缺口後第一天的 change_pct 對著錯的錨點算 (09/10 +1.31% 實為 -0.51%, 正負翻轉)
    · temp_history.taiex_change_pct 60 筆 36 錯 / 18 None
    · heartbeat 全程 PASS — 它只看錯位與最新一筆, 不看中間的洞

  一次性回補在多排程並寫的環境不可靠 → 改成每日流程自己檢查並補 (冪等).
"""
import sys, os, json, copy, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.fetchers.history import heal_market_gaps, _prev_month
from src.pipelines.crawler_pipeline import _sync_temp_with_market
import heartbeat_check as hb

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1

# 官方指數 (假資料)
OFF = {
    '20260828': 100.0, '20260831': 102.0, '20260901': 101.0,
    '20260902': 103.0, '20260903': 104.0, '20260904': 102.96,
}
def fake_fetch(ym):
    return {d: v for d, v in OFF.items() if d.startswith(ym)}
calls = []
def counting_fetch(ym):
    calls.append(ym)
    return fake_fetch(ym)

def roc(d):
    return f'{int(d[:4]) - 1911}{d[4:]}'

def mk(days, pct_override=None):
    out = {}
    for d in days:
        out[d] = {'index': OFF[d], 'change_pct': (pct_override or {}).get(d, 0.0),
                  'quote_date': roc(d)}
    return out

# ─── 1. 無缺口 → 零成本 ───
print("\n[1] 無缺口 → 不打網路")
h = {'dates': sorted(OFF), 'market': mk(sorted(OFF))}
calls.clear()
check("回傳空清單", heal_market_gaps(h, '20260904', fetch_month=counting_fetch) == [])
check("完全沒有呼叫 FMTQIK", calls == [], calls)

# ─── 2. 中間缺口 → 補回 + 正確 change_pct ───
print("\n[2] 中間缺口 (重現 9/22 被蓋掉後的狀態)")
# 缺 0831/0901/0902, 而 0903 的 change_pct 是對著 0828 算的 (錯錨點)
bad_0903 = round((104.0 - 100.0) / 100.0 * 100, 2)   # +4.0 (錯)
h = {'dates': sorted(OFF),
     'market': mk(['20260828', '20260903', '20260904'], {'20260903': bad_0903})}
healed = heal_market_gaps(h, '20260904', fetch_month=fake_fetch)
check("補回 3 天", healed == ['20260831', '20260901', '20260902'], healed)
check("0831 index 正確", h['market']['20260831']['index'] == 102.0)
check("0831 change_pct 以官方前一日算 (+2.0%)",
      h['market']['20260831']['change_pct'] == 2.0, h['market']['20260831'])
check("0901 下跌正負號正確 (-0.98%)",
      h['market']['20260901']['change_pct'] == -0.98, h['market']['20260901'])
check("補回的列有 quote_date (過得了 v3.77 守門)",
      h['market']['20260902']['quote_date'] == '1150902')
check("缺口後錨點校正: 0903 從 +4.0 改成 +0.97",
      h['market']['20260903']['change_pct'] == 0.97, h['market']['20260903'])
check("錨點校正有標來源", 'post_gap' in h['market']['20260903'].get('change_pct_source', ''))
check("0904 (非缺口後) 不動", h['market']['20260904']['change_pct'] == 0.0)

# ─── 3. 冪等 ───
print("\n[3] 冪等 — 再跑一次不應有任何改動")
snap = copy.deepcopy(h)
calls.clear()
check("第二次回傳空", heal_market_gaps(h, '20260904', fetch_month=counting_fetch) == [])
check("第二次不打網路", calls == [])
check("資料完全不變", h == snap)

# ─── 4. 官方尚未公布 → 保留缺口, 不亂寫 ───
print("\n[4] 官方也沒有的日子 → 不寫, 留待下次")
h = {'dates': ['20260828', '20260907'], 'market': mk(['20260828'])}
check("FMTQIK 沒有 0907 → 不補", heal_market_gaps(h, '20260907', fetch_month=fake_fetch) == [])
check("0907 仍不存在 (沒寫入 None 列)", '20260907' not in h['market'])
h = {'dates': ['20260828', '20260831'], 'market': mk(['20260828'])}
check("FMTQIK 整個失敗 → 回空不炸",
      heal_market_gaps(h, '20260831', fetch_month=lambda ym: {}) == [])

# ─── 5. upto 邊界 ───
print("\n[5] upto 之後的日子不處理")
h = {'dates': sorted(OFF), 'market': mk(['20260828'])}
healed = heal_market_gaps(h, '20260901', fetch_month=fake_fetch)
check("只補到 upto", healed == ['20260831', '20260901'], healed)
check("跨年前一個月", _prev_month('202601') == '202512' and _prev_month('202609') == '202608')

# ─── 6. temp_history 全量對齊 ───
print("\n[6] temp_history 以 market 全量重算")
days = sorted(OFF)
h = {'dates': days, 'market': mk(days)}
for i, d in enumerate(days):
    if i:
        p0 = OFF[days[i - 1]]
        h['market'][d]['change_pct'] = round((OFF[d] - p0) / p0 * 100, 2)
temp = [
    {'date': '20260831', 'taiex_change_pct': -9.9, 'next_day_change_pct': None},   # 錯 + 缺
    {'date': '20260901', 'taiex_change_pct': None, 'next_day_change_pct': 5.55},   # 缺 + 錯
    {'date': '20260904', 'taiex_change_pct': None, 'next_day_change_pct': None},   # 最新
]
r = _sync_temp_with_market(temp, h['market'])
check("錯的 taiex_change_pct 被更正", temp[0]['taiex_change_pct'] == 2.0, temp[0])
check("None 的 next_day 被補上 (=0901 漲跌)", temp[0]['next_day_change_pct'] == -0.98, temp[0])
check("錯的 next_day 被更正 (=0902 漲跌)", temp[1]['next_day_change_pct'] == 1.98, temp[1])
check("最新一筆 next_day 維持 None (還沒有隔日)", temp[2]['next_day_change_pct'] is None)
check("回報修正數", r['taiex_fixed'] >= 2 and r['next_fixed'] == 2, r)
temp2 = [{'date': '20260831', 'taiex_change_pct': 2.0, 'next_day_change_pct': 7.7}]
_sync_temp_with_market(temp2, {'20260831': {'index': 102.0, 'change_pct': 2.0}})
check("market 沒有隔日 → 不把既有值蓋成 None", temp2[0]['next_day_change_pct'] == 7.7)

# ─── 7. heartbeat 中間缺口 ───
print("\n[7] heartbeat — 中間缺口必須 FAIL (原本 9 天都是 PASS)")
def write(obj):
    fd, p = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    return p
p = write({'dates': days, 'market': mk(['20260828', '20260903', '20260904']), 'stocks': {}})
r = hb.check_data_integrity(p); os.unlink(p)
check("中間缺 3 天 → FAIL", r['verdict'] == 'FAIL', r)
check("stats 記錄 interior_gaps=3", r['stats'].get('interior_gaps') == 3, r['stats'])
p = write({'dates': days, 'market': mk(days[:-1]), 'stocks': {}})
r = hb.check_data_integrity(p); os.unlink(p)
check("只缺最新一天 → 不算中間缺口", r['stats'].get('interior_gaps') == 0, r)
p = write({'dates': days, 'market': mk(days), 'stocks': {}})
check("完整 → PASS", hb.check_data_integrity(p)['verdict'] == 'PASS')
os.unlink(p)

# ─── 8. workflow 不可並行 ───
print("\n[8] daily-full 必須序列化")
import yaml
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, '.github/workflows/daily-full.yml'), encoding='utf-8') as f:
    wf = yaml.safe_load(f)
c = wf.get('concurrency') or {}
check("有 concurrency group", bool(c.get('group')), c)
check("cancel-in-progress=false (不可砍掉正在跑的)", c.get('cancel-in-progress') is False, c)

print(f"\n{'=' * 58}")
print(f"test_v3805_market_self_heal: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
