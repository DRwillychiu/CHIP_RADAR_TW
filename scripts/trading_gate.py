"""Trading-day gate for scheduled workflows (v3.80.4).

Every data workflow asks this first: does this run belong to a real trading
session? Writes run=true|false, session=YYYYMMDD, reason=... to $GITHUB_OUTPUT.

Kinds (user rules, 2026-09-29):
  evening      daily-full / margin evening layers. Session = run date, or the
               previous date before 12:00 (late cron still serving last night).
               Runs only if the session was a trading day; the close is out, so
               FMTQIK is checked too (catches typhoon closures).
  day          intraday settlement / settlement tracking. Same session rule;
               FMTQIK checked only once the close is published (>= 15:00).
  premarket    pre-market brief. Today must be a scheduled trading day.
  weekly_last  weekly summary. Today is a trading day and the next trading day
               falls in a later ISO week (Friday holiday -> Thursday).
  margin       margin-refresh. Evening crons -> 'evening'. Morning crons
               (08:00-14:00 TW) -> 'margin_morning': the target is the previous
               trading day; run only while its margin is not yet verified for
               that day (confidence high). So Saturday morning fixes Friday, and
               Sunday/Monday runs do work only if Friday/Saturday failed.
Manual (workflow_dispatch) and non-schedule events always run.
Any source unreachable -> run (never miss a real trading day).
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'core'))
import trading_calendar as tc  # noqa: E402

MORNING_UTC_HOURS = {0, 1, 2, 3, 4, 5, 6}   # 08:00-14:59 TW


def margin_done(target: dt.date, latest_path: Path) -> tuple:
    """(done: bool|None, detail). None = could not tell (treated as not done)."""
    pw = os.environ.get('CHIP_RADAR_PASSWORD', '')
    if not pw or not latest_path.exists():
        return None, 'no password or latest.json'
    try:
        sys.path.insert(0, str(ROOT))
        import src  # noqa: F401
        from src.pipelines.crawler_output import decrypt_data
        enc = json.loads(latest_path.read_text(encoding='utf-8'))
        data = json.loads(decrypt_data(enc['data'], pw, iterations=enc.get('iterations'))) \
            if enc.get('encrypted') else enc
        v = data.get('margin_verification') or {}
        got = v.get('data_date') or ''
        ok = got >= target.strftime('%Y%m%d') and v.get('confidence') == 'high'
        return ok, f"stored margin data_date={got or '-'} confidence={v.get('confidence', '-')}"
    except Exception as e:  # noqa: BLE001
        return None, f'could not read latest.json ({e})'


def decide(kind: str, now: dt.datetime, event: str = 'schedule', schedule: str = '',
           latest_path: Path = ROOT / 'data' / 'latest.json', cache_path=None) -> dict:
    if event != 'schedule':
        return {'run': True, 'session': '', 'reason': f'{event}: not gated'}
    today = now.date()

    if kind == 'margin':
        hour_field = (schedule.split() or ['', ''])[1] if schedule else ''
        is_morning = hour_field.isdigit() and int(hour_field) in MORNING_UTC_HOURS
        kind = 'margin_morning' if is_morning else 'evening'

    if kind in ('evening', 'day'):
        s = tc.session_date(now)
        check = kind == 'evening' or s < today or now.hour >= 15
        ok = tc.is_trading_day(s, check_actual=check, cache_path=cache_path)
        return {'run': ok, 'session': s.strftime('%Y%m%d'),
                'reason': f"session {s} {'is' if ok else 'is NOT'} a trading day ({kind})"}

    if kind == 'premarket':
        ok = tc.is_trading_day(today, cache_path=cache_path)
        return {'run': ok, 'session': today.strftime('%Y%m%d'),
                'reason': f"today {today} {'is' if ok else 'is NOT'} a trading day (premarket)"}

    if kind == 'weekly_last':
        if not tc.is_trading_day(today, check_actual=now.hour >= 15, cache_path=cache_path):
            return {'run': False, 'session': today.strftime('%Y%m%d'),
                    'reason': f'today {today} is not a trading day (weekly_last)'}
        nxt = tc.next_scheduled_trading_day(today, cache_path=cache_path)
        last = nxt.isocalendar()[:2] != today.isocalendar()[:2]
        return {'run': last, 'session': today.strftime('%Y%m%d'),
                'reason': f"next trading day {nxt} is {'in a later week -> last of week' if last else 'in the same week'}"}

    if kind == 'margin_morning':
        target = tc.prev_trading_day(today, check_actual=True, cache_path=cache_path)
        done, detail = margin_done(target, latest_path)
        return {'run': done is not True, 'session': target.strftime('%Y%m%d'),
                'reason': f"margin for {target}: {'already verified' if done else 'not verified yet'} ({detail})"}

    raise ValueError(f'unknown kind {kind}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', required=True,
                    choices=['evening', 'day', 'premarket', 'weekly_last', 'margin', 'margin_morning'])
    ap.add_argument('--event', default=os.environ.get('GITHUB_EVENT_NAME', 'schedule'))
    ap.add_argument('--schedule', default='')
    ap.add_argument('--now', default='', help='ISO datetime for testing, e.g. 2026-09-25T21:57+08:00')
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now).astimezone(tc.TW) if a.now else dt.datetime.now(tc.TW)
    r = decide(a.kind, now, a.event, a.schedule)
    for w in tc.warnings:
        print(f'::warning title=Trading gate::{w}')
    title = 'Trading gate: RUN' if r['run'] else 'Trading gate: SKIP'
    print(f"::notice title={title}::{now:%Y-%m-%d %H:%M} TW | {r['reason']}")
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a', encoding='utf-8') as f:
            f.write(f"run={'true' if r['run'] else 'false'}\nsession={r['session']}\nreason={r['reason']}\n")


if __name__ == '__main__':
    main()
