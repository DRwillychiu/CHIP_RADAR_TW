"""
trading_calendar.py — 台股交易日判斷 (v3.80.4)

問題: 2026-09-25 (中秋) / 09-28 (教師節) 排程照跑、照輸出 (盤前簡報、盤中試算、
週報、每日籌碼 10 次). 原本所有排程只認星期一~五, 不認國定假日.

判斷來源 (兩層):
  1. 證交所年度開休市表 (holidaySchedule). 存一份在 data/twse_holidays.json;
     API 的 queryYear 參數無效, 只回傳「今年」, 所以只能每年存一次.
     表內也列「開始交易日 / 最後交易日」這種**有交易**的日子, 要排除.
  2. 已收盤的日子再看證交所當月成交統計 (FMTQIK) 有沒有這一天 —
     颱風假不在開休市表 (實測 2026-07-10 不在表上但無交易).

原則: 查不到 (網路失敗) 一律當「有交易」, 寧可多跑不可漏跑.
只用標準函式庫 (urllib), gate job 不必裝套件.
"""
import datetime as dt
import json
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

TW = dt.timezone(dt.timedelta(hours=8))
CACHE_PATH = Path(__file__).resolve().parents[2] / 'data' / 'twse_holidays.json'
HOLIDAY_URL = 'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json'
FMTQIK_URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym}01&response=json'
_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

_CLOSED_WORDS = ('放假', '補假', '無交易', '休市')
_OPEN_WORDS = ('開始交易', '最後交易')      # e.g. 國曆新年開始交易日 — a trading day
warnings: List[str] = []                    # filled when a source was unreachable


def _get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8'))


def parse_schedule(rows: List[list]) -> List[str]:
    """holidaySchedule rows [date 'YYYY-MM-DD', name, desc] -> closed dates YYYYMMDD."""
    closed = set()
    for r in rows:
        if not r:
            continue
        name = str(r[1]) if len(r) > 1 else ''
        text = name + (str(r[2]) if len(r) > 2 else '')
        if any(w in name for w in _OPEN_WORDS) and '無交易' not in text:
            continue
        if any(w in text for w in _CLOSED_WORDS):
            closed.add(str(r[0]).replace('-', ''))
    return sorted(closed)


def fetch_schedule() -> Dict[str, object]:
    """Live fetch. Returns {'year': 2026, 'closed': [...], 'rows': [...]}."""
    j = _get_json(HOLIDAY_URL)
    rows = j.get('data') or []
    year = int(str(rows[0][0])[:4]) if rows else None
    return {'year': year, 'closed': parse_schedule(rows), 'rows': rows}


_closed_cache: Dict[int, set] = {}


def closed_dates(year: int, cache_path: Optional[Path] = None) -> set:
    if year in _closed_cache:
        return _closed_cache[year]
    p = Path(cache_path) if cache_path else CACHE_PATH
    closed = None
    if p.exists():
        doc = json.loads(p.read_text(encoding='utf-8'))
        if str(year) in doc:
            closed = set(doc[str(year)]['closed'])
    if closed is None:
        try:
            live = fetch_schedule()
            if live['year'] == year:
                closed = set(live['closed'])
                warnings.append(f'holiday list for {year} not in {p.name}; used live TWSE list — commit it')
        except Exception as e:  # noqa: BLE001
            warnings.append(f'holiday list for {year} unavailable ({e}); weekdays treated as open')
    closed = closed if closed is not None else set()
    _closed_cache[year] = closed
    return closed


def is_scheduled_open(d: dt.date, cache_path: Optional[Path] = None) -> bool:
    return d.weekday() < 5 and d.strftime('%Y%m%d') not in closed_dates(d.year, cache_path)


_traded_cache: Dict[str, Optional[set]] = {}


def traded_days_in_month(d: dt.date) -> Optional[set]:
    """Dates (YYYYMMDD) with actual TWSE trading in d's month, or None if unreachable."""
    ym = d.strftime('%Y%m')
    if ym not in _traded_cache:
        try:
            rows = _get_json(FMTQIK_URL.format(ym=ym)).get('data') or []
            days = set()
            for r in rows:                              # '115/09/24'
                y, m, dd = str(r[0]).split('/')
                days.add(f'{int(y) + 1911}{int(m):02d}{int(dd):02d}')
            _traded_cache[ym] = days
        except Exception as e:  # noqa: BLE001
            warnings.append(f'FMTQIK {ym} unreachable ({e}); actual-trading check skipped')
            _traded_cache[ym] = None
    return _traded_cache[ym]


def is_trading_day(d: dt.date, check_actual: bool = False, cache_path: Optional[Path] = None) -> bool:
    """Scheduled open, and (if check_actual) TWSE really traded that day.
    check_actual only makes sense once that day's close is published (after ~15:00)."""
    if not is_scheduled_open(d, cache_path):
        return False
    if check_actual:
        days = traded_days_in_month(d)
        if days is not None and d.strftime('%Y%m%d') not in days:
            return False                                # ad hoc closure (typhoon)
    return True


def prev_trading_day(d: dt.date, check_actual: bool = True, cache_path: Optional[Path] = None) -> dt.date:
    """Most recent trading day strictly before d."""
    x = d - dt.timedelta(days=1)
    for _ in range(40):
        if is_trading_day(x, check_actual, cache_path):
            return x
        x -= dt.timedelta(days=1)
    raise RuntimeError(f'no trading day in the 40 days before {d}')


def next_scheduled_trading_day(d: dt.date, cache_path: Optional[Path] = None) -> dt.date:
    """Next scheduled trading day strictly after d (future: schedule only)."""
    x = d + dt.timedelta(days=1)
    for _ in range(40):
        if is_scheduled_open(x, cache_path):
            return x
        x += dt.timedelta(days=1)
    raise RuntimeError(f'no scheduled trading day in the 40 days after {d}')


def session_date(now_tw: dt.datetime, rollover_hour: int = 12) -> dt.date:
    """Trading day a run belongs to: before rollover_hour it is still the
    previous day's evening job running late (GitHub cron delays run to ~06:00)."""
    d = now_tw.date()
    return d - dt.timedelta(days=1) if now_tw.hour < rollover_hour else d
