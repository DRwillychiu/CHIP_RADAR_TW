"""v3.64.5 P/C Ratio 與 TAIFEX 官方交叉驗證 (公開資訊源 — 終極 ground truth)

用途: 直接呼叫現有 fetch_official_pcr() 抓 TAIFEX 官方 P/C Ratio,
      與 temp_history.json 的 raw value 比對, 確認 Q5 banner 上游精準度.

執行條件: 需網路 + TAIFEX 可達
"""
import sys, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── 讀本機 temp_history 最新 P/C Ratio raw value ──
with open(ROOT / 'data' / 'temp_history.json', 'r', encoding='utf-8') as f:
    th = json.load(f)
latest_entry = (th.get('history') or [])[-1]
trade_date = latest_entry.get('date')
pcr_sig = next((s for s in latest_entry.get('signals', []) if s.get('name') == 'P/C Ratio'), None)
if not pcr_sig:
    print("❌ temp_history 找不到 P/C Ratio")
    sys.exit(1)
local_pcr = pcr_sig.get('value')
local_level = pcr_sig.get('level')
print(f"=== 本機 temp_history ({trade_date}) ===")
print(f"  P/C OI Ratio = {local_pcr}")
print(f"  Level = {local_level}")
print()

# ── 用現有 fetcher 抓 TAIFEX 官方 ──
print(f"=== TAIFEX 官方 fetch_official_pcr({trade_date}) ===")
try:
    from src.fetchers.futures import fetch_official_pcr
    official = fetch_official_pcr(trade_date)
    if not official:
        print(f"  ⚠️ TAIFEX 沒有 {trade_date} 資料 (可能非交易日 / TAIFEX 還沒 publish)")
        sys.exit(0)
    print(f"  TAIFEX 日期: {official['date']}")
    print(f"  P/C OI Ratio = {official['pcr_oi']}")
    print(f"  Call OI: {official['call_oi']:,} / Put OI: {official['put_oi']:,}")
    print()

    # ── Cross-validate ──
    print(f"=== Cross-Validate ===")
    diff = abs(official['pcr_oi'] - float(local_pcr))
    if diff < 0.001:
        print(f"  ✅ PASS: TAIFEX {official['pcr_oi']} == 本機 {local_pcr} (diff {diff:.6f})")
    else:
        print(f"  ❌ FAIL: TAIFEX {official['pcr_oi']} ≠ 本機 {local_pcr} (diff {diff:.4f})")
        sys.exit(1)
except Exception as e:
    print(f"  ⚠️ 抓 TAIFEX 失敗: {type(e).__name__}: {e}")
    print(f"  (網路問題不影響 cross_validate_dashboard.py L1-L3 三層內部驗證)")
