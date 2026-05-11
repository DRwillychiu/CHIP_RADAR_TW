"""test_signal_audit.py — 模擬 35 天累積 temp_history 驗證 signal_audit.py 可正確產生 hit-rate 分析

生成 fixture 後直接呼叫 signal_audit.py main(),斷言關鍵字串出現。
"""
import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


def make_entry(d_str, signals_levels_values, taiex, next_pct):
    """signals_levels_values: list of (name, level, value)"""
    level_score = {'extreme-bull': 20, 'bull': 15, 'neutral': 10, 'bear': 5, 'extreme-bear': 0}
    sigs = []
    for nm, lv, val in signals_levels_values:
        sigs.append({'name': nm, 'score': level_score[lv], 'level': lv, 'value': val})
    total = sum(s['score'] for s in sigs)
    return {
        'date': d_str,
        'score': round(total / (len(sigs) * 20) * 100),
        'signals': sigs,
        'taiex_index': taiex,
        'taiex_change_pct': None,
        'next_day_change_pct': next_pct,
    }


def main():
    random.seed(42)
    history = []
    start = date(2026, 4, 1)
    for i in range(35):
        d = start + timedelta(days=i)
        d_str = d.strftime("%Y%m%d")
        # 設計一個「外資期貨 extreme-bear 高機率次日跌」的合成 dataset 驗證腳本能抓出來
        eq = random.choice([-50000, -40000, -5000, 5000, 40000])
        if eq <= -30000:
            lv_eq = 'extreme-bear'
            next_pct = round(random.gauss(-0.8, 0.5), 2)  # 偏向跌
        elif eq <= -10000:
            lv_eq = 'bear'
            next_pct = round(random.gauss(-0.3, 0.5), 2)
        elif eq >= 30000:
            lv_eq = 'extreme-bull'
            next_pct = round(random.gauss(0.8, 0.5), 2)
        elif eq >= 10000:
            lv_eq = 'bull'
            next_pct = round(random.gauss(0.3, 0.5), 2)
        else:
            lv_eq = 'neutral'
            next_pct = round(random.gauss(0.0, 0.7), 2)

        # 另一個信號「分點漲停」隨機 — 應該沒明顯 hit rate (control case)
        lv_lu = random.choice(['extreme-bull', 'bull', 'neutral', 'bear'])

        history.append(make_entry(d_str, [
            ('外資期貨', lv_eq, eq),
            ('分點漲停', lv_lu, None),
        ], taiex=22000 + i * 10, next_pct=next_pct))

    # Write to temp dir
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        payload = {
            'updated_at': '2026-05-10T22:00:00+08:00',
            'count': len(history),
            'history': history,
            '_calibration_meta': {
                'min_days_for_calibration': 30,
                'ideal_days_for_calibration': 60,
                'thresholds_snapshot': {'foreign_futures_eq': [30000, 10000, -10000, -30000]},
                'last_calibrated_at': None,
            },
        }
        with open(data_dir / "temp_history.json", 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # Run signal_audit.py
        script = Path(__file__).parent / "signal_audit.py"
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, str(script), '--data-dir', str(data_dir), '--min-cases', '3'],
            capture_output=True, text=True, encoding='utf-8', env=env,
        )
        out = result.stdout
        print(out)

        # Assert key features
        checks = [
            ('Accumulation report', '累積交易日數: 35'),
            ('Hit rate analysis ran', '預測力評估'),
            ('外資期貨 signal block', '▼ 外資期貨'),
            ('Recommendation section', '校準建議'),
        ]
        all_pass = True
        for name, needle in checks:
            ok = needle in out
            print(f"  {'✅' if ok else '❌'} {name}: {'PASS' if ok else 'FAIL'} (looking for '{needle}')")
            if not ok:
                all_pass = False

        # 額外: 外資期貨 extreme-bear 在這個 fixture 應該 hit rate 高 (我刻意 gauss(-0.8))
        if '外資期貨' in out:
            print("\n  (fixture 設計: 外資期貨 extreme-bear → 次日 gauss(-0.8, 0.5);")
            print("   預期 hit_rate >= 65%,腳本應推薦「預測力佳,維持」)")

        sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
