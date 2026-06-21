"""
backtester.py — v3.29+ Phase A 信號 backtest (futures-only)

破壞式 review (2026-05-14) 後新工具,取代 T-c 等 30 天累積的設計。

用 TAIFEX + TWSE 歷史資料一次性算過去 N 天的信號 level,
配對 (T 日 signal) ↔ (T+1 日 TAIEX 漲跌%) → 計算 hit rate。

Phase A 涵蓋信號 (3/7):
  - 信號 2: 外資期貨等效大台淨 OI
  - 信號 3: P/C OI Ratio (反指標)
  - 信號 7: 結算日壓力 (信號 2 + 距結算日)

Phase B (押 v3.29.1+) 補:
  - 信號 1: 外資現貨 (需 T86 aggregate)
  - 信號 4: 分點漲停數 (需個股全市場 close)
  - 信號 5: 融資熱度 (需融資餘額 daily)
  - 信號 6: 法人共識 (需 1 同等資料)

輸出:
  data/backtest_results.json — pairs + hit rate 結果
  stdout — 各信號 × level: n / mean_next_day_return / hit_rate / verdict

用法: python backtester.py [--days 90] [--end 20260513]
"""
import argparse
import csv
import io
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# 借既有 helper (信號計分邏輯一致)
sys.path.insert(0, str(Path(__file__).parent))
from crawler import _temp_signal_score, _days_to_settlement, TEMP_THRESHOLDS


# ════════════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════════════
TAIFEX_BASE = 'https://www.taifex.com.tw/cht/3'
TWSE_FMTQIK = 'https://www.twse.com.tw/exchangeReport/FMTQIK'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://www.taifex.com.tw/cht/3/futContractsDate',
}

# 預設參數
DEFAULT_DAYS = 90
CHUNK_DAYS = 30      # TAIFEX range 一次抓 30 天保險
REQUEST_DELAY = 2.0  # 兩次 TAIFEX 請求間 sleep 秒數


# ════════════════════════════════════════════════════════════════════
#  HTTP helpers
# ════════════════════════════════════════════════════════════════════
def _date_fmt(d):
    """date object → '2026/05/13' (TAIFEX 格式)"""
    return d.strftime('%Y/%m/%d')


def _date_str(d):
    return d.strftime('%Y%m%d')


def _to_int(s):
    if not s or not s.strip():
        return 0
    try:
        return int(s.replace(',', '').strip())
    except (ValueError, TypeError):
        return 0


def _to_float(s):
    if not s or not s.strip():
        return None
    try:
        return float(s.replace(',', '').replace('%', '').strip())
    except (ValueError, TypeError):
        return None


def _post_csv(endpoint, data, retries=3):
    url = f"{TAIFEX_BASE}/{endpoint}"
    for attempt in range(retries):
        try:
            r = requests.post(url, data=data, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 100:
                r.encoding = 'big5'
                return r.text
            print(f"    ⚠️ {endpoint} attempt {attempt+1}: HTTP {r.status_code} size={len(r.text)}")
        except Exception as e:
            print(f"    ⚠️ {endpoint} attempt {attempt+1}: {e}")
        if attempt < retries - 1:
            time.sleep(5 + attempt * 5)
    return None


def _parse_csv(text):
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        row_dict = {headers[i]: val.strip() for i, val in enumerate(row) if i < len(headers)}
        result.append(row_dict)
    return result


# ════════════════════════════════════════════════════════════════════
#  Data fetchers
# ════════════════════════════════════════════════════════════════════
def fetch_3insti_range(start_d, end_d, commodity='TXF'):
    """抓 TAIFEX 三大法人 range CSV. 用 30 天 chunk 防 server timeout.
    Returns: {date_str_YYYYMMDD: {'foreign': net_oi, 'trust': net_oi, 'dealer': net_oi}}
    """
    result = {}
    cur = start_d
    while cur <= end_d:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS - 1), end_d)
        print(f"  [3insti {commodity}] {_date_fmt(cur)} ~ {_date_fmt(chunk_end)}...")
        text = _post_csv('futContractsDateDown', {
            'queryStartDate': _date_fmt(cur),
            'queryEndDate': _date_fmt(chunk_end),
            'commodityId': commodity,
        })
        if text:
            rows = _parse_csv(text)
            identity_map = {
                '自營商': 'dealer', '投信': 'trust',
                '外資': 'foreign', '外資及陸資': 'foreign',
            }
            for row in rows:
                date_raw = row.get('日期', '').strip()
                if not date_raw or '/' not in date_raw:
                    continue
                # '2026/05/13' → '20260513'
                date_key = date_raw.replace('/', '')
                identity = row.get('身份別', '').strip()
                key = identity_map.get(identity)
                if not key:
                    continue
                net_oi = _to_int(row.get('多空未平倉口數淨額', '0'))
                if date_key not in result:
                    result[date_key] = {}
                result[date_key][key] = net_oi
            print(f"    ✓ {len(rows)} rows")
        cur = chunk_end + timedelta(days=1)
        time.sleep(REQUEST_DELAY)
    return result


def fetch_pcr_range(start_d, end_d):
    """抓 TAIFEX P/C Ratio (Put/Call OI) range CSV.
    Returns: {date_str: pc_ratio_oi (float)}
    """
    result = {}
    cur = start_d
    while cur <= end_d:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS - 1), end_d)
        print(f"  [PCR] {_date_fmt(cur)} ~ {_date_fmt(chunk_end)}...")
        text = _post_csv('pcRatioDown', {
            'queryStartDate': _date_fmt(cur),
            'queryEndDate': _date_fmt(chunk_end),
        })
        if text:
            rows = _parse_csv(text)
            for row in rows:
                date_raw = row.get('日期', '').strip()
                if not date_raw or '/' not in date_raw:
                    continue
                date_key = date_raw.replace('/', '')
                # PCR OI 欄位: '買賣權未平倉量比率%' (含 % 符號) 或 '賣權買權未平倉量比率%'
                pcr_str = (row.get('賣權買權未平倉量比率%')
                           or row.get('買賣權未平倉量比率%')
                           or row.get('P/C Ratio (OI)')
                           or '')
                pcr_pct = _to_float(pcr_str)
                if pcr_pct is None:
                    continue
                # 161.65% → 1.6165 (chip_radar 內部用小數)
                pcr_decimal = pcr_pct / 100.0
                result[date_key] = pcr_decimal
            print(f"    ✓ {len([r for r in rows if r])} rows")
        cur = chunk_end + timedelta(days=1)
        time.sleep(REQUEST_DELAY)
    return result


def fetch_taiex_history(end_d, months=4):
    """抓 TWSE 大盤加權指數 history (FMTQIK 每月一個檔案).
    Returns: {date_str_YYYYMMDD: change_pct_float}
    """
    result = {}
    # 從 end_d 往前抓 N 個月
    cur_year, cur_month = end_d.year, end_d.month
    for _ in range(months):
        date_param = f"{cur_year}{cur_month:02d}01"
        url = f"{TWSE_FMTQIK}?response=json&date={date_param}"
        print(f"  [TAIEX] {cur_year}-{cur_month:02d}...")
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if data.get('stat') == 'OK':
                    fields = data.get('fields', [])
                    rows = data.get('data', [])
                    date_idx = next((i for i, f in enumerate(fields) if '日期' in f), None)
                    chg_idx = next((i for i, f in enumerate(fields) if '漲跌' in f and '%' not in f), None)
                    close_idx = next((i for i, f in enumerate(fields) if '收盤' in f or '加權' in f), None)
                    pct_idx = next((i for i, f in enumerate(fields) if '%' in f or '幅度' in f or '漲跌百分' in f), None)
                    for row in rows:
                        if not row:
                            continue
                        roc_date = row[date_idx] if date_idx is not None else None  # '115/05/13'
                        if not roc_date or '/' not in roc_date:
                            continue
                        parts = roc_date.split('/')
                        if len(parts) != 3:
                            continue
                        ad_year = int(parts[0]) + 1911
                        date_key = f"{ad_year:04d}{parts[1]:0>2}{parts[2]:0>2}"
                        # 漲跌點數 + 收盤 → change_pct
                        if pct_idx is not None and pct_idx < len(row):
                            pct = _to_float(row[pct_idx])
                            if pct is not None:
                                result[date_key] = pct
                                continue
                        # fallback: 漲跌點數 / (收盤-漲跌點數)
                        chg = _to_float(row[chg_idx]) if chg_idx is not None else None
                        close = _to_float(row[close_idx]) if close_idx is not None else None
                        if chg is not None and close is not None and close - chg != 0:
                            pct = chg / (close - chg) * 100
                            result[date_key] = round(pct, 2)
            else:
                print(f"    ⚠️ HTTP {r.status_code}")
        except Exception as e:
            print(f"    ⚠️ {e}")
        # 上個月
        if cur_month == 1:
            cur_year -= 1
            cur_month = 12
        else:
            cur_month -= 1
        time.sleep(1.5)
    print(f"  ✓ TAIEX 共 {len(result)} 天")
    return result


# ════════════════════════════════════════════════════════════════════
#  Compute signals (mirrors crawler.compute_chip_temperature for tier-A signals)
# ════════════════════════════════════════════════════════════════════
def compute_signals_for_day(date_str, txf, mxf, tmf, pcr):
    """單日算 3 個 tier-A 信號. 返 {sig_name: (value, score, level)} 或缺失值 None"""
    out = {}

    # 信號 2: 外資期貨等效大台淨 OI = TXF + MXF/4 + TMF/40
    txf_f = txf.get(date_str, {}).get('foreign')
    mxf_f = mxf.get(date_str, {}).get('foreign', 0)
    tmf_f = tmf.get(date_str, {}).get('foreign', 0)
    if txf_f is not None:
        eq = txf_f + mxf_f / 4 + tmf_f / 40
        sc = _temp_signal_score(eq, TEMP_THRESHOLDS['foreign_futures_eq'])
        out['foreign_futures_eq'] = {'value': round(eq, 1), 'score': sc[0], 'level': sc[1]} if sc else None
    else:
        out['foreign_futures_eq'] = None

    # 信號 3: P/C OI Ratio
    pcr_val = pcr.get(date_str)
    if pcr_val is not None:
        sc = _temp_signal_score(pcr_val, TEMP_THRESHOLDS['pc_ratio_oi'])
        out['pc_ratio_oi'] = {'value': round(pcr_val, 4), 'score': sc[0], 'level': sc[1]} if sc else None
    else:
        out['pc_ratio_oi'] = None

    # 信號 7: 結算日壓力 (用 信號 2 + 距結算日)
    eq_val = (out.get('foreign_futures_eq') or {}).get('value')
    if eq_val is not None:
        d = _days_to_settlement(date_str)
        if d is not None:
            near_thr = TEMP_THRESHOLDS['settlement_near_oi']
            week_thr = TEMP_THRESHOLDS['settlement_week_oi']
            if abs(d) <= 1:
                if eq_val <= -near_thr:    sc = (20, 'extreme-bull')
                elif eq_val >= near_thr:   sc = (0, 'extreme-bear')
                else:                      sc = (10, 'neutral')
            elif abs(d) <= 3:
                if eq_val <= -week_thr:    sc = (15, 'bull')
                elif eq_val >= week_thr:   sc = (5, 'bear')
                else:                      sc = (10, 'neutral')
            else:
                sc = (10, 'neutral')
            out['settlement_pressure'] = {
                'value': {'days_to_settle': d, 'foreign_eq_oi': eq_val},
                'score': sc[0], 'level': sc[1],
            }
        else:
            out['settlement_pressure'] = None
    else:
        out['settlement_pressure'] = None

    return out


# ════════════════════════════════════════════════════════════════════
#  Pair (T 日 signal) ↔ (T+1 日 TAIEX 漲跌%)
# ════════════════════════════════════════════════════════════════════
def pair_with_next_day(signals_by_day, taiex_by_day):
    """signals_by_day[date_str] + taiex_by_day[next_trading_day] → list of pairs"""
    sorted_dates = sorted(set(signals_by_day.keys()) | set(taiex_by_day.keys()))
    pairs = []
    for i, d in enumerate(sorted_dates):
        if d not in signals_by_day:
            continue
        # 找 d 之後最近的 trading day (taiex_by_day 有 entry)
        next_d = None
        for j in range(i + 1, len(sorted_dates)):
            cand = sorted_dates[j]
            if cand in taiex_by_day:
                next_d = cand
                break
        if next_d is None:
            continue
        pairs.append({
            'date': d,
            'next_date': next_d,
            'signals': signals_by_day[d],
            'next_day_change_pct': taiex_by_day[next_d],
        })
    return pairs


# ════════════════════════════════════════════════════════════════════
#  Hit rate analysis
# ════════════════════════════════════════════════════════════════════
LEVEL_DIRECTION = {
    'extreme-bull': +1, 'bull': +1, 'neutral': 0, 'bear': -1, 'extreme-bear': -1,
}
LEVEL_ORDER = ['extreme-bull', 'bull', 'neutral', 'bear', 'extreme-bear']
LEVEL_LABEL = {
    'extreme-bull': '極多', 'bull': '偏多', 'neutral': '中性',
    'bear': '偏空', 'extreme-bear': '極空',
}


def hit_rate_analysis(pairs, min_cases=5):
    """signal × level 聚合 + hit rate"""
    bucket = defaultdict(lambda: defaultdict(list))
    for p in pairs:
        nd_pct = p['next_day_change_pct']
        if nd_pct is None:
            continue
        for sig_name, sig_data in (p['signals'] or {}).items():
            if not sig_data:
                continue
            level = sig_data.get('level')
            bucket[sig_name][level].append(nd_pct)

    report = {}
    for sig_name in bucket:
        report[sig_name] = {}
        for level in LEVEL_ORDER:
            vals = bucket[sig_name].get(level, [])
            if not vals:
                continue
            n = len(vals)
            mean_nd = sum(vals) / n
            expected_dir = LEVEL_DIRECTION[level]
            if expected_dir == +1:
                hits = sum(1 for v in vals if v > 0)
            elif expected_dir == -1:
                hits = sum(1 for v in vals if v < 0)
            else:
                hits = sum(1 for v in vals if abs(v) <= 0.5)
            hit_rate = hits / n * 100
            report[sig_name][level] = {
                'n': n,
                'mean_next_day_pct': round(mean_nd, 3),
                'hit_rate': round(hit_rate, 1),
                'enough_cases': n >= min_cases,
            }
    return report


def print_report(report, total_pairs):
    print()
    print("=" * 72)
    print(f"  Backtest Hit-Rate 報告 (n={total_pairs} 配對)")
    print("=" * 72)
    for sig_name in ['foreign_futures_eq', 'pc_ratio_oi', 'settlement_pressure']:
        if sig_name not in report:
            print(f"\n▼ {sig_name}: 無資料")
            continue
        print(f"\n▼ {sig_name}")
        for level in LEVEL_ORDER:
            data = report[sig_name].get(level)
            if not data:
                continue
            n = data['n']
            mean = data['mean_next_day_pct']
            hit = data['hit_rate']
            expected_dir = LEVEL_DIRECTION[level]
            verdict = "✅" if hit >= 55 else ("⚠️ " if hit >= 45 else "❌")
            if not data['enough_cases']:
                verdict += " (n 小, 僅參考)"
            print(f"  {LEVEL_LABEL[level]:<5} n={n:>4}  avg次日={mean:+.3f}%  hit={hit:5.1f}%  {verdict}")


# ════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS, help='backtest days (default 90)')
    parser.add_argument('--end', type=str, default=None, help='end date YYYYMMDD (default yesterday)')
    parser.add_argument('--out', type=str, default='data/backtest_results.json')
    args = parser.parse_args()

    if args.end:
        end_d = datetime.strptime(args.end, '%Y%m%d').date()
    else:
        end_d = date.today() - timedelta(days=1)
    start_d = end_d - timedelta(days=args.days + 7)  # extra buffer for weekends

    print(f"\n╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║  Chip Radar Backtester (Phase A: futures-only signals)              ║")
    print(f"║  Range: {start_d} ~ {end_d} ({args.days} 天 + 緩衝)                ║")
    print(f"╚══════════════════════════════════════════════════════════════════════╝\n")

    print("[1/4] 抓 TAIFEX 三大法人 (TXF + MXF + TMF)...")
    txf = fetch_3insti_range(start_d, end_d, 'TXF')
    mxf = fetch_3insti_range(start_d, end_d, 'MXF')
    tmf = fetch_3insti_range(start_d, end_d, 'TMF')

    print("\n[2/4] 抓 TAIFEX P/C OI Ratio...")
    pcr = fetch_pcr_range(start_d, end_d)

    print("\n[3/4] 抓 TWSE TAIEX 大盤歷史...")
    months_needed = (args.days // 30) + 2
    taiex = fetch_taiex_history(end_d, months=months_needed)

    print(f"\n[4/4] 計算信號 + 配對次日漲跌...")
    all_dates = sorted(set(txf.keys()) | set(mxf.keys()) | set(tmf.keys()) | set(pcr.keys()))
    print(f"  共 {len(all_dates)} 個交易日有任何 TAIFEX 資料")

    signals_by_day = {}
    for d_str in all_dates:
        signals_by_day[d_str] = compute_signals_for_day(d_str, txf, mxf, tmf, pcr)

    pairs = pair_with_next_day(signals_by_day, taiex)
    print(f"  配對成功: {len(pairs)} 個 (T 日 signal ↔ T+1 日 TAIEX)")

    report = hit_rate_analysis(pairs)
    print_report(report, len(pairs))

    # 存結果
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_payload = {
        'generated_at': datetime.now().isoformat(),
        'range': {'start': str(start_d), 'end': str(end_d), 'days_requested': args.days},
        'thresholds_used': {k: list(v) if isinstance(v, tuple) else v
                            for k, v in TEMP_THRESHOLDS.items()},
        'total_pairs': len(pairs),
        'pairs': pairs,
        'hit_rate_report': report,
    }
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2,
                                     default=lambda x: list(x) if isinstance(x, tuple) else str(x)),
                          encoding='utf-8')
    print(f"\n[結果] {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    print("\n結論 (信心 ≥ 65% = ✅ 維持 / 45-65% = ⚠️ 觀察 / < 45% = ❌ 檢視閾值)")
    print()


if __name__ == '__main__':
    main()
