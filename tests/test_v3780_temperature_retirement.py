# -*- coding: utf-8 -*-
"""v3.78.0 溫度計方向判定退役 — 落實驗證

背景 (2026-08-30 P1):
  160 天乾淨資料實測後, 溫度計的方向判定確認無可測量 alpha:
    · 配對命中率 Δ +0.0pp (全期/train/test 三段皆是, p=1.000)
    · 選擇能力 全期 -0.032% / OOS -0.310%
    · 9 個重設計候選 OOS 全部衰減 (最佳 train z=1.82 → test z=0.38)
    · t+1~t+10 全 horizon 無 edge
  結構性主因: 160 天只喊過 2 次偏空 — 幾乎不站空方就不可能贏過全多.

退役 ≠ 刪除. 處置是「數值保留, 方向判定不得當預測使用」,
所以本測試要同時鎖住**該留的有留**和**該標的有標**.
"""
import sys, os, json, io
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

# ─── 1. ALPHA_VERDICT 存在且數字與文件一致 ───
print("\n[1] ALPHA_VERDICT — 實測結論寫進程式碼")
from src.analyzers.signal_engine import ALPHA_VERDICT, infer_market_direction

check("verdict = no_measurable_edge", ALPHA_VERDICT['verdict'] == 'no_measurable_edge')
check("樣本 160 天", ALPHA_VERDICT['sample_days'] == 160)
check("方向 alpha 記為 0.0pp", ALPHA_VERDICT['directional_alpha_pp'] == 0.0)
check("OOS 選擇 alpha 為負", ALPHA_VERDICT['selection_alpha_pct_oos'] < 0)
check("記錄結構性主因 (偏空次數)", ALPHA_VERDICT['short_calls_in_sample'] == 2)
check("記錄候選數 (多重比較暴露量)", ALPHA_VERDICT['redesign_candidates_tested'] == 9)
check("OOS z 低於 train z (過擬合衰減)",
      ALPHA_VERDICT['best_candidate_test_z'] < ALPHA_VERDICT['best_candidate_train_z'])
check("指向 verdict 文件", ALPHA_VERDICT['doc'].endswith('TEMPERATURE_GAUGE_FINAL_VERDICT.md'))

# ─── 2. 每次呼叫都帶著判決 (消費端拿得到) ───
print("\n[2] infer_market_direction 回傳必須帶判決")
sigs = [{'name': 'P/C Ratio', 'score': 20, 'level': 'extreme-bull', 'value': 1.5},
        {'name': '分點漲停', 'score': 20, 'level': 'extreme-bull', 'value': 40}]
m = infer_market_direction(sigs)
check("回傳含 alpha_verdict", 'alpha_verdict' in m)
check("回傳含 confidence_is_measured_alpha", 'confidence_is_measured_alpha' in m)
check("明示 confidence 非實測 alpha", m['confidence_is_measured_alpha'] is False)
check("direction 仍計算 (未刪功能)", m['direction'] in ('偏多', '偏空', '中性'))
check("net_weight 仍計算", isinstance(m['net_weight'], float))

# 空輸入不可炸
m0 = infer_market_direction([])
check("空信號不炸且仍帶判決", m0['direction'] == '中性' and 'alpha_verdict' in m0)

# ─── 3. headline 不得再宣稱預測信心 ───
print("\n[3] headline — 不得把 net_weight 換算講成「信心%」")
src = io.open(os.path.join(ROOT, 'src/analyzers/signal_engine.py'),
              encoding='utf-8').read()
i = src.index('headline = ')
seg = src[i:i + 400]
check("headline 不含「信心」字樣", '信心' not in seg, seg[:120])
check("headline 標明非預測訊號", '非預測訊號' in seg, seg[:120])

# ─── 4. algo_params 狀態 ───
print("\n[4] algo_params.yaml — 狀態與保留項")
import yaml
cfg = yaml.safe_load(io.open(os.path.join(ROOT, 'config/algo_params.yaml'),
                             encoding='utf-8'))
ct = cfg['chip_temperature']
check("status = retired_as_direction_signal",
      ct['status'] == 'retired_as_direction_signal', ct['status'])
check("記錄退役日期", ct.get('retired_date') == '2026-08-30')
check("記錄退役理由", '0.0pp' in (ct.get('retired_reason') or ''))
# 退役 ≠ 刪除: signals 閾值必須保留 (溫度分數仍要算)
check("signals 閾值保留 (數值顯示仍需要)", len(ct.get('signals') or {}) >= 7)
check("algo_version 已升", cfg['algo_version'] == '3.78.0', cfg['algo_version'])

# ─── 5. 前端揭露 ───
print("\n[5] 前端 — 使用者必須看得到這是描述不是預測")
html = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
check("有揭露框", '這是描述,不是預測' in html)
check("揭露框寫出 Δ+0.0pp", 'Δ +0.0pp' in html or '+0.0pp' in html)
check("揭露框寫出 OOS 負值", '-0.31%' in html)
check("溫度計本體仍在 (未整個拿掉)", 'chip-temp-header' in html)

# ─── 6. 評估腳本可重現 ───
print("\n[6] 評估腳本存在且宣告方法論紀律")
sp = os.path.join(ROOT, 'scripts/eval_temperature_edge.py')
check("eval_temperature_edge.py 存在", os.path.exists(sp))
if os.path.exists(sp):
    s = io.open(sp, encoding='utf-8').read()
    check("宣告 train/test 不得回頭改", '不得回頭改' in s)
    check("宣告要報多重比較暴露量", '多重比較' in s)
    check("同時實作 M1 方向 與 M2 選擇 兩把尺",
          'def evaluate(' in s and 'def eval_selection(' in s)

# ─── 7. verdict 文件含誠實邊界 ───
print("\n[7] verdict 文件 — 必須寫明這份判決不能宣稱什麼")
dp = os.path.join(ROOT, 'docs/TEMPERATURE_GAUGE_FINAL_VERDICT.md')
check("文件存在", os.path.exists(dp))
if os.path.exists(dp):
    d = io.open(dp, encoding='utf-8').read()
    check("有「誠實的邊界」段", '誠實的邊界' in d)
    check("承認 test n=41 很小", 'n=41' in d)
    check("有重啟條件", '重新評估' in d or '重啟' in d)
    check("說明退役≠刪除 (數值保留)", '保留顯示' in d)

print(f"\n{'=' * 58}")
print(f"test_v3780_temperature_retirement: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
