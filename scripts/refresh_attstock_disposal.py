"""v3.71.7: 抓 attstock.tw 處置股清單寫 data/disposal_attstock.json.

整合到 Chip Radar 「今日避開」 section. 跟自己的 disposal_watch repo 同源
(attstock.tw 公開 API), 但 Chip Radar 只用「codes set + count」, 不重複
disposal_watch 的完整節錄功能.

執行: python scripts/refresh_attstock_disposal.py
寫入: data/disposal_attstock.json
  {
    "fetched_at": ISO,
    "count_in_disposal": int,    # 目前已處置
    "count_pending_1d": int,      # 1 天內即將處置 (minDaysToDisposal=1)
    "codes_in_disposal": [...],
    "codes_pending_1d": [...],
    "sample": [{code, name, type, days_to_disposal}, ...]   # 給 hover 用
  }
"""
import json, os, sys, requests, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
# v3.73.1: 尊重 CHIP_RADAR_DATA_DIR (本機排程用 local_data/)
OUT = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data') / 'disposal_attstock.json'

URL = 'https://attstock.tw/api/stocks/risk'


def main():
    print(f"fetch {URL}")
    try:
        r = requests.get(URL, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ✗ fetch failed: {e}")
        sys.exit(1)

    if not isinstance(data, list):
        print(f"  ✗ unexpected response shape")
        sys.exit(1)

    in_disposal = []      # status='disposal' or similar
    pending_1d = []        # minDaysToDisposal == 1
    sample = []
    for s in data:
        code = s.get('code')
        name = s.get('name', '—')
        if not code: continue
        status = s.get('status') or ''
        analysis = s.get('analysis') or {}
        days_to_disp = analysis.get('minDaysToDisposal')
        disp_type = analysis.get('disposalType') or '—'

        # 「正在處置」: 有 disposal_start_date 且 disposal_end_date >= 今天
        ds = s.get('disposal_start_date')
        de = s.get('disposal_end_date')
        today_yyyymmdd = datetime.datetime.now().strftime('%Y-%m-%d')
        is_in_disposal = bool(ds) and (not de or de >= today_yyyymmdd[:10])

        if is_in_disposal:
            in_disposal.append(code)
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'in_disposal', 'end': de})
        elif days_to_disp == 1:
            pending_1d.append(code)
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'pending_1d', 'days_to_disposal': 1})

    out = {
        'fetched_at': datetime.datetime.now().isoformat(),
        'source': 'attstock.tw/api/stocks/risk',
        'total_risk_count': len(data),
        'count_in_disposal': len(in_disposal),
        'count_pending_1d': len(pending_1d),
        'codes_in_disposal': sorted(in_disposal),
        'codes_pending_1d': sorted(pending_1d),
        'sample': sample[:30],
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    total risk: {len(data)}")
    print(f"    in_disposal: {len(in_disposal)} → top 5: {sorted(in_disposal)[:5]}")
    print(f"    pending_1d: {len(pending_1d)} → top 5: {sorted(pending_1d)[:5]}")


if __name__ == '__main__':
    main()
