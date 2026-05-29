"""
========================================================================
Module: histock_branch_audit.py  (v3.30.2 新增)
功能：個股 × 分點 buy_lot / buy_amt 雙向 cross-check
      用 histock by-stock view 反向比對我們的 by-branch 抓取結果

背景：
  TWSE 提供兩個視角,but by-stock view 有 CAPTCHA 鎖死,
  我們的 by-branch 抓取沒第二源可比 (參見 ARCHITECTURE.md §6.1)。
  histock 是 scrape TWSE 後重新呈現的第三方,可作 by-stock cross-check。

驗證邏輯:
  1. buy_lot (張數) 直接比對:差異 > 5% warning, > 20% error
  2. buy_amt (金額) 反推比對:implied_amt(仟元) = buy_lot × avg_price (our buy_amt 單位是仟元)
     差異 > 10% warning, > 30% error (均價是近似,容忍寬一點)

Sample 策略:
  動態挑高關注個股 — 漲停 + sniper master 買的 + 共買榜 Top + 高金額。
  預設 cap 50 檔,1 小時 hard time budget。

Rate Limit:
  每 request 4-6 sec + ±1 sec jitter (用戶明示「適當 delay」)
  50 檔 × ~5 sec ≈ 4-5 min 跑完,對 histock server 幾乎無感。

輸出:
  data/histock_audit.json:
  {
    "verdict": "PASS|WARN|FAIL",
    "trade_date": "2026/05/26",
    "audited_at": "2026-05-26T22:30:00+08:00",
    "stats": {"stocks_audited": 50, "branches_compared": 142, "mismatches": 3},
    "mismatches": [...],
    "summary": "..."
  }

CLI:
  python histock_branch_audit.py                     # default 50 檔
  python histock_branch_audit.py --max-stocks 10     # 限制 10 檔
  python histock_branch_audit.py --stock-code 2330   # 單檔 debug
  python histock_branch_audit.py --dry-run           # 只列 sample 不抓
========================================================================
"""
import re
import sys
import time
import json
import random
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests

TW_TZ = timezone(timedelta(hours=8))

HISTOCK_BRANCH_URL = "https://histock.tw/stock/branch.aspx?no={code}"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
}

# === 預設參數 (用戶明示) ===
DEFAULT_DELAY_RANGE = (4, 6)     # base sec
DEFAULT_JITTER = 1                # ±sec
DEFAULT_MAX_STOCKS = 50
DEFAULT_TIME_BUDGET_SEC = 3600    # 1 小時 hard cap

# Tolerance
BUY_LOT_WARN_PCT = 5.0
BUY_LOT_ERROR_PCT = 20.0
BUY_AMT_WARN_PCT = 10.0   # 均價是近似,容忍寬一點
BUY_AMT_ERROR_PCT = 30.0

# Sniper masters (v3.26 SNIPER_STYLES)
SNIPER_MASTERS = {'蔣承翰', '迷你哥', 'Tradow', '巨人傑'}


# ════════════════════════════════════════════════════════════════════
#  histock 抓取 + parser
# ════════════════════════════════════════════════════════════════════

def fetch_histock_branch(stock_code: str, timeout: int = 15,
                         max_retries: int = 2) -> Optional[Dict[str, Any]]:
    """
    抓 histock 個股分點頁面.

    Returns:
        {
            'stock_code': '2330',
            'date': '2026/05/26',
            'sells': [{'bno':'1480','name':'元大','buy_lot':637,'sell_lot':2891,'net':-2254,'avg_price':2286.39}, ...],
            'buys':  [{'bno':'9A9g','name':'永豐金-內湖','buy_lot':550,'sell_lot':25,'net':524,'avg_price':2291.96}, ...]
        }
        或 None (失敗)
    """
    url = HISTOCK_BRANCH_URL.format(code=stock_code)
    html = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                html = resp.text
                break
            else:
                print(f"    ⚠️ {stock_code} 第 {attempt+1}/{max_retries} 次: HTTP {resp.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5 + attempt * 3)
        except Exception as e:
            print(f"    ⚠️ {stock_code} 第 {attempt+1}/{max_retries} 次失敗: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)

    if html is None:
        return None

    return parse_histock_table(html, stock_code)


def parse_histock_table(html: str, stock_code: str = '') -> Optional[Dict[str, Any]]:
    """解析 histock branch HTML"""
    # 找日期 (前一日 YYYY/MM/DD 後一日)
    date_match = re.search(r'(\d{4}/\d{2}/\d{2})', html)
    trade_date = date_match.group(1) if date_match else ''

    # 找 table (class="tb-stock tbChip ...")
    table_match = re.search(
        r'<table class="tb-stock tbChip[^"]*"[^>]*>(.*?)</table>',
        html, re.DOTALL
    )
    if not table_match:
        return None
    table_html = table_match.group(1)

    # 每個 <tr> 10 個 <td>:賣超側 (5) + 買超側 (5)
    # td[0] sell-bno-name, td[1] buy_lot, td[2] sell_lot, td[3] net (-), td[4] avg
    # td[5] buy-bno-name,  td[6] buy_lot, td[7] sell_lot, td[8] net (+), td[9] avg
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    bno_name_pattern = re.compile(
        r'<a href="/stock/brokertrace\.aspx\?bno=([^&]+)&no=[^"]+"[^>]*>([^<]+)</a>'
    )
    td_text_pattern = re.compile(r'<td[^>]*>([^<]*)</td>')

    sells, buys = [], []

    for tr in tr_pattern.findall(table_html):
        # 找 2 個 <a> tag(賣方 + 買方)
        anchors = bno_name_pattern.findall(tr)
        if len(anchors) != 2:
            continue  # 跳過 header / 異常 row

        # 抽所有 <td> 純文字
        tds_text = td_text_pattern.findall(tr)
        # 但 anchors 在 td 內,所以原始 td 順序需用全 tag pattern
        td_full = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
        if len(td_full) != 10:
            continue

        try:
            def _num(s: str) -> float:
                s = re.sub(r'<[^>]+>', '', s).strip().replace(',', '')
                if not s or s == '-':
                    return 0.0
                return float(s)

            def _int(s: str) -> int:
                return int(_num(s))

            # 賣超側
            sells.append({
                'bno': anchors[0][0],
                'name': anchors[0][1].strip(),
                'buy_lot': _int(td_full[1]),
                'sell_lot': _int(td_full[2]),
                'net': _int(td_full[3]),
                'avg_price': _num(td_full[4]),
            })

            # 買超側
            buys.append({
                'bno': anchors[1][0],
                'name': anchors[1][1].strip(),
                'buy_lot': _int(td_full[6]),
                'sell_lot': _int(td_full[7]),
                'net': _int(td_full[8]),
                'avg_price': _num(td_full[9]),
            })
        except (ValueError, IndexError) as e:
            print(f"    ⚠️ {stock_code} row 解析失敗: {e}")
            continue

    if not sells and not buys:
        return None

    return {
        'stock_code': stock_code,
        'date': trade_date,
        'sells': sells,
        'buys': buys,
    }


# ════════════════════════════════════════════════════════════════════
#  Sample list 動態建構
# ════════════════════════════════════════════════════════════════════

def build_sample_list(latest_data: Dict[str, Any],
                      max_stocks: int = DEFAULT_MAX_STOCKS,
                      hot_amt_threshold: int = 50_000_000) -> List[str]:
    """
    從 latest.json 動態挑 sample:
      Priority 1: 漲停股 (limit_up_summary.limit_up_codes)
      Priority 2: Sniper master 買的個股 (蔣承翰/迷你哥/Tradow/巨人傑)
      Priority 3: 共買榜 Top 5
      Priority 4: 高金額個股 (buy_amt > 5000 萬)
    去重 + cap.
    """
    sample = []  # 用 list 保 priority 順序
    seen = set()

    def _add(code):
        if code and code not in seen and re.match(r'^\d{4,6}[A-Z]?$', code):
            seen.add(code)
            sample.append(code)

    # P1: 漲停股
    lu = latest_data.get('limit_up_summary', {})
    for c in lu.get('limit_up_codes', []):
        _add(c)
    # fallback:limit_up_summary 結構可能不同
    for entry in lu.get('limit_up_stocks', []):
        if isinstance(entry, dict):
            _add(entry.get('code'))

    # P2: Sniper master 買的個股
    for br in latest_data.get('branches', []):
        if br.get('master') in SNIPER_MASTERS:
            for s in br.get('buys', [])[:5]:
                _add(s.get('code'))

    # P3: 共買榜 Top 5
    cobuy = latest_data.get('co_buy_ranking', latest_data.get('co_buy_stocks', []))
    for item in cobuy[:5]:
        if isinstance(item, dict):
            _add(item.get('code'))

    # P4: 高金額
    for br in latest_data.get('branches', []):
        for s in br.get('buys', []):
            if s.get('buy_amt', 0) > hot_amt_threshold:
                _add(s.get('code'))
            if len(sample) >= max_stocks:
                break
        if len(sample) >= max_stocks:
            break

    return sample[:max_stocks]


# ════════════════════════════════════════════════════════════════════
#  Cross-check 邏輯
# ════════════════════════════════════════════════════════════════════

def cross_check_stock(stock_code: str,
                      our_branches: List[Dict[str, Any]],
                      histock_data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    比對單一個股.

    Args:
        stock_code: 個股代碼
        our_branches: 我們抓到的這檔個股對應的分點清單,每筆有
                      {branch_code, buy_lot, buy_amt, sell_lot, sell_amt}
        histock_data: parse_histock_table 回傳結構

    Returns:
        (verdict, mismatches)
        verdict: PASS / WARN / FAIL
        mismatches: list of dict
    """
    mismatches = []

    # 建 histock lookup: bno -> entry
    histock_lookup = {}
    for entry in histock_data.get('buys', []) + histock_data.get('sells', []):
        histock_lookup[entry['bno']] = entry

    for our_br in our_branches:
        bno = our_br.get('branch_code') or our_br.get('code')
        if not bno or bno not in histock_lookup:
            continue  # histock 沒這分點,跳

        hi = histock_lookup[bno]
        our_buy_lot = our_br.get('buy_lot', 0) or 0
        our_buy_amt = our_br.get('buy_amt', 0) or 0
        hi_buy_lot = hi['buy_lot']
        hi_avg = hi['avg_price']

        # === Check 1: buy_lot 直接比對 ===
        if hi_buy_lot > 0 or our_buy_lot > 0:
            denom = max(hi_buy_lot, our_buy_lot, 1)
            diff = abs(our_buy_lot - hi_buy_lot)
            rel = (diff / denom) * 100
            if rel > BUY_LOT_WARN_PCT:
                severity = 'error' if rel > BUY_LOT_ERROR_PCT else 'warning'
                mismatches.append({
                    'stock': stock_code,
                    'branch_code': bno,
                    'branch_name': hi.get('name', ''),
                    'field': 'buy_lot',
                    'ours': our_buy_lot,
                    'histock': hi_buy_lot,
                    'diff': diff,
                    'rel_diff_pct': round(rel, 2),
                    'severity': severity,
                })

        # === Check 2: buy_amt 反推比對 ===
        # ⚠️ 單位: our buy_amt 是「仟元」(crawler convention, 見 excel_report L331/L406).
        #   總金額(元) = 張數 × 1000股/張 × 均價(元/股)
        #   仟元 = 元 / 1000 = 張數 × 均價  (1000股/張 與 1000元/仟元 相消)
        #   故 implied(仟元) = hi_buy_lot × hi_avg, 不可再 × 1000 (v3.30.2 bug, v3.30.6 修)
        if hi_buy_lot > 0 and hi_avg > 0:
            implied_amt = hi_buy_lot * hi_avg
            if our_buy_amt > 0 or implied_amt > 0:
                denom = max(implied_amt, our_buy_amt, 1)
                diff = abs(our_buy_amt - implied_amt)
                rel = (diff / denom) * 100
                if rel > BUY_AMT_WARN_PCT:
                    severity = 'error' if rel > BUY_AMT_ERROR_PCT else 'warning'
                    mismatches.append({
                        'stock': stock_code,
                        'branch_code': bno,
                        'branch_name': hi.get('name', ''),
                        'field': 'buy_amt',
                        'ours': our_buy_amt,
                        'histock_implied': round(implied_amt),
                        'avg_price': hi_avg,
                        'diff': round(diff),
                        'rel_diff_pct': round(rel, 2),
                        'severity': severity,
                    })

    if any(m['severity'] == 'error' for m in mismatches):
        verdict = 'FAIL'
    elif mismatches:
        verdict = 'WARN'
    else:
        verdict = 'PASS'

    return verdict, mismatches


# ════════════════════════════════════════════════════════════════════
#  從 latest.json 抽 our_branches by stock
# ════════════════════════════════════════════════════════════════════

def build_our_branches_for_stock(latest_data: Dict[str, Any],
                                  stock_code: str) -> List[Dict[str, Any]]:
    """
    從 latest.json 抽某檔個股對應的所有分點交易 (反向 view).
    Returns: [{branch_code, branch_name, buy_lot, buy_amt, sell_lot, sell_amt}, ...]
    """
    result = []
    for br in latest_data.get('branches', []):
        bno = br.get('code')
        name = br.get('name', '')
        for s in br.get('buys', []) + br.get('sells', []):
            if s.get('code') == stock_code:
                result.append({
                    'branch_code': bno,
                    'branch_name': name,
                    'buy_lot': s.get('buy_lot', 0),
                    'buy_amt': s.get('buy_amt', 0),
                    'sell_lot': s.get('sell_lot', 0),
                    'sell_amt': s.get('sell_amt', 0),
                })
                break  # 同 branch 內同股只取一次
    return result


# ════════════════════════════════════════════════════════════════════
#  主跑迴圈
# ════════════════════════════════════════════════════════════════════

def now_tw():
    return datetime.now(TW_TZ)


def run_audit(latest_data: Dict[str, Any],
              max_stocks: int = DEFAULT_MAX_STOCKS,
              delay_range: Tuple[int, int] = DEFAULT_DELAY_RANGE,
              jitter: float = DEFAULT_JITTER,
              time_budget_sec: int = DEFAULT_TIME_BUDGET_SEC,
              dry_run: bool = False,
              stock_filter: Optional[str] = None,
              verbose: bool = True) -> Dict[str, Any]:
    """
    主跑函式.

    Args:
        latest_data: 解密後的 latest.json dict
        max_stocks: 最多 audit 多少個股
        delay_range: (min, max) sec per request
        jitter: ±sec random jitter
        time_budget_sec: 總時間預算 (秒),超過 hard stop
        dry_run: 只列 sample,不發 request
        stock_filter: 只測單一個股 (debug 用)
        verbose: 印 progress

    Returns: audit result dict
    """
    start_time = time.time()

    # 1. 建 sample list
    if stock_filter:
        sample = [stock_filter]
    else:
        sample = build_sample_list(latest_data, max_stocks=max_stocks)

    if verbose:
        print(f"[Histock Audit] Sample {len(sample)} 檔: {sample[:20]}{'...' if len(sample) > 20 else ''}")

    if dry_run:
        return {
            'verdict': 'DRY_RUN',
            'audited_at': now_tw().isoformat(),
            'sample_size': len(sample),
            'sample': sample,
        }

    # 2. 對每檔 fetch + cross-check
    all_mismatches = []
    audited_count = 0
    skipped_count = 0
    failed_fetch = []
    total_branches_compared = 0

    for i, stock_code in enumerate(sample, 1):
        # Time budget check
        elapsed = time.time() - start_time
        if elapsed > time_budget_sec:
            if verbose:
                print(f"[Histock Audit] ⏰ 時間預算用完 ({elapsed:.0f}s > {time_budget_sec}s),停止")
            break

        if verbose:
            print(f"[{i}/{len(sample)}] {stock_code} fetching... (elapsed {elapsed:.0f}s)", end=' ', flush=True)

        # fetch
        histock_data = fetch_histock_branch(stock_code)
        if histock_data is None:
            failed_fetch.append(stock_code)
            if verbose:
                print("❌ fetch failed")
            # 失敗也 delay,不要連續轟
            time.sleep(random.uniform(*delay_range))
            continue

        # build our branches
        our_branches = build_our_branches_for_stock(latest_data, stock_code)
        if not our_branches:
            skipped_count += 1
            if verbose:
                print(f"⏭️ 我們沒抓到這檔的分點資料")
            time.sleep(random.uniform(*delay_range))
            continue

        # cross-check
        verdict, mismatches = cross_check_stock(stock_code, our_branches, histock_data)
        total_branches_compared += len(our_branches)
        audited_count += 1
        all_mismatches.extend(mismatches)

        if verbose:
            mark = '✅' if verdict == 'PASS' else ('⚠️' if verdict == 'WARN' else '❌')
            print(f"{mark} {verdict} ({len(mismatches)} mismatch, {len(our_branches)} br compared)")

        # === delay (用戶明示「適當 delay」) ===
        if i < len(sample):  # 最後一筆不用 sleep
            base = random.uniform(*delay_range)
            jit = random.uniform(-jitter, jitter)
            delay = max(1.0, base + jit)
            time.sleep(delay)

    # 3. 彙總
    errors = [m for m in all_mismatches if m['severity'] == 'error']
    warnings = [m for m in all_mismatches if m['severity'] == 'warning']

    if errors:
        overall = 'FAIL'
    elif warnings:
        overall = 'WARN'
    else:
        overall = 'PASS'

    elapsed = time.time() - start_time
    summary = (
        f"audited {audited_count}/{len(sample)} 檔, "
        f"{total_branches_compared} branches compared, "
        f"{len(errors)} errors + {len(warnings)} warnings, "
        f"elapsed {elapsed:.0f}s"
    )
    if failed_fetch:
        summary += f", failed_fetch={len(failed_fetch)} ({failed_fetch[:5]})"

    result = {
        'verdict': overall,
        'audited_at': now_tw().isoformat(),
        'trade_date': latest_data.get('trade_date', ''),
        'stats': {
            'sample_size': len(sample),
            'stocks_audited': audited_count,
            'stocks_skipped': skipped_count,
            'fetch_failed': len(failed_fetch),
            'branches_compared': total_branches_compared,
            'errors': len(errors),
            'warnings': len(warnings),
            'elapsed_sec': round(elapsed),
        },
        'mismatches': all_mismatches,
        'failed_fetch': failed_fetch,
        'summary': summary,
    }

    if verbose:
        print()
        print(f"[Histock Audit] {overall}: {summary}")

    return result


# ════════════════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════════════════

def load_latest_decrypted(latest_path: str, password: str) -> Dict[str, Any]:
    """Helper: decrypt latest.json"""
    from crawler import decrypt_data
    with open(latest_path, 'r', encoding='utf-8') as f:
        enc = json.load(f)
    if not enc.get('encrypted'):
        return enc
    plaintext = decrypt_data(enc['data'], password)
    return json.loads(plaintext)


def main():
    import os
    parser = argparse.ArgumentParser(description='Histock × 我方 cross-check')
    parser.add_argument('--max-stocks', type=int, default=DEFAULT_MAX_STOCKS)
    parser.add_argument('--delay-min', type=float, default=DEFAULT_DELAY_RANGE[0])
    parser.add_argument('--delay-max', type=float, default=DEFAULT_DELAY_RANGE[1])
    parser.add_argument('--jitter', type=float, default=DEFAULT_JITTER)
    parser.add_argument('--time-budget', type=int, default=DEFAULT_TIME_BUDGET_SEC)
    parser.add_argument('--stock-code', type=str, help='只測單一個股(debug)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--latest', default='data/latest.json')
    parser.add_argument('--output', default='data/histock_audit.json')
    args = parser.parse_args()

    password = os.environ.get('CHIP_RADAR_PASSWORD')
    if not password:
        print("❌ CHIP_RADAR_PASSWORD not set")
        sys.exit(1)

    print(f"[Histock Audit] 載入 {args.latest}...")
    latest_data = load_latest_decrypted(args.latest, password)
    print(f"  trade_date: {latest_data.get('trade_date')}")
    print(f"  branches: {len(latest_data.get('branches', []))}")

    result = run_audit(
        latest_data,
        max_stocks=args.max_stocks,
        delay_range=(args.delay_min, args.delay_max),
        jitter=args.jitter,
        time_budget_sec=args.time_budget,
        dry_run=args.dry_run,
        stock_filter=args.stock_code,
    )

    if not args.dry_run:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[Histock Audit] → {out_path}")

    # GitHub Actions annotations
    if result['verdict'] == 'FAIL':
        print(f"::error::Histock cross-check FAIL: {result['summary']}")
        sys.exit(1)
    elif result['verdict'] == 'WARN':
        print(f"::warning::Histock cross-check WARN: {result['summary']}")
    else:
        print(f"::notice::Histock cross-check PASS: {result['summary']}")


if __name__ == '__main__':
    main()
