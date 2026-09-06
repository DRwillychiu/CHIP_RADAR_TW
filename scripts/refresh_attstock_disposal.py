"""v3.75.0: 抓 attstock.tw 處置股清單寫 data/disposal_attstock.json.

整合三支 API:
  1. /api/stocks/risk              → 完整風險股清單 + analysis
  2. /api/stocks/daily-report      → 處置進出追蹤
  3. /api/stocks/analysis/{code}   → 1d/2d 逐檔條件描述

供 src/exports/excel_report.py 的「今日避開」使用。圖卡不走這裡 ——
那是 scripts/push_disposal_telegram.py 抓 disposal-watch 雲端 artifact。

執行: python scripts/refresh_attstock_disposal.py
寫入: data/disposal_attstock.json
"""
import json, os, re, sys, time, requests, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data') / 'disposal_attstock.json'

URL_RISK = 'https://attstock.tw/api/stocks/risk'
URL_REPORT = 'https://attstock.tw/api/stocks/daily-report'
URL_DISPOSAL = 'https://attstock.tw/api/stocks/disposal'
URL_ANALYSIS = 'https://attstock.tw/api/stocks/analysis'

# 2026-08-24 起 attstock 擋非瀏覽器 UA。實測 (2026-09-06) 短字串 'Mozilla/5.0'
# 一律 403,完整 Chrome UA 才 200 —— 勿再簡寫或加自訂後綴。
# 這支用短 UA 撐到 8/24 之後就整整兩週抓不到東西 (每次 exit 1,無人察覺),
# 期間還照三班節奏重打,推測是本機 IP 被升級封鎖的原因之一 (9/06 已解除)。
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36')
_HDR = {'User-Agent': _UA, 'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-TW,zh;q=0.9', 'Referer': 'https://attstock.tw/'}

# 逐檔請求之間的間隔。上游 disposal-watch 在 2026-08-24 來源開始限流時加了
# 同樣的節流;本檔當時沒跟上,十幾二十個請求連珠炮打出去。每日 10-25 檔,
# 多花十秒換不被封,划算。
_THROTTLE = 0.5

_CLAUSE_LABEL = {
    1: '價格', 2: '成交量', 3: '成交筆數',
    4: '當沖', 5: '本益比', 6: '估值+週轉', 13: '當沖',
}
_CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _parse_clause(reason):
    """從 reason 文字提取主要觸發款項 (第六款 → 6)."""
    m = re.findall(r'第([一二三四五六七八九十]+)款', reason or '')
    if not m:
        return 0
    s = m[0]
    if len(s) == 1:
        return _CN_NUM.get(s, 0)
    if s.startswith('十'):
        return 10 + _CN_NUM.get(s[1:], 0) if len(s) > 1 else 10
    if s.endswith('十'):
        return _CN_NUM.get(s[0], 0) * 10
    return _CN_NUM.get(s, 0)


def _load_industry_map():
    p = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data') / 'industry_map.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8')).get('stock_industry', {})
    except Exception:
        return {}


def _fetch_tracking():
    """抓 daily-report + disposal API, 回傳處置進出追蹤 dict.

    用當天日期抓 daily-report（排程器在盤後跑, 需要當天的出關資料）,
    若當天沒報告則 fallback 到最新。
    """
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f'{URL_REPORT}/{today}'
    try:
        r = requests.get(url, timeout=15, headers=_HDR)
        r.raise_for_status()
        data = r.json()
        print(f"  daily-report/{today}: OK (date={data.get('date','')})")
    except Exception:
        try:
            r = requests.get(URL_REPORT, timeout=15, headers=_HDR)
            r.raise_for_status()
            data = r.json()
            print(f"  daily-report (fallback): date={data.get('date','')}")
        except Exception as e:
            print(f"  ⚠️ daily-report fetch failed: {e}")
            return {}

    entering = data.get('enteringDisposal') or []
    exits = data.get('upcomingExits') or []

    tracking = {
        'entering': [{'code': x['code'], 'name': x['name'],
                      'type': x.get('disposalType', ''),
                      'start': x.get('startDate', ''), 'end': x.get('endDate', '')}
                     for x in entering],
        'exits': [{'code': x['code'], 'name': x['name'],
                   'exit_date': x.get('exitDate', ''),
                   'days_remaining': x.get('daysRemaining', 0)}
                  for x in exits],
        'report_date': data.get('date', ''),
        'disposal_5min': [{'code': x['code'], 'name': x['name'],
                          'trigger_desc': x.get('triggerDescription', '')}
                         for x in (data.get('disposal5min') or [])],
        'disposal_20min': [{'code': x['code'], 'name': x['name'],
                           'trigger_desc': x.get('triggerDescription', '')}
                          for x in (data.get('disposal20min') or [])],
        'self_cert_yesterday': [{'code': x['code'], 'name': x['name'],
                                'eps': x.get('eps')}
                               for x in (data.get('selfCertYesterday') or [])],
    }

    try:
        rd = requests.get(URL_DISPOSAL, timeout=15, headers=_HDR)
        rd.raise_for_status()
        disp_list = rd.json()
        tracking['total'] = len(disp_list) if isinstance(disp_list, list) else 0
    except Exception:
        tracking['total'] = 0

    return tracking


def _fetch_stock_conditions(codes):
    """對 1d/2d 股票逐檔抓 analysis API, 回傳 {code: (label, desc)}.

    403/429 一出現就整批中止: 那代表被來源擋下,繼續打只會讓封鎖延長
    (上游 disposal-watch 的 get_json 同樣策略)。已取得的部分照常回傳,
    缺的欄位在下游是空字串,不會讓整份 json 產不出來。
    """
    result = {}
    for i, code in enumerate(codes):
        if i:
            time.sleep(_THROTTLE)
        try:
            r = requests.get(f'{URL_ANALYSIS}/{code}',
                             timeout=10, headers=_HDR)
            r.raise_for_status()
            data = r.json()
        except requests.HTTPError as e:
            sc = getattr(e.response, 'status_code', 0)
            if sc in (403, 429):
                print(f"    ⛔ analysis/{code} HTTP {sc} 被來源擋下,中止逐檔查詢 "
                      f"(已取得 {len(result)}/{len(codes)} 檔)")
                break
            print(f"    ⚠️ analysis/{code} failed: {e}")
            result[code] = ('', '')
            continue
        except Exception as e:
            print(f"    ⚠️ analysis/{code} failed: {e}")
            result[code] = ('', '')
            continue

        ana = (data.get('analysis') or {})
        conditions = ana.get('conditions') or []
        notices = ana.get('recentNotices') or []

        best = min(conditions, key=lambda c: c.get('daysToTrigger', 999),
                   default=None)

        clause_num = 0
        if notices:
            clause_num = _parse_clause(notices[0].get('reason', ''))
        clause_lbl = _CLAUSE_LABEL.get(clause_num, '')

        if not best:
            result[code] = (clause_lbl, '')
            continue

        cid = best.get('id')
        cur = best.get('current', 0)
        req = best.get('required', 0)
        dtg = best.get('daysToTrigger', 0)

        if cid == 1:
            label = clause_lbl or '價格'
            desc = f'連續{cur}/{req}日達第一款'
        elif cid == 2:
            label = clause_lbl or '連續注意'
            desc = f'連續{cur}/{req}日達注意標準'
        elif cid in (3, 4):
            label = '次數累積'
            window = '10' if cid == 3 else '30'
            desc = f'{window}日內{cur}/{req}次'
        else:
            label = clause_lbl or ''
            desc = best.get('name', '')

        if dtg > 0:
            desc += f'({dtg}日內成形)'

        result[code] = (label, desc)
        print(f"    {code}: {label} | {desc}")

    return result


def main():
    print(f"fetch {URL_RISK}")
    try:
        r = requests.get(URL_RISK, timeout=15, headers=_HDR)
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as e:
        sc = getattr(e.response, 'status_code', 0)
        if sc in (403, 429):
            # 讓「被擋」跟「壞掉」一眼可分,並把檢查順序寫進訊息 ——
            # 2026-08-24 那次就是因為訊息只寫 failed,兩週沒人看出是 UA 的問題。
            print(f"  ⛔ risk HTTP {sc} — 被來源擋下,不重試 (重打只會讓封鎖更久)")
            print("     檢查順序: 1) _UA 是否為完整瀏覽器字串 (勿簡寫)")
            print("               2) 同 IP 近期請求量")
            print("               3) https://attstock.tw/ 首頁是否仍可開")
        else:
            print(f"  ✗ risk fetch failed: HTTP {sc}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ risk fetch failed: {e}")
        sys.exit(1)

    if not isinstance(data, list):
        print(f"  ✗ unexpected response shape")
        sys.exit(1)

    industry_map = _load_industry_map()
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    tracking = _fetch_tracking()
    print(f"  tracking: 新進{len(tracking.get('entering',[]))} / "
          f"出關{len(tracking.get('exits',[]))} / "
          f"5min{len(tracking.get('disposal_5min',[]))} / "
          f"20min{len(tracking.get('disposal_20min',[]))} / "
          f"自結{len(tracking.get('self_cert_yesterday',[]))}")

    in_disposal = []
    pending_1d = []
    pending_2d = []
    pending_3d = []
    sample = []
    detail = []
    stock_map = {}

    for s in data:
        code = s.get('code')
        if not code:
            continue
        analysis = s.get('analysis') or {}
        days_to_disp = analysis.get('minDaysToDisposal')
        ds = s.get('disposal_start_date')
        de = s.get('disposal_end_date')
        is_in_disposal = bool(ds) and (not de or de >= today_str)

        if is_in_disposal:
            in_disposal.append(code)
        elif days_to_disp == 1:
            pending_1d.append(code)
        elif days_to_disp == 2:
            pending_2d.append(code)
        elif days_to_disp is not None and days_to_disp >= 3:
            pending_3d.append(code)
        stock_map[code] = s

    near_codes = pending_1d + pending_2d
    print(f"  fetching per-stock analysis for {len(near_codes)} stocks ...")
    cond_results = _fetch_stock_conditions(near_codes)

    for code in in_disposal + pending_1d + pending_2d + pending_3d:
        s = stock_map[code]
        name = s.get('name', '—')
        analysis = s.get('analysis') or {}
        days_to_disp = analysis.get('minDaysToDisposal')
        disp_type = analysis.get('disposalType') or '—'
        ds = s.get('disposal_start_date')
        de = s.get('disposal_end_date')

        trig_label, trig_desc = cond_results.get(code, ('', ''))

        row = {
            'code': code,
            'name': name,
            'type': disp_type,
            'industry': industry_map.get(code, ''),
            'days_to_disposal': days_to_disp,
            'trigger_label': trig_label,
            'trigger_desc': trig_desc,
            'consecutive_days': analysis.get('consecutiveDays'),
            'consecutive_days_first': analysis.get('consecutiveDaysFirst'),
            'count_in_10d': analysis.get('countIn10Days'),
            'count_in_30d': analysis.get('countIn30Days'),
            'duration': analysis.get('disposalDuration'),
            'last_price': s.get('last_price'),
            'change_pct': s.get('price_change_pct'),
            'volume': s.get('volume'),
            'turnover_rate': s.get('turnover_rate'),
            'day_trade_ratio': s.get('day_trade_ratio'),
            'risk_score': s.get('risk_score'),
            'market': s.get('market'),
        }

        if code in in_disposal:
            row['bucket'] = 'in_disposal'
            row['end'] = de
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'in_disposal', 'end': de})
        elif code in pending_1d:
            row['bucket'] = '1d'
            sample.append({'code': code, 'name': name, 'type': disp_type,
                           'status': 'pending_1d', 'days_to_disposal': 1})
        elif code in pending_2d:
            row['bucket'] = '2d'
        else:
            row['bucket'] = '3d'

        detail.append(row)

    _order = {'in_disposal': 0, '1d': 1, '2d': 2, '3d': 3}
    detail.sort(key=lambda x: (_order.get(x['bucket'], 9),
                               -(x.get('risk_score') or 0)))

    out = {
        'fetched_at': datetime.datetime.now().isoformat(),
        'source': 'attstock.tw/api/stocks/risk+daily-report',
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
        # ── v3.73.7 改用 daily-report API ──
        'disposal_tracking': tracking,
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    total risk: {len(data)}")
    print(f"    in_disposal : {len(in_disposal)}")
    print(f"    pending_1d  : {len(pending_1d)} → {sorted(pending_1d)[:5]}")
    print(f"    pending_2d  : {len(pending_2d)} → {sorted(pending_2d)[:5]}")
    print(f"    pending_3d+ : {len(pending_3d)}")
    print(f"    detail 明細 : {len(detail)} 筆 "
          f"(含條件描述 {sum(1 for d in detail if d.get('trigger_label'))} 筆)")


if __name__ == '__main__':
    main()
