"""v3.86.0 build data/daily_summary.json (今日總整理, the site's first page).

Runs in daily-full right after "Refresh attstock disposal", so the disposal
lane uses tonight's list. Reads the last W+2 day files (hot + archive),
data/stock_history.json, data/disposal_attstock.json, data/stock_categories.json.
Writes the same encrypted envelope as the day files, and only when the content
changed (re-runs on the same night add no git history).

  python scripts/build_daily_summary.py                      # nightly (CHIP_RADAR_PASSWORD set)
  python scripts/build_daily_summary.py --preview-dir DIR    # local preview copy, plaintext envelope
"""
import argparse, datetime as dt, gzip, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analyzers.daily_summary import W, build_summary          # noqa: E402
from src.pipelines.crawler_output import encrypt_data, decrypt_data, PBKDF2_ITERATIONS  # noqa: E402
from src.core.quarantine import filter_day                     # noqa: E402

OUT_NAME = "daily_summary.json"


def _read(p):
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(p.read_text(encoding="utf-8"))


def load_days(data_dir, password, n):
    files = list(data_dir.glob("[0-9]" * 8 + ".json"))
    arc = data_dir / "archive"
    if arc.exists():
        files += list(arc.glob("[0-9]" * 8 + ".json")) + list(arc.glob("[0-9]" * 8 + ".json.gz"))
    by_date = {}
    for f in files:
        by_date.setdefault(f.name[:8], f)          # hot copy wins over archive
    days = []
    for d in sorted(by_date)[-n:]:
        env = _read(by_date[d])
        raw = env.get("data")
        if env.get("encrypted"):
            raw = decrypt_data(raw, password, env.get("iterations"))
        data = json.loads(raw) if isinstance(raw, str) else raw
        days.append({"date": d, "data": filter_day(data, d)})   # v3.80.3: skip quarantined branch-days
    return days


def _json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(data_dir, password):
    days = load_days(data_dir, password, W + 2)
    cats = (_json(data_dir / "stock_categories.json").get("classifications") or {})
    official = {c: v.get("name") for c, v in cats.items() if isinstance(v, dict) and v.get("name")}
    return build_summary(days, _json(data_dir / "stock_history.json"),
                         _json(data_dir / "disposal_attstock.json"), official), days


def _same_as_stored(path, plaintext, password):
    try:
        env = json.loads(path.read_text(encoding="utf-8"))
        old = decrypt_data(env["data"], password, env.get("iterations")) if env.get("encrypted") else env.get("data")
        return old == plaintext
    except Exception:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--preview-dir", help="also write a plaintext envelope here (local preview only)")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir)
    password = os.environ.get("CHIP_RADAR_PASSWORD", "")
    if not password:
        print("[今日總整理] CHIP_RADAR_PASSWORD not set - skipped")
        return 0
    summary, days = build(data_dir, password)
    plaintext = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    k = summary["kpis"]
    print(f"[今日總整理] {summary['date']} 用 {len(days)} 天 | 強籌 {k['strong_count']} 檔 (昨 {k['strong_prev']}) | "
          f"本土 {k['domestic_net_yi']} 億 / 外資 {k['foreign_net_yi']} 億 | 明日恐處置 {k['disposal_pending']}")
    if a.preview_dir:
        pv = Path(a.preview_dir) / OUT_NAME
        pv.write_text(json.dumps({"encrypted": True, "trade_date": summary["date"], "data": plaintext},
                                 ensure_ascii=False), encoding="utf-8")
        print(f"  preview copy -> {pv}")
        return 0
    out = data_dir / OUT_NAME
    if _same_as_stored(out, plaintext, password):
        print("  unchanged - not rewritten")
        return 0
    env = {
        "encrypted": True, "algorithm": "AES-256-GCM", "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS, "trade_date": summary["date"],
        "crawled_at": days[-1]["data"].get("crawled_at"),
        "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "data": encrypt_data(plaintext, password),
    }
    out.write_text(json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
