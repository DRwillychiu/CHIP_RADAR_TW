"""v3.27.3 stale-data 偵測測試
驗證:
  1. _yyyymmdd_to_roc 西元↔民國轉換
  2. fetch_twse_daily_quotes 收到舊日期資料 → 回傳 {} 觸發 fallback
  3. fetch_twse_daily_quotes 收到當日資料 → 正常解析
  4. _fetch_taiex_index 收到舊日期資料 → 回傳 None
  5. _fetch_taiex_index 收到當日資料 → 正常解析
"""
import json
import sys
from unittest.mock import patch, MagicMock

# Import target modules
sys.path.insert(0, '.')
import institutional
import history


def make_mock_response(json_data, status=200):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status = MagicMock()
    m.json = MagicMock(return_value=json_data)
    m.text = json.dumps(json_data, ensure_ascii=False)
    m.encoding = 'utf-8'
    return m


print("=" * 64)
print("  v3.27.3 stale-data 偵測測試")
print("=" * 64)

# ────────────── 1. _yyyymmdd_to_roc ──────────────
print("\n1. _yyyymmdd_to_roc")
cases = [
    ('20260511', '1150511'),
    ('20260101', '1150101'),
    ('20251231', '1141231'),
    ('', ''),
    ('2026051', ''),  # 長度錯誤
    ('20260X11', ''),  # 含非數字
]
all_pass = True
for inp, expected in cases:
    actual = institutional._yyyymmdd_to_roc(inp)
    ok = actual == expected
    print(f"  {'✅' if ok else '❌'} '{inp}' → '{actual}' (expect '{expected}')")
    if not ok:
        all_pass = False

# ────────────── 2-3. fetch_twse_daily_quotes stale 偵測 ──────────────
print("\n2. fetch_twse_daily_quotes 收到 5/8 舊資料 (預期 5/11)")
stale_data = [
    {"Date": "1150508", "Code": "2330", "Name": "台積電",
     "ClosingPrice": "2290", "OpeningPrice": "2300",
     "HighestPrice": "2300", "LowestPrice": "2280",
     "TradeVolume": "31000000", "Change": "-20"}
]
with patch('institutional.requests.get', return_value=make_mock_response(stale_data)):
    result = institutional.fetch_twse_daily_quotes(expected_trade_date='20260511')
ok = result == {}
print(f"  {'✅' if ok else '❌'} stale 應回傳 {{}} 觸發 fallback, 實際: {len(result)} 檔")
if not ok:
    all_pass = False

print("\n3. fetch_twse_daily_quotes 收到 5/11 當日資料 (預期 5/11)")
fresh_data = [
    {"Date": "1150511", "Code": "2330", "Name": "台積電",
     "ClosingPrice": "2235", "OpeningPrice": "2280",
     "HighestPrice": "2290", "LowestPrice": "2230",
     "TradeVolume": "46000000", "Change": "-55"}
]
with patch('institutional.requests.get', return_value=make_mock_response(fresh_data)):
    result = institutional.fetch_twse_daily_quotes(expected_trade_date='20260511')
ok = len(result) == 1 and result.get('2330', {}).get('close') == 2235.0
print(f"  {'✅' if ok else '❌'} fresh 應回 1 檔 close=2235, 實際: {len(result)} 檔, 2330 close={result.get('2330', {}).get('close')}")
if not ok:
    all_pass = False
ok2 = result.get('2330', {}).get('quote_date') == '1150511'
print(f"  {'✅' if ok2 else '❌'} quote_date 應為 1150511, 實際: {result.get('2330', {}).get('quote_date')}")
if not ok2:
    all_pass = False

# ────────────── 4-5. _fetch_taiex_index stale 偵測 ──────────────
print("\n4. _fetch_taiex_index 收到 5/8 舊 MI_INDEX (預期 5/11)")
stale_taiex = [
    {"Date": "1150508", "指數": "發行量加權股價指數",
     "收盤指數": "41,603.94", "漲跌": "+", "漲跌百分比": "0.79"}
]
with patch('history.requests.get', return_value=make_mock_response(stale_taiex)):
    result = history._fetch_taiex_index(expected_trade_date='20260511')
ok = result is None
print(f"  {'✅' if ok else '❌'} stale 應回 None, 實際: {result}")
if not ok:
    all_pass = False

print("\n5. _fetch_taiex_index 收到 5/11 當日 MI_INDEX (預期 5/11)")
fresh_taiex = [
    {"Date": "1150511", "指數": "發行量加權股價指數",
     "收盤指數": "41,200.00", "漲跌": "-", "漲跌百分比": "0.97"}
]
with patch('history.requests.get', return_value=make_mock_response(fresh_taiex)):
    result = history._fetch_taiex_index(expected_trade_date='20260511')
ok = result is not None and result.get('index') == 41200.0 and result.get('change_pct') == -0.97
print(f"  {'✅' if ok else '❌'} fresh 應回 index=41200 / -0.97%, 實際: {result}")
if not ok:
    all_pass = False
ok2 = result and result.get('quote_date') == '1150511'
print(f"  {'✅' if ok2 else '❌'} quote_date 應為 1150511, 實際: {result.get('quote_date') if result else None}")
if not ok2:
    all_pass = False

# ────────────── 6. 回溯相容: 不傳 expected_trade_date 行為不變 ──────────────
print("\n6. backward compat: 不傳 expected_trade_date → 即使日期不對也接受 (向後相容)")
with patch('institutional.requests.get', return_value=make_mock_response(stale_data)):
    result = institutional.fetch_twse_daily_quotes()  # no expected_trade_date
ok = len(result) == 1
print(f"  {'✅' if ok else '❌'} 不檢查日期應正常解析,實際: {len(result)} 檔")
if not ok:
    all_pass = False

print()
print("─" * 64)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ FAIL'}")
sys.exit(0 if all_pass else 1)
