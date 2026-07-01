"""v3.71.20 L1 Temperature Audit — 對齊 8 個 signal 到官方 API.

對每個 signal:
  1. 從 temp_history.json 最後 entry 抓「我們記錄的值」
  2. 從官方 API (TWSE / TAIFEX / MoneyDJ) 抓「真實值」
  3. 比對 → 差異 > tolerance 標 ⚠️

Signal ↔ 官方 endpoint:
  1. foreign_cash        → TWSE BFI82U (三大法人買賣超)
  2. foreign_futures_eq  → TAIFEX 期貨三大法人交易口數 (需計算大台等效)
  3. pc_ratio_oi         → TAIFEX 選擇權 P/C ratio (已有 verify_pcr_vs_taifex.py)
  4. limit_up_count      → TWSE MI_INDEX (盤後漲停家數統計)
  5. margin_top5_yi      → TWSE MI_MARGN (融資融券餘額)
  6. consensus_foreign   → 個股外資買超 top 統計 (計算類)
  7. consensus_trust     → 個股投信買超 top 統計 (計算類)
  8. settlement_pressure → TAIFEX 期貨大盤 OI

輸出: data/temp_verify_YYYYMMDD.json + console report
"""
import json, sys, requests
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
TH_PATH = ROOT / 'data' / 'temp_history.json'

th = json.loads(TH_PATH.read_text(encoding='utf-8'))
history = th.get('history') or []
if not history:
    print("❌ temp_history 空"); sys.exit(1)
last = history[-1]
today = last.get('date')
print(f"=== Temperature Audit for {today} ===\n")

signals_our = {}
for s in (last.get('signals') or []):
    signals_our[s.get('name')] = s

def _yyyymmdd_to_roc(d):
    y = int(d[:4]) - 1911
    return f"{y:03d}{d[4:]}"

# ── Signal 1: 外資現貨 ──
# Our value: temp_history.外資現貨.value (千元 or 億)
# Official: TWSE BFI82U (三大法人買賣超)
def verify_foreign_cash():
    our = signals_our.get('外資現貨', {})
    our_val = our.get('value')
    print(f"--- 外資現貨 ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    try:
        url = f'https://openapi.twse.com.tw/v1/fund/BFI82U'
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        # BFI82U 回今日或最近交易日全市場三大法人買賣超
        # 找「外資及陸資」買賣差
        foreign_net = None
        for row in data:
            name = row.get('名稱', '') or row.get('身份別', '')
            if '外資' in name and '陸資' in name:
                try:
                    foreign_net = int(row.get('買賣差額', '0').replace(',', ''))
                    break
                except Exception:
                    pass
        if foreign_net is not None:
            official = foreign_net / 1_000_000   # 元 → 百萬元? 待確認單位
            print(f"  Official (TWSE BFI82U 買賣差額): {foreign_net:,}")
            return {'signal': 'foreign_cash', 'our': our_val, 'official': foreign_net,
                    'unit_note': 'BFI82U raw (千元 or 元)', 'match': None}
        else:
            print(f"  ⚠️ TWSE BFI82U parse fail")
            return {'signal': 'foreign_cash', 'our': our_val, 'official': None,
                    'error': 'parse_fail'}
    except Exception as e:
        print(f"  ⚠️ API error: {e}")
        return {'signal': 'foreign_cash', 'our': our_val, 'error': str(e)}

# ── Signal 2: 外資期貨等效 ──
# Our: 外資期貨.value (大台等效淨 OI)
# Official: TAIFEX 三大法人期貨交易 → 需計算 (大台+小台/4)
def verify_foreign_futures():
    our = signals_our.get('外資期貨', {})
    our_val = our.get('value')
    print(f"\n--- 外資期貨 ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    # TAIFEX 三大法人期貨明細 API 較複雜, 需 daily fetcher, 這裡標為需 fetcher audit
    print(f"  ⚠️ TAIFEX 期貨三大法人 API 需 dedicated fetcher (skip in orchestrator)")
    return {'signal': 'foreign_futures_eq', 'our': our_val,
            'note': 'need dedicated TAIFEX fetcher audit'}

# ── Signal 3: P/C Ratio ──
def verify_pc_ratio():
    our = signals_our.get('P/C Ratio', {})
    our_val = our.get('value')
    print(f"\n--- P/C Ratio ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    try:
        # TAIFEX 選擇權公開報表 (put/call ratio)
        # 用 verify_pcr_vs_taifex.py 的邏輯簡化版
        url = 'https://www.taifex.com.tw/cht/3/pcRatioExcel'
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200 and '日期' in r.text:
            # csv-like data, 找最新日期
            lines = [l for l in r.text.split('\n') if l.strip()]
            if len(lines) > 1:
                last_line = lines[1]   # header 之後第一筆 = 最新
                cols = [c.strip() for c in last_line.split(',')]
                if len(cols) >= 6:
                    try:
                        official_pcr = float(cols[5])  # 通常 col 5 是 P/C OI 比
                        diff = abs(our_val - official_pcr) if our_val else None
                        match = diff < 0.05 if diff is not None else None
                        print(f"  Official (TAIFEX pcRatioExcel): {official_pcr}, diff={diff:.3f}, match={match}")
                        return {'signal': 'pc_ratio_oi', 'our': our_val,
                                'official': official_pcr, 'diff': diff, 'match': match}
                    except (ValueError, IndexError):
                        pass
        print(f"  ⚠️ parse fail")
        return {'signal': 'pc_ratio_oi', 'our': our_val, 'error': 'parse_fail'}
    except Exception as e:
        print(f"  ⚠️ API error: {e}")
        return {'signal': 'pc_ratio_oi', 'our': our_val, 'error': str(e)}

# ── Signal 4: 分點漲停 ──
# Our: 分點漲停.value = 全市場漲停家數
# Official: TWSE MI_INDEX (盤後漲停家數統計)
def verify_limit_up():
    our = signals_our.get('分點漲停', {})
    our_val = our.get('value')
    print(f"\n--- 分點漲停 (limit_up count) ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    try:
        # TWSE MI_INDEX_ALLBUT0999 (上市當日漲跌家數統計)
        roc = _yyyymmdd_to_roc(today)
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={today}&type=IND'
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(r.text)
        # MI_INDEX 有「漲跌家數」統計但通常需要另一 endpoint
        # TWSE 「當日交易統計」 STOCK_DAY_ALL 之類
        # 先試 MI_5MINS (盤後 5min 統計)
        print(f"  ⚠️ TWSE 漲停家數需另 endpoint (MI_STAT), skip orchestrator")
        return {'signal': 'limit_up_count', 'our': our_val,
                'note': 'need MI_STAT dedicated audit'}
    except Exception as e:
        print(f"  ⚠️ API error: {e}")
        return {'signal': 'limit_up_count', 'our': our_val, 'error': str(e)}

# ── Signal 5: 融資熱度 ──
def verify_margin():
    our = signals_our.get('融資熱度', {})
    our_val = our.get('value')
    print(f"\n--- 融資熱度 (margin top5) ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    # 融資餘額 top5 券商 → 需要券商公會 or TWSE MI_MARGN
    # 融資熱度 = 前 5 大券商融資餘額 (億)
    # 我系統若 value=0.0 且 level=neutral → 明顯 fetcher 有問題
    print(f"  ⚠️ Our value=0.0 表示 fetcher 沒拿到 或計算錯; 需 audit fetcher")
    return {'signal': 'margin_top5_yi', 'our': our_val,
            'suspect_bug': our_val == 0.0}

# ── Signal 6/7: 法人共識 ──
def verify_consensus():
    our = signals_our.get('法人共識', {})
    our_val = our.get('value')
    print(f"\n--- 法人共識 (foreign + trust net top) ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    if isinstance(our_val, dict):
        f_net = our_val.get('foreign_net', 0)
        t_net = our_val.get('trust_net', 0)
        if f_net == 0 and t_net == 0:
            print(f"  ⚠️ 兩者皆 0 → 可能 fetcher 沒拿到 個股外資/投信買賣超")
            return {'signal': 'consensus', 'our': our_val, 'suspect_bug': True}
    return {'signal': 'consensus', 'our': our_val, 'suspect_bug': False}

# ── Signal 8: 結算日壓力 ──
def verify_settlement():
    our = signals_our.get('結算日壓力', {})
    our_val = our.get('value')
    print(f"\n--- 結算日壓力 ---")
    print(f"  Our: value={our_val}, level={our.get('level')}")
    if isinstance(our_val, dict):
        days = our_val.get('days_to_settle')
        oi = our_val.get('foreign_eq_oi')
        # 結算日通常每月第三個週三, 用日期直接算
        from datetime import datetime, timedelta
        t = datetime.strptime(today, '%Y%m%d')
        # 找當月/下月第三週三
        first = t.replace(day=1)
        offset = (2 - first.weekday()) % 7   # 週三 = 2
        third_wed = first + timedelta(days=offset + 14)
        our_days = (third_wed - t).days
        if our_days < 0:
            # 已過本月結算 → 找下月
            nm = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            offset2 = (2 - nm.weekday()) % 7
            third_wed = nm + timedelta(days=offset2 + 14)
            our_days = (third_wed - t).days
        match = abs(days - our_days) <= 1 if days is not None else None
        print(f"  Official (計算第三週三): {third_wed.strftime('%Y%m%d')} → {our_days} 天, match={match}")
        return {'signal': 'settlement', 'our_days': days, 'calc_days': our_days,
                'match': match, 'our_oi': oi}
    return {'signal': 'settlement', 'our': our_val}


# === Run all ===
results = []
for f in [verify_foreign_cash, verify_foreign_futures, verify_pc_ratio,
          verify_limit_up, verify_margin, verify_consensus, verify_settlement]:
    try:
        r = f()
        results.append(r)
    except Exception as e:
        print(f"  ✗ verify failed: {e}")
        results.append({'error': str(e), 'signal': f.__name__})

# Summary
print(f"\n\n=== Summary ({today}) ===")
bugs = []
for r in results:
    sig = r.get('signal', '?')
    if r.get('suspect_bug') is True or (r.get('our') in [0, 0.0]):
        bugs.append(sig)
        print(f"  🔴 {sig}: value=0 or suspect bug")
    elif r.get('match') is False:
        bugs.append(sig)
        print(f"  🔴 {sig}: mismatch vs official")
    elif r.get('match') is True:
        print(f"  ✅ {sig}: match")
    else:
        print(f"  ⚪ {sig}: (skip / need dedicated audit)")

print(f"\n🚨 疑似 bug: {len(bugs)} signal → {bugs}")

# Write
import datetime
op = ROOT / 'data' / f'temp_verify_{today}.json'
op.write_text(json.dumps({
    'date': today, 'audited_at': datetime.datetime.now().isoformat(),
    'results': results, 'suspect_bugs': bugs,
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {op}")
