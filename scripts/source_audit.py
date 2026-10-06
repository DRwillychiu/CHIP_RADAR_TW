"""v3.80.15 source audit CLI - Excel day sheet vs the original Fubon pages.

Runs in daily-full.yml after the last Excel regen. Audits the newest 8-digit
day sheet of data/reports/latest.xlsx (trade date = sheet name) with
src/audit/source_audit.py and writes data/audit/source_audit_latest.json:
  {trade_date, checked_at, status: ok|mismatch|incomplete|error, rows,
   verdicts{REAL, LOT_EST, AMT_EST, MISMATCH, UNVERIFIED}, mismatches[<=50],
   unverified_branches[], error, ...}
Prints GitHub annotations and, under Actions, writes status=<status> to
$GITHUB_OUTPUT. Always exits 0: the audit must never break the nightly run.

Usage:
  python scripts/source_audit.py                 # audit the newest day sheet
  python scripts/source_audit.py --sheet 20261002
  python scripts/source_audit.py --email-line    # one line for the daily mail
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_XLSX = ROOT / "data" / "reports" / "latest.xlsx"
DEFAULT_OUT = ROOT / "data" / "audit" / "source_audit_latest.json"
DEFAULT_INDEX = ROOT / "data" / "index.json"
FALLBACK_LINE = "⚠️ 來源比對：今天沒有跑完"


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _esc(s):
    """GitHub workflow-command escaping for the message part."""
    return str(s).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def email_line_from_files(out_path, index_path):
    try:
        from src.audit.source_audit import email_line
        idx = _read_json(index_path) or {}
        return email_line(_read_json(out_path), idx.get("latest"))
    except Exception:
        return FALLBACK_LINE


def annotate(doc):
    td = doc.get("trade_date") or "?"
    v = doc.get("verdicts") or {}
    st = doc.get("status")
    n_bad = doc.get("mismatch_total", 0)
    n_unv = v.get("UNVERIFIED", 0)
    n_br = len(doc.get("unverified_branches") or [])
    if st == "mismatch":
        msg = f"{td} 有 {n_bad} 列與富邦原始頁不符 (data/audit/source_audit_latest.json)"
        print(f"::error title=來源比對不符::{_esc(msg)}")
    elif st == "incomplete":
        msg = f"{td} 未比對 {n_unv} 列 ({n_br} 個分點抓不到原始頁)"
        print(f"::warning title=來源比對未完成::{_esc(msg)}")
    elif st == "error":
        print(f"::warning title=來源比對出錯::{_esc(doc.get('error') or 'unknown error')}")
    else:
        msg = f"{td} {doc.get('rows', 0)} 列全部相符"
        print(f"::notice title=來源比對::{_esc(msg)}")


def write_output(status):
    gh = os.environ.get("GITHUB_OUTPUT")
    if not gh:
        return
    try:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
    except Exception:
        pass


def main(argv=None):
    _utf8_stdout()
    p = argparse.ArgumentParser(description="Excel day sheet vs Fubon source pages")
    p.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--index", default=str(DEFAULT_INDEX))
    p.add_argument("--sheet", default=None, help="day sheet to audit (default: newest)")
    p.add_argument("--budget", type=float, default=None, help="time budget in seconds")
    p.add_argument("--email-line", action="store_true", help="print the one-line mail summary")
    try:
        args = p.parse_args(argv)
    except SystemExit:
        return 0

    if args.email_line:
        print(email_line_from_files(args.out, args.index))
        return 0

    status = "error"
    try:
        from src.audit import source_audit as sa
        doc = sa.run_audit(args.xlsx, sheet=args.sheet,
                           budget_s=args.budget if args.budget else sa.BUDGET_S)
        status = doc.get("status", "error")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        v = doc.get("verdicts") or {}
        print(f"[source audit] status={status} rows={doc.get('rows')} "
              + " ".join(f"{k}={v.get(k, 0)}" for k in sa.VERDICTS)
              + f" elapsed={doc.get('elapsed_s')}s -> {out}")
        for m in doc.get("mismatches") or []:
            print(f"  MISMATCH row {m['row']} {m['master']} {m['bno']} {m['stock']}: "
                  f"excel {m['excel']} expected {m['expected']} source {m['source']} | {m['reason']}")
        for b in doc.get("unverified_branches") or []:
            print(f"  UNVERIFIED {b['bno']} {b['master']} ({b['rows']} rows): {b['reason']}")
        if doc.get("error"):
            print(f"  error: {doc['error']}")
        annotate(doc)
    except Exception as e:
        print(f"::warning title=來源比對出錯::{_esc(f'{type(e).__name__}: {e}')}")
    write_output(status)
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:      # always exit 0 (KeyboardInterrupt included)
        print(f"::warning title=來源比對出錯::{_esc(f'{type(e).__name__}: {e}')}")
    sys.exit(0)
