"""v3.31.6 archive_manager 測試"""
import os
import sys
import gzip
import json
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, '.')

from archive_manager import classify_age_days, plan_rotation, rotate, TW_TZ

all_pass = True
print("=" * 64)
print("  v3.31.6 archive_manager 測試")
print("=" * 64)

# 固定 now 為 2026-06-04 (避免每次跑結果不同)
NOW = datetime(2026, 6, 4, 12, 0, tzinfo=TW_TZ)


# ── 1. classify_age_days 基本 ──
print("\n1. classify_age_days: 今天 6/4 vs 各日期")
cases = [
    ('20260603.json',    1),   # 1 天前 (hot)
    ('20260530.json',    5),   # 5 天前 (hot, <7)
    ('20260520.json',   15),   # 15 天前 (warm, 7-60)
    ('20260301.json',   95),   # 95 天前 (cold, >60)
    ('20260301.json.gz', 95),
    ('invalid.json',  None),
]
ok = True
for fn, expected in cases:
    got = classify_age_days(fn, now=NOW)
    if got != expected:
        ok = False
        print(f"  ❌ {fn}: got {got}, expect {expected}")
print(f"  {'OK' if ok else 'FAIL'} 6 cases")
if not ok: all_pass = False


# ── 2. plan_rotation 規劃正確 ──
print("\n2. plan_rotation: hot=7d warm=60d → 規劃正確")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    # 建 4 個 daily.json: 1 天 / 8 天 / 30 天 / 90 天
    fixtures = [
        ('20260603.json', 1),    # hot, 不動
        ('20260526.json', 9),    # warm: 移
        ('20260505.json', 30),   # warm: 移
        ('20260305.json', 91),   # cold: 直接壓
    ]
    for fn, _age in fixtures:
        (d / fn).write_text('{"encrypted":true}', encoding='utf-8')

    actions = plan_rotation(d, hot_days=7, warm_days=60, now=NOW)
    move_count = sum(1 for _,_,a in actions if a == 'move')
    compress_count = sum(1 for _,_,a in actions if a == 'compress')
    ok = move_count == 2 and compress_count == 1
    print(f"  {'OK' if ok else 'FAIL'} move={move_count} (expect 2), compress={compress_count} (expect 1)")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


# ── 3. rotate dry-run 不動檔案 ──
print("\n3. rotate(dry_run=True): 不動實際檔案")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    f = d / '20260520.json'
    f.write_text('test', encoding='utf-8')
    stats = rotate(str(d), dry_run=True, now=NOW, verbose=False)
    ok = f.exists() and stats['moved'] == 0 and stats['compressed'] == 0 and stats['planned'] >= 1
    print(f"  {'OK' if ok else 'FAIL'} dry_run 後檔案還在, planned={stats['planned']}")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


# ── 4. rotate 真執行 move + compress ──
print("\n4. rotate 真執行: warm move + cold compress")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    # warm: 20 天前
    warm_file = d / '20260515.json'
    warm_file.write_text('{"warm":true}' * 200, encoding='utf-8')  # 多寫點看壓縮
    # cold: 90 天前
    cold_file = d / '20260306.json'
    cold_file.write_text('{"cold":true}' * 500, encoding='utf-8')

    stats = rotate(str(d), now=NOW, verbose=False)

    archive = d / 'archive'
    moved_ok = (archive / '20260515.json').exists() and not warm_file.exists()
    compressed_ok = (archive / '20260306.json.gz').exists() and not cold_file.exists()
    ok = moved_ok and compressed_ok and stats['moved'] == 1 and stats['compressed'] == 1
    print(f"  {'OK' if ok else 'FAIL'} warm move OK={moved_ok}, cold compress OK={compressed_ok}")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


# ── 5. compress 後內容可還原 (gzip 解開 = 原檔) ──
print("\n5. gzip 還原: archive/*.json.gz 可解回原內容")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    f = d / '20260305.json'
    original = '{"test":"中文 + emoji 🎯"}' * 50
    f.write_text(original, encoding='utf-8')

    rotate(str(d), now=NOW, verbose=False)
    gz_path = d / 'archive' / '20260305.json.gz'
    with gzip.open(gz_path, 'rt', encoding='utf-8') as fh:
        restored = fh.read()
    ok = restored == original
    print(f"  {'OK' if ok else 'FAIL'} 解壓後內容一致 (len={len(restored)})")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


# ── 6. warm 已在 archive/ 經 N 天後 → 自動 gzip ──
print("\n6. archive/*.json 經時間後 → 自動 gzip (warm → cold)")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    archive = d / 'archive'
    archive.mkdir()
    old_warm = archive / '20260305.json'   # 91 天前但已在 warm 區
    old_warm.write_text('old', encoding='utf-8')

    rotate(str(d), now=NOW, verbose=False)
    ok = (archive / '20260305.json.gz').exists() and not old_warm.exists()
    print(f"  {'OK' if ok else 'FAIL'} warm 區的 old json → gzipped")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


# ── 7. hot 區檔案不被動 ──
print("\n7. < hot_days 的檔案保留 data/ 不動")
tmp = tempfile.mkdtemp()
try:
    d = Path(tmp)
    f = d / '20260601.json'   # 3 天前
    f.write_text('hot', encoding='utf-8')
    rotate(str(d), now=NOW, verbose=False)
    ok = f.exists()
    print(f"  {'OK' if ok else 'FAIL'} hot 檔案還在原位")
    if not ok: all_pass = False
finally:
    shutil.rmtree(tmp)


print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
