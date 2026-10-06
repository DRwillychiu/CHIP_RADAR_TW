# -*- coding: utf-8 -*-
"""v3.75.0 quad 實測命中率 + 動態 premium tier 測試

背景 (2026-08-23 稽核):
  quad_hit_log.vs_expected 自己記著 expected 78.9% vs actual 49.4% (delta -29.5pp),
  但 Excel 有 5 處硬寫 78.9%. 使用者會據此高估勝率而放大部位.
  同時 PREMIUM_MASTERS 是 2026-06-26 用 n=6~18 小樣本凍結的名單,
  樣本累積後三位全數反轉 (陳族元 83.3%→23.1%, 陳律師 77.8%→31.6%).

驗證:
  1. _quad_live_stats 正確算出命中率 + Wilson CI
  2. 缺資料時 stale=True 且不當機
  3. 顯著性判定 (CI 與對照組重疊 → 未達顯著)
  4. 動態 premium 三條件 (n / hit% / CI 下界 > baseline)
  5. PREMIUM_MASTERS lazy shim 雙向 & 都正確 (frozenset 子類陷阱)
  6. refresh_premium_masters 可強制刷新
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import src.exports.excel_report as er

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1


def mkdir_with(files):
    d = Path(tempfile.mkdtemp())
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    return d


# ─── 1. 基本命中率 + Wilson CI ───
print("\n[1] _quad_live_stats 基本計算")
d1 = mkdir_with({
    'quad_hit_log.json': {'rolling_all': {'n': 233, 'hits': 115},
                          'rolling_30d': {'n': 47, 'hits': 22}},
    'phase32_backtest.json': {'summary': {'baseline': {'n': 638, 'hits': 275}}},
})
s1 = er._quad_live_stats(d1)
check("n / hits 正確", s1['n'] == 233 and s1['hits'] == 115)
check("命中率 49.4%", s1['hit_rate_pct'] == 49.4, f"got {s1['hit_rate_pct']}")
check("Wilson CI ≈ [43.0, 55.7]",
      abs(s1['ci_lo'] - 43.0) < 0.3 and abs(s1['ci_hi'] - 55.7) < 0.3,
      f"got [{s1['ci_lo']}, {s1['ci_hi']}]")
check("30 日 46.8%", s1['hit_rate_30d_pct'] == 46.8, f"got {s1['hit_rate_30d_pct']}")
check("對照組 43.1%", s1['baseline_pct'] == 43.1, f"got {s1['baseline_pct']}")
check("stale=False", s1['stale'] is False)

# ─── 2. 顯著性 ───
print("\n[2] 顯著性判定 (CI 重疊 → 未達顯著)")
check("quad CI 與對照組重疊 → significant=False", s1['significant'] is False)
d2 = mkdir_with({   # 造一個真的顯著的情境
    'quad_hit_log.json': {'rolling_all': {'n': 300, 'hits': 240}},   # 80%
    'phase32_backtest.json': {'summary': {'baseline': {'n': 600, 'hits': 260}}},  # 43%
})
s2 = er._quad_live_stats(d2)
check("80% vs 43% → significant=True", s2['significant'] is True,
      f"CI[{s2['ci_lo']},{s2['ci_hi']}] base={s2['baseline_pct']}")

# ─── 3. 缺資料退化 ───
print("\n[3] 缺資料時不當機")
d3 = Path(tempfile.mkdtemp())
s3 = er._quad_live_stats(d3)
check("無檔案 → stale=True", s3['stale'] is True)
check("無檔案 → label 說明待累積", '待累積' in s3['label'])
check("無檔案 → hit_rate_pct=None", s3['hit_rate_pct'] is None)
d4 = mkdir_with({'quad_hit_log.json': {'rolling_all': {'n': 0, 'hits': 0}}})
check("n=0 → stale=True", er._quad_live_stats(d4)['stale'] is True)

# ─── 4. 動態 premium 三條件 ───
print("\n[4] 動態 premium tier 三條件")
base_mc = lambda rows: {'baseline': {'hit_rate_pct': 49.4}, 'per_master': rows}

# 4a 全達標
d = mkdir_with({'master_contribution.json': base_mc([
    {'master': 'OK', 'n_with': 34, 'hr_with_pct': 67.6, 'ci_lo_pct': 50.8},
])})
er._PREMIUM_CACHE.clear()
check("n足+hit足+CI超越 → 入選", er.get_premium_masters(d) == {'OK'})

# 4b n 不足
d = mkdir_with({'master_contribution.json': base_mc([
    {'master': 'SmallN', 'n_with': 12, 'hr_with_pct': 83.3, 'ci_lo_pct': 55.2},
])})
er._PREMIUM_CACHE.clear()
check("n=12 < 20 → 排除 (即使 hit 83%)", er.get_premium_masters(d) == set())

# 4c hit 不足
d = mkdir_with({'master_contribution.json': base_mc([
    {'master': 'LowHit', 'n_with': 40, 'hr_with_pct': 55.0, 'ci_lo_pct': 50.1},
])})
er._PREMIUM_CACHE.clear()
check("hit 55% < 60% → 排除", er.get_premium_masters(d) == set())

# 4d CI 下界未超越 baseline
d = mkdir_with({'master_contribution.json': base_mc([
    {'master': 'WideCI', 'n_with': 25, 'hr_with_pct': 64.0, 'ci_lo_pct': 45.0},
])})
er._PREMIUM_CACHE.clear()
check("CI下界 45 <= baseline 49.4 → 排除 (優勢不顯著)",
      er.get_premium_masters(d) == set())

# 4e 檔案不存在 → 空集合 (寧可不標也不標錯)
er._PREMIUM_CACHE.clear()
check("無 contribution 檔 → 空集合", er.get_premium_masters(Path(tempfile.mkdtemp())) == set())

# ─── 5. lazy shim 雙向 & (frozenset 子類陷阱) ───
print("\n[5] PREMIUM_MASTERS lazy shim 運算子")
d5 = mkdir_with({'master_contribution.json': base_mc([
    {'master': '巨人傑', 'n_with': 34, 'hr_with_pct': 67.6, 'ci_lo_pct': 50.8},
])})
er._PREMIUM_CACHE.clear()
er._PREMIUM_CACHE[str(d5)] = {'巨人傑'}
# 直接驗 shim 行為 (用 module 級 PREMIUM_MASTERS 需真實 data, 這裡驗運算子語意)
live = er.PREMIUM_MASTERS
t = {'巨人傑', '蔣承翰'}
check("set & PREMIUM (右運算元, frozenset 子類會踩雷的方向)",
      isinstance(t & live, set), f"got {type(t & live)}")
check("PREMIUM & set", isinstance(live & t, set))
check("in 運算子可用", isinstance('巨人傑' in live, bool))
check("len / bool 可用", isinstance(len(live), int) and isinstance(bool(live), bool))
check("sorted() 可迭代", isinstance(sorted(live), list))
check("PREMIUM_MASTERS 非 frozenset 子類 (避免 C 路徑繞過 __rand__)",
      not isinstance(live, frozenset))

# ─── 6. refresh ───
print("\n[6] refresh_premium_masters 強制刷新")
er._PREMIUM_CACHE.clear()
er._PREMIUM_CACHE['stale_key'] = {'舊名單'}
r = er.refresh_premium_masters(d5)
check("refresh 後 cache 被清空重算", 'stale_key' not in er._PREMIUM_CACHE)
check("refresh 回傳實測結果", r == {'巨人傑'}, f"got {r}")

print(f"\n{'='*58}")
print(f"test_v3750_quad_live_stats: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
