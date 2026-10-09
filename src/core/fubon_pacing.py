"""v3.85.6 one source for the Fubon (MoneyDJ) request pacing.

Owner 2026-10-08: "富邦停頓，絕對要多留0.5秒" -> never below 1.6 s.
Owner 2026-10-09: the audit paths (source audit, light verify, transfer watch)
used 1.1 s -> unified to 1.6 s, "同時也要定時每周驗證是否間隔時間有改變".

Two layers:
- static: every module that talks to fubon-ebrokerdj takes its gap from here
  (tests/test_v38506_fubon_pacing.py fails on any other value or on a new
  Fubon caller that does not import this module);
- runtime: note_request() is called right before every Fubon request; the
  measured gaps between request starts are summarised per process and
  appended to data/fubon_pacing_log.json, which scripts/check_fubon_pacing.py
  reads every week (.github/workflows/fubon-pacing-weekly.yml).
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

FUBON_MIN_GAP_S = 1.6       # floor between two Fubon requests (owner rule)
FUBON_MAX_GAP_S = 2.1       # upper end of the random gap used by the crawler
TOLERANCE_S = 0.02          # timer jitter allowed when checking measured gaps
LOG_PATH = os.path.join("data", "fubon_pacing_log.json")
LOG_KEEP = 400              # entries kept (a night writes ~2-6)
TW = timezone(timedelta(hours=8))

_state = {"last": None, "gaps": [], "requests": 0}


def reset():
    _state.update(last=None, gaps=[], requests=0)


def note_request(clock=time.monotonic):
    """Call right before every Fubon request (retries included)."""
    now = clock()
    if _state["last"] is not None:
        _state["gaps"].append(now - _state["last"])
    _state["last"] = now
    _state["requests"] += 1


def summary():
    gaps = sorted(_state["gaps"])
    below = sum(1 for g in gaps if g < FUBON_MIN_GAP_S - TOLERANCE_S)
    return {
        "requests": _state["requests"],
        "min_gap_s": round(gaps[0], 3) if gaps else None,
        "p50_gap_s": round(gaps[len(gaps) // 2], 3) if gaps else None,
        "below_floor": below,
        "floor_s": FUBON_MIN_GAP_S,
    }


def append_log(component, path=LOG_PATH, now=None, force=False):
    """Append this process's summary (no-op when it made no Fubon request).

    Only on GitHub Actions (or force=True): local test runs fake the network
    and must not touch data/ in the working tree."""
    s = summary()
    if not s["requests"] or not (force or os.environ.get("GITHUB_ACTIONS") == "true"):
        return None
    entry = {"at": (now or datetime.now(TW)).strftime("%Y-%m-%d %H:%M"), "component": component, **s}
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    except (OSError, ValueError):
        log = []
    log.append(entry)
    log = log[-LOG_KEEP:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=0)
    return entry
