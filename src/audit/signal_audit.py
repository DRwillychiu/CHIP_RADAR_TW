"""signal_audit.py — v3.27.1 籌碼溫度計校準資料審計工具

用途:檢視 data/temp_history.json,評估各信號的預測力,給 v3.28 校準提供基礎。

用法: python signal_audit.py [--data-dir data] [--min-cases 5]
  --data-dir: temp_history.json 所在目錄 (預設 ./data)
  --min-cases: 每個 (signal, level) 至少幾個 case 才算有意義 (預設 5)

輸出:
  1. 資料累積狀況 (距校準下限/理想還差幾天)
  2. 信號 × level 分布 (各 level 出現次數)
  3. 若資料 >= 30 天: 各 signal × level 的「平均次日漲幅」+ 預測力評估
  4. 校準建議 (哪些 level 預測力差,建議下版調整)

注意: 此腳本只「印報告」,不修改任何閾值。實際校準仍須人工 review 後手動改 TEMP_THRESHOLDS。
"""
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


MIN_DAYS_FOR_CALIBRATION = 30
IDEAL_DAYS_FOR_CALIBRATION = 60

# 每個 level 的「預測方向」: +1 = 預期次日漲, -1 = 預期跌, 0 = 中性 (預期窄幅)
LEVEL_DIRECTION = {
    'extreme-bull': +1,
    'bull':         +1,
    'neutral':       0,
    'bear':         -1,
    'extreme-bear': -1,
}

LEVEL_ORDER = ['extreme-bull', 'bull', 'neutral', 'bear', 'extreme-bear']
LEVEL_LABEL = {
    'extreme-bull': '極多',
    'bull':         '偏多',
    'neutral':      '中性',
    'bear':         '偏空',
    'extreme-bear': '極空',
}


def load_history(data_dir: Path):
    f = data_dir / "temp_history.json"
    if not f.exists():
        print(f"[ERR] temp_history.json 不存在於 {data_dir}")
        sys.exit(1)
    with open(f, 'r', encoding='utf-8') as fp:
        payload = json.load(fp)
    return payload


def section(title):
    print()
    print("=" * 64)
    print(f"  {title}")
    print("=" * 64)


def report_accumulation(history, meta):
    section("1. 資料累積狀況")
    n = len(history)
    n_with_return = sum(1 for h in history if h.get('next_day_change_pct') is not None)
    print(f"  累積交易日數: {n}")
    print(f"  含 next_day_change_pct 可用 case: {n_with_return}")
    min_d = meta.get('min_days_for_calibration', MIN_DAYS_FOR_CALIBRATION)
    ideal_d = meta.get('ideal_days_for_calibration', IDEAL_DAYS_FOR_CALIBRATION)
    bar_n = min(n_with_return, ideal_d)
    bar = "▓" * int(bar_n * 32 / ideal_d) + "░" * (32 - int(bar_n * 32 / ideal_d))
    print(f"  進度 (vs 理想 {ideal_d} 天): [{bar}] {n_with_return}/{ideal_d} = {n_with_return * 100 // ideal_d}%")
    if n_with_return < min_d:
        print(f"  ⏳ 距校準下限 {min_d} 天還差 {min_d - n_with_return} 個交易日")
        return False
    if n_with_return < ideal_d:
        print(f"  ✅ 已達校準下限 (>= {min_d}), 但離理想 {ideal_d} 還差 {ideal_d - n_with_return} 天")
        return True
    print(f"  🌟 已達理想累積 {ideal_d} 天,可信心校準")
    return True


def report_distribution(history):
    section("2. 信號 × Level 分布 (累積出現次數)")
    # signal_name -> level -> count
    dist = defaultdict(lambda: defaultdict(int))
    signal_names_order = []
    for h in history:
        for s in h.get('signals', []):
            nm = s.get('name')
            lv = s.get('level')
            if nm not in dist:
                signal_names_order.append(nm)
            dist[nm][lv] += 1
    if not dist:
        print("  (沒有信號資料)")
        return
    # Print header
    header = f"  {'信號':<14} " + "".join(f"{LEVEL_LABEL[l]:>7}" for l in LEVEL_ORDER) + "    總計"
    print(header)
    print("  " + "─" * (len(header) - 2))
    for nm in signal_names_order:
        row = f"  {nm:<14} "
        total = 0
        for lv in LEVEL_ORDER:
            c = dist[nm].get(lv, 0)
            row += f"{c:>7}"
            total += c
        row += f"   {total:>5}"
        print(row)


def report_hit_rates(history, min_cases):
    section(f"3. 信號預測力評估 (每組至少 {min_cases} case)")
    # signal_name -> level -> [next_day_change_pct values]
    bucket = defaultdict(lambda: defaultdict(list))
    signal_names_order = []
    for h in history:
        nd = h.get('next_day_change_pct')
        if nd is None:
            continue
        for s in h.get('signals', []):
            nm = s.get('name')
            lv = s.get('level')
            if nm not in bucket:
                signal_names_order.append(nm)
            bucket[nm][lv].append(nd)
    if not bucket:
        print("  (沒有任何 case 含 next_day_change_pct,無法分析)")
        print("  → 至少等到隔天再次 crawl 完才會出現第一個可用 case")
        return []

    recommendations = []
    for nm in signal_names_order:
        print(f"\n  ▼ {nm}")
        any_meaningful = False
        for lv in LEVEL_ORDER:
            vals = bucket[nm].get(lv, [])
            if len(vals) < min_cases:
                if vals:
                    print(f"    {LEVEL_LABEL[lv]:<5} n={len(vals)} (case 不足 {min_cases}, 略)")
                continue
            any_meaningful = True
            n = len(vals)
            mean = sum(vals) / n
            expected_dir = LEVEL_DIRECTION[lv]
            if expected_dir == +1:
                hits = sum(1 for v in vals if v > 0)
            elif expected_dir == -1:
                hits = sum(1 for v in vals if v < 0)
            else:
                hits = sum(1 for v in vals if abs(v) <= 0.5)
            hit_rate = hits / n * 100
            verdict = "✅" if hit_rate >= 55 else ("⚠️ " if hit_rate >= 45 else "❌")
            print(f"    {LEVEL_LABEL[lv]:<5} n={n:>3}  avg次日={mean:+.2f}%  hit={hit_rate:5.1f}%  {verdict}")
            # 評估
            if hit_rate < 45 and expected_dir != 0:
                recommendations.append(
                    f"信號「{nm}」的 {LEVEL_LABEL[lv]} ({lv}) hit rate 僅 {hit_rate:.1f}% (n={n}, "
                    f"avg={mean:+.2f}%) — 預測方向可能反向, 建議檢視閾值或反指標標記"
                )
            elif hit_rate >= 65:
                recommendations.append(
                    f"信號「{nm}」的 {LEVEL_LABEL[lv]} hit rate {hit_rate:.1f}% (n={n}) — 預測力佳,維持"
                )
        if not any_meaningful:
            print(f"    (此信號各 level 樣本都不足 {min_cases},再累積)")
    return recommendations


def report_recommendations(recommendations, can_calibrate):
    section("4. 校準建議 (v3.28 參考)")
    if not can_calibrate:
        print("  ⏳ 資料不足下限,本次無校準建議。繼續累積後重跑此腳本。")
        return
    if not recommendations:
        print("  ✅ 目前各信號預測力皆在合理範圍,無立即調整建議")
        return
    for i, rec in enumerate(recommendations, 1):
        print(f"  {i}. {rec}")
    print()
    print("  ⚠️ 注意:此腳本只給「建議」,實際調整 TEMP_THRESHOLDS 仍需人工 review")
    print("       並重跑 test_v327_signals.py 確認沒打破邊界 case")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='data', help='temp_history.json 所在目錄')
    parser.add_argument('--min-cases', type=int, default=5, help='每組最少 case 數')
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    payload = load_history(data_dir)
    history = payload.get('history', [])
    meta = payload.get('_calibration_meta', {})

    print()
    print("╔" + "═" * 62 + "╗")
    print("║" + "  Chip Radar v3.27.1 籌碼溫度計校準資料審計  ".center(62) + "║")
    print("╚" + "═" * 62 + "╝")

    can_calibrate = report_accumulation(history, meta)
    report_distribution(history)
    recommendations = report_hit_rates(history, args.min_cases)
    report_recommendations(recommendations, can_calibrate)

    print()
    print("─" * 64)
    if meta.get('thresholds_snapshot'):
        print("  當前閾值快照 (v3.27 初版):")
        for k, v in meta['thresholds_snapshot'].items():
            print(f"    {k}: {v}")
    print()


if __name__ == '__main__':
    main()
