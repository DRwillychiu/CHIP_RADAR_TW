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


def _load_industry_map():
    """讀 industry_map.json 取得 stock_industry 對照 (code → 產業名)."""
    p = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data') / 'industry_map.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8')).get('stock_industry', {})
    except Exception:
        return {}


URL_DISPOSAL = 'https://attstock.tw/api/stocks/disposal'


def _fetch_disposal_tracking(today_str):
    """抓目前處置中清單, 回傳 tracking dict."""
    try:
        r = requests.get(URL_DISPOSAL, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️ disposal tracking fetch failed: {e}")
        return {}

    if not isinstance(data, list):
        return {}

    stocks = []
    new_today = []
    expiring_today = []
    expiring_soon = []

    for s in data:
        code = s.get('code', '')
        name = s.get('name', '')
        sd = s.get('disposal_start_date', '')
        ed = s.get('disposal_end_date', '')
        measures = s.get('disposal_measures', '')
        entry = {'code': code, 'name': name, 'start': sd, 'end': ed, 'type': measures}
        stocks.append(entry)
        if sd == today_str:
            new_today.append(entry)
        if ed == today_str:
            expiring_today.append(entry)
        elif ed and ed > today_str and ed <= (datetime.datetime.now() + datetime.timedelta(days=7)).strftime('%Y-%m-%d'):
            expiring_soon.append(entry)

    expiring_soon.sort(key=lambda x: x.get('end', ''))
    return {
        'total': len(stocks),
        'stocks': stocks,
        'new_today': new_today,
        'expiring_today': expiring_today,
        'expiring_soon': expiring_soon,
    }


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

    industry_map = _load_industry_map()
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')

    in_disposal = []
    pending_1d = []
    pending_2d = []
    pending_3d = []
    sample = []
    detail = []

    for s in data:
        code = s.get('code')
        name = s.get('name', '—')
        if not code: continue
        analysis = s.get('analysis') or {}
        days_to_disp = analysis.get('minDaysToDisposal')
        disp_type = analysis.get('disposalType') or '—'

        ds = s.get('disposal_start_date')
        de = s.get('disposal_end_date')
        is_in_disposal = bool(ds) and (not de or de >= today_str)

        def _detail_row(bucket):
            return {
                'code': code,
                'name': name,
                'type': disp_type,
                'bucket': bucket,
                'industry': industry_map.get(code, ''),
                'days_to_disposal': days_to_disp,
                'consecutive_days': analysis.get('consecutiveDays'),
                'consecutive_days_first': analysis.get('consecutiveDaysFirst'),
                'count_in_10d': analysis.get('countIn10Days'),
                'count_in_30d': analysis.get('countIn30Days'),
                'duration': analysis.get('disposalDuration'),
                'has_clause13': analysis.get('hasClause13InPeriod', False),
                'last_price': s.get('last_price'),
                'price_change': s.get('price_change'),
                'change_pct': s.get('price_change_pct'),
                'volume': s.get('volume'),
                'turnover': s.get('turnover'),
                'turnover_rate': s.get('turnover_rate'),
                'foreign_buy': s.get('foreign_buy'),
                'margin_ratio': s.get('margin_ratio'),
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
            bucket = f'{days_to_disp}d' if days_to_disp <= 5 else '6d+'
            detail.append(_detail_row(bucket))

    _order = {'in_disposal': 0, '1d': 1, '2d': 2, '3d': 3, '4d': 4, '5d': 5, '6d+': 6}
    detail.sort(key=lambda x: (_order.get(x['bucket'], 9), -(x.get('risk_score') or 0)))

    tracking = _fetch_disposal_tracking(today_str)

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
        'detail': detail,
        # ── v3.73.6 新增 (處置進出追蹤) ──
        'disposal_tracking': tracking,
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    total risk: {len(data)}")
    print(f"    in_disposal : {len(in_disposal)} → {sorted(in_disposal)[:5]}")
    print(f"    pending_1d  : {len(pending_1d)} → {sorted(pending_1d)[:5]}")
    print(f"    pending_2d  : {len(pending_2d)} → {sorted(pending_2d)[:5]}")
    print(f"    pending_3d+ : {len(pending_3d)} (只計數, 不列清單)")
    print(f"    detail 明細 : {len(detail)} 筆")
    if tracking:
        print(f"    tracking    : 處置中 {tracking.get('total',0)}, "
              f"今日新進 {len(tracking.get('new_today',[]))}, "
              f"今日出關 {len(tracking.get('expiring_today',[]))}")


if __name__ == '__main__':
    main()
