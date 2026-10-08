"""v3.80.27 per-stage wall-clock timing of the nightly crawl (owner 2026-10-08).

The "Run full crawler" step is ~85% of a run (19-25 min) but its log needs a
GitHub sign-in. crawler.main() calls timer.phase('<stage>') at each stage
boundary; timer.report() then
  - prints one ::notice annotation "Crawl timing" (readable through the public
    annotations API / Actions page),
  - prints a ::warning "Slow stage" for any stage over SLOW_S,
  - appends the run to data/crawl_timing.json (last KEEP runs) so stages can be
    compared night by night.
Never raises: timing must not break the crawl.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

TW = timezone(timedelta(hours=8))
KEEP = 60
SLOW_S = 180          # a single stage over 3 min gets its own warning
MIN_SHOW_S = 1.0      # stages under 1 s are left out of the notice (kept in json)


def fmt(seconds):
    s = int(round(seconds))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


class PhaseTimer:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.t0 = clock()
        self.name, self.start = None, self.t0
        self.phases = []              # [(stage, seconds)] in run order

    def phase(self, name):
        """Close the running stage (if any) and start `name` (None = stop)."""
        now = self.clock()
        if self.name is not None:
            self.phases.append((self.name, now - self.start))
        self.name, self.start = name, now

    def total(self):
        return self.clock() - self.t0

    def lines(self, stats=None):
        """-> (notice_text, [slow warning texts])."""
        total = self.total()
        shown = [f"{n} {fmt(s)}" for n, s in self.phases if s >= MIN_SHOW_S]
        text = f"total {fmt(total)} | " + " | ".join(shown)
        if stats:
            text += (f" || Fubon {stats.get('requests', 0)} req, {stats.get('retries', 0)} retries,"
                     f" net {fmt(stats.get('net_s', 0))}, pauses {fmt(stats.get('sleep_s', 0))}")
        slow = [f"{n} {fmt(s)} ({s / total:.0%} of the crawl)" for n, s in self.phases
                if s >= SLOW_S and total > 0]
        return text, slow

    def report(self, stats=None, data_dir=None, trade_date=None, log=print):
        try:
            self.phase(None)
            text, slow = self.lines(stats)
            log(f"::notice title=Crawl timing::{text}")
            for w in slow:
                log(f"::warning title=Slow stage::{w}")
            if data_dir is not None:
                self._append(data_dir, trade_date, stats)
        except Exception as e:  # pragma: no cover - never break the crawl
            log(f"  ⚠️ crawl timing report failed: {type(e).__name__}: {e}")

    def _append(self, data_dir, trade_date, stats):
        path = os.path.join(str(data_dir), "crawl_timing.json")
        try:
            with open(path, encoding="utf-8") as f:
                runs = json.load(f).get("runs", [])
        except (OSError, ValueError):
            runs = []
        runs.append({
            "at": datetime.now(TW).isoformat(timespec="seconds"),
            "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
            "trade_date": trade_date,
            "total_s": round(self.total(), 1),
            "phases": [[n, round(s, 1)] for n, s in self.phases],
            "fubon": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in (stats or {}).items()},
        })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"runs": runs[-KEEP:]}, f, ensure_ascii=False, indent=1)
            f.write("\n")
