# -*- coding: utf-8 -*-
"""v3.72.9 P2 #6 sniper_top_buyer_enricher 測試

驗證:
  1. 白名單 master 買的漲停股 → fetch histock, is_top_market_buyer 正確
  2. 非白名單 master 不 fetch (省流量)
  3. 空 sniper_ranking → 空 index, 0 fetch
  4. histock 全 fail → is_top_market_buyer=False 一律
  5. top_bno match 該 sn.branch_code → True
  6. top_bno 不 match 該 sn.branch_code → False
  7. top_buyer_index 回傳並含 {stock_code: bno}
  8. stats + fetched_at 回傳
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from unittest.mock import patch

from src.analyzers.sniper_top_buyer_enricher import enrich_sniper_top_buyer

pass_count = 0
fail_count = 0
def check(label, cond):
    global pass_count, fail_count
    if cond:
        print(f"  ✅ {label}")
        pass_count += 1
    else:
        print(f"  ❌ {label}")
        fail_count += 1


# Mock histock: 6577 top = 9A9S, 2330 top = 元大 (非 sniper)
MOCK_HISTOCK = {
    "6577": {"date": "2026/07/24",
             "buys": [{"bno": "9A9S", "net": 200, "buy_lot": 22, "sell_lot": 0}]},
    "2330": {"date": "2026/07/24",
             "buys": [{"bno": "1480", "net": 1000, "buy_lot": 500, "sell_lot": 100}]},
    "8888": {"date": "2026/07/24",
             "buys": [{"bno": "9227", "net": 50, "buy_lot": 5, "sell_lot": 0}]},
}

def mock_fetch(stock_code, timeout=8, max_retries=1):
    return MOCK_HISTOCK.get(stock_code)


# ─── 1. 蔣承翰的 3 分點各買不同漲停股, top 判定 ───
print("\n1. 蔣承翰 3 分點各買不同漲停股, is_top_market_buyer 正確")
limit_up_summary = {
    'sniper_ranking': [
        {
            'master': '蔣承翰',
            'branch_code': '9A9S',
            'branch_name': '永豐金-南京',
            'limit_up_details': [
                {'code': '6577', 'name': '勁豐', 'buy_amt': 200000, 'buy_lot': 22},
            ]
        },
        {
            'master': '蔣承翰',
            'branch_code': '9227',
            'branch_name': '凱基-城中',
            'limit_up_details': [
                {'code': '2330', 'name': '台積電', 'buy_amt': 500000, 'buy_lot': 5},
                {'code': '8888', 'name': 'X 股', 'buy_amt': 50000, 'buy_lot': 5},
            ]
        },
    ]
}

with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_fetch):
    result = enrich_sniper_top_buyer(limit_up_summary, {"蔣承翰"}, trade_date="20260724")

# Verify
d_9A9S_6577 = limit_up_summary['sniper_ranking'][0]['limit_up_details'][0]
d_9227_2330 = limit_up_summary['sniper_ranking'][1]['limit_up_details'][0]
d_9227_8888 = limit_up_summary['sniper_ranking'][1]['limit_up_details'][1]

check("9A9S 買 6577 (top=9A9S) → is_top=True", d_9A9S_6577.get('is_top_market_buyer') is True)
check("9227 買 2330 (top=1480 非蔣承翰) → is_top=False", d_9227_2330.get('is_top_market_buyer') is False)
check("9227 買 8888 (top=9227) → is_top=True", d_9227_8888.get('is_top_market_buyer') is True)

# top_market_buyer_bno 應該存在於所有已 fetch 的
check("6577 → top_market_buyer_bno=9A9S", d_9A9S_6577.get('top_market_buyer_bno') == '9A9S')
check("2330 → top_market_buyer_bno=1480", d_9227_2330.get('top_market_buyer_bno') == '1480')

# ─── 2. 非白名單 master 不受影響 ───
print("\n2. 非白名單 master (民哥) 的 details 不 fetch")
limit_up_summary2 = {
    'sniper_ranking': [
        {'master': '民哥', 'branch_code': '9B25', 'branch_name': '台新-五權西',
         'limit_up_details': [{'code': '6577', 'name': '勁豐', 'buy_amt': 100000, 'buy_lot': 10}]},
    ]
}
with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_fetch) as m:
    result = enrich_sniper_top_buyer(limit_up_summary2, {"蔣承翰"}, trade_date="20260724")
check("民哥 (非白名單) → 0 fetch", m.call_count == 0)
d = limit_up_summary2['sniper_ranking'][0]['limit_up_details'][0]
check("民哥 details 沒 is_top_market_buyer 欄位", 'is_top_market_buyer' not in d)
check("top_buyer_index 為空", result['top_buyer_index'] == {})

# ─── 3. 空 sniper_ranking ───
print("\n3. 空 sniper_ranking → 空 index")
with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_fetch) as m:
    result = enrich_sniper_top_buyer({}, {"蔣承翰"}, trade_date="20260724")
check("空 dict → 0 fetch", m.call_count == 0)
check("top_buyer_index = {}", result['top_buyer_index'] == {})

# ─── 4. histock 全 fail ───
print("\n4. histock 全 fail → is_top 一律 False + top_bno 不寫")
def mock_fail(code, timeout=8, max_retries=1):
    return None

limit_up_summary4 = {
    'sniper_ranking': [
        {'master': '蔣承翰', 'branch_code': '9A9S', 'branch_name': '永豐金-南京',
         'limit_up_details': [{'code': '6577', 'name': '勁豐', 'buy_amt': 200000, 'buy_lot': 22}]},
    ]
}
with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_fail):
    result = enrich_sniper_top_buyer(limit_up_summary4, {"蔣承翰"}, trade_date="20260724")
d = limit_up_summary4['sniper_ranking'][0]['limit_up_details'][0]
check("全 fail → is_top_market_buyer=False", d.get('is_top_market_buyer') is False)
check("全 fail → 沒有 top_market_buyer_bno 欄位", 'top_market_buyer_bno' not in d)
check("top_buyer_index = {}", result['top_buyer_index'] == {})

# ─── 5. 時效 guard 傳遞 ───
print("\n5. 時效 guard: histock date != trade_date → is_top=False")
def mock_stale(code, timeout=8, max_retries=1):
    return {"date": "2026/07/23",  # T-1
            "buys": [{"bno": "9A9S", "net": 200, "buy_lot": 22, "sell_lot": 0}]}
limit_up_summary5 = {
    'sniper_ranking': [
        {'master': '蔣承翰', 'branch_code': '9A9S', 'branch_name': '永豐金-南京',
         'limit_up_details': [{'code': '6577', 'name': '勁豐', 'buy_amt': 200000, 'buy_lot': 22}]},
    ]
}
with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_stale):
    result = enrich_sniper_top_buyer(limit_up_summary5, {"蔣承翰"}, trade_date="20260724")
d = limit_up_summary5['sniper_ranking'][0]['limit_up_details'][0]
check("stale date (T-1) → is_top=False (safe skip)",
      d.get('is_top_market_buyer') is False)

# ─── 6. 回傳格式 ───
print("\n6. 回傳格式含 top_buyer_index / stats / fetched_at")
with patch("src.audit.histock_branch_audit.fetch_histock_branch", side_effect=mock_fetch):
    result = enrich_sniper_top_buyer(limit_up_summary, {"蔣承翰"}, trade_date="20260724")
check("回傳含 top_buyer_index", 'top_buyer_index' in result)
check("回傳含 stats", 'stats' in result)
check("回傳含 fetched_at", 'fetched_at' in result and result['fetched_at'])

# ─── 總結 ───
print(f"\n{'─' * 60}")
print(f"整體: {pass_count} pass / {fail_count} fail")
sys.exit(0 if fail_count == 0 else 1)
