"""v3.96.0 insider radar 1.5: per-person pages (MOPS query6_1) for the flagged company-months.
Spec: docs/specs/INSIDER_RADAR_SPEC.md 5.1 (IRB110 only screens; the numbers come from these pages).

Queue: insider_monthly.screen() over data/insider_monthly/*.json, buy side first, then sell side,
then IRB140-only, oldest month first. The average close comes from data/price_history (the nearest
fetched month when that month is not fetched yet - a screen, not a number we report).
Raw pages go to data/insider_q61_raw/{code}_{ym}.html (not in git; re-parse any time); a cached page
is never fetched again, so a rerun resumes.

Owner 2026-10-11: a block = (requests when the 502 came) - 10. Observed 502s: the sampling run's
32nd request (15:37) and this script's 17th (15:49, after an 11-minute rest) -> the smallest count
is used: 17 - 10 = 7 requests per block, one block every 2 minutes.
Queue order (quality first): 0 a fixed random control sample of NOT flagged company-months (how much
the screen misses), 1 buy side, 2 sell side, 3 IRB140 only, 5 the monthly pre-transfer declarations
(t56sb21, listed + OTC, complete months). The queue is written to data/insider_people_queue.json.
Polite: one thread, >= 5 s between requests. A 403 / 429 / 5xx or a page without its table stops:
the body is kept in <raw>/_fail/, 10 min cool-down, then the same page once more; a page failing
twice goes to the end of the run; three failures in a row end the run (a rerun resumes).
Pace (owner 2026-10-12): --cycle by day, --slow-cycle after two failures within 30 min (for the rest of
the run) and from 21:30 to 07:00.
    python scripts/fetch_insider_people.py --max-requests 1800 [--dry-run]
"""
import argparse
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.fetchers import insider_monthly as M  # noqa: E402

GAP_S, BLOCK, CYCLE_S, COOL_S = 5.0, 7, 120.0, 600.0
CONTROL_N, SEED = 22, 20261011       # per control group: manager / >10 % holder change, everything else
T56_MONTHS = ("202309", "202609")   # complete months; --since moves the start (year 3 from 2023-09, owner 2026-10-11)
GONE = "不繼續公開發行"
SLOW_FROM, SLOW_UNTIL, FAIL_WINDOW_S = "21:30", "07:00", 1800.0


def pick_cycle(base, slow, fail_times, now_s, hhmm, slowed=False):
    """Owner 2026-10-12 「可以」: by day one block per `base` s (90); two failures within 30 min, or the
    evening (21:30 on, when MOPS was unstable 10-11) -> `slow` s (120). Once slowed by failures the run stays slow.
    -> (cycle, slowed_by_failures)."""
    slowed = slowed or sum(1 for t in fail_times if now_s - t <= FAIL_WINDOW_S) >= 2
    return (slow if slowed or hhmm >= SLOW_FROM or hhmm < SLOW_UNTIL else base), slowed
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://mopsov.twse.com.tw/mops/web/query6_1"}


def _ym_index(ym):
    return int(ym[:4]) * 12 + int(ym[4:])


def avg_prices(price_dir):
    out = {}
    for f in sorted(Path(price_dir).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["month"]] = {c: statistics.mean(v.values()) for c, v in d["close"].items() if v}
    return out


def last_complete_month(today=None):
    import datetime as dt
    d = (today or dt.date.today()).replace(day=1) - dt.timedelta(days=1)
    return d.strftime("%Y%m")


def build_queue(monthly_dir, price_dir, control=True, since="000000", until="999999"):
    """-> sorted [(priority, ym, code)]; t56 jobs use code 'T56:sii' / 'T56:otc'."""
    px = avg_prices(price_dir)
    q, rest_mgr, rest_other_all, prev = [], [], [], None
    for f in sorted(Path(monthly_dir).glob("*.json")):
        month = json.loads(f.read_text(encoding="utf-8"))
        ym = month["ym"]
        near = sorted(px, key=lambda m: abs(_ym_index(m) - _ym_index(ym)))
        avg = {}
        for m in reversed(near):            # the nearest month wins
            avg.update(px[m])
        flagged = M.screen(month, avg, prev)
        keep = since <= ym <= until          # earlier months still feed the next month's holdings change
        q += [(p, ym, code) for p, code in flagged] if keep else []
        done = {c for _, c in flagged}
        for code, r in month["companies"].items():
            if code in done:
                continue
            o = (prev or {}).get("companies", {}).get(code)
            iss, p = r.get("issued") or 0, avg.get(code)
            moved = o and any(M.screen({"companies": {code: {"issued": iss, "dir_inc": abs((r.get(k) or 0) - (o.get(k) or 0))}}},
                                       {code: p} if p else {}) for k in ("mgr_held", "big10_held"))
            (rest_mgr if moved else rest_other_all).append((0, ym, code))
        prev = month
    qf = ROOT / "data" / "insider_people_queue.json"
    old_p0 = [tuple(x) for x in json.loads(qf.read_text(encoding="utf-8")) if x[0] == 0] if qf.exists() else []
    if control:
        # one control sample per year, drawn once and kept (new prices must not redraw it); all of them
        # are fetched first in every run (owner 2026-10-11: year 2's control sample right away too)
        q += [x for x in old_p0 if x[1] >= since]      # owner 2026-10-11: year 1 complete first - later years wait
        pool_all = rest_mgr + rest_other_all
        for lo, hi in (("202509", "999999"), ("202410", "202508"), ("202309", "202409")):   # one per year
            if hi < since:
                continue
            if sum(1 for x in old_p0 if lo <= x[1] <= hi) >= 2 * CONTROL_N:
                q += []
                continue
            pool = [x for x in pool_all if lo <= x[1] <= hi]
            q += random.Random(SEED + int(lo)).sample(pool, min(2 * CONTROL_N, len(pool)))
    from scripts.backfill_prices import months
    t56_end = min(until, max(T56_MONTHS[1], last_complete_month()))      # complete months only
    q += [(5, ym, f"T56:{mkt}") for ym in months(max(since, T56_MONTHS[0]), t56_end) for mkt in ("sii", "otc")]
    seen, out = set(), []
    # owner 2026-10-11: what the backtest needs first - buy side, then the holder changes, then the rest
    rank = {0: 0, 1: 1, 4: 2, 2: 3, 3: 4, 5: 5}
    for x in sorted(q, key=lambda x: (rank[x[0]], x[1], x[2])):   # one page once (a frozen control page may be screened now)
        if (x[1], x[2]) not in seen:
            seen.add((x[1], x[2]))
            out.append(x)
    return out


def raw_path(raw, ym, code):
    if code.startswith("T56:"):
        return raw.parent / "insider_t56_raw" / f"{code[4:]}_{ym}.html"
    return raw / f"{code}_{ym}.html"


def page_ok(raw: bytes, t56=False) -> bool:
    t = raw.decode("utf-8", errors="replace")
    if t56:
        return "申報日期" in t or "查無" in t
    # an answer, not an error: the table, no data, or the company left (4130 202602: 不繼續公開發行);
    # an EMPTY company picker is MOPS's "nothing to show" for some foreign listings (674191 2026-03)
    if "請點選欲查詢之公司" in t and "<form" not in t.lower():
        return True
    return any(k in t for k in ("身份別", "查無", GONE, "不存在", "已下市"))


def now():
    return time.strftime("%H:%M:%S")


def fetch(code, ym, form=None):
    if code.startswith("T56:"):
        return requests.post(M.T56_URL, data=M.t56_form(code[4:], ym), headers=HEAD_T56, timeout=90)
    return requests.post(M.Q61_URL, data=form or M.q61_form(code, ym), headers=HEAD, timeout=60)


def picker_form(body: bytes, code: str):
    """Financial holdings (2884 玉山金 ...) first answer 「請點選欲查詢之公司」 with one form per group
    company; the holding's own form (co_id == code) is posted next - a second request, not an error."""
    t = body.decode("utf-8", errors="replace")
    if "請點選欲查詢之公司" not in t:
        return None
    for f in re.findall(r"(?is)<form[^>]*>(.*?)</form>", t):
        fields = dict(re.findall(r"name='([^']+)' value='([^']*)'", f))
        if fields.get("co_id") == code:
            return fields
    return None


HEAD_T56 = {**HEAD, "Referer": "https://mopsov.twse.com.tw/mops/web/t56sb21_q1"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", default=str(ROOT / "data" / "insider_monthly"))
    ap.add_argument("--prices", default=str(ROOT / "data" / "price_history"))
    ap.add_argument("--raw", default=str(ROOT / "data" / "insider_q61_raw"))
    ap.add_argument("--max-requests", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default="000000", help="first month YYYYMM (owner 2026-10-11: the last year first)")
    ap.add_argument("--delay", type=float, default=0, help="seconds to wait before the first request")
    ap.add_argument("--until", default="999999", help="last month YYYYMM (the monthly update fetches one month)")
    ap.add_argument("--no-control", action="store_true", help="no control sample (the monthly update)")
    ap.add_argument("--block", type=int, default=BLOCK, help="requests per block")
    ap.add_argument("--cycle", type=float, default=CYCLE_S, help="seconds from one block start to the next")
    ap.add_argument("--slow-cycle", type=float, default=None, help="cycle after 2 failures in 30 min or from 21:30 (default: --cycle)")
    a = ap.parse_args()
    raw = Path(a.raw)
    (raw / "_fail").mkdir(parents=True, exist_ok=True)
    (raw.parent / "insider_t56_raw").mkdir(parents=True, exist_ok=True)
    queue = build_queue(a.monthly, a.prices, control=not a.no_control, since=a.since, until=a.until)
    # keep every year's frozen control sample in the file, also the ones this run does not fetch
    qf = ROOT / "data" / "insider_people_queue.json"
    kept = [tuple(x) for x in json.loads(qf.read_text(encoding="utf-8")) if x[0] == 0] if qf.exists() else []
    qset = set(queue)
    qf.write_text(json.dumps([list(x) for x in queue] + [list(x) for x in kept if x not in qset],
                             ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    todo = [x for x in queue if not raw_path(raw, x[1], x[2]).exists()]
    by_p = {p: sum(1 for x in todo if x[0] == p) for p in (0, 1, 2, 3, 4, 5)}
    print(f"[q61] {now()} queue {len(queue)}, cached {len(queue) - len(todo)}, to fetch {len(todo)} "
          f"(control {by_p[0]}, buy {by_p[1]}, sell {by_p[2]}, IRB140 only {by_p[3]}, holder change {by_p[4]}, t56 {by_p[5]})", flush=True)
    if a.dry_run:
        blocks = -(-min(len(todo), a.max_requests) // a.block)
        print(f"[dry-run] {blocks} blocks of {a.block}, about {blocks * max(a.cycle, a.block * 5.6) / 3600:.1f} h without failures")
        return 0
    time.sleep(a.delay)
    trace = (ROOT / "logs" / "insider_people_requests.csv").open("a", encoding="utf-8")
    n, last, block_start, in_block, streak = 0, 0.0, time.monotonic(), 0, 0
    tries, later, i, follow = {}, [], 0, {}
    fail_times, slowed, cyc = [], False, a.cycle
    # owner 2026-10-11: 「不繼續公開發行」這種，絕對就是跳過 - one such answer skips the company's other months
    gone = {f.stem.split("_")[0] for f in raw.glob("*.html")
            if f.stat().st_size < 5000 and GONE in f.read_bytes().decode("utf-8", errors="replace")}
    while i < len(todo) or later:
        if i >= len(todo):                   # pages that failed twice: one last try each
            todo, later, i = later, [], 0
            print(f"[q61] {now()} last try for {len(todo)} pages that failed twice", flush=True)
        p, ym, code = todo[i]
        if code in gone:
            print(f"[q61] {now()} skip {code} {ym}: {GONE}", flush=True)
            i += 1
            continue
        if n >= a.max_requests:
            print(f"[q61] {now()} max requests {a.max_requests} reached at {i}/{len(todo)}; rerun resumes", flush=True)
            return 1
        if in_block >= a.block:
            c2, slowed = pick_cycle(a.cycle, a.slow_cycle or a.cycle, fail_times, time.monotonic(), time.strftime("%H:%M"), slowed)
            if c2 != cyc:
                print(f"[q61] {now()} pace {a.block} per {cyc:.0f} s -> {a.block} per {c2:.0f} s "
                      f"({'2 failures within 30 min' if slowed else 'time of day'})", flush=True)
                cyc = c2
            rest = cyc - (time.monotonic() - block_start)
            if rest > 0:
                time.sleep(rest)
            block_start, in_block = time.monotonic(), 0
        wait = GAP_S - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        n += 1
        in_block += 1
        t0 = time.monotonic()
        try:
            r = fetch(code, ym, follow.pop((ym, code), None))
            status, body = r.status_code, r.content
        except requests.RequestException as e:
            status, body = f"error {type(e).__name__}", b""
        last = time.monotonic()
        # one line per request, to learn what the 502s depend on: position in block, rest before, latency
        trace.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{n},{in_block},{t0 - block_start:.0f},{code},{ym},"
                    f"{status},{len(body)},{last - t0:.2f}\n")
        trace.flush()
        pf = picker_form(body, code) if status == 200 and not code.startswith("T56:") else None
        if pf:
            follow[(ym, code)] = pf          # same page again, now for the holding company itself
            continue
        if status == 200 and page_ok(body, code.startswith("T56:")):
            raw_path(raw, ym, code).write_bytes(body)
            if GONE.encode("utf-8") in body:
                gone.add(code)
            streak = 0
            i += 1
            if n % 70 == 0:
                print(f"[q61] {now()} {n} requests, {i}/{len(todo)} pages", flush=True)
            continue
        streak += 1
        fail_times.append(time.monotonic())
        tries[(ym, code)] = tries.get((ym, code), 0) + 1
        tag = code.replace(":", "_")
        (raw / "_fail" / f"{tag}_{ym}_{time.strftime('%H%M%S')}.txt").write_bytes(body)
        print(f"[q61] {now()} request {n} failed ({code} {ym}, try {tries[(ym, code)]}): HTTP {status}, "
              f"{len(body)} bytes; {streak} in a row", flush=True)
        if streak >= 3:
            print(f"[q61] {now()} three failures in a row - run ends; rerun resumes", flush=True)
            return 1
        if tries[(ym, code)] >= 2:
            if tries[(ym, code)] == 2:
                later.append((p, ym, code))      # a third failure (the last try) gives the page up
            i += 1
        print(f"[q61] {now()} cooling down {COOL_S / 60:.0f} min", flush=True)
        time.sleep(COOL_S)
        block_start, in_block = time.monotonic(), 0
    lost = sorted(f"{c} {y}" for (y, c), t in tries.items() if t >= 3)
    print(f"[q61] {now()} queue finished, requests {n}, pages given up {len(lost)}: {lost}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
