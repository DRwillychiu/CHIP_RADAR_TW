"""v3.85.6 weekly check of the measured Fubon request gaps.

Owner 2026-10-09: "富邦稽核路徑的請求間隔 ... 統一成 1.6 秒 ... 同時也要定時每周驗證是否間隔時間有改變".
Reads data/fubon_pacing_log.json (written by crawler.py, scripts/source_audit.py
and scripts/daily_rolling_update.py on GitHub Actions) and fails when, inside
the window:
  - any run measured a gap below the floor (1.6 s minus timer tolerance), or
  - trading days happened (data/index.json) but no crawler run was logged
    (silence = anomaly: the log or the measurement stopped working).
Exit 0 = pass, 1 = fail; --report writes a Markdown summary (Issue body).
Run weekly by .github/workflows/fubon-pacing-weekly.yml (Sunday 21:00 Taipei).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.core.fubon_pacing import FUBON_MIN_GAP_S, TOLERANCE_S  # noqa: E402

TW = timezone(timedelta(hours=8))
# v3.95.0: the measurement reached production with V1.0 on 2026-10-10 (a Saturday); the first
# production crawl that writes the log is the 2026-10-12 run. Trading days before it cannot have a
# log, so they do not count as silence (the first weekly check, 2026-10-11, would raise a false Issue).
MEASURED_SINCE = "20261012"


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, list) else []
    except (OSError, ValueError):
        return []


def check(log, trade_dates, now, days=7):
    """-> (ok, lines). trade_dates: 'YYYYMMDD' strings."""
    since = now - timedelta(days=days)
    recent = []
    for e in log:
        try:
            at = datetime.strptime(e["at"], "%Y-%m-%d %H:%M").replace(tzinfo=TW)
        except (KeyError, ValueError):
            continue
        if at >= since:
            recent.append(e)
    window_days = [d for d in trade_dates if max(since.strftime("%Y%m%d"), MEASURED_SINCE) <= d <= now.strftime("%Y%m%d")]
    bad = [e for e in recent if (e.get("below_floor") or 0) > 0
           or (e.get("min_gap_s") is not None and e["min_gap_s"] < FUBON_MIN_GAP_S - TOLERANCE_S)]
    crawler_runs = [e for e in recent if e.get("component") == "crawler"]
    lines = [f"## 富邦請求間隔週檢查（{since:%m/%d}–{now:%m/%d}，底線 {FUBON_MIN_GAP_S} 秒）", "",
             f"- 紀錄 {len(recent)} 筆，其中主爬蟲 {len(crawler_runs)} 筆；期間交易日 {len(window_days)} 天"]
    if recent:
        mins = [e["min_gap_s"] for e in recent if e.get("min_gap_s") is not None]
        if mins:
            lines.append(f"- 量到的最小間隔 {min(mins):.3f} 秒；總請求數 {sum(e.get('requests', 0) for e in recent)}")
    ok = True
    if bad:
        ok = False
        lines.append(f"- ❌ {len(bad)} 筆低於底線：")
        lines += [f"  - {e['at']} {e.get('component')}: 最小 {e.get('min_gap_s')} 秒，低於底線 {e.get('below_floor')} 次"
                  for e in bad[:20]]
    if window_days and not crawler_runs:
        ok = False
        lines.append("- ❌ 期間有交易日，卻沒有任何主爬蟲的間隔紀錄（量測或紀錄可能失效）")
    if ok:
        lines.append("- ✅ 全部 ≥ 底線")
    return ok, lines


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", default=str(ROOT / "data" / "fubon_pacing_log.json"))
    p.add_argument("--index", default=str(ROOT / "data" / "index.json"))
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--report", default=None)
    a = p.parse_args(argv)
    try:
        with open(a.index, encoding="utf-8") as f:
            dates = [str(d) for d in (json.load(f).get("dates") or [])]
    except (OSError, ValueError):
        dates = []
    ok, lines = check(_load(a.log), dates, datetime.now(TW), a.days)
    text = "\n".join(lines)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
