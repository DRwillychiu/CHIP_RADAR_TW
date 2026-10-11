"""v3.96.0 insider radar stage 4: the monthly update, run locally first (owner 2026-10-11: 「沒問題」;
manual top-up: 「面板上也要有一個自動fresh的按鈕，確保如果發現沒有更新，可以手動補上」 -> update_insider.cmd).

One run = one month, every step must pass or nothing new reaches the web data:
  1. the summary tables of the next month (IRB110 / IRB140, listed + OTC); not published -> stop quietly
  2. that month's per-person pages (same screen, same pace: 7 requests per 90 s, 502 -> cool down)
  3. parse + the radar (data/insider_radar.json and its encrypted part)
  4. the independent check: 5 pages of the month by tools/independent/cleanroom_q61.py -> must agree
Every run writes data/insider_update_status.json (what the page's 「檢查更新」 shows).
Refuses to start while another fetch is sending MOPS requests (the request log moved < 3 min ago).
    python scripts/update_insider_monthly.py [--ym YYYYMM]
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable]
STATUS = ROOT / "data" / "insider_update_status.json"
TRACE = ROOT / "logs" / "insider_people_requests.csv"


def step(name, args):
    print(f"[update] {time.strftime('%H:%M:%S')} {name}", flush=True)
    r = subprocess.run(PY + args, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return r.returncode


def write_status(**kw):
    STATUS.write_text(json.dumps({"checked_at": dt.datetime.now().isoformat(timespec="seconds"), **kw},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[update] status: {kw}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ym", help="month to add (default: the month after the newest one we have)")
    a = ap.parse_args()
    have = sorted(p.stem for p in (ROOT / "data" / "insider_monthly").glob("*.json"))
    newest = have[-1] if have else None
    if a.ym:
        ym = a.ym
    else:
        y, m = int(newest[:4]), int(newest[4:])
        ym = f"{y + (m == 12):04d}{m % 12 + 1:02d}"
    if TRACE.exists() and time.time() - TRACE.stat().st_mtime < 180:
        write_status(target=ym, have_until=newest, ok=False, message="另一個抓取正在跑，這次不啟動")
        return 1
    if step(f"1 summary tables {ym}", ["scripts/fetch_insider_monthly.py", "--start", ym, "--end", ym, "--max-requests", "4"]):
        write_status(target=ym, have_until=newest, ok=False, message="彙總表抓取失敗（觀測站錯誤），稍後再試")
        return 1
    if not (ROOT / "data" / "insider_monthly" / f"{ym}.json").exists():
        write_status(target=ym, have_until=newest, ok=True, published=False, message=f"{ym[:4]}-{ym[4:]} 官方尚未公告")
        return 0
    if step(f"2 per-person pages {ym}", ["scripts/fetch_insider_people.py", "--since", ym, "--until", ym, "--no-control",
                                         "--block", "7", "--cycle", "90", "--max-requests", "600"]):
        write_status(target=ym, have_until=newest, ok=False, message="逐人明細沒抓完（已抓的保留），重跑會從中斷處接續")
        return 1
    if step("3 parse + radar", ["scripts/build_insider_people.py"]) or \
       step("3 radar", ["scripts/run_insider_radar.py", "--since", have[0] if have else ym]):
        write_status(target=ym, have_until=newest, ok=False, message="分析失敗，網頁資料未更新")
        return 1
    if step(f"4 independent check {ym}", ["scripts/verify_insider_monthly.py", "--ym", ym]):
        write_status(target=ym, have_until=ym, ok=False, message=f"獨立核對不一致，請看 docs/verify/INSIDER_AUTO_{ym}.md")
        return 1
    write_status(target=ym, have_until=ym, ok=True, published=True, message=f"{ym[:4]}-{ym[4:]} 已更新並通過獨立核對")
    return 0


if __name__ == "__main__":
    sys.exit(main())
