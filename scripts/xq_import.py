"""v3.85.0 import the XQ screener exports (cr_a_chips / cr_b_flows / cr_c_history).

XQ data is licensed: the merged file is written OUTSIDE the repo (default
<Desktop>/CHIP_RADAR_LOCAL/xq/) and must never be committed.

Each export (CSV, cp950) starts with a few title lines, a line
'資料日期：2026年 10月  7日', then a header row with 代碼 / 商品 / ... and the
script's OutputField labels. Codes look like '2330.TW'.

Usage:
  python scripts/xq_import.py --a cr_a.csv --b cr_b.csv --c cr_c.csv [--out DIR]
Prints, per column, how many stocks have a non-zero value, so a field that
returned nothing (no permission, wrong name) shows up at once.
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

DEFAULT_OUT = Path.home() / "Desktop" / "CHIP_RADAR_LOCAL" / "xq"
BASE_COLS = ("代碼", "商品", "成交", "漲幅%", "總量", "產業", "細產業", "所有細產業", "產業地位")


def read_export(path):
    """-> (data_date YYYYMMDD or None, {code: {column: value}}, [script columns])."""
    raw = Path(path).read_bytes()
    for enc in ("cp950", "utf-8-sig", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text)))
    date = None
    for r in rows[:6]:
        m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", " ".join(r))
        if m:
            date = f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    h = next(i for i, r in enumerate(rows) if r and r[0].strip() in ("序號", "代碼") or "代碼" in r)
    hdr = [c.strip() for c in rows[h]]
    ci = hdr.index("代碼")
    out = {}
    for r in rows[h + 1:]:
        if len(r) != len(hdr) or not r[ci].strip():
            continue
        code = r[ci].strip().split(".")[0]
        rec = {}
        for k, v in zip(hdr, r):
            v = v.strip().replace("\t", "")
            if k in ("序號", "代碼"):
                continue
            try:
                rec[k] = float(v.replace(",", "")) if k not in ("商品", "產業", "細產業", "所有細產業", "產業地位") else v
            except ValueError:
                rec[k] = v
        out[code] = rec
    script_cols = [k for k in hdr if k not in BASE_COLS and k not in ("序號",)]
    return date, out, script_cols


def coverage(recs, cols):
    n = len(recs) or 1
    return {c: sum(1 for r in recs.values() if isinstance(r.get(c), float) and r[c] != 0) / n for c in cols}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--c", required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    merged, dates, report = {}, {}, {}
    for key, path in (("a", a.a), ("b", a.b), ("c", a.c)):
        d, recs, cols = read_export(path)
        dates[key] = d
        report[key] = {"stocks": len(recs), "columns": len(cols), "coverage": coverage(recs, cols)}
        for code, rec in recs.items():
            merged.setdefault(code, {}).update(rec)
    if len({d for d in dates.values() if d}) > 1:
        print(f"⚠️ the three exports have different data dates: {dates}")
    # v3.85.2: close vs main-force cost from the export's own price column (成交);
    # the screener script no longer reads Close
    for rec in merged.values():
        px, cost = rec.get("成交"), rec.get("mf_cost")
        if isinstance(px, float) and isinstance(cost, float) and cost > 0:
            rec["close_vs_mf_cost"] = px / cost - 1
    day = next((d for d in dates.values() if d), "unknown")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"xq_{day}.json"
    target.write_text(json.dumps({"data_date": day, "dates": dates, "stocks": merged}, ensure_ascii=False),
                      encoding="utf-8")
    print(f"merged {len(merged)} stocks, data date {day} -> {target}")
    for key, r in report.items():
        empty = [c for c, v in r["coverage"].items() if v == 0]
        low = [f"{c} {v:.0%}" for c, v in r["coverage"].items() if 0 < v < 0.2]
        print(f"  script {key}: {r['stocks']} stocks, {r['columns']} columns; all-zero: {empty or '-'}; "
              f"under 20% non-zero: {low or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
