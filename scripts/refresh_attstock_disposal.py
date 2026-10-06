"""抓 attstock.tw 處置股清單寫 data/disposal_attstock.json.

v3.71.7 起: Chip Radar「今日避開」(Excel / Email) 用 codes set + count.
v3.73-v3.75 (dev, 本機 track 2): 加 2 天內恐處置、逐檔條件描述、處置進出追蹤,
  給 send_daily_telegram.py / push_disposal_telegram.py 用.
v3.80.14 (main): 完整瀏覽器標頭、403/429 不重試、處置中改讀 /api/stocks/disposal
  (/risk 只回 status=risk, 處置中原本永遠 0 檔), fetched_at 帶 +08:00.
v3.80.19 (合併 dev + main): 基本清單 = v3.80.14 的兩支 API. 額外明細 (每日報告 +
  逐檔 analysis, 每晚多十幾個請求) 只在本機跑 — 雲端 (GITHUB_ACTIONS) 預設不抓,
  免得 GitHub 共用 IP 被 attstock 限流; 本機 Telegram 排程自己跑本檔, 不讀雲端的檔.
  ATTSTOCK_DETAIL=1 / 0 可強制開關.

執行: python scripts/refresh_attstock_disposal.py
寫入: <CHIP_RADAR_DATA_DIR 或 data>/disposal_attstock.json
  fetched_at, count_in_disposal, count_pending_1d, codes_in_disposal,
  codes_pending_1d, sample                                  ← Excel / Email
  count_pending_2d, count_pending_3d_plus, codes_pending_2d,
  detail, disposal_tracking                                 ← 只在抓明細時有
"""
import json, os, re, sys, time, requests, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
OUT = DATA_DIR / 'disposal_attstock.json'

URL = 'https://attstock.tw/api/stocks/risk'                 # 風險股 → 明日恐處置 (minDaysToDisposal)
URL_RISK = URL
URL_DISPOSAL = 'https://attstock.tw/api/stocks/disposal'    # 處置中 (v3.80.14)
URL_REPORT = 'https://attstock.tw/api/stocks/daily-report'  # 處置進出追蹤 (明細)
URL_ANALYSIS = 'https://attstock.tw/api/stocks/analysis'    # 逐檔條件 (明細)
TW = datetime.timezone(datetime.timedelta(hours=8))
# attstock 自 2026-08-24 起擋非瀏覽器 UA: 短字串 'Mozilla/5.0' 一律 403, 完整 Chrome
# UA 才 200 —— 勿再簡寫或加自訂後綴. 短 UA 讓本檔 8/21 後整整兩週抓不到 (每次
# exit 1, 步驟 continue-on-error 沒人發現), Email 一直寄 8/21 的清單.
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-TW,zh;q=0.9',
    'Referer': 'https://attstock.tw/',
}
_HDR = HEADERS   # dev 時期的名稱

# 逐檔請求之間的間隔. 上游 disposal-watch 在 2026-08-24 來源開始限流時加了同樣的
# 節流. 每日 10-25 檔, 多花十秒換不被封.
_THROTTLE = 0.5

_CLAUSE_LABEL = {
    1: '價格', 2: '成交量', 3: '成交筆數',
    4: '當沖', 5: '本益比', 6: '估值+週轉', 13: '當沖',
}
_CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def want_detail(env=None):
    """額外明細: ATTSTOCK_DETAIL=1/0 優先; 否則雲端 (GITHUB_ACTIONS) 不抓, 本機抓."""
    env = os.environ if env is None else env
    flag = str(env.get('ATTSTOCK_DETAIL', '')).strip()
    if flag in ('0', '1'):
        return flag == '1'
    return env.get('GITHUB_ACTIONS') != 'true'


def fetch(url, retries=3):
    """403/429 = 被來源擋下, 不重試 (重打只會讓封鎖更久, 同 disposal-watch)."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30, headers=HEADERS)
            if r.status_code in (403, 429):
                raise PermissionError(f"{url} HTTP {r.status_code} — attstock 擋下請求 (UA 過濾或 IP 限流), 不重試")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                raise ValueError(f"{url} unexpected response shape: {type(data).__name__}")
            return data
        except (PermissionError, ValueError):
            raise
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} fetch failed after {retries} tries: {last}")


def summarize(risk, disposal, today):
    """today: 'YYYY-MM-DD' (台灣日期).
    處置中 = /disposal 中 起日 <= today <= 迄日. v3.80.14 以前用 /risk 的
    disposal_start_date 判斷, 但 /risk 只回 status=risk (2026-10-06 實測 139/139 皆空),
    「處置中」永遠是 0 檔.
    明日恐處置 = /risk 中 analysis.minDaysToDisposal == 1, 且不在處置中."""
    in_disposal, sample = [], []
    for s in disposal:
        code = s.get('code')
        ds, de = s.get('disposal_start_date') or '', s.get('disposal_end_date') or ''
        if code and ds and ds[:10] <= today and (not de or today <= de[:10]):
            in_disposal.append(code)
            sample.append({'code': code, 'name': s.get('name', '—'), 'status': 'in_disposal',
                           'start': ds[:10], 'end': de[:10] or None})
    pending_1d = []
    for s in risk:
        code = s.get('code')
        analysis = s.get('analysis') or {}
        if code and code not in in_disposal and analysis.get('minDaysToDisposal') == 1:
            pending_1d.append(code)
            sample.append({'code': code, 'name': s.get('name', '—'),
                           'type': analysis.get('disposalType') or '—',
                           'status': 'pending_1d', 'days_to_disposal': 1})
    return sorted(set(in_disposal)), sorted(set(pending_1d)), sample


# ─── 額外明細 (dev v3.73-v3.75, 本機 Telegram 用) ───
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
    p = DATA_DIR / 'industry_map.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8')).get('stock_industry', {})
    except Exception:
        return {}


def _fetch_tracking(today, disposal_total):
    """抓 daily-report, 回傳處置進出追蹤 dict (當天沒報告則用最新)."""
    url = f'{URL_REPORT}/{today}'
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        print(f"  daily-report/{today}: OK (date={data.get('date','')})")
    except Exception:
        try:
            r = requests.get(URL_REPORT, timeout=15, headers=HEADERS)
            r.raise_for_status()
            data = r.json()
            print(f"  daily-report (fallback): date={data.get('date','')}")
        except Exception as e:
            print(f"  ⚠️ daily-report fetch failed: {e}")
            return {}

    entering = data.get('enteringDisposal') or []
    exits = data.get('upcomingExits') or []
    return {
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
        'total': disposal_total,
    }


def _fetch_stock_conditions(codes):
    """對 1d/2d 股票逐檔抓 analysis API, 回傳 {code: (label, desc)}.

    403/429 一出現就整批中止: 那代表被來源擋下, 繼續打只會讓封鎖延長.
    已取得的部分照常回傳, 缺的欄位在下游是空字串.
    """
    result = {}
    for i, code in enumerate(codes):
        if i:
            time.sleep(_THROTTLE)
        try:
            r = requests.get(f'{URL_ANALYSIS}/{code}', timeout=10, headers=HEADERS)
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
        best = min(conditions, key=lambda c: c.get('daysToTrigger', 999), default=None)

        clause_num = _parse_clause(notices[0].get('reason', '')) if notices else 0
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


def build_detail(risk, disposal, in_disposal, pending_1d, conditions, industry_map):
    """2 天 / 3 天以上恐處置 + 每檔明細列 (Telegram 完整清單用).
    -> (pending_2d, pending_3d, detail)."""
    stock_map = {s.get('code'): s for s in risk if s.get('code')}
    disp_map = {s.get('code'): s for s in disposal if s.get('code')}
    pending_2d, pending_3d = [], []
    for code, s in stock_map.items():
        if code in in_disposal or code in pending_1d:
            continue
        days = (s.get('analysis') or {}).get('minDaysToDisposal')
        if days == 2:
            pending_2d.append(code)
        elif days is not None and days >= 3:
            pending_3d.append(code)

    detail = []
    for code in in_disposal + pending_1d + sorted(pending_2d) + sorted(pending_3d):
        s = stock_map.get(code) or disp_map.get(code) or {}
        analysis = s.get('analysis') or {}
        trig_label, trig_desc = conditions.get(code, ('', ''))
        row = {
            'code': code,
            'name': s.get('name', '—'),
            'type': analysis.get('disposalType') or '—',
            'industry': industry_map.get(code, ''),
            'days_to_disposal': analysis.get('minDaysToDisposal'),
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
            row['end'] = (disp_map.get(code, {}).get('disposal_end_date') or '')[:10] or None
        elif code in pending_1d:
            row['bucket'] = '1d'
        elif code in pending_2d:
            row['bucket'] = '2d'
        else:
            row['bucket'] = '3d'
        detail.append(row)
    order = {'in_disposal': 0, '1d': 1, '2d': 2, '3d': 3}
    detail.sort(key=lambda x: (order.get(x['bucket'], 9), -(x.get('risk_score') or 0)))
    return sorted(pending_2d), sorted(pending_3d), detail


def main():
    try:
        print(f"fetch {URL}")
        risk = fetch(URL)
        time.sleep(1.5)
        print(f"fetch {URL_DISPOSAL}")
        disposal = fetch(URL_DISPOSAL)
    except Exception as e:
        print(f"  ✗ fetch failed: {e}")
        if isinstance(e, PermissionError):
            print("     檢查順序: 1) User-Agent 是否為完整瀏覽器字串 (勿簡寫)")
            print("               2) 同 IP 近期請求量")
            print("               3) https://attstock.tw/ 首頁是否仍可開")
        # GitHub Actions 註記: 步驟是 continue-on-error, 不留註記就會像 8/21 起那樣沒人發現
        print(f"::warning title=attstock disposal::refresh failed — {e}; "
              f"data/disposal_attstock.json not updated (Excel/Email hide stale lists)")
        sys.exit(1)

    now = datetime.datetime.now(TW)
    today = now.strftime('%Y-%m-%d')
    in_disposal, pending_1d, sample = summarize(risk, disposal, today)
    out = {
        'fetched_at': now.isoformat(timespec='seconds'),   # v3.80.14: 帶 +08:00
        'source': 'attstock.tw/api/stocks/risk + /api/stocks/disposal',
        'total_risk_count': len(risk),
        'total_disposal_rows': len(disposal),
        # ── Excel / Email 讀這些, 不可更動 ──
        'count_in_disposal': len(in_disposal),
        'count_pending_1d': len(pending_1d),
        'codes_in_disposal': in_disposal,
        'codes_pending_1d': pending_1d,
        'sample': sample[:40],
    }

    if want_detail():
        tracking = _fetch_tracking(today, len(disposal))
        print(f"  tracking: 新進{len(tracking.get('entering',[]))} / "
              f"出關{len(tracking.get('exits',[]))} / "
              f"5min{len(tracking.get('disposal_5min',[]))} / "
              f"20min{len(tracking.get('disposal_20min',[]))} / "
              f"自結{len(tracking.get('self_cert_yesterday',[]))}")
        days2 = sorted(s.get('code') for s in risk if s.get('code')
                       and s.get('code') not in in_disposal
                       and (s.get('analysis') or {}).get('minDaysToDisposal') == 2)
        near = pending_1d + days2
        print(f"  fetching per-stock analysis for {len(near)} stocks ...")
        conditions = _fetch_stock_conditions(near)
        pending_2d, pending_3d, detail = build_detail(risk, disposal, in_disposal, pending_1d,
                                                      conditions, _load_industry_map())
        out.update({
            'source': out['source'] + ' + daily-report + analysis',
            # ── v3.73.3 (Telegram 完整清單用) ──
            'count_pending_2d': len(pending_2d),
            'count_pending_3d_plus': len(pending_3d),
            'codes_pending_2d': pending_2d,
            'detail': detail,
            # ── v3.73.7 daily-report API ──
            'disposal_tracking': tracking,
        })
    else:
        print("  (額外明細不抓: 雲端執行; 本機 Telegram 排程會自己抓. ATTSTOCK_DETAIL=1 可強制)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    risk rows: {len(risk)} | disposal rows: {len(disposal)}")
    print(f"    in_disposal: {len(in_disposal)} → top 5: {in_disposal[:5]}")
    print(f"    pending_1d: {len(pending_1d)} → top 5: {pending_1d[:5]}")
    if 'detail' in out:
        print(f"    pending_2d: {out['count_pending_2d']} | pending_3d+: {out['count_pending_3d_plus']}")
        print(f"    detail 明細 : {len(out['detail'])} 筆 "
              f"(含條件描述 {sum(1 for d in out['detail'] if d.get('trigger_label'))} 筆)")


if __name__ == '__main__':
    main()
