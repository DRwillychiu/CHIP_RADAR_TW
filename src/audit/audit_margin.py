"""
audit_margin.py — v3.21 融資融券審計

對齊資料源:
  TWSE: https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN (上市)
  TPEx: TPEx OpenAPI

驗證方式:
  1. 直接從 TWSE OpenAPI 抓 raw data
  2. 用 margin.py 解析
  3. 逐欄位對比 (融資餘額/融券餘額/融資買進/融資賣出/融券賣出 等)
  4. 找出差異 → 修正
"""

import sys
import requests
import json
from typing import Dict, Any

sys.path.insert(0, '.')
import margin


# ════════════════════════════════════════════════════════════════════
#  獨立解析 TWSE Margin (作為 ground truth)
# ════════════════════════════════════════════════════════════════════

def fetch_official_margin() -> Dict[str, dict]:
    """直接從 TWSE OpenAPI 抓融資融券 raw data"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    r.raise_for_status()
    raw = r.json()
    
    if not raw:
        return {}
    
    # 看欄位
    print(f"  TWSE Margin OpenAPI 欄位:")
    if raw:
        for k in raw[0].keys():
            print(f"    • {k}")
    print()
    
    def parse_int(v):
        try: return int(str(v).replace(',', '').strip())
        except (ValueError, AttributeError): return 0
    
    result = {}
    for row in raw:
        code = row.get('股票代號', '').strip()
        if not code:
            continue
        
        result[code] = {
            'name': row.get('股票名稱', '').strip(),
            
            # 融資 6 欄位
            'margin_buy': parse_int(row.get('融資買進')),
            'margin_sell': parse_int(row.get('融資賣出')),
            'margin_redeem': parse_int(row.get('融資現金償還')),
            'margin_prev': parse_int(row.get('融資前日餘額')),
            'margin_balance': parse_int(row.get('融資今日餘額')),
            'margin_quota': parse_int(row.get('融資限額')),
            
            # 融券 6 欄位
            'short_buy': parse_int(row.get('融券買進')),
            'short_sell': parse_int(row.get('融券賣出')),
            'short_redeem': parse_int(row.get('融券現券償還')),
            'short_prev': parse_int(row.get('融券前日餘額')),
            'short_balance': parse_int(row.get('融券今日餘額')),
            'short_quota': parse_int(row.get('融券限額')),
            
            # 資券互抵
            'offsetting': parse_int(row.get('資券互抵')),
        }
    return result


# ════════════════════════════════════════════════════════════════════
#  對比審計
# ════════════════════════════════════════════════════════════════════

def audit_margin() -> Dict[str, Any]:
    """執行完整融資融券審計"""
    
    print("═" * 75)
    print(f"  🔍 融資融券審計 (TWSE OpenAPI)")
    print("═" * 75)
    print()
    
    # 1. 獨立抓官方資料 (ground truth)
    print("【1】從 TWSE OpenAPI 抓官方資料 (獨立解析)")
    official = fetch_official_margin()
    if not official:
        print("  ❌ 無資料")
        return {'pass': False}
    
    print(f"  ✅ 官方資料: {len(official)} 檔個股")
    print()
    
    # 2. 用 margin.py 抓 (受測對象)
    print("【2】用 margin.fetch_twse_margin 抓系統資料")
    system = margin.fetch_twse_margin()
    print(f"  ✅ 系統資料: {len(system)} 檔個股")
    print()
    
    # 3. 逐檔比對
    print("【3】逐檔對比 (12 個融資融券核心欄位)")
    
    common_codes = set(official.keys()) & set(system.keys())
    print(f"  共同個股: {len(common_codes)}")
    print()
    
    # 12 個核心欄位
    fields_to_check = [
        # 融資
        'margin_buy', 'margin_sell', 'margin_redeem',
        'margin_prev', 'margin_balance', 'margin_quota',
        # 融券
        'short_buy', 'short_sell', 'short_redeem',
        'short_prev', 'short_balance', 'short_quota',
    ]
    
    field_pass = {f: 0 for f in fields_to_check}
    field_total = {f: 0 for f in fields_to_check}
    
    sample_mismatches = []
    
    for code in common_codes:
        off = official[code]
        sys_d = system[code]
        
        for field in fields_to_check:
            field_total[field] += 1
            o = off.get(field, 0)
            s = sys_d.get(field, 0)
            if o == s:
                field_pass[field] += 1
            else:
                if len(sample_mismatches) < 8:
                    sample_mismatches.append({
                        'code': code, 'field': field, 'official': o, 'system': s, 'diff': s - o
                    })
    
    # 4. 報告
    print("【4】審計結果")
    print()
    print(f"  {'欄位':<20} {'通過':>10} {'總數':>10} {'比率':>10}")
    print(f"  {'-'*52}")
    for field in fields_to_check:
        match_rate = (field_pass[field] / field_total[field] * 100) if field_total[field] > 0 else 0
        emoji = '✅' if match_rate == 100.0 else '⚠️' if match_rate > 95 else '❌'
        print(f"  {emoji} {field:<18} {field_pass[field]:>10} {field_total[field]:>10} {match_rate:>9.2f}%")
    
    print()
    if sample_mismatches:
        print(f"  不匹配樣本 (前 8 個):")
        for m in sample_mismatches:
            print(f"    {m['code']} {m['field']}: 官方={m['official']:,} 系統={m['system']:,} (差 {m['diff']:+,})")
    else:
        print(f"  ✅ 零不匹配 (完美對齊)")
    
    # 5. 統計
    only_in_system = set(system.keys()) - set(official.keys())
    only_in_official = set(official.keys()) - set(system.keys())
    if only_in_system:
        print(f"\n  ⚠️ 只在系統有 (前 5): {list(only_in_system)[:5]}")
    if only_in_official:
        print(f"\n  ⚠️ 只在官方有 (前 5): {list(only_in_official)[:5]}")
    
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
        'sample_mismatches': sample_mismatches,
        'common_codes_count': len(common_codes),
        'fields_count': len(fields_to_check),
    }


if __name__ == '__main__':
    result = audit_margin()
    
    # 儲存結果
    with open('/tmp/audit_margin.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 結果儲存: /tmp/audit_margin.json")
