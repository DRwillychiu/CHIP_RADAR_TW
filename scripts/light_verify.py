"""v3.80.31 light verification for the late schedule re-runs (owner 2026-10-08).

The schedule re-runs (GitHub cron, really 02:00-06:00) used to repeat the
whole crawl: ~264 Fubon requests (crawler + audit) and ~20 min each, 3 times
a night, although the punctual 21:17 / 22:37 rounds had already stored the
day. Now a schedule run first checks the committed state:

  eligible = mail_rounds.json is for this session, its last round's source
             audit was 'ok', and the last crawl of that day had 0 failed
             branches (crawl_timing.json)
  eligible -> audit the committed latest.xlsx against the Fubon pages again
              (~100 requests, ~2 min). All rows match -> verdict=verified and
              the crawl job is skipped (nothing committed, no mail).
  otherwise, or any mismatch / error -> verdict=full: the crawl job runs
              exactly as before (the re-run is still the safety net).

Writes verdict=verified|full and reason=... to $GITHUB_OUTPUT; always exit 0.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def eligibility(session, rounds_doc, timing_doc):
    """-> (eligible, reason). Pure: committed state only, no network."""
    if not session:
        return False, "no session date from the gate"
    if rounds_doc.get("trade_date") != session:
        return False, f"no stored round for {session} (have {rounds_doc.get('trade_date')})"
    last = (rounds_doc.get("rounds") or [None])[-1] or {}
    if last.get("audit") != "ok":
        return False, f"last round's source audit was {last.get('audit')!r}, not 'ok'"
    runs = [r for r in (timing_doc.get("runs") or []) if r.get("trade_date") == session]
    crawl = (runs[-1].get("crawl") if runs else None) or {}
    if not runs or "fail" not in crawl:
        return False, "no crawl outcome stored for that day"
    if crawl["fail"]:
        return False, f"last crawl had {crawl['fail']} failed branches"
    return True, f"round {last.get('round')} ({last.get('rows')} rows) audited ok, 0 failed branches"


def main(argv=None, audit=None, log=print):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="")
    ap.add_argument("--data", default=str(DATA))
    a = ap.parse_args(argv)
    data = Path(a.data)
    verdict, reason = "full", ""
    try:
        ok, reason = eligibility(a.session, _load(data / "reports" / "mail_rounds.json"),
                                 _load(data / "crawl_timing.json"))
        if ok:
            if audit is None:
                from src.audit.source_audit import run_audit as audit
            doc = audit(data / "reports" / "latest.xlsx")
            if doc.get("trade_date") != a.session:
                reason = f"Excel day sheet is {doc.get('trade_date')}, not {a.session}"
            elif doc.get("status") != "ok":
                reason = f"re-audit status {doc.get('status')} -> full crawl"
            else:
                verdict = "verified"
                reason = f"{doc.get('rows')} rows still match the Fubon pages; {reason}"
    except Exception as e:      # any doubt -> the full crawl runs
        verdict, reason = "full", f"light check failed ({type(e).__name__}: {e})"
    title = "Light verification OK" if verdict == "verified" else "Light verification -> full crawl"
    log(f"::notice title={title}::{reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict}\nreason={reason}\n")
    return verdict


if __name__ == "__main__":
    main()
    sys.exit(0)
