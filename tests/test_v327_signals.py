# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.27 信號 6/7 本地測試 — 不需網路, 不需爬蟲
驗證 compute_chip_temperature() 對 4 個邊界 case 給出預期分數。
"""
import sys
sys.path.insert(0, '.')

from crawler import compute_chip_temperature, _days_to_settlement

# ────────────────── A. 結算日演算 ──────────────────
print("A. _days_to_settlement 驗證")
print("-" * 60)
# May 2026 第三個週三 = 5/20 (May 1 = Friday, May 6 = first Wed, +14 = May 20)
cases_days = [
    ('20260520',  0,   '5/20 = 結算當日'),
    ('20260519',  1,   '5/19 = 結算前 1 天'),
    ('20260521', -1,   '5/21 = 結算後 1 天'),
    ('20260508', 12,   '5/8 = 距結算 12 天 (5/20)'),
    ('20260415',  0,   '4/15 = April 第三週三'),  # 4月: 4/1 = Wed → 第三週三 = 4/15
    ('20260514',  6,   '5/14 = 距結算 6 天'),
    ('20260601',  16,  '6/1 = 距結算 16 天?'),  # 6月: 6/1=Mon, 6/3=Wed, +14=6/17, 6/1→6/17 = 16
]
for date, expected, desc in cases_days:
    actual = _days_to_settlement(date)
    ok = "✅" if actual == expected else "❌"
    print(f"  {ok} {date} expected d={expected:+}, got d={actual:+} ({desc})")

# ────────────────── B. 信號 6 法人共識 ──────────────────
print("\nB. 信號 6 法人共識")
print("-" * 60)

def make_raw(foreign_net=0, trust_net=0, futures_eq=None, pcr=None, limit_up=0, margin_top5=0):
    """偽造 raw_output. net 用張數,塞進單一 stock 條目讓加總對。"""
    return {
        'institutional_rankings': {
            'foreign': {
                'buy':  [{'foreign_net_lot': foreign_net}] if foreign_net > 0 else [],
                'sell': [{'foreign_net_lot': foreign_net}] if foreign_net < 0 else [],
            },
            'trust': {
                'buy':  [{'trust_net_lot': trust_net}] if trust_net > 0 else [],
                'sell': [{'trust_net_lot': trust_net}] if trust_net < 0 else [],
            },
        },
        'futures_data': {'summary': {'foreign_equivalent_net_oi': futures_eq, 'pc_ratio_oi': pcr}},
        'limit_up_summary': {'limit_up_stocks': [{}] * limit_up},
        'margin_rankings': {'top_margin_buy': [{'margin_change': margin_top5 * 1e8}]} if margin_top5 else {},
    }

cases_consensus = [
    # (foreign, trust, expected_score, expected_level, desc)
    (50000,  5000,  20, 'extreme-bull', '外資+50k / 投信+5k → 共識做多'),
    (40000,  4000,  20, 'extreme-bull', '剛超門檻 +30k/+3k → extreme-bull'),
    (20000,  2000,  15, 'bull',         '同向但未達門檻 → bull'),
    (50000, -5000,  10, 'neutral',      '一買一賣 → 分歧中性'),
    (-50000, -5000,  0, 'extreme-bear', '外資-50k / 投信-5k → 共識做空'),
    (-20000, -2000,  5, 'bear',         '同向賣但未達門檻 → bear'),
]
for f, t, exp_score, exp_level, desc in cases_consensus:
    raw = make_raw(foreign_net=f, trust_net=t)
    result = compute_chip_temperature(raw, trade_date='20260508')  # 非結算週,避免 sig7 干擾
    sig6 = next((s for s in result['signals'] if s['name'] == '法人共識'), None)
    ok = "✅" if sig6 and sig6['score'] == exp_score and sig6['level'] == exp_level else "❌"
    actual = f"score={sig6['score']} level={sig6['level']}" if sig6 else "MISSING"
    print(f"  {ok} {desc}: expected {exp_score}/{exp_level}, got {actual}")

# ────────────────── C. 信號 7 結算日壓力 ──────────────────
print("\nC. 信號 7 結算日壓力")
print("-" * 60)

cases_settle = [
    # (date, futures_eq, expected_score, expected_level, desc)
    ('20260520', -25000, 20, 'extreme-bull', '結算當日 外資深空 → 預期反彈'),
    ('20260519', -25000, 20, 'extreme-bull', '結算前 1 天 外資深空 → 反彈'),
    ('20260520',  25000,  0, 'extreme-bear', '結算當日 外資深多 → 預期回檔'),
    ('20260520',  0,     10, 'neutral',      '結算當日 外資中性 → neutral'),
    ('20260518', -15000, 15, 'bull',         '結算週 D-2 外資偏空 → bull (反指標)'),
    ('20260518',  15000,  5, 'bear',         '結算週 D-2 外資偏多 → bear'),
    ('20260508', -50000, 10, 'neutral',      '非結算週 任何持倉 → 退化中性'),
    ('20260601',  50000, 10, 'neutral',      '距結算 16 天 → 中性'),
]
for date, eq, exp_score, exp_level, desc in cases_settle:
    raw = make_raw(futures_eq=eq)
    result = compute_chip_temperature(raw, trade_date=date)
    sig7 = next((s for s in result['signals'] if s['name'] == '結算日壓力'), None)
    ok = "✅" if sig7 and sig7['score'] == exp_score and sig7['level'] == exp_level else "❌"
    actual = f"score={sig7['score']} level={sig7['level']}" if sig7 else "MISSING"
    print(f"  {ok} {desc}: expected {exp_score}/{exp_level}, got {actual}")

# ────────────────── D. 完整 7 信號 + 加總 ──────────────────
print("\nD. 完整 7 信號加總範例 (5/8 真實數據近似)")
print("-" * 60)
raw_full = make_raw(
    foreign_net=15000,    # → 外資現貨 bull (15)
    trust_net=2000,       # 不夠 3k 門檻
    futures_eq=-54530,    # → 外資期貨 extreme-bear (0); 結算 d=12 → neutral (10)
    pcr=1.81,             # → P/C extreme-bull (20)
    limit_up=33,          # → 分點漲停 extreme-bull (20)
    margin_top5=15,       # → 融資熱度 bear (5)
)
result = compute_chip_temperature(raw_full, trade_date='20260508')
print(f"  總分: {result['score']}/100  (signal_count={result['signal_count']}, total={result['total']}/{result['max_total']})")
for s in result['signals']:
    print(f"    - {s['name']}: {s['score']}/20 [{s['level']}]")
