# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, os, json, datetime as dt, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.4 交易日排程開關 — 離線 (休市表用 repo 內 data/twse_holidays.json,
實際成交用固定樣本, 融資完成度用暫存檔). 使用者 2026-09-29 規則:
  - 非交易日不跑、不輸出; 某交易日的晚間處理 (含延遲到隔天凌晨) 算那個交易日
  - 融資早上那輪: 前一交易日融資未正確更新才跑 (週六早上補週五; 週日只在失敗時)
  - 週報: 本週最後一個交易日跑
"""
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import trading_calendar as tc
import trading_gate as g

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


# 實際成交樣本 (FMTQIK 格式轉成 YYYYMMDD): 7/10 颱風停市, 9/25 9/28 國定假日
def fake_traded(d):
    ym = d.strftime('%Y%m')
    start = dt.date(d.year, d.month, 1)
    days = set()
    x = start
    while x.month == start.month:
        s = x.strftime('%Y%m%d')
        if x.weekday() < 5 and s not in tc.closed_dates(x.year) and s != '20260710':
            days.add(s)
        x += dt.timedelta(days=1)
    return days


tc.traded_days_in_month = fake_traded
T = lambda s: dt.datetime.fromisoformat(s + '+08:00')
D = lambda s: dt.date.fromisoformat(s)

print("=" * 72)
print("  v3.80.4 交易日排程開關 (離線)")
print("=" * 72)

# ── A. 休市表解析 ──
print("\nA. 休市表解析 (data/twse_holidays.json, 2026)")
closed = tc.closed_dates(2026)
check("2026 年 24 個休市日", len(closed) == 24, len(closed))
check("9/25 中秋、9/28 教師節 休市", {'20260925', '20260928'} <= closed)
check("1/2 開始交易日、2/11 最後交易日、2/23 開始交易日 是交易日",
      not ({'20260102', '20260211', '20260223'} & closed))
check("2/12、2/13「市場無交易，僅辦理結算交割」算休市", {'20260212', '20260213'} <= closed)
rows = [['2027-01-01', 'X紀念日', '依規定放假1日。'], ['2027-01-04', '國曆新年開始交易日', '國曆新年開始交易。'],
        ['2027-02-05', '市場無交易，僅辦理結算交割作業', ''], ['2027-02-08', 'Y節', 'Y節適逢星期六，於2月8日補假。']]
check("解析規則: 放假/補假/無交易 → 休市, 開始交易日 → 不休市",
      tc.parse_schedule(rows) == ['20270101', '20270205', '20270208'], tc.parse_schedule(rows))

# ── B. 這一輪算哪個交易日 ──
print("\nB. 這一輪屬於哪一天 (中午前 = 前一天晚上的延遲排程)")
check("9/25 03:57 → 9/24", tc.session_date(T('2026-09-25T03:57')) == D('2026-09-24'))
check("9/25 21:57 → 9/25", tc.session_date(T('2026-09-25T21:57')) == D('2026-09-25'))
check("9/29 05:43 → 9/28", tc.session_date(T('2026-09-29T05:43')) == D('2026-09-28'))

# ── C. 每日籌碼 / 盤前 / 盤中 ──
print("\nC. 每日籌碼 (evening) / 盤前 (premarket) / 盤中與結算 (day)")
dec = lambda kind, t, cron='', lp=None: g.decide(kind, T(t), 'schedule', cron, **({'latest_path': lp} if lp else {}))['run']
check("9/24 21:17 每日籌碼 → 跑", dec('evening', '2026-09-24T21:17'))
check("9/25 02:14 / 03:57 (9/24 延遲) → 跑", dec('evening', '2026-09-25T02:14') and dec('evening', '2026-09-25T03:57'))
check("9/25 21:57 / 9/26 03:52 (中秋) → 不跑", not dec('evening', '2026-09-25T21:57') and not dec('evening', '2026-09-26T03:52'))
check("9/28 21:40 / 9/29 05:43 (教師節) → 不跑", not dec('evening', '2026-09-28T21:40') and not dec('evening', '2026-09-29T05:43'))
check("週六 21:17 → 不跑", not dec('evening', '2026-10-03T21:17'))
check("9/25 盤前簡報 → 不跑; 9/29 → 跑", not dec('premarket', '2026-09-25T13:29') and dec('premarket', '2026-09-29T08:50'))
check("9/25 / 9/28 盤中試算 → 不跑; 9/29 13:35 → 跑",
      not dec('day', '2026-09-25T18:31') and not dec('day', '2026-09-28T19:57') and dec('day', '2026-09-29T13:35'))
check("颱風 7/10 (休市表沒有): 晚上每日籌碼 → 不跑 (成交統計沒有這天)", not dec('evening', '2026-07-10T21:17'))
check("颱風 7/10: 盤前 → 會跑 (開盤前無從得知, 已知限制)", dec('premarket', '2026-07-10T08:50'))

# ── D. 週報 ──
print("\nD. 週報: 本週最後一個交易日")
check("9/24 (週四, 週五中秋) → 跑", dec('weekly_last', '2026-09-24T14:30'))
check("9/23 (週三) → 不跑", not dec('weekly_last', '2026-09-23T14:30'))
check("10/2 (一般週五) → 跑", dec('weekly_last', '2026-10-02T14:30'))
check("10/8 (週四, 週五國慶補假) → 跑; 10/9 → 不跑", dec('weekly_last', '2026-10-08T14:30') and not dec('weekly_last', '2026-10-09T14:30'))

# ── E. 融資 ──
print("\nE. 融資: 晚上幾輪看交易日; 早上幾輪只在前一交易日融資還沒正確時跑")
tmp = pathlib.Path(tempfile.mkdtemp())
def latest(data_date):
    p = tmp / f'latest_{data_date}.json'
    p.write_text(json.dumps({'encrypted': False, 'margin_verification': {'data_date': data_date, 'confidence': 'high'}}), encoding='utf-8')
    return p
os.environ.setdefault('CHIP_RADAR_PASSWORD', 'offline-test')
M = '0 0 * * *'   # 08:00 TW morning cron
check("早上 cron (UTC 0/1/4 點) 判為早上那輪; 晚上 cron (UTC 14/15/16/18) 判為晚上那輪",
      not dec('margin', '2026-09-25T22:30', '30 14 * * 1-5') and dec('margin', '2026-09-24T22:30', '30 14 * * 1-5'))
check("9/25 早上: 9/24 融資還是 9/23 的 → 跑", dec('margin', '2026-09-25T10:24', '0 1 * * *', latest('20260923')))
check("9/25 12:00: 9/24 已正確 → 不跑", not dec('margin', '2026-09-25T12:00', '0 4 * * *', latest('20260924')))
check("一般週六早上: 週五融資未更新 → 跑", dec('margin', '2026-10-03T08:00', M, latest('20261001')))
check("週日早上: 週六已補好 → 不跑", not dec('margin', '2026-10-04T08:00', M, latest('20261002')))
check("週日早上: 週五、六都失敗 → 跑 (補救)", dec('margin', '2026-10-04T08:00', M, latest('20261001')))
check("週一早上: 週五已補好 → 不跑", not dec('margin', '2026-10-05T08:00', M, latest('20261002')))
check("9/29 (週二) 早上: 前一交易日 9/24 已正確 → 不跑", not dec('margin', '2026-09-29T08:00', M, latest('20260924')))
check("讀不到融資狀態 (沒有檔案) → 跑 (寧可多跑)", dec('margin', '2026-10-06T08:00', M, tmp / 'missing.json'))

# ── G. crawler.py 融資模式 (手動觸發時) 的「已是最新交易日」判斷 ──
print("\nG. crawler.py 融資模式改用交易日曆")
crawler_src = (ROOT / 'crawler.py').read_text(encoding='utf-8')
check("用 trading_calendar 判斷最新交易日", 'from trading_calendar import is_trading_day, prev_trading_day' in crawler_src)
check("舊的「只認週一~五」迴圈已移除", 'check.weekday() < 5' not in crawler_src)
latest_td = lambda s: (T(s).strftime('%Y%m%d') if T(s).hour >= 8 and tc.is_trading_day(T(s).date())
                       else tc.prev_trading_day(T(s).date()).strftime('%Y%m%d'))
check("9/25 (中秋) 10:24 → 9/24; 9/29 07:00 → 9/24; 9/29 10:00 → 9/29",
      (latest_td('2026-09-25T10:24'), latest_td('2026-09-29T07:00'), latest_td('2026-09-29T10:00'))
      == ('20260924', '20260924', '20260929'))

# ── F. 手動 / 失敗保護 ──
print("\nF. 手動觸發一律跑; 資料源失敗一律跑")
check("手動觸發 9/25 → 跑", g.decide('evening', T('2026-09-25T21:57'), 'workflow_dispatch')['run'])
tc.traded_days_in_month = lambda d: None      # FMTQIK unreachable
check("成交統計連不上 → 依休市表判斷 (9/29 照跑, 9/28 仍不跑)",
      dec('evening', '2026-09-29T21:17') and not dec('evening', '2026-09-28T21:40'))
tc._closed_cache.pop(2031, None)
tc.fetch_schedule = lambda: (_ for _ in ()).throw(OSError('offline'))
check("沒有該年休市表且連不上 → 週一到五都照跑並警告",
      tc.is_scheduled_open(D('2031-01-01')) and any('2031' in w for w in tc.warnings))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
