"""
transfer_watch.py - v3.80.21 account-transfer watch: data layer.

Why (owner, 2026-10-06): the Jiao family (Walsin group) buys 2492 / 4919 / 6173
at branch 984K and moves the shares by account transfer (not a market trade) to
accounts at branches 989N and 585b. Branch data never shows the transfer itself,
so the daily Excel puts the three branches' net lots side by side: today and the
last trading days. The sheet is drawn by excel_report.build_transfer_sheet.

Config: TRANSFER_WATCH_GROUPS, one dict per family. Adding a family = adding a
dict here; nothing else changes (one sheet per dict, after the Pinned sheet).

Where every cell comes from (net lots = buy_lot - sell_lot of the stock in the
branch's net-buy or net-sell list; net-buy list first, like source_audit):
  1. today = the branches_data of this Excel build (the nightly crawl);
     past days = stored day files data/YYYYMMDD.json (+ archive/ .json and
     .json.gz), decrypted like scripts/daily_rolling_update.py and ALWAYS passed
     through quarantine.filter_day. Window = trade_date + the newest
     WINDOW_DAYS - 1 stored dates before it.
  2. The crawl stores only the top TOP_N rows of each page region
     (crawler_fetch.merge_rows), so "stock not in the stored lists" proves
     "not on the page" only when both lists are shorter than TOP_N. A stored
     branch-day that is missing, failed, quarantined or of another data date
     cannot answer at all. Such cells are read from the Fubon date-pinned full
     pages (source_audit.fetch_branch_pages: hex code for lettered bno, page
     identity and data-date checks), once per branch-day, and cached in
     data/transfer_watch_cache.json (plaintext, only these cells; the Excel is
     public too - owner OK 2026-10-06). A cached branch-day is never fetched
     again. Failures are not cached; at most FETCH_CAP branch-days per build;
     a build with fetch=False (the nightly final regen) never fetches.
  3. Lots that are an estimate (stock not on the lots page) follow the
     crawler's rule (source_audit.est_lots: per side max(1, round(amt / close)))
     and carry est=True; the sheet prefixes them with an approx sign.

Cell states: 'value'   on the list, lots = net lots (est = estimate)
             'absent'  known not on that branch's lists that day (shown as a dash)
             'missing' unknown: fetch failed / cap reached / no close for an
                       estimate (shown as a dash + a footnote)
"""
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.audit import source_audit as sa
from src.core.quarantine import filter_day
from src.pipelines.crawler_fetch import TOP_N
from src.pipelines.crawler_output import decrypt_data

TW = timezone(timedelta(hours=8))

TRANSFER_WATCH_GROUPS: List[Dict] = [
    {
        # owner 2026-10-06: bought at 984K, moved by account transfer to 989N / 585b
        "group": "焦家",
        "sheet": "🔁 焦家匯撥",
        "title": "焦家匯撥追蹤",
        "stocks": [("2492", "華新科"), ("4919", "新唐"), ("6173", "信昌電")],
        "from_branches": [("984K", "元大-館前")],
        "to_branches": [("989N", "元大-內湖"), ("585b", "統一-內湖")],
    },
]
SHEET_PREFIX = "🔁 "      # every transfer-watch sheet name starts with this
WINDOW_DAYS = 5
CACHE_NAME = "transfer_watch_cache.json"
FETCH_CAP = 15            # branch-day page pairs per build (3 branches x 5 days)
FETCH_BUDGET_S = 180      # wall clock for those fetches per build
CACHE_KEEP_DATES = 30     # newest trade dates kept in the cache file

ABSENT = {"state": "absent", "lots": None, "est": False}


def _value(lots, est, src):
    return {"state": "value", "lots": int(lots), "est": bool(est), "src": src}


def _missing(reason):
    return {"state": "missing", "lots": None, "est": False, "reason": reason}


def group_branches(group: Dict) -> List[Tuple[str, str]]:
    return list(group["from_branches"]) + list(group["to_branches"])


# ----------------------------------------------------------------------------
#  Stored day files
# ----------------------------------------------------------------------------

_DATE_GLOB = "[0-9]" * 8


def stored_dates(data_dir: Path) -> List[str]:
    """Trade dates that have a stored day file, newest first."""
    data_dir = Path(data_dir)
    found = set()
    for folder, pattern in ((data_dir, _DATE_GLOB + ".json"),
                            (data_dir / "archive", _DATE_GLOB + ".json"),
                            (data_dir / "archive", _DATE_GLOB + ".json.gz")):
        if folder.is_dir():
            found.update(p.name[:8] for p in folder.glob(pattern))
    return sorted(found, reverse=True)


def window_dates(data_dir: Path, trade_date: str, n: int = WINDOW_DAYS) -> List[str]:
    """trade_date + the newest n-1 stored dates before it, newest first."""
    return [trade_date] + [d for d in stored_dates(data_dir) if d < trade_date][:n - 1]


def day_file(data_dir: Path, date: str) -> Optional[Path]:
    data_dir = Path(data_dir)
    for p in (data_dir / f"{date}.json", data_dir / "archive" / f"{date}.json",
              data_dir / "archive" / f"{date}.json.gz"):
        if p.is_file():
            return p
    return None


def read_day(data_dir: Path, date: str, password: str) -> Optional[Dict]:
    """Stored day, decrypted, quarantined branch-days blanked. None if no file."""
    p = day_file(data_dir, date)
    if p is None or not password:
        return None
    raw = p.read_bytes()
    if p.name.endswith(".gz"):
        raw = gzip.decompress(raw)
    enc = json.loads(raw.decode("utf-8"))
    data = json.loads(decrypt_data(enc["data"], password, iterations=enc.get("iterations")))
    return filter_day(data, date)  # v3.80.3: skip quarantined branch-days (data/quarantine.json)


# ----------------------------------------------------------------------------
#  Closes (estimates + the today table)
# ----------------------------------------------------------------------------

def _record_quotes(branches, codes) -> Dict[str, Tuple[float, Optional[float]]]:
    """{code: (close, change_pct)} from the crawl's quote fields of one day."""
    out = {}
    for b in branches or []:
        if not isinstance(b, dict):
            continue
        for side in ("buys", "sells"):
            for s in b.get(side) or []:
                c = s.get("code") if isinstance(s, dict) else None
                if c in codes and c not in out and s.get("close_price") and not s.get("quote_stale"):
                    out[c] = (float(s["close_price"]), s.get("change_pct"))
    return out


def load_history_quotes(data_dir: Path, dates, codes) -> Dict[str, Dict[str, Tuple]]:
    """{date: {code: (close, change_pct)}} from data/stock_history.json (60 days)."""
    p = Path(data_dir) / "stock_history.json"
    out: Dict[str, Dict[str, Tuple]] = {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    stocks = doc.get("stocks") or {}
    for code in codes:
        daily = (stocks.get(code) or {}).get("daily") or {}
        for d in dates:
            q = daily.get(d) or {}
            if q.get("close"):
                out.setdefault(d, {})[code] = (float(q["close"]), q.get("change_pct"))
    return out


# ----------------------------------------------------------------------------
#  Cells from a crawl / stored record and from a source page
# ----------------------------------------------------------------------------

def _find(rec: Dict, code: str) -> Optional[Dict]:
    for side in ("buys", "sells"):
        for s in rec.get(side) or []:
            if isinstance(s, dict) and s.get("code") == code:
                return s
    return None


def _usable(rec, date: str) -> bool:
    """A record that can answer for this branch-day."""
    return (isinstance(rec, dict) and not rec.get("error") and not rec.get("quarantined")
            and (not rec.get("date") or str(rec["date"]) == date))


def _complete(rec: Dict) -> bool:
    """Both stored lists shorter than TOP_N = both page regions fully stored."""
    return len(rec.get("buys") or []) < TOP_N and len(rec.get("sells") or []) < TOP_N


def cell_from_entry(s: Dict, close: Optional[float]) -> Dict:
    """A stock row of a crawl / stored record (crawler.py estimate block rules)."""
    bl, sl = int(s.get("buy_lot") or 0), int(s.get("sell_lot") or 0)
    listed = s.get("lot_listed")
    estimated = s.get("lot_source") == "estimated_from_close"
    if listed is None:                  # day files before v3.80.1 (2026-09-25)
        return _value(bl - sl, estimated, "stored")
    if listed:
        return _value(bl - sl, False, "stored")
    # the lots page lacked the stock -> stored lots are the crawler's estimate,
    # or 0 placeholders when the crawler had no close
    if estimated:
        return _value(bl - sl, True, "stored")
    ba, sm = int(s.get("buy_amt") or 0), int(s.get("sell_amt") or 0)
    if not (ba or sm):
        return _value(bl - sl, False, "stored")
    if close:
        return _value(sa.est_lots(ba, close) - sa.est_lots(sm, close), True, "stored+close")
    return _missing("no close for the lots estimate")


def cell_from_page(row: Optional[Dict], close: Optional[float]) -> Dict:
    """row = cached page lookup {'amt': [buy, sell] | None, 'lots': [...] | None}."""
    if not row or (row.get("amt") is None and row.get("lots") is None):
        return dict(ABSENT)
    lots, amt = row.get("lots"), row.get("amt")
    if lots is not None:
        return _value(lots[0] - lots[1], False, "page")
    if close:
        return _value(sa.est_lots(amt[0], close) - sa.est_lots(amt[1], close), True, "page")
    return _missing("no close for the lots estimate")


def page_row(pages: Dict, code: str) -> Optional[Dict]:
    """source_audit page maps -> the cached form of one stock (None = not on page)."""
    reg, amt, lots = sa.lookup(pages["B"], pages["E"], code)
    if reg is None:
        return None
    return {"region": reg, "amt": list(amt) if amt else None,
            "lots": list(lots) if lots else None}


# ----------------------------------------------------------------------------
#  Cache (data/transfer_watch_cache.json)
# ----------------------------------------------------------------------------

_ABOUT = ("Fubon date-pinned branch pages (zgb0 e=f=date), only the cells of the "
          "transfer-watch Excel sheet (src/exports/transfer_watch.py). "
          "pages[bno][YYYYMMDD].rows[code]: amt = [buy, sell] thousand TWD, "
          "lots = [buy, sell]; null = stock not on that page. Never refetched.")


def load_cache(path: Path) -> Dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("pages"), dict):
            return doc
    except (OSError, ValueError):
        pass
    return {"about": _ABOUT, "pages": {}}


def cached_rows(cache: Dict, bno: str, date: str, codes) -> Optional[Dict]:
    """Cached rows of a branch-day if every wanted code was looked up, else None."""
    entry = (cache.get("pages", {}).get(bno) or {}).get(date)
    rows = entry.get("rows") if isinstance(entry, dict) else None
    if isinstance(rows, dict) and all(c in rows for c in codes):
        return rows
    return None


def save_cache(path: Path, cache: Dict) -> None:
    dates = sorted({d for days in cache["pages"].values() for d in days}, reverse=True)
    keep = set(dates[:CACHE_KEEP_DATES])
    cache["pages"] = {b: {d: v for d, v in days.items() if d in keep}
                      for b, days in cache["pages"].items()}
    cache["pages"] = {b: days for b, days in cache["pages"].items() if days}
    cache["about"] = _ABOUT
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def fetch_branch_day(bno: str, date: str, pacer) -> Dict:
    """Network: the amount + lots date-pinned pages of one branch-day
    -> source_audit page maps. Raises source_audit.SourceError."""
    return sa.fetch_branch_pages(bno, date, sa.http_get, pacer)


# ----------------------------------------------------------------------------
#  Collect everything the sheets need
# ----------------------------------------------------------------------------

def collect(groups: List[Dict], branches_data: List[Dict], trade_date: str, data_dir,
            fetch: bool = True, password: Optional[str] = None,
            log: Callable = print, now: Optional[Callable] = None) -> Dict[str, Dict]:
    """-> {group name: {'config', 'days', 'branches', 'stocks', 'cells', 'quotes',
    'missing'}} plus key '_stats'. cells[(bno, date, code)] = cell dict;
    quotes[code] = (close, change_pct) of trade_date; missing = [(bno, date)]
    branch-days of that group with at least one 'missing' cell, newest first."""
    data_dir = Path(data_dir)
    now = now or (lambda: datetime.now(TW))
    if password is None:
        password = os.environ.get("CHIP_RADAR_PASSWORD", "")
    days = window_dates(data_dir, trade_date)
    codes_by_bno: Dict[str, set] = {}
    bno_order: List[str] = []
    for g in groups:
        for bno, _ in group_branches(g):
            if bno not in codes_by_bno:
                bno_order.append(bno)
            codes_by_bno.setdefault(bno, set()).update(c for c, _ in g["stocks"])
    all_codes = set().union(*codes_by_bno.values()) if codes_by_bno else set()

    # records[date][bno] (only the watched branches are kept) + crawl quotes
    records: Dict[str, Dict[str, Dict]] = {}
    quotes: Dict[str, Dict[str, Tuple]] = {}
    for d in days:
        if d == trade_date:
            branches = branches_data or []
        else:
            try:
                branches = (read_day(data_dir, d, password) or {}).get("branches") or []
            except Exception as e:      # unreadable file -> those cells come from the page
                log(f"  [transfer watch] stored day {d} unreadable: {type(e).__name__}: {e}")
                branches = []
        records[d] = {b.get("code"): b for b in branches
                      if isinstance(b, dict) and b.get("code") in codes_by_bno}
        quotes[d] = _record_quotes(branches, all_codes)
    hist = load_history_quotes(data_dir, days, all_codes)
    for d in days:
        for c, q in (hist.get(d) or {}).items():
            quotes[d].setdefault(c, q)

    def close(d, c):
        q = quotes.get(d, {}).get(c)
        return q[0] if q else None

    cells: Dict[Tuple[str, str, str], Dict] = {}
    need: Dict[Tuple[str, str], set] = {}
    for d in days:
        for bno in bno_order:
            rec = records[d].get(bno)
            ok = _usable(rec, d)
            complete = ok and _complete(rec)
            for code in sorted(codes_by_bno[bno]):
                s = _find(rec, code) if ok else None
                if s is not None:
                    cells[(bno, d, code)] = cell_from_entry(s, close(d, code))
                elif complete:
                    cells[(bno, d, code)] = dict(ABSENT)
                else:
                    need.setdefault((bno, d), set()).add(code)

    cache_path = data_dir / CACHE_NAME
    cache = load_cache(cache_path)
    stats = {"cache_hits": 0, "fetched": 0, "failed": 0, "skipped": 0}
    pacer = None
    changed = False
    order = sorted(need, key=lambda k: (-int(k[1]), bno_order.index(k[0])))
    for bno, d in order:
        rows = cached_rows(cache, bno, d, codes_by_bno[bno])
        reason = None
        if rows is not None:
            stats["cache_hits"] += 1
        elif not fetch:
            reason = "not fetched in this build"
            stats["skipped"] += 1
        elif stats["fetched"] + stats["failed"] >= FETCH_CAP:
            reason = "request cap"
            stats["skipped"] += 1
        else:
            if pacer is None:
                pacer = sa._Pacer(sa._sleep, sa._clock, sa._clock() + FETCH_BUDGET_S)
            try:
                pages = fetch_branch_day(bno, d, pacer)
                rows = {c: page_row(pages, c) for c in sorted(codes_by_bno[bno])}
                entry = cache["pages"].setdefault(bno, {}).setdefault(d, {})
                entry["rows"] = {**(entry.get("rows") or {}), **rows}
                entry["fetched_at"] = now().isoformat(timespec="seconds")
                rows = entry["rows"]
                changed = True
                stats["fetched"] += 1
                log(f"  [transfer watch] {bno} {d}: date-pinned page cached")
            except Exception as e:      # SourceError / BudgetExhausted / network
                reason = f"{type(e).__name__}: {e}"
                stats["failed"] += 1
                log(f"  [transfer watch] {bno} {d}: fetch failed ({reason})")
        for code in need[(bno, d)]:
            cells[(bno, d, code)] = (cell_from_page(rows.get(code), close(d, code))
                                     if rows is not None else _missing(reason))
    if changed:
        save_cache(cache_path, cache)

    out: Dict[str, Dict] = {"_stats": stats}
    for g in groups:
        brs = group_branches(g)
        g_cells = {(bno, d, c): cells[(bno, d, c)]
                   for d in days for bno, _ in brs for c, _ in g["stocks"]}
        miss = []
        for d in days:
            for bno, _ in brs:
                if any(g_cells[(bno, d, c)]["state"] == "missing" for c, _ in g["stocks"]):
                    miss.append((bno, d))
        out[g["group"]] = {
            "config": g, "days": days, "branches": brs, "stocks": list(g["stocks"]),
            "cells": g_cells,
            "quotes": {c: quotes.get(trade_date, {}).get(c, (None, None)) for c, _ in g["stocks"]},
            "missing": miss,
        }
    return out
