"""v3.63.2 共同買超 雙重驗證 — 比對「網站共買榜邏輯」vs「Dashboard Section 0 嚴格邏輯」

網站共買榜定義 (index.html buildStockIndex + render):
  - 來源: branches[].buys[] (該分點當日 top-15 買進金額榜)
  - 共買分點數 = stock 出現在多少個分點的 buys 清單
  - ⚠️ 不過濾 net > 0 — 一個分點即使「買 200 賣 250 (淨賣 -50)」仍算 1 共買
  - totalNet = 加總所有分點的 net_amt (可能負)

Dashboard Section 0 定義 (本檔嚴格版, 對應使用者「買超」spec):
  - 來源: 同上 branches[].buys[]
  - 共買分點數 = 該分點 net_amt > 0 的分點數
  - 嚴格過濾 net > 0 — 上面例子「買 200 賣 250」不算共買

兩者都只看追蹤清單 (TRACKED_MASTERS).
"""
import sys, json
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.exports.excel_report import TRACKED_MASTERS, MASTER_MAPPING

# ── 構造測試 branches_data (covers 4 case: 嚴格通過 / 嚴格剔除 / 邊界 / 大戶不在追蹤) ──
branches_data = [
    # CASE A: 2330 — 3 分點全部 net>0, 兩個邏輯結果相同
    {'code': '9B25', 'name': '台新-五權西', 'master': '民哥', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_amt': 250000, 'sell_amt': 50000,
         'net_amt': 200000, 'buy_lot': 100, 'sell_lot': 20, 'net_lot': 80,
         'change_pct': 1.0, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9666', 'name': '富邦-南屯', 'master': '民哥', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_amt': 150000, 'sell_amt': 25000,
         'net_amt': 125000, 'buy_lot': 60, 'sell_lot': 10, 'net_lot': 50,
         'change_pct': 1.0, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9658', 'name': '富邦-建國', 'master': '林滄海', 'buys': [
        {'code': '2330', 'name': '台積電', 'buy_amt': 125000, 'sell_amt': 25000,
         'net_amt': 100000, 'buy_lot': 50, 'sell_lot': 10, 'net_lot': 40,
         'change_pct': 1.0, 'is_limit_up': False},
    ], 'sells': []},
    # CASE B: 2454 — 民哥分點 net>0 (進), 蔣承翰分點 net<0 (反向)
    # → 網站邏輯算 2 共買; 嚴格邏輯算 1
    {'code': '9B25', 'name': '台新-五權西', 'master': '民哥', 'buys': [
        {'code': '2454', 'name': '聯發科', 'buy_amt': 90000, 'sell_amt': 15000,
         'net_amt': 75000, 'buy_lot': 30, 'sell_lot': 5, 'net_lot': 25,
         'change_pct': 9.9, 'is_limit_up': True},
    ], 'sells': []},
    {'code': '9227', 'name': '凱基-城中', 'master': '蔣承翰', 'buys': [
        {'code': '2454', 'name': '聯發科', 'buy_amt': 80000, 'sell_amt': 110000,
         'net_amt': -30000, 'buy_lot': 40, 'sell_lot': 55, 'net_lot': -15,
         'change_pct': 9.9, 'is_limit_up': True},
    ], 'sells': []},
    # CASE C: 00919 — 2 分點都 net>0 不同大戶, 兩邏輯結果同
    {'code': '779Z', 'name': '國票-安和', 'master': '張濬安(航海王)', 'buys': [
        {'code': '00919', 'name': '群益台灣精選高息', 'buy_amt': 200000, 'sell_amt': 0,
         'net_amt': 200000, 'buy_lot': 10000, 'sell_lot': 0, 'net_lot': 10000,
         'change_pct': 0.5, 'is_limit_up': False},
    ], 'sells': []},
    {'code': '9B2a', 'name': '台新-松德', 'master': 'Tradow', 'buys': [
        {'code': '00919', 'name': '群益台灣精選高息', 'buy_amt': 100000, 'sell_amt': 0,
         'net_amt': 100000, 'buy_lot': 5000, 'sell_lot': 0, 'net_lot': 5000,
         'change_pct': 0.5, 'is_limit_up': False},
    ], 'sells': []},
    # CASE D: 9999 — 非追蹤大戶 (江士勳), 兩邏輯都應該排除
    {'code': '888A', 'name': '國泰-館前', 'master': '江士勳', 'buys': [
        {'code': '9999', 'name': '不應出現股', 'buy_amt': 500000, 'sell_amt': 100000,
         'net_amt': 400000, 'buy_lot': 100, 'sell_lot': 20, 'net_lot': 80,
         'change_pct': 0.0, 'is_limit_up': False},
    ], 'sells': []},
]

def website_consensus(branches_data, only_tracked=True, side='buy', rank_type='amount'):
    """模擬 index.html buildStockIndex (v3.63.3 後嚴格 net 過濾版).
    現在與 strict_consensus 邏輯應 100% 一致.
    """
    stock_map = {}
    for b in branches_data:
        if only_tracked and b.get('master') not in TRACKED_MASTERS:
            continue
        source_key = 'sells' if side == 'sell' else 'buys'
        for s in (b.get(source_key) or []):
            # v3.63.3 嚴格 net 方向過濾
            s_net_amt = s.get('net_amt') or 0
            s_net_lot = s.get('net_lot') or 0
            net_for_filter = s_net_lot if rank_type == 'lots' else s_net_amt
            if side == 'buy' and net_for_filter <= 0:
                continue
            if side == 'sell' and net_for_filter >= 0:
                continue
            key = (s['code'], s.get('name', ''))
            if key not in stock_map:
                stock_map[key] = {'branches': [], 'totalNet': 0, 'totalBuy': 0}
            stock_map[key]['branches'].append({
                'master': b['master'], 'branch_code': b['code'],
                'branch_name': b['name'], 'net': s_net_amt,
            })
            stock_map[key]['totalNet'] += s_net_amt
            stock_map[key]['totalBuy'] += (s.get('buy_amt') or 0)
    out = []
    for (code, name), info in stock_map.items():
        if len(info['branches']) >= 2:
            out.append({
                'code': code, 'name': name,
                'branch_count': len(info['branches']),
                'totalNet': info['totalNet'],
                'branches': info['branches'],
            })
    out.sort(key=lambda x: (-x['branch_count'], -x['totalNet']))
    return out

def strict_consensus(branches_data, only_tracked=True):
    """Section 0 嚴格邏輯 — 只算 net > 0 的分點."""
    stock_map = {}
    for b in branches_data:
        if only_tracked and b.get('master') not in TRACKED_MASTERS:
            continue
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            net = (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
            if net <= 0:
                continue
            key = (s['code'], s.get('name', ''))
            if key not in stock_map:
                stock_map[key] = {'branches': [], 'totalNet': 0}
            stock_map[key]['branches'].append({
                'master': b['master'], 'branch_code': b['code'],
                'branch_name': b['name'], 'net': net,
            })
            stock_map[key]['totalNet'] += net
    out = []
    for (code, name), info in stock_map.items():
        if len(info['branches']) >= 2:
            out.append({
                'code': code, 'name': name,
                'branch_count': len(info['branches']),
                'totalNet': info['totalNet'],
                'branches': info['branches'],
            })
    out.sort(key=lambda x: (-x['branch_count'], -x['totalNet']))
    return out

# ── 跑兩個邏輯 ──
web = website_consensus(branches_data)
strict = strict_consensus(branches_data)

print("="*78)
print("方法 A: 網站「共買榜」邏輯 (不過濾 net>0, 只看分點是否進 top-buys)")
print("="*78)
for i, item in enumerate(web):
    print(f"  #{i+1}: {item['code']}({item['name']}) — {item['branch_count']} 分點 / 合計淨買 {int(item['totalNet']/10):,}萬")
    for br in item['branches']:
        sign = '✓買超' if br['net'] > 0 else '✗淨賣!'
        print(f"      [{sign}] {br['master']} ({br['branch_name']}): net={int(br['net']/10):,}萬")

print()
print("="*78)
print("方法 B: Dashboard Section 0 「嚴格買超」邏輯 (只算 net>0 分點)")
print("="*78)
for i, item in enumerate(strict):
    print(f"  #{i+1}: {item['code']}({item['name']}) — {item['branch_count']} 分點 / 合計淨買 {int(item['totalNet']/10):,}萬")
    for br in item['branches']:
        print(f"      [✓買超] {br['master']} ({br['branch_name']}): net={int(br['net']/10):,}萬")

print()
print("="*78)
print("差異分析")
print("="*78)
web_codes = {item['code'] for item in web}
strict_codes = {item['code'] for item in strict}
only_web = web_codes - strict_codes
only_strict = strict_codes - web_codes
print(f"  網站有 / 嚴格沒有: {only_web}")
print(f"  嚴格有 / 網站沒有: {only_strict}")
print(f"  兩者皆有: {web_codes & strict_codes}")
# 同 code 但 branch_count 不同
common = web_codes & strict_codes
for code in common:
    w = next(x for x in web if x['code'] == code)
    s = next(x for x in strict if x['code'] == code)
    if w['branch_count'] != s['branch_count']:
        print(f"  ⚠️ {code}: 網站算 {w['branch_count']} 分點, 嚴格算 {s['branch_count']} 分點")
        print(f"      (差異: 該股有分點淨賣但仍出現在其 buys top-15)")

print()
print("="*78)
print("✅ 用戶 spec 對齊驗證")
print("="*78)
print("使用者 spec: 「篩選條件只要是兩個分點有買超就上榜」")
print("「買超」= net > 0 → 嚴格邏輯 (方法 B) 才符合此 spec.")
print()
print("不應入榜 (但網站邏輯會誤判) 的個案:")
for code in only_web:
    w = next(x for x in web if x['code'] == code)
    n_buy = sum(1 for br in w['branches'] if br['net'] > 0)
    n_sell = sum(1 for br in w['branches'] if br['net'] <= 0)
    print(f"  {code}({w['name']}): 網站算 {w['branch_count']} 共買 (內含 {n_sell} 個其實是淨賣) → 嚴格剔除 ✓")
