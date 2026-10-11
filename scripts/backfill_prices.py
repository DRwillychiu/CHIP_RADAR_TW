"""v3.96.0 insider radar 1.6: two years of daily closes (all listed + OTC stocks) and the TAIEX,
for the event study. Spec: docs/specs/INSIDER_RADAR_SPEC.md (S6).

One month at a time: FMTQIK (1 request: the trading days and the TAIEX close), then for each
trading day one TWSE MI_INDEX and one TPEx daily-quotes request (the same official pages and
parsers the source audit uses). Output data/price_history/YYYYMM.json:
    {"month", "days": [...], "taiex": {day: close}, "close": {code: {day: close}}}
A finished month is never fetched again (resume after a stop).

Polite: one thread, >= 5 s between requests, stop at the first 403 / 429 / 5xx or a payload error,
--max-requests caps a run. --dry-run prints how many requests a range needs and fetches nothing
beyond the month calendars it already has.
    python scripts/backfill_prices.py --start 202410 --end 202610 --dry-run
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.audit.source_audit import TWSE_URL, TPEX_URL, parse_twse_closes, parse_tpex_closes  # noqa: E402

FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym}01&response=json"
GAP_S = 5.0
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}


class Stop(Exception):
    pass


class Polite:
    def __init__(self, max_requests):
        self.last, self.n, self.max = 0.0, 0, max_requests

    def get_json(self, url):
        if self.n >= self.max:
            raise Stop(f"max requests {self.max} reached")
        wait = GAP_S - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.n += 1
        try:
            r = requests.get(url, headers=HEAD, timeout=60)
        finally:
            self.last = time.monotonic()
        if r.status_code in (403, 429) or r.status_code >= 500:
            raise Stop(f"HTTP {r.status_code} for {url}")
        try:
            return r.json()
        except ValueError:
            raise Stop(f"not JSON (blocked page?) for {url}")


def months(start, end):
    y, m = int(start[:4]), int(start[4:])
    while f"{y:04d}{m:02d}" <= end:
        yield f"{y:04d}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def parse_fmtqik(doc, ym):
    """-> {YYYYMMDD: taiex close}; dates are ROC like '115/10/01'."""
    if not isinstance(doc, dict) or doc.get("stat") != "OK":
        raise Stop(f"FMTQIK {ym}: stat {doc.get('stat') if isinstance(doc, dict) else '?'}")
    f = [str(x).strip() for x in doc.get("fields") or []]
    di, ti = f.index("日期"), f.index("發行量加權股價指數")
    out = {}
    for r in doc.get("data") or []:
        y, mo, d = str(r[di]).strip().split("/")
        out[f"{int(y) + 1911:04d}{int(mo):02d}{int(d):02d}"] = float(str(r[ti]).replace(",", ""))
    return out


def run(start, end, out_dir, max_requests, dry_run):
    out_dir.mkdir(parents=True, exist_ok=True)
    pol = Polite(max_requests)
    need = 0
    for ym in months(start, end):
        path = out_dir / f"{ym}.json"
        if path.exists():
            print(f"  {ym}: done earlier, skipped")
            continue
        if dry_run:
            need += 1 + 2 * 22          # calendar + ~22 trading days x 2 markets
            continue
        taiex = parse_fmtqik(pol.get_json(FMTQIK.format(ym=ym)), ym)
        days = sorted(taiex)
        close = {}
        for d in days:
            tw = parse_twse_closes(pol.get_json(TWSE_URL.format(ymd=d)), d)
            tp = parse_tpex_closes(pol.get_json(TPEX_URL.format(y=d[:4], m=d[4:6], d=d[6:])), d)
            for code, c in list(tw.items()) + list(tp.items()):
                close.setdefault(code, {})[d] = c
        path.write_text(json.dumps({"month": ym, "days": days, "taiex": taiex, "close": close},
                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {ym}: {len(days)} days, {len(close)} codes, requests so far {pol.n}")
    if dry_run:
        print(f"[dry-run] about {need} requests (~{need * GAP_S / 60:.0f} min at {GAP_S:.0f} s each)")
    return pol.n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "price_history"))
    ap.add_argument("--max-requests", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        n = run(a.start, a.end, Path(a.out), a.max_requests, a.dry_run)
        print(f"[prices] requests {n}")
    except Exception as e:      # Stop, or a payload the official parsers reject (SourceError)
        print(f"[prices] stopped: {type(e).__name__}: {e} - finished months are kept, rerun resumes")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
