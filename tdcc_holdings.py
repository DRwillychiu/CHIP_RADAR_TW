"""
========================================================================
Module: tdcc_holdings.py  (v3.37.0)
集保結算所 (TDCC) 股權分散表 — 大戶/散戶持股結構追蹤

資料源 (已實證):
  URL: https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5
  格式: CSV (UTF-8 BOM), 6 欄: 資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
  Size: ~2.3MB (全市場每檔 17 列 × ~2000 檔)
  更新: 每週六上午 (公布上週五資料)
  保留: 官方僅保留當週 → 必須自己存歷史快照

持股分級 (15 級 + 16 差異調整 + 17 合計, 業界共識):
  1: 1-999股       (散戶最小)
  2: 1,000-5,000
  3: 5,001-10,000
  4: 10,001-15,000
  5: 15,001-20,000
  6: 20,001-30,000
  7: 30,001-40,000
  8: 40,001-50,000              ← 50 張以下 = 一般散戶
  9: 50,001-100,000             ← 中戶 (50-100 張)
  10: 100,001-200,000           ← 中大戶 (100-200 張)
  11: 200,001-400,000           ← 大戶 (200-400 張)
  12: 400,001-600,000           ← 400 張大戶
  13: 600,001-800,000
  14: 800,001-1,000,000
  15: 1,000,001 以上            ← 千張大戶 (mega holder)

聚合定義 (本模組):
  big400_pct    = sum(level 12-15)  比例 — 業界共識「400 張以上大戶」
  mega1000_pct  = sum(level 15)     比例 — 千張大戶 (機構/超大戶)
  retail_pct    = sum(level 1-8)    比例 — 散戶 (50 張以下)
  mid_pct       = sum(level 9-11)   比例 — 中戶 (50-400 張)

整合架構:
  - tdcc-weekly.yml workflow: 週六 11:00 TW 跑 main_fetch()
  - data/tdcc_holdings.json (主檔, ~500 檔精選 ~1MB)
  - data/tdcc_history/YYYYMMDD.json (每週快照供 vs_prev_week 比較)
  - crawler.py stage 6.5 讀 tdcc_holdings.json → inject per stock
========================================================================
"""
import csv
import io
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

import requests

TW_TZ = timezone(timedelta(hours=8))

TDCC_CSV_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"

# 大戶 / 散戶 / 中戶分級
BIG_HOLDER_LEVELS = {12, 13, 14, 15}    # ≥400,001 股 = ≥400 張
MEGA_HOLDER_LEVELS = {15}                # ≥1,000,001 股 = ≥1000 張
RETAIL_LEVELS = {1, 2, 3, 4, 5, 6, 7, 8}  # ≤50,000 股 = ≤50 張
MID_HOLDER_LEVELS = {9, 10, 11}          # 50,001-400,000 股 = 50-400 張

# 抓取設定
MAX_CSV_SIZE_MB = 50          # safe guard, TDCC 實際 ~2.3MB
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


# ════════════════════════════════════════════════════════════════════
#  Step 1: 抓 CSV (stream + size guard)
# ════════════════════════════════════════════════════════════════════

def fetch_tdcc_csv(url: str = TDCC_CSV_URL,
                    max_size_mb: int = MAX_CSV_SIZE_MB,
                    timeout: int = TIMEOUT_SECONDS) -> Optional[str]:
    """Stream 下載 TDCC CSV, size guard + retry.
    Returns: UTF-8 文字內容 或 None (失敗)."""
    max_bytes = max_size_mb * 1024 * 1024
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, stream=True, timeout=timeout,
                              headers={'User-Agent': 'Mozilla/5.0 (compatible; ChipRadar/3.37)'})
            r.raise_for_status()
            total = 0
            chunks = []
            for chunk in r.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    r.close()
                    raise ValueError(f"TDCC CSV 超過 {max_size_mb}MB 上限")
                chunks.append(chunk)
            r.close()
            content = b''.join(chunks)
            # UTF-8 BOM 處理
            if content.startswith(b'\xef\xbb\xbf'):
                content = content[3:]
            return content.decode('utf-8', errors='replace')
        except Exception as e:
            print(f"  ⚠️ TDCC fetch 第 {attempt+1}/{MAX_RETRIES} 次失敗: {e}",
                  file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                import time
                time.sleep(5 + attempt * 5)
    return None


# ════════════════════════════════════════════════════════════════════
#  Step 2: 解析 CSV → per-stock 聚合
# ════════════════════════════════════════════════════════════════════

def parse_csv_to_aggregates(csv_text: str) -> Tuple[Optional[str], Dict[str, Dict[str, Any]]]:
    """解析 CSV → {code: {effective_date, big400_pct, mega1000_pct, retail_pct,
                          mid_pct, total_holders, total_shares}}.

    每檔 17 列, 我們聚合 level 1-15 (16=差異調整, 17=合計, 略過)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    # buckets: per code → {level → {人數, 股數, 比例}}
    buckets: Dict[str, Dict[int, Dict[str, float]]] = {}
    effective_date = None
    for row in reader:
        code = (row.get('證券代號') or '').strip()
        if not code:
            continue
        try:
            level = int(row.get('持股分級') or 0)
        except (ValueError, TypeError):
            continue
        if level < 1 or level > 15:
            continue   # 略過 16 差異調整 / 17 合計
        try:
            holders = int(row.get('人數') or 0)
            shares = int(row.get('股數') or 0)
            ratio = float(row.get('占集保庫存數比例%') or 0)
        except (ValueError, TypeError):
            continue
        date_str = (row.get('資料日期') or '').strip()
        if not effective_date:
            effective_date = date_str
        buckets.setdefault(code, {})[level] = {
            'holders': holders, 'shares': shares, 'ratio': ratio,
        }

    aggregates: Dict[str, Dict[str, Any]] = {}
    for code, levels in buckets.items():
        big400 = sum(levels.get(L, {}).get('ratio', 0) for L in BIG_HOLDER_LEVELS)
        mega1000 = sum(levels.get(L, {}).get('ratio', 0) for L in MEGA_HOLDER_LEVELS)
        retail = sum(levels.get(L, {}).get('ratio', 0) for L in RETAIL_LEVELS)
        mid = sum(levels.get(L, {}).get('ratio', 0) for L in MID_HOLDER_LEVELS)
        total_holders = sum(lv.get('holders', 0) for lv in levels.values())
        total_shares = sum(lv.get('shares', 0) for lv in levels.values())
        aggregates[code] = {
            'effective_date': effective_date,
            'big400_pct': round(big400, 3),
            'mega1000_pct': round(mega1000, 3),
            'retail_pct': round(retail, 3),
            'mid_pct': round(mid, 3),
            'total_holders': total_holders,
            'total_shares': total_shares,
            'big400_holders': sum(levels.get(L, {}).get('holders', 0) for L in BIG_HOLDER_LEVELS),
        }
    return effective_date, aggregates


# ════════════════════════════════════════════════════════════════════
#  Step 3: 篩選 → 只存 watched + Top 200 熱門 (~500 檔)
# ════════════════════════════════════════════════════════════════════

def load_watched_codes(data_dir: str = 'data') -> Set[str]:
    """從最近的 latest.json (明文 metadata) + branches.py 推算 watched 股票.
    退化策略: 沒密碼讀不到加密內容, 用 stock_history.json 的 keys."""
    watched = set()
    # stock_history (明文) 含過去 30 天有交易的股票
    p = Path(data_dir) / 'stock_history.json'
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.load(f)
            for code in (d.get('stocks') or {}).keys():
                watched.add(str(code))
        except Exception:
            pass
    return watched


def select_codes_to_keep(aggregates: Dict[str, Dict[str, Any]],
                          watched: Set[str],
                          top_n_by_total_shares: int = 200) -> Set[str]:
    """選 watched 關聯 + 全市場 Top N 熱門股 (按總股數降冪)."""
    selected = set()
    # 1. 全部 watched
    for code in watched:
        if code in aggregates:
            selected.add(code)
    # 2. 全市場 Top N (按 total_shares)
    ranked = sorted(aggregates.items(),
                     key=lambda kv: -kv[1].get('total_shares', 0))
    for code, _ in ranked[:top_n_by_total_shares]:
        selected.add(code)
    return selected


# ════════════════════════════════════════════════════════════════════
#  Step 4: vs 上週 計算 — load 上一個 history snapshot
# ════════════════════════════════════════════════════════════════════

def load_prev_week_snapshot(data_dir: str = 'data',
                              current_date: Optional[str] = None
                              ) -> Optional[Dict[str, Dict[str, Any]]]:
    """讀 data/tdcc_history/ 最近一個非 current_date 的快照."""
    hdir = Path(data_dir) / 'tdcc_history'
    if not hdir.exists():
        return None
    files = sorted(hdir.glob('[0-9]' * 8 + '.json'), reverse=True)
    for f in files:
        if current_date and f.stem == current_date:
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                snap = json.load(fh)
            return snap.get('holdings') or {}
        except Exception:
            continue
    return None


def compute_vs_prev_week(current: Dict[str, Dict[str, Any]],
                          prev: Optional[Dict[str, Dict[str, Any]]]
                          ) -> Dict[str, Dict[str, Any]]:
    """加入 vs_prev_week 欄位 (delta_pp)."""
    if not prev:
        for code, d in current.items():
            d['vs_prev_week'] = None
        return current
    for code, d in current.items():
        p = prev.get(code) or {}
        if not p:
            d['vs_prev_week'] = None
            continue
        d['vs_prev_week'] = {
            'big400_delta_pp': round(d['big400_pct'] - p.get('big400_pct', 0), 3),
            'mega1000_delta_pp': round(d['mega1000_pct'] - p.get('mega1000_pct', 0), 3),
            'retail_delta_pp': round(d['retail_pct'] - p.get('retail_pct', 0), 3),
            'prev_effective_date': p.get('effective_date'),
        }
    return current


# ════════════════════════════════════════════════════════════════════
#  Step 5: 主流程 — fetch + parse + filter + diff + 寫檔
# ════════════════════════════════════════════════════════════════════

def main_fetch(data_dir: str = 'data',
                top_n_market: int = 200,
                force: bool = False) -> Optional[Dict[str, Any]]:
    """週六 workflow 主入口.

    Returns: 結果 dict 或 None (失敗)."""
    data_path = Path(data_dir)
    data_path.mkdir(exist_ok=True)
    hist_dir = data_path / 'tdcc_history'
    hist_dir.mkdir(exist_ok=True)

    # 1. fetch
    print("[TDCC] 抓取股權分散表 CSV...")
    csv_text = fetch_tdcc_csv()
    if not csv_text:
        print("[TDCC] ❌ CSV 抓取失敗")
        return None
    print(f"  ✓ CSV {len(csv_text)/1024:.1f} KB")

    # 2. parse
    effective_date, aggregates = parse_csv_to_aggregates(csv_text)
    if not aggregates:
        print("[TDCC] ❌ CSV 解析失敗 (無資料)")
        return None
    print(f"  ✓ 解析 {len(aggregates)} 檔, 資料日期 {effective_date}")

    # 3. 不要重複跑同一週 (除非 force)
    snap_file = hist_dir / f'{effective_date}.json'
    if snap_file.exists() and not force:
        print(f"  ⏭️ {effective_date} 快照已存在 (--force 可覆寫), 跳過")
        return None

    # 4. filter
    watched = load_watched_codes(data_dir)
    print(f"  ✓ watched {len(watched)} 檔 (from stock_history)")
    selected = select_codes_to_keep(aggregates, watched, top_n_market)
    filtered = {c: aggregates[c] for c in selected if c in aggregates}
    print(f"  ✓ 篩選後保留 {len(filtered)} 檔 (watched ∪ Top {top_n_market})")

    # 5. vs prev week
    prev = load_prev_week_snapshot(data_dir, current_date=effective_date)
    filtered = compute_vs_prev_week(filtered, prev)
    if prev:
        with_diff = sum(1 for d in filtered.values() if d.get('vs_prev_week'))
        print(f"  ✓ 對比上週: {with_diff} 檔有 delta")

    # 6. 寫主檔 + history snapshot
    main_file = data_path / 'tdcc_holdings.json'
    payload = {
        'fetched_at': now_tw().isoformat(),
        'effective_date': effective_date,
        'effective_week_iso': _iso_week_of(effective_date),
        'count': len(filtered),
        'method': 'tdcc_csv_opendata_id1-5',
        'caveat': '集保戶持股結構 (TDCC), 每週五為基準,本週六公布. big400=400張以上,mega1000=千張大戶.',
        'level_definitions': {
            'big_holder_levels': sorted(BIG_HOLDER_LEVELS),
            'mega_holder_levels': sorted(MEGA_HOLDER_LEVELS),
            'retail_levels': sorted(RETAIL_LEVELS),
            'mid_holder_levels': sorted(MID_HOLDER_LEVELS),
        },
        'holdings': filtered,
    }
    main_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding='utf-8')
    print(f"  ✓ → {main_file}")

    # history snapshot (純 holdings, 不重複 meta)
    snap_file.write_text(json.dumps(
        {'effective_date': effective_date, 'holdings': filtered},
        ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"  ✓ → {snap_file}")

    # 7. 簡易摘要
    big_movers = sorted(filtered.items(),
                          key=lambda kv: abs((kv[1].get('vs_prev_week') or {})
                                              .get('big400_delta_pp', 0)),
                          reverse=True)[:5]
    if big_movers and big_movers[0][1].get('vs_prev_week'):
        print("  Top 5 大戶比例變化:")
        for code, d in big_movers:
            vp = d.get('vs_prev_week') or {}
            delta = vp.get('big400_delta_pp', 0)
            if delta:
                print(f"    {code}: 400張大戶 {d['big400_pct']}% ({delta:+.2f}pp)")

    return payload


def _iso_week_of(date_str: str) -> Optional[str]:
    """20260612 → '2026-W24'"""
    try:
        dt = datetime.strptime(date_str, '%Y%m%d')
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (ValueError, TypeError):
        return None


# ════════════════════════════════════════════════════════════════════
#  Step 6: 給 crawler.py 用 — 載入 cache 並注入 per-stock dict
# ════════════════════════════════════════════════════════════════════

def load_holdings_cache(data_dir: str = 'data') -> Optional[Dict[str, Any]]:
    """daily-full crawler 讀 tdcc_holdings.json (週頻 cache, 不打網路)."""
    p = Path(data_dir) / 'tdcc_holdings.json'
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️ tdcc_holdings.json 讀取失敗: {e}", file=sys.stderr)
        return None


def inject_holdings_into_stocks(branches: List[Dict[str, Any]],
                                 cache: Dict[str, Any]) -> Dict[str, Any]:
    """注入 holdings 摘要到 branches[].buys/sells 各 stock dict.
    Returns: {'injected': N, 'metadata': {...}, 'movers': {...}} 給 crawler 組進 raw_output."""
    if not cache:
        return {'injected': 0}
    holdings = cache.get('holdings', {}) or {}
    if not holdings:
        return {'injected': 0}
    injected = 0
    for br in branches:
        for side in ('buys', 'sells'):
            for stock in (br.get(side) or []):
                code = str(stock.get('code') or '')
                h = holdings.get(code)
                if h:
                    stock['tdcc_holdings'] = {
                        'big400_pct': h.get('big400_pct'),
                        'mega1000_pct': h.get('mega1000_pct'),
                        'retail_pct': h.get('retail_pct'),
                        'vs_prev_week': h.get('vs_prev_week'),
                    }
                    injected += 1
    return {
        'injected': injected,
        'metadata': {
            'effective_date': cache.get('effective_date'),
            'effective_week': cache.get('effective_week_iso'),
            'fetched_at': cache.get('fetched_at'),
            'count': cache.get('count'),
            'caveat': cache.get('caveat'),
        },
        'movers': _compute_movers(holdings),
    }


def _compute_movers(holdings: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """大戶比例上升/下降 Top N (vs 上週)."""
    items = []
    for code, h in holdings.items():
        vp = h.get('vs_prev_week') or {}
        delta = vp.get('big400_delta_pp')
        if delta is None:
            continue
        items.append({
            'code': code,
            'big400_pct': h.get('big400_pct'),
            'big400_delta_pp': delta,
            'mega1000_pct': h.get('mega1000_pct'),
            'mega1000_delta_pp': vp.get('mega1000_delta_pp', 0),
            'retail_pct': h.get('retail_pct'),
            'retail_delta_pp': vp.get('retail_delta_pp', 0),
        })
    if not items:
        return None
    risers = sorted(items, key=lambda x: -x['big400_delta_pp'])[:20]
    fallers = sorted(items, key=lambda x: x['big400_delta_pp'])[:20]
    return {
        'big400_risers': risers,
        'big400_fallers': fallers,
    }


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='TDCC 集保股權分散表 fetcher')
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--top-market', type=int, default=200,
                         help='全市場 Top N 熱門股 (預設 200, 加上 watched 約 500 檔)')
    parser.add_argument('--force', action='store_true',
                         help='強制覆寫已存在的當週快照')
    args = parser.parse_args()
    r = main_fetch(args.data_dir, args.top_market, args.force)
    sys.exit(0 if r else 1)
