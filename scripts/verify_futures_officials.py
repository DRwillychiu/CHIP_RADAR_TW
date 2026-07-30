"""v3.71.21 L1 續: 信號 2/3/4/5 dedicated verify (TAIFEX + TWSE 官方對照).

補完 v3.71.20 orchestrator 沒 parse 到的 4 個 signal:

信號 2 外資期貨:  fetch_institutional_futures(TXF) → foreign net OI vs 本機 signal value
信號 3 P/C Ratio: fetch_official_pcr → pcr_oi vs 本機 signal value (已有 verify_pcr_vs_taifex.py, 這裡整合)
信號 4 分點漲停:  TWSE MI_INDEX (漲停家數) vs 本機 signal value
信號 5 融資熱度:  raw_output.margin_rankings.top_margin_buy top5 sum → 需 daily JSON (skip / stub)

輸出: 追加到 data/temp_verify_YYYYMMDD.json
"""
import json, sys, requests, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── 讀本機 signal ──
with open(ROOT / 'data' / 'temp_history.json', 'r', encoding='utf-8') as f:
    th = json.load(f)
last = (th.get('history') or [])[-1]
today = last.get('date')
signals_our = {s.get('name'): s for s in (last.get('signals') or [])}

print(f"=== Verify Futures Officials for {today} ===\n")

results = []


# ── 信號 2 外資期貨 ──
def verify_foreign_futures():
    our = signals_our.get('外資期貨', {})
    our_val = our.get('value')
    our_level = our.get('level')
    print(f"--- 信號 2 外資期貨 ---")
    print(f"  Our: value={our_val}, level={our_level}")
    try:
        from src.fetchers.futures import fetch_institutional_futures
        r = fetch_institutional_futures(today, commodity='TXF')
        if not r:
            print(f"  ⚠️ TAIFEX 抓不到 {today} 外資期貨資料")
            return {'signal': 'foreign_futures_eq', 'our': our_val,
                    'error': 'taifex_empty'}
        foreign_oi = r.get('foreign', {}).get('net_oi')
        # 大台等效: 需要 mtx 資料才能算, 暫先對 TXF net_oi
        print(f"  Official TAIFEX TXF foreign net_oi = {foreign_oi}")
        diff = None
        match = None
        if isinstance(foreign_oi, (int, float)) and isinstance(our_val, (int, float)):
            diff = abs(our_val - foreign_oi)
            match = diff < 100   # 100 口以下容忍 (可能有大台+小台等效差異)
            print(f"  diff = {diff}, match = {match}")
        return {'signal': 'foreign_futures_eq', 'our': our_val,
                'official_txf': foreign_oi, 'diff': diff, 'match': match,
                'note': 'TXF only; 大台等效 = TXF + MXF/4 (未算)'}
    except Exception as e:
        print(f"  ✗ error: {type(e).__name__}: {e}")
        return {'signal': 'foreign_futures_eq', 'our': our_val, 'error': str(e)}


# ── 信號 3 P/C Ratio ──
def verify_pc_ratio():
    our = signals_our.get('P/C Ratio', {})
    our_val = our.get('value')
    print(f"\n--- 信號 3 P/C Ratio ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    try:
        from src.fetchers.futures import fetch_official_pcr
        official = fetch_official_pcr(today)
        if not official:
            print(f"  ⚠️ TAIFEX 沒有 {today} P/C 資料")
            return {'signal': 'pc_ratio_oi', 'our': our_val,
                    'error': 'taifex_empty'}
        off_pcr = official.get('pcr_oi')
        print(f"  Official TAIFEX pcr_oi = {off_pcr}")
        diff = abs(off_pcr - float(our_val)) if our_val else None
        match = diff < 0.001 if diff is not None else None
        print(f"  diff = {diff}, match = {match}")
        return {'signal': 'pc_ratio_oi', 'our': our_val,
                'official': off_pcr, 'diff': diff, 'match': match}
    except Exception as e:
        print(f"  ✗ error: {type(e).__name__}: {e}")
        return {'signal': 'pc_ratio_oi', 'our': our_val, 'error': str(e)}


# ── 信號 4 分點漲停 ──
def verify_limit_up():
    our = signals_our.get('分點漲停', {})
    our_val = our.get('value')
    print(f"\n--- 信號 4 分點漲停 ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    # 我們的「分點漲停」= 全市場當日漲停家數
    # TWSE 官方: STOCK_DAY_ALL 沒直接漲停 count, 但 MI_5MINS_HIST 或個股逐檔可算
    # 用 STOCK_DAY_ALL 全市場當日資料 → 篩漲停 (change_pct >= 9.5 rough)
    try:
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json'
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(r.text)
        if d.get('stat') != 'OK':
            print(f"  ⚠️ TWSE STOCK_DAY_ALL 狀態非 OK")
            return {'signal': 'limit_up_count', 'our': our_val, 'error': 'twse_stat_not_ok'}
        rows = d.get('data', [])
        # 對 change_pct 找 >= 9.5 的
        count_limit_up = 0
        for row in rows:
            try:
                # STOCK_DAY_ALL 欄位: 證券代號, 證券名稱, 成交股數, 成交筆數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 最後揭示買價, ...
                # 漲跌價差 col idx 9
                open_p = float(row[5].replace(',', ''))
                close_p = float(row[8].replace(',', ''))
                if open_p == 0: continue
                change_pct = (close_p - open_p) / open_p * 100
                if change_pct >= 9.5:
                    count_limit_up += 1
            except (ValueError, IndexError):
                continue
        print(f"  Official TWSE STOCK_DAY_ALL 漲停 (change ≥9.5%): {count_limit_up}")
        # 差距在 5 家內容忍 (我們用「分點漲停」= 追蹤 master 買到漲停股數 or 全市場, 定義不同)
        diff = abs(our_val - count_limit_up) if isinstance(our_val, (int, float)) else None
        # 若 our 是「追蹤 master 買漲停股數」, 應 < TWSE 全市場
        match_check = 'our ≤ twse' if isinstance(our_val, (int, float)) else None
        print(f"  Match check: {match_check} ({our_val} vs {count_limit_up})")
        return {'signal': 'limit_up_count', 'our': our_val,
                'twse_full_market': count_limit_up, 'diff': diff,
                'note': 'our=追蹤 master 買漲停 數 vs twse=全市場漲停家數, 定義不同'}
    except Exception as e:
        print(f"  ✗ error: {type(e).__name__}: {e}")
        return {'signal': 'limit_up_count', 'our': our_val, 'error': str(e)}


# ── 信號 5 融資熱度 ──
def verify_margin():
    our = signals_our.get('融資熱度', {})
    our_val = our.get('value')
    print(f"\n--- 信號 5 融資熱度 ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    # 融資熱度 = raw_output.margin_rankings.top_margin_buy top 5 之 margin_change 加總 / 1e8 (億)
    # 若 value=0.0 → mr.top_margin_buy 空 or margin_change 都 0
    # 需要 daily JSON (加密) 才能對比 real fetcher output
    print(f"  ⚠️ 融資熱度需 raw daily JSON (加密) audit fetcher output")
    print(f"     若 value=0 且持續 → margin fetcher 沒抓到 (可能自 v3.11 起 bug)")
    if our_val == 0.0:
        print(f"  🔴 SUSPECT BUG: 過去持續 0.0")
        return {'signal': 'margin_top5_yi', 'our': our_val,
                'suspect_bug': True, 'need_daily_json': True}
    return {'signal': 'margin_top5_yi', 'our': our_val, 'suspect_bug': False}


for f in [verify_foreign_futures, verify_pc_ratio, verify_limit_up, verify_margin]:
    try:
        r = f()
        results.append(r)
    except Exception as e:
        print(f"  ✗ verify failed: {e}")
        results.append({'error': str(e), 'signal': f.__name__})

# Summary
print(f"\n\n=== Summary ===")
for r in results:
    sig = r.get('signal', '?')
    if r.get('suspect_bug'):
        print(f"  🔴 {sig}: suspect bug (need investigation)")
    elif r.get('match') is True:
        print(f"  ✅ {sig}: match official")
    elif r.get('match') is False:
        print(f"  ⚠️ {sig}: mismatch")
    else:
        print(f"  ⚪ {sig}: {r.get('note', 'need dedicated audit')}")

# Merge into existing temp_verify file
op = ROOT / 'data' / f'temp_verify_{today}.json'
prev = {}
if op.exists():
    try:
        prev = json.loads(op.read_text(encoding='utf-8'))
    except Exception:
        pass
import datetime
prev.setdefault('futures_officials', {})
prev['futures_officials'] = {
    'audited_at': datetime.datetime.now().isoformat(),
    'results': results,
}
op.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 追加到 {op}")
