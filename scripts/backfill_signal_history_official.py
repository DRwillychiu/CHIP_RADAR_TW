"""v3.72.0 P0: 官方 API signal history backfill (取代「等 60 天」).

背景 (L1/L2/L3 audit 揭穿):
  - 信號 1 外資現貨: key mismatch bug → temp_history 35 天全 0, 乾淨資料只 1 天
  - 信號 6 法人共識: 同 bug 家族 (net_lot key), 值存在但需驗證
  - 信號 5 融資熱度: 單位 bug (張/1e8 ≈ 0) → 本 script 不處理, 需先修 production 語意
  - Phase B backtest 因 n=0 無法產 weight → Q5 只靠 P/C Ratio 撐

解法: 信號 1/6 的原始資料 = TWSE T86 官方歷史 (可回溯數年), 直接 backfill
      120 交易日, 不等自家 crawler 累積.

輸出: data/signal_history_official.json (temp_history 相容格式)
  {
    '_meta': {...},
    'history': [
      {'date': 'YYYYMMDD',
       'signals': [{'name','score','level','value'}, ...],
       'next_day_change_pct': float}
    ]
  }

涵蓋信號:
  信號 1 外資現貨   : T86 top100 buy+sell foreign_net_lot 加總 (120d)
  信號 2 外資期貨   : TAIFEX futContractsDate TXF+MXF/4+TMF/40 (120d)
  信號 3 P/C Ratio : TAIFEX pcRatio (120d)
  信號 4 分點漲停   : 自家 archive limit_up_summary (46d, 4/21 起)
  信號 6 法人共識   : T86 foreign/trust top100 net (120d)
  信號 7 結算日壓力  : 信號 2 + days_to_settlement (120d)
  (信號 5 融資熱度: 略過 — production 單位 bug 未修, 語意待定)

驗證: 對 temp_history 重疊日 (5/11~7/1) 比對信號 6 f_net/t_net → 檢查 T86 方法正確性

Resume: data/cache/backfill_t86/{date}.json 逐日 cache, 中斷可續跑
用法: python scripts/backfill_signal_history_official.py [--days 120] [--end 20260701]
"""
import argparse
import json
import os
import sys
import time
import gzip
from datetime import date as _date, timedelta
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src' / 'backtest'))
sys.path.insert(0, str(ROOT / 'src'))

from src.pipelines.crawler_pipeline import (
    TEMP_THRESHOLDS, _temp_signal_score, _days_to_settlement,
)
from src.backtest.backtester import (
    fetch_3insti_range, fetch_pcr_range, fetch_taiex_history,
)

T86_URL = 'https://www.twse.com.tw/rwd/zh/fund/T86'
MARGN_URL = 'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
T86_DELAY = 3.5   # TWSE rate limit 保守值 (秒)
TOP_N = 100       # crawler build_inst_ranking top_n=100

CACHE_DIR = ROOT / 'data' / 'cache' / 'backfill_t86'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MARGN_CACHE_DIR = ROOT / 'data' / 'cache' / 'backfill_margn'
MARGN_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_int(v):
    try:
        return int(str(v).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0


def fetch_t86_aggregates(date_str):
    """T86(date) → {sig1_net, f_net, t_net} (張). Cache per day.

    復刻 crawler 邏輯:
      per-stock foreign_net_lot = (外陸資買賣超[4] + 外資自營商買賣超[7]) // 1000
      per-stock trust_net_lot   = 投信買賣超[10] // 1000
      ranking top100 buy (net>0 desc) + top100 sell (net<0 asc)
      sig1_net = sum(top100 buy) + sum(top100 sell)   ← 信號 1 & 6 的 f_net
      t_net    = 同法 trust                            ← 信號 6 的 t_net
    """
    cache_p = CACHE_DIR / f'{date_str}.json'
    if cache_p.exists():
        try:
            return json.loads(cache_p.read_text(encoding='utf-8'))
        except Exception:
            pass

    url = f'{T86_URL}?response=json&date={date_str}&selectType=ALL'
    try:
        r = requests.get(url, timeout=20, headers=HEADERS)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f'    ! T86 {date_str} fetch fail: {e}')
        return None
    if d.get('stat') != 'OK':
        # 非交易日或 API 無資料
        result = {'no_data': True}
        cache_p.write_text(json.dumps(result), encoding='utf-8')
        return result

    foreign_nets = []
    trust_nets = []
    for row in d.get('data', []):
        if len(row) < 19:
            continue
        f_net = _safe_int(row[4]) // 1000 + _safe_int(row[7]) // 1000
        t_net = _safe_int(row[10]) // 1000
        if f_net != 0:
            foreign_nets.append(f_net)
        if t_net != 0:
            trust_nets.append(t_net)

    def _ranked_sum(nets):
        buys = sorted([n for n in nets if n > 0], reverse=True)[:TOP_N]
        sells = sorted([n for n in nets if n < 0])[:TOP_N]
        return sum(buys) + sum(sells)

    result = {
        'f_net': _ranked_sum(foreign_nets),
        't_net': _ranked_sum(trust_nets),
        'n_stocks': len(d.get('data', [])),
    }
    cache_p.write_text(json.dumps(result), encoding='utf-8')
    return result


def fetch_margin_aggregate(date_str):
    """MI_MARGN(date, MS) → 全市場融資金額日增減 (億). Cache per day.

    v3.72.1 P0-4: 信號 5 新語意 — 全市場融資金額增減 (取代 top5 張數 bug).
    tables[0] 信用交易統計 row '融資金額(仟元)': [買進, 賣出, 現償, 前日餘額, 今日餘額]
    change_yi = (今日餘額 - 前日餘額) 仟元 / 1e5 → 億
    """
    cache_p = MARGN_CACHE_DIR / f'{date_str}.json'
    if cache_p.exists():
        try:
            return json.loads(cache_p.read_text(encoding='utf-8'))
        except Exception:
            pass
    url = f'{MARGN_URL}?date={date_str}&selectType=MS&response=json'
    try:
        r = requests.get(url, timeout=20, headers=HEADERS)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f'    ! MI_MARGN {date_str} fetch fail: {e}')
        return None
    if d.get('stat') != 'OK':
        result = {'no_data': True}
        cache_p.write_text(json.dumps(result), encoding='utf-8')
        return result
    result = {'no_data': True}
    for t in (d.get('tables') or []):
        for row in (t.get('data') or []):
            if row and str(row[0]).startswith('融資金額'):
                prev = _safe_int(row[4])
                today = _safe_int(row[5])
                if prev > 0 and today > 0:
                    result = {
                        'margin_amt_change_yi': round((today - prev) / 1e5, 2),
                        'margin_amt_balance_yi': round(today / 1e5, 1),
                    }
                break
        if not result.get('no_data'):
            break
    cache_p.write_text(json.dumps(result), encoding='utf-8')
    return result


def sig5_from(change_yi, thresholds):
    """信號 5 v3.72.1 新語意: 全市場融資金額日增減 (億), 反指標.

    thresholds = (t_eb, t_b, t_bull, t_eb_bull) descending —
    change >= t_eb → extreme-bear (散戶大幅追漲 = 看空) ... 依 crawler 同映射.
    """
    if change_yi is None:
        return None
    t = thresholds
    if change_yi >= t[0]:   sc = (0, 'extreme-bear')
    elif change_yi >= t[1]: sc = (5, 'bear')
    elif change_yi >= t[2]: sc = (10, 'neutral')
    elif change_yi >= t[3]: sc = (15, 'bull')
    else:                   sc = (20, 'extreme-bull')
    return {'name': '融資熱度', 'score': sc[0], 'level': sc[1],
            'value': change_yi}


def sig1_from(f_net):
    sc = _temp_signal_score(f_net, TEMP_THRESHOLDS['foreign_cash'])
    if not sc:
        return None
    return {'name': '外資現貨', 'score': sc[0], 'level': sc[1], 'value': f_net}


def sig6_from(f_net, t_net):
    """復刻 crawler 法人共識雙條件邏輯."""
    f_thr = TEMP_THRESHOLDS['consensus_foreign']
    t_thr = TEMP_THRESHOLDS['consensus_trust']
    if f_net >= f_thr and t_net >= t_thr:
        sc = (20, 'extreme-bull')
    elif f_net > 0 and t_net > 0:
        sc = (15, 'bull')
    elif f_net <= -f_thr and t_net <= -t_thr:
        sc = (0, 'extreme-bear')
    elif f_net < 0 and t_net < 0:
        sc = (5, 'bear')
    else:
        sc = (10, 'neutral')
    return {'name': '法人共識', 'score': sc[0], 'level': sc[1],
            'value': {'foreign_net': f_net, 'trust_net': t_net}}


def sig4_from(n_limit_up):
    thr = TEMP_THRESHOLDS['limit_up_count']
    if n_limit_up >= thr[0]:   sc = (20, 'extreme-bull')
    elif n_limit_up >= thr[1]: sc = (15, 'bull')
    elif n_limit_up >= thr[2]: sc = (10, 'neutral')
    else:                      sc = (5, 'bear')
    return {'name': '分點漲停', 'score': sc[0], 'level': sc[1], 'value': n_limit_up}


def sig2_from(eq):
    sc = _temp_signal_score(eq, TEMP_THRESHOLDS['foreign_futures_eq'])
    if not sc:
        return None
    return {'name': '外資期貨', 'score': sc[0], 'level': sc[1], 'value': round(eq, 1)}


def sig3_from(pcr):
    sc = _temp_signal_score(pcr, TEMP_THRESHOLDS['pc_ratio_oi'])
    if not sc:
        return None
    return {'name': 'P/C Ratio', 'score': sc[0], 'level': sc[1], 'value': round(pcr, 4)}


def sig7_from(eq, date_str):
    d = _days_to_settlement(date_str)
    if d is None or eq is None:
        return None
    near_thr = TEMP_THRESHOLDS['settlement_near_oi']
    week_thr = TEMP_THRESHOLDS['settlement_week_oi']
    if abs(d) <= 1:
        if eq <= -near_thr:    sc = (20, 'extreme-bull')
        elif eq >= near_thr:   sc = (0, 'extreme-bear')
        else:                  sc = (10, 'neutral')
    elif abs(d) <= 3:
        if eq <= -week_thr:    sc = (15, 'bull')
        elif eq >= week_thr:   sc = (5, 'bear')
        else:                  sc = (10, 'neutral')
    else:
        sc = (10, 'neutral')
    return {'name': '結算日壓力', 'score': sc[0], 'level': sc[1],
            'value': {'days_to_settle': d, 'foreign_eq_oi': round(eq, 1)}}


def load_archive_limit_up():
    """自家 archive 解密 → {date: limit_up_count}. 需 CHIP_RADAR_PASSWORD."""
    password = os.environ.get('CHIP_RADAR_PASSWORD', '')
    if not password:
        print('  ! CHIP_RADAR_PASSWORD 未設, 信號 4 archive 補洞略過')
        return {}
    try:
        from src.pipelines.crawler_output import decrypt_data
    except ImportError:
        print('  ! decrypt_data import fail, 信號 4 略過')
        return {}
    result = {}
    files = sorted(
        list((ROOT / 'data').glob('[0-9]' * 8 + '.json')) +
        list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json')) +
        list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz')),
        key=lambda p: p.name[:8]
    )
    seen = set()
    for p in files:
        date_str = p.name[:8]
        if date_str in seen:
            continue
        seen.add(date_str)
        try:
            if str(p).endswith('.gz'):
                with gzip.open(p, 'rt', encoding='utf-8') as f:
                    enc = json.load(f)
            else:
                with open(p, 'r', encoding='utf-8') as f:
                    enc = json.load(f)
            plain = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
            data = json.loads(plain)
            lus = data.get('limit_up_summary') or {}
            stocks = lus.get('limit_up_stocks')
            if stocks is not None:
                result[date_str] = len(stocks)
        except Exception:
            continue
    print(f'  ✓ archive 信號 4: {len(result)} 天 ({min(result) if result else "-"} ~ {max(result) if result else "-"})')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=120)
    ap.add_argument('--end', type=str, default='20260701')
    args = ap.parse_args()

    end_d = _date(int(args.end[:4]), int(args.end[4:6]), int(args.end[6:8]))

    # ── 1. TAIEX 交易日 + change_pct (FMTQIK, 8 個月保險) ──
    print('=' * 70)
    print('Step 1/5: TAIEX history (FMTQIK)')
    print('=' * 70)
    taiex = fetch_taiex_history(end_d, months=8)
    trading_days = sorted(d for d in taiex if d <= args.end)
    window_days = trading_days[-args.days:]
    print(f'  交易日: {len(trading_days)} 總 | 視窗: {window_days[0]} ~ {window_days[-1]} ({len(window_days)} 天)')

    # next-day map
    next_chg = {}
    for i, d in enumerate(trading_days[:-1]):
        next_chg[d] = taiex[trading_days[i + 1]]

    # ── 2. TAIFEX 信號 2/3 range ──
    print()
    print('=' * 70)
    print('Step 2/5: TAIFEX futures OI + PCR')
    print('=' * 70)
    start_d = _date(int(window_days[0][:4]), int(window_days[0][4:6]), int(window_days[0][6:8]))
    txf = fetch_3insti_range(start_d, end_d, 'TXF')
    mxf = fetch_3insti_range(start_d, end_d, 'MXF')
    tmf = fetch_3insti_range(start_d, end_d, 'TMF')
    pcr = fetch_pcr_range(start_d, end_d)
    print(f'  TXF {len(txf)} 天 | MXF {len(mxf)} | TMF {len(tmf)} | PCR {len(pcr)}')

    # ── 3. T86 per-day (cache + resume) ──
    print()
    print('=' * 70)
    print(f'Step 3/5: T86 backfill ({len(window_days)} 天, cache resume)')
    print('=' * 70)
    t86_by_day = {}
    n_cached = sum(1 for d in window_days if (CACHE_DIR / f'{d}.json').exists())
    print(f'  已 cache: {n_cached}/{len(window_days)}')
    for i, d in enumerate(window_days):
        was_cached = (CACHE_DIR / f'{d}.json').exists()
        agg = fetch_t86_aggregates(d)
        if agg and not agg.get('no_data'):
            t86_by_day[d] = agg
        if not was_cached:
            if (i + 1) % 10 == 0:
                print(f'  ... {i+1}/{len(window_days)} ({d})')
            time.sleep(T86_DELAY)
    print(f'  ✓ T86 有效: {len(t86_by_day)} 天')

    # ── 3.5. MI_MARGN aggregate per-day (信號 5 新語意) ──
    print()
    print('=' * 70)
    print(f'Step 3.5/5: MI_MARGN 全市場融資金額 backfill ({len(window_days)} 天)')
    print('=' * 70)
    margn_by_day = {}
    n_m_cached = sum(1 for d in window_days if (MARGN_CACHE_DIR / f'{d}.json').exists())
    print(f'  已 cache: {n_m_cached}/{len(window_days)}')
    for i, d in enumerate(window_days):
        was_cached = (MARGN_CACHE_DIR / f'{d}.json').exists()
        agg = fetch_margin_aggregate(d)
        if agg and not agg.get('no_data'):
            margn_by_day[d] = agg
        if not was_cached:
            if (i + 1) % 10 == 0:
                print(f'  ... {i+1}/{len(window_days)} ({d})')
            time.sleep(T86_DELAY)
    print(f'  ✓ MI_MARGN 有效: {len(margn_by_day)} 天')

    # 信號 5 quantile 閾值 (P80/P60/P40/P20 — L2 audit 方法論)
    margin_thresholds = None
    m_values = sorted(v['margin_amt_change_yi'] for v in margn_by_day.values())
    if len(m_values) >= 30:
        def _pct(p):
            k = (len(m_values) - 1) * p
            f = int(k)
            c = min(f + 1, len(m_values) - 1)
            return round(m_values[f] + (m_values[c] - m_values[f]) * (k - f), 1)
        margin_thresholds = (_pct(0.8), _pct(0.6), _pct(0.4), _pct(0.2))
        print(f'  信號 5 分佈: min={m_values[0]:.1f} med={_pct(0.5):.1f} max={m_values[-1]:.1f} 億')
        print(f'  ★ 信號 5 quantile 閾值 (P80/P60/P40/P20): {margin_thresholds}')
        print(f'    (production TEMP_THRESHOLDS[margin_market_yi] 應設此值)')
    else:
        print(f'  ! margin 樣本 <30, 不產閾值')

    # ── 4. 信號 4 from archive ──
    print()
    print('=' * 70)
    print('Step 4/5: 信號 4 分點漲停 (自家 archive)')
    print('=' * 70)
    limit_up_by_day = load_archive_limit_up()

    # ── 5. Assemble ──
    print()
    print('=' * 70)
    print('Step 5/5: Assemble history')
    print('=' * 70)
    history = []
    for d in window_days:
        if d not in next_chg:
            continue   # 最後一天無 next day
        signals = []
        # 信號 1 + 6
        agg = t86_by_day.get(d)
        if agg:
            s1 = sig1_from(agg['f_net'])
            if s1: signals.append(s1)
        # 信號 2: 等效大台 = TXF + MXF/4 + TMF/40
        txf_f = txf.get(d, {}).get('foreign')
        eq = None
        if txf_f is not None:
            mxf_f = mxf.get(d, {}).get('foreign', 0)
            tmf_f = tmf.get(d, {}).get('foreign', 0)
            eq = txf_f + mxf_f / 4 + tmf_f / 40
            s2 = sig2_from(eq)
            if s2: signals.append(s2)
        # 信號 3
        if d in pcr:
            s3 = sig3_from(pcr[d])
            if s3: signals.append(s3)
        # 信號 4
        if d in limit_up_by_day:
            signals.append(sig4_from(limit_up_by_day[d]))
        # 信號 5 (v3.72.1 新語意: 全市場融資金額增減)
        if margin_thresholds and d in margn_by_day:
            s5 = sig5_from(margn_by_day[d]['margin_amt_change_yi'], margin_thresholds)
            if s5: signals.append(s5)
        # 信號 6
        if agg:
            signals.append(sig6_from(agg['f_net'], agg['t_net']))
        # 信號 7
        if eq is not None:
            s7 = sig7_from(eq, d)
            if s7: signals.append(s7)

        if not signals:
            continue
        history.append({
            'date': d,
            'signals': signals,
            'next_day_change_pct': round(next_chg[d], 2),
        })

    out = {
        '_meta': {
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'source': 'TWSE T86 + TAIFEX futContractsDate/pcRatio + FMTQIK + own archive',
            'window': [window_days[0], window_days[-1]],
            'days_requested': args.days,
            'signal_coverage': {
                '外資現貨': sum(1 for h in history if any(s['name'] == '外資現貨' for s in h['signals'])),
                '外資期貨': sum(1 for h in history if any(s['name'] == '外資期貨' for s in h['signals'])),
                'P/C Ratio': sum(1 for h in history if any(s['name'] == 'P/C Ratio' for s in h['signals'])),
                '分點漲停': sum(1 for h in history if any(s['name'] == '分點漲停' for s in h['signals'])),
                '融資熱度': sum(1 for h in history if any(s['name'] == '融資熱度' for s in h['signals'])),
                '法人共識': sum(1 for h in history if any(s['name'] == '法人共識' for s in h['signals'])),
                '結算日壓力': sum(1 for h in history if any(s['name'] == '結算日壓力' for s in h['signals'])),
            },
            # v3.72.1 P0-4: 信號 5 新語意 (全市場融資金額增減 億, quantile 閾值)
            'margin_market_yi_thresholds': list(margin_thresholds) if margin_thresholds else None,
        },
        'history': history,
    }
    out_path = ROOT / 'data' / 'signal_history_official.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'  ✓ {len(history)} 天 history → {out_path}')
    print(f'  coverage: {out["_meta"]["signal_coverage"]}')

    # ── 6. 驗證: 對 temp_history 重疊日比對 法人共識 f_net ──
    print()
    print('=' * 70)
    print('驗證: T86 backfill vs temp_history 實際值 (法人共識 f_net/t_net)')
    print('=' * 70)
    try:
        th = json.loads((ROOT / 'data' / 'temp_history.json').read_text(encoding='utf-8'))
        th_by_date = {e['date']: e for e in th.get('history', [])}
        n_match = n_mismatch = n_compared = 0
        for h in history:
            te = th_by_date.get(h['date'])
            if not te:
                continue
            th_sig6 = next((s for s in te.get('signals', []) if s.get('name') == '法人共識'), None)
            my_sig6 = next((s for s in h['signals'] if s['name'] == '法人共識'), None)
            if not th_sig6 or not my_sig6:
                continue
            th_v = th_sig6.get('value') or {}
            my_v = my_sig6['value']
            if not isinstance(th_v, dict) or th_v.get('foreign_net') in (None, 0):
                continue
            n_compared += 1
            th_f = th_v.get('foreign_net', 0)
            my_f = my_v['foreign_net']
            # production 含上櫃 TPEx, backfill 只有 TWSE → 允許差異但 level 應多數一致
            same_level = (th_sig6.get('level') == my_sig6['level'])
            if same_level:
                n_match += 1
            else:
                n_mismatch += 1
                if n_mismatch <= 5:
                    print(f'  {h["date"]}: level {th_sig6.get("level")} vs {my_sig6["level"]} '
                          f'(f_net {th_f} vs {my_f})')
        if n_compared:
            rate = n_match / n_compared * 100
            print(f'  重疊 {n_compared} 天, level 一致 {n_match} ({rate:.0f}%)')
            if rate >= 80:
                print('  ✅ backfill 方法可信 (level 一致 ≥80%; 差異來自 production 含上櫃)')
            else:
                print('  ⚠️ level 一致 <80% — 需人工檢查 T86 方法')
        else:
            print('  (無可比對重疊日)')
    except Exception as e:
        print(f'  ! 驗證失敗: {e}')


if __name__ == '__main__':
    main()
