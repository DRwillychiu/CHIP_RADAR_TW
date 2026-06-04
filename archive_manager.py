"""
========================================================================
Module: archive_manager.py  (v3.31.6 新增 — Phase 1.1)
功能: daily.json 分層 archive (hot / warm / cold)

使用者 6/1 選 Q3=A 分層策略:
  hot  (< 7 天)      → 留 data/*.json 原位 (latest crawler 抓取期間)
  warm (7-60 天)     → 移到 data/archive/*.json (子目錄, 未壓縮)
  cold (>= 60 天)    → 移到 data/archive/*.json.gz (gzip level 9)

每天 daily-full 跑完 rotate 一次:
  - 7 天前的 daily.json 自動 move 進 archive/
  - 60 天前的 archive/*.json 自動 gzip
  - latest.json / stock_history.json 等不動 (只動 YYYYMMDD.json)

CLI:
  python archive_manager.py --dry-run         # 預覽計畫不執行
  python archive_manager.py                   # 真跑
  python archive_manager.py --hot-days 14 --warm-days 90   # 自訂閾值

archive 後仍可解密還原: gzip.open() + crawler.decrypt_data() 即可讀回。
========================================================================
"""
import gzip
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List

TW_TZ = timezone(timedelta(hours=8))

DATE_PATTERN_LEN = 8   # YYYYMMDD


def classify_age_days(filename: str, now: Optional[datetime] = None) -> Optional[int]:
    """從 YYYYMMDD.json / YYYYMMDD.json.gz 檔名算今天距離資料日期幾天.
    回傳 None 若檔名格式不符。"""
    if now is None:
        now = datetime.now(TW_TZ)
    # 移除 .json.gz / .json
    stem = filename
    for suf in ('.json.gz', '.json'):
        if stem.endswith(suf):
            stem = stem[:-len(suf)]
            break
    if len(stem) != DATE_PATTERN_LEN or not stem.isdigit():
        return None
    try:
        d = datetime.strptime(stem, '%Y%m%d').replace(tzinfo=TW_TZ)
        return (now - d).days
    except ValueError:
        return None


def plan_rotation(data_dir: Path, hot_days: int, warm_days: int,
                   now: Optional[datetime] = None) -> List[Tuple[Path, Path, str]]:
    """規劃 (不執行). 回傳 list of (src, dst, action) action ∈ {move, compress}."""
    data_dir = Path(data_dir)
    archive_dir = data_dir / 'archive'
    actions: List[Tuple[Path, Path, str]] = []

    # 1. data/*.json (hot 區) → 看 age 是否超過 hot_days
    for f in sorted(data_dir.glob('[0-9]' * DATE_PATTERN_LEN + '.json')):
        age = classify_age_days(f.name, now)
        if age is None:
            continue
        if age >= warm_days:
            # 跳過 warm 直接進 cold (極舊資料一次性壓)
            target = archive_dir / (f.name + '.gz')
            actions.append((f, target, 'compress'))
        elif age >= hot_days:
            # warm: 移到 archive/
            target = archive_dir / f.name
            actions.append((f, target, 'move'))

    # 2. data/archive/*.json (warm) → 看 age 是否超過 warm_days
    if archive_dir.exists():
        for f in sorted(archive_dir.glob('[0-9]' * DATE_PATTERN_LEN + '.json')):
            age = classify_age_days(f.name, now)
            if age is None:
                continue
            if age >= warm_days:
                target = f.with_name(f.name + '.gz')
                actions.append((f, target, 'compress'))

    return actions


def _do_compress(src: Path, dst: Path) -> int:
    """gzip 壓縮 + 刪原檔. 回傳 dst 大小."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, 'rb') as fi, gzip.open(dst, 'wb', compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)
    src.unlink()
    return dst.stat().st_size


def _do_move(src: Path, dst: Path) -> None:
    """檔案移動 (保留 git history 用 rename)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)


def rotate(data_dir: str = 'data', hot_days: int = 7, warm_days: int = 60,
           dry_run: bool = False, verbose: bool = True,
           now: Optional[datetime] = None) -> dict:
    """主入口 — 掃 data/ + data/archive/ 按 age 移動 / 壓縮."""
    actions = plan_rotation(Path(data_dir), hot_days, warm_days, now)

    if not actions:
        if verbose:
            print(f"[archive] nothing to rotate (hot<{hot_days}d, warm<{warm_days}d)")
        return {'moved': 0, 'compressed': 0, 'planned': 0}

    if dry_run:
        if verbose:
            print(f"[archive] DRY RUN — 計畫 {len(actions)} 個動作:")
            for src, dst, act in actions:
                rel_dst = dst.relative_to(Path(data_dir))
                print(f"  {act:10s} {src.name:20s} → {rel_dst}")
        return {'moved': 0, 'compressed': 0, 'planned': len(actions)}

    stats = {'moved': 0, 'compressed': 0, 'failed': 0,
             'bytes_compressed_in': 0, 'bytes_compressed_out': 0}
    for src, dst, act in actions:
        try:
            if act == 'compress':
                size_in = src.stat().st_size
                size_out = _do_compress(src, dst)
                stats['bytes_compressed_in'] += size_in
                stats['bytes_compressed_out'] += size_out
                stats['compressed'] += 1
                if verbose:
                    ratio = (1 - size_out / size_in) * 100 if size_in else 0
                    print(f"  ✓ compress {src.name} → {dst.name} "
                          f"({size_in/1024:.0f}KB → {size_out/1024:.0f}KB, -{ratio:.0f}%)")
            elif act == 'move':
                _do_move(src, dst)
                stats['moved'] += 1
                if verbose:
                    print(f"  ✓ move     {src.name} → archive/")
        except Exception as e:
            stats['failed'] += 1
            if verbose:
                print(f"  ❌ {act} {src.name} 失敗: {type(e).__name__}: {e}")

    if verbose:
        in_kb = stats['bytes_compressed_in'] / 1024
        out_kb = stats['bytes_compressed_out'] / 1024
        saved = in_kb - out_kb
        print(f"[archive] moved={stats['moved']} compressed={stats['compressed']} "
              f"failed={stats['failed']}")
        if saved > 0:
            print(f"          gzip 省下 {saved/1024:.1f} MB "
                  f"({in_kb/1024:.1f} → {out_kb/1024:.1f} MB)")

    return stats


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description='v3.31.6 daily.json 分層 archive')
    p.add_argument('--data-dir', default='data')
    p.add_argument('--hot-days', type=int, default=7,
                   help='< N 天保留在 data/ (預設 7)')
    p.add_argument('--warm-days', type=int, default=60,
                   help='>= N 天 gzip (預設 60)')
    p.add_argument('--dry-run', action='store_true', help='只規劃不執行')
    args = p.parse_args()

    rotate(args.data_dir, args.hot_days, args.warm_days, args.dry_run)


if __name__ == '__main__':
    main()
