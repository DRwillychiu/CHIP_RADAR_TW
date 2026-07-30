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
    pending_2d = []        # v3.73.3: minDaysToDisposal == 2
    pending_3d = []        # v3.73.3: minDaysToDisposal >= 3 (只留數量, 長尾 160+ 檔)
    sample = []
    detail = []            # v3.73.3: D-1/D-2 的完整明細 (Telegram 推播用)

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

        # v3.73.3: D-1 / D-2 存完整明細供推播使用
        def _detail_row(bucket):
            return {
                'code': code,
                'name': name,
                'type': disp_type,                       # 5分盤 / 20分盤
                'bucket': bucket,                        # in_disposal / 1d / 2d
                'days_to_disposal': days_to_disp,
                'consecutive_days': analysis.get('consecutiveDays'),
                'count_in_10d': analysis.get('countIn10Days'),
                'count_in_30d': analysis.get('countIn30Days'),
                'duration': analysis.get('disposalDuration'),
                'last_price': s.get('last_price'),
                'change_pct': s.get('price_change_pct'),
                'day_trade_ratio': s.get('day_trade_ratio'),
                'risk_score': s.get('risk_score'),
                'market': s.get('market'),
            }

        if is_in_disposal:
            in_disposal.append(code)
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'in_disposal', 'end': de})
            detail.append(dict(_detail_row('in_disposal'), end=de))
        elif days_to_disp == 1:
            pending_1d.append(code)
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'pending_1d', 'days_to_disposal': 1})
            detail.append(_detail_row('1d'))
        elif days_to_disp == 2:
            pending_2d.append(code)
            detail.append(_detail_row('2d'))
        elif days_to_disp is not None and days_to_disp >= 3:
            pending_3d.append(code)

    # 排序: 先按 bucket (處置中 → D-1 → D-2),再按風險分數高的在前
    _order = {'in_disposal': 0, '1d': 1, '2d': 2}
    detail.sort(key=lambda x: (_order.get(x['bucket'], 9), -(x.get('risk_score') or 0)))

    out = {
        'fetched_at': datetime.datetime.now().isoformat(),
        'source': 'attstock.tw/api/stocks/risk',
        'total_risk_count': len(data),
        # ── 既有欄位 (excel_report.py 讀這些, 不可更動) ──
        'count_in_disposal': len(in_disposal),
        'count_pending_1d': len(pending_1d),
        'codes_in_disposal': sorted(in_disposal),
        'codes_pending_1d': sorted(pending_1d),
        'sample': sample[:30],
        # ── v3.73.3 新增 (Telegram 完整清單用) ──
        'count_pending_2d': len(pending_2d),
        'count_pending_3d_plus': len(pending_3d),
        'codes_pending_2d': sorted(pending_2d),
        'detail': detail,          # D-1 + D-2 完整明細 (約 38 筆)
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    total risk: {len(data)}")
    print(f"    in_disposal : {len(in_disposal)} → {sorted(in_disposal)[:5]}")
    print(f"    pending_1d  : {len(pending_1d)} → {sorted(pending_1d)[:5]}")
    print(f"    pending_2d  : {len(pending_2d)} → {sorted(pending_2d)[:5]}")
    print(f"    pending_3d+ : {len(pending_3d)} (只計數, 不列清單)")
    print(f"    detail 明細 : {len(detail)} 筆")


if __name__ == '__main__':
    main()
