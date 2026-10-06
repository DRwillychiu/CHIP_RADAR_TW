# -*- coding: utf-8 -*-
"""v3.80.9 一次性清理 — 從 stock_history.json 移除上櫃權證

背景 (2026-10-01 稽核):
  data/stock_history.json 已長到 ~30 MB, daily-full 一個月 commit ~100 次,
  .git 已 2.5 GB. 拆解 stocks:
    權證 (70xxxx~73xxxx, 認售尾碼 U)  15,618 筆  ~16.7 MB  ← 來自 TPEx 日收盤
    4 碼個股                            1,994 筆   ~6.4 MB
    00 開頭 ETF/ETN                       352 筆   ~1.2 MB
  權證在 quad_hit_log / master_contribution / multiday_backtest /
  daily_trading_signals / master_profiles 的引用次數 = 0, 從來沒被讀過.
  ETF 有被引用 (daily_trading_signals / master_profiles), 必須保留.

  src/fetchers/history.py 自 v3.80.9 起每次 update_history 都會
  prune_warrants() + 略過新權證, 本 script 只負責把現有檔案先清一次,
  並驗證清完後所有被引用的代號仍查得到.

用法:
  python scripts/prune_warrants_history.py --dry-run    # 只報告不寫入
  python scripts/prune_warrants_history.py              # 實際寫入 (自動備份)

備份: data/backup_v3809/stock_history_<時間>.json (gitignored, 不進 repo)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TW_TZ = timezone(timedelta(hours=8))
sys.path.insert(0, str(ROOT))

from src.fetchers.history import is_warrant_code, prune_warrants  # noqa: E402

DRY = '--dry-run' in sys.argv

# 會讀 stock_history 個股資料的下游輸出; 代號一律在 code / stock_code 欄位
REFERENCE_FILES = [
    'daily_trading_signals.json',
    'master_profiles.json',
    'quad_hit_log.json',
    'multiday_backtest.json',
]
CODE_KEYS = ('code', 'stock_code')


def collect_referenced_codes(data_dir: Path) -> dict[str, set[str]]:
    """回傳 {檔名: {被引用的個股代號}}. 檔案不存在 → 空集合."""
    out: dict[str, set[str]] = {}
    for fn in REFERENCE_FILES:
        codes: set[str] = set()
        p = data_dir / fn
        if p.exists():
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k in CODE_KEYS and isinstance(v, str) and v.strip():
                            codes.add(v.strip())
                        else:
                            walk(v)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)
            walk(json.loads(p.read_text(encoding='utf-8')))
        out[fn] = codes
    return out


def unresolved(refs: dict[str, set[str]], stocks: dict) -> dict[str, list[str]]:
    """被引用但 stocks 裡查不到的代號 {檔名: [代號]} (只列有缺的檔)."""
    return {fn: sorted(c for c in codes if c not in stocks)
            for fn, codes in refs.items() if any(c not in stocks for c in codes)}


def bucket(code: str) -> str:
    if is_warrant_code(code):
        return '權證'
    if len(code) == 4 and code.isdigit():
        return '4 碼個股'
    if code.startswith('00'):
        return 'ETF/ETN (00)'
    return '其他'


def summarize(stocks: dict) -> dict[str, tuple[int, int]]:
    """{分類: (筆數, bytes)} — bytes 以 indent=1 序列化估算, 與實際寫檔一致."""
    out: dict[str, list[int]] = {}
    for c, v in stocks.items():
        b = out.setdefault(bucket(c), [0, 0])
        b[0] += 1
        b[1] += len(json.dumps(v, ensure_ascii=False, indent=1).encode('utf-8'))
    return {k: (n, sz) for k, (n, sz) in out.items()}


def main() -> int:
    sh_path = DATA / 'stock_history.json'
    if not sh_path.exists():
        print('X stock_history.json 不存在'); return 1

    size_before = sh_path.stat().st_size
    sh = json.loads(sh_path.read_text(encoding='utf-8'))
    stocks = sh.get('stocks') or {}

    print(f'stock_history.json  {size_before / 1e6:.1f} MB, stocks {len(stocks):,} 筆')
    for k, (n, sz) in sorted(summarize(stocks).items(), key=lambda kv: -kv[1][1]):
        print(f'  {k:<14} {n:>7,} 筆  {sz / 1e6:6.2f} MB')

    refs = collect_referenced_codes(DATA)
    print('\n[引用] 下游檔案中的個股代號:')
    for fn, codes in refs.items():
        w = sorted(c for c in codes if is_warrant_code(c))
        print(f'  {fn:<28} {len(codes):>4} 檔  (其中權證 {len(w)})' + (f'  {w[:5]}' if w else ''))
    if any(is_warrant_code(c) for codes in refs.values() for c in codes):
        print('X 有下游檔案引用權證 — 前提不成立, 中止')
        return 1

    before_missing = unresolved(refs, stocks)

    removed = prune_warrants(sh)
    after_missing = unresolved(refs, sh['stocks'])
    print(f'\n[清理] 移除權證 {removed:,} 筆 → stocks 剩 {len(sh["stocks"]):,} 筆')

    # 驗證: 清理不可讓任何原本查得到的代號變成查不到
    newly = {fn: sorted(set(cs) - set(before_missing.get(fn, [])))
             for fn, cs in after_missing.items()}
    newly = {fn: cs for fn, cs in newly.items() if cs}
    if newly:
        print(f'X 清理後有原本查得到的代號消失: {newly} — 中止, 未寫入')
        return 1
    if before_missing:
        print('  (清理前就查不到, 與本次無關:)')
        for fn, cs in before_missing.items():
            print(f'    {fn}: {cs}')
    print('  ✓ 所有被引用代號的可查性與清理前一致')

    if DRY:
        print('\n(--dry-run: 未寫入任何檔案)')
        return 0

    # ── 備份 + 寫入 ──
    stamp = datetime.now(TW_TZ).strftime('%Y%m%d_%H%M%S')
    bak_dir = DATA / 'backup_v3809'
    bak_dir.mkdir(exist_ok=True)
    bak = bak_dir / f'stock_history_{stamp}.json'
    shutil.copy2(sh_path, bak)
    print(f'\n備份 → {bak}')

    sh['warrants_pruned_at'] = datetime.now(TW_TZ).strftime('%Y-%m-%dT%H:%M:%S+08:00')
    # indent=1 與 update_history 寫法一致, 下次每日流程重寫時不會產生整檔格式 diff
    with open(sh_path, 'w', encoding='utf-8') as f:
        json.dump(sh, f, ensure_ascii=False, indent=1)

    # ── 寫入後從磁碟重讀再驗一次 ──
    re_sh = json.loads(sh_path.read_text(encoding='utf-8'))
    left = [c for c in re_sh['stocks'] if is_warrant_code(c)]
    miss = unresolved(collect_referenced_codes(DATA), re_sh['stocks'])
    regress = {fn: sorted(set(cs) - set(before_missing.get(fn, []))) for fn, cs in miss.items()}
    regress = {fn: cs for fn, cs in regress.items() if cs}
    if left or regress:
        print(f'X 寫入後驗證失敗: 殘留權證 {len(left)} / 消失代號 {regress} — 請由備份還原')
        return 1
    size_after = sh_path.stat().st_size
    print(f'✅ 寫入 {sh_path.name}: {size_before / 1e6:.1f} MB → {size_after / 1e6:.1f} MB '
          f'(-{(1 - size_after / size_before) * 100:.0f}%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
