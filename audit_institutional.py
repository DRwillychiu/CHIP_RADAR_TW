"""
audit_institutional.py — v3.21 三大法人 audit script

對齊資料源:
  TWSE: https://www.twse.com.tw/fund/T86 (上市三大法人買賣超)
  TPEx: TPEx 三大法人買賣超

驗證方式:
  1. 直接從 TWSE 官方 T86 API 抓 raw data
  2. 用同樣的 institutional.py 解析
  3. 逐欄位對比 (code, foreign_net, trust_net, dealer_net, total)
  4. 找出差異 → 修正
"""

import sys
import requests
import json
from typing import Dict, Any, List

sys.path.insert(0, '.')
import institutional


# ════════════════════════════════════════════════════════════════════
#  獨立解析 TWSE T86 (不依賴 institutional.py, 用最原始方式)
# ════════════════════════════════════════════════════════════════════

def fetch_official_t86(trade_date: str) -> Dict[str, dict]:
    """
    直接從 TWSE 官方 T86 API 抓資料,獨立解析作為 ground truth
    """
    url = f"https://www.twse.com.tw/fund/T86?response=json&date={trade_date}&selectType=ALL"
    
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    }
    
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    d = r.json()
    
    if d.get('stat') != 'OK':
        return {}
    
    data = d.get('data', [])
    fields = d.get('fields', [])
    print(f"  TWSE T86 欄位 ({len(fields)} 個):")
    for i, f in enumerate(fields):
        print(f"    [{i}] {f}")
    print()
    
    # 用 fields 精準匹配 (避免「自營商」匹配到「外資自營商」)
    def find_idx_exact(target):
        for i, f in enumerate(fields):
            if f == target:
                return i
        return None
    
    idx_code = find_idx_exact('證券代號')
    idx_foreign_net = find_idx_exact('外陸資買賣超股數(不含外資自營商)')
    idx_foreign_dealer_net = find_idx_exact('外資自營商買賣超股數')
    idx_trust_net = find_idx_exact('投信買賣超股數')
    idx_dealer_net = find_idx_exact('自營商買賣超股數')          # [11] 合計
    idx_dealer_self_net = find_idx_exact('自營商買賣超股數(自行買賣)')  # [14]
    idx_dealer_hedge_net = find_idx_exact('自營商買賣超股數(避險)')     # [17]
    idx_total = find_idx_exact('三大法人買賣超股數')
    
    print(f"  解析欄位 index:")
    print(f"    code={idx_code}, foreign={idx_foreign_net}, foreign_dealer={idx_foreign_dealer_net}")
    print(f"    trust={idx_trust_net}, dealer={idx_dealer_net}, total={idx_total}")
    print()
    
    result = {}
    for row in data:
        try:
            code = str(row[idx_code]).strip()
            if not code:
                continue
            
            def parse_int(v):
                try: return int(str(v).replace(',', ''))
                except (ValueError, AttributeError): return 0
            
            # 對齊 institutional.py 的算法:
            # foreign_net = 外陸資 [4] + 外資自營商 [7]
            # dealer_net = 自行買賣 [14] + 避險 [17] (等同合計 [11])
            foreign_net = parse_int(row[idx_foreign_net]) + parse_int(row[idx_foreign_dealer_net])
            trust_net = parse_int(row[idx_trust_net])
            dealer_net = parse_int(row[idx_dealer_net])  # 合計 [11]
            total_net = parse_int(row[idx_total])
            
            result[code] = {
                'foreign_net_股': foreign_net,
                'trust_net_股': trust_net,
                'dealer_net_股': dealer_net,
                'total_net_股': total_net,
                # 換算成 張 (1 張 = 1000 股)
                'foreign_net_lot': foreign_net // 1000,
                'trust_net_lot': trust_net // 1000,
                'dealer_net_lot': dealer_net // 1000,
                'total_net_lot': total_net // 1000,
            }
        except (ValueError, IndexError, TypeError):
            continue
    
    return result


# ════════════════════════════════════════════════════════════════════
#  對比審計
# ════════════════════════════════════════════════════════════════════

def audit_three_legal(trade_date: str) -> Dict[str, Any]:
    """執行完整三大法人審計"""
    
    print("═" * 75)
    print(f"  🔍 三大法人審計 (TWSE T86, {trade_date})")
    print("═" * 75)
    print()
    
    # 1. 獨立抓官方資料 (ground truth)
    print("【1】從 TWSE T86 抓官方資料 (獨立解析)")
    official = fetch_official_t86(trade_date)
    if not official:
        print("  ❌ 無資料")
        return {'pass': False}
    
    print(f"  ✅ 官方資料: {len(official)} 檔個股")
    print()
    
    # 2. 用 institutional.py 抓 (受測對象)
    print("【2】用 institutional.fetch_twse_t86 抓系統資料")
    system = institutional.fetch_twse_t86(trade_date)
    print(f"  ✅ 系統資料: {len(system)} 檔個股")
    print()
    
    # 3. 逐檔比對
    print("【3】逐檔對比 (foreign_net / trust_net / dealer_net / total_net)")
    
    common_codes = set(official.keys()) & set(system.keys())
    print(f"  共同個股: {len(common_codes)}")
    
    mismatch_count = 0
    field_pass = {'foreign_net_lot': 0, 'trust_net_lot': 0, 'dealer_net_lot': 0, 'total_net_lot': 0}
    field_total = {'foreign_net_lot': 0, 'trust_net_lot': 0, 'dealer_net_lot': 0, 'total_net_lot': 0}
    
    sample_mismatches = []
    
    for code in common_codes:
        off = official[code]
        sys_d = system[code]
        
        for field in ['foreign_net_lot', 'trust_net_lot', 'dealer_net_lot', 'total_net_lot']:
            field_total[field] += 1
            o = off.get(field, 0)
            s = sys_d.get(field, 0)
            if o == s:
                field_pass[field] += 1
            else:
                mismatch_count += 1
                if len(sample_mismatches) < 5:
                    sample_mismatches.append({
                        'code': code, 'field': field, 'official': o, 'system': s, 'diff': s - o
                    })
    
    # 4. 報告
    print()
    print("【4】審計結果")
    print()
    for field in ['foreign_net_lot', 'trust_net_lot', 'dealer_net_lot', 'total_net_lot']:
        match_rate = (field_pass[field] / field_total[field] * 100) if field_total[field] > 0 else 0
        emoji = '✅' if match_rate == 100.0 else '⚠️' if match_rate > 95 else '❌'
        print(f"  {emoji} {field}: {field_pass[field]}/{field_total[field]} = {match_rate:.2f}%")
    
    print()
    if sample_mismatches:
        print(f"  不匹配樣本 (前 5 個):")
        for m in sample_mismatches:
            print(f"    {m['code']} {m['field']}: 官方={m['official']:,} 系統={m['system']:,} (差 {m['diff']:+,})")
    else:
        print(f"  ✅ 零不匹配 (完美對齊)")
    
    # 5. 只在系統有但官方沒有的個股
    only_in_system = set(system.keys()) - set(official.keys())
    only_in_official = set(official.keys()) - set(system.keys())
    if only_in_system:
        print(f"\n  ⚠️ 只在系統有的個股 (前 5): {list(only_in_system)[:5]}")
    if only_in_official:
        print(f"\n  ⚠️ 只在官方有的個股 (前 5): {list(only_in_official)[:5]}")
    
    print()
    total_pass = sum(field_pass.values())
    total_count = sum(field_total.values())
    overall_rate = (total_pass / total_count * 100) if total_count > 0 else 0
    print("═" * 75)
    print(f"  📈 總體通過率: {total_pass:,} / {total_count:,} = {overall_rate:.2f}%")
    print("═" * 75)
    
    return {
        'pass': overall_rate == 100.0,
        'overall_rate': overall_rate,
        'field_results': {f: {
            'pass': field_pass[f], 'total': field_total[f],
            'rate': (field_pass[f] / field_total[f] * 100) if field_total[f] > 0 else 0
        } for f in field_pass},
        'mismatch_count': mismatch_count,
        'sample_mismatches': sample_mismatches,
        'only_in_system_count': len(only_in_system),
        'only_in_official_count': len(only_in_official),
        'common_codes_count': len(common_codes),
    }


if __name__ == '__main__':
    # 用最近一個交易日 (4/30 週四)
    trade_date = sys.argv[1] if len(sys.argv) > 1 else '20260430'
    result = audit_three_legal(trade_date)
    
    # 儲存結果
    with open(f'/tmp/audit_institutional_{trade_date}.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 結果儲存: /tmp/audit_institutional_{trade_date}.json")
