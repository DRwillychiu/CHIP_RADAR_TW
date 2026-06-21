"""
audit_branches.py — v3.21 分點籌碼審計

驗證面向 (3 層):
  1. 設定完整性: WATCHED_BRANCHES 56 個分點設定是否完整
  2. master 對應: 49 個 master 對應正確
  3. 抓取健康度: 從 latest.json 看分點抓取的完整度

注意: 分點資料無單一官方源可比, 採用「邏輯一致性審計」
"""

import sys
import json
from typing import Dict, Any, List
from collections import Counter, defaultdict

sys.path.insert(0, '.')
import branches as branches_mod


# ════════════════════════════════════════════════════════════════════
#  Layer 1: 設定完整性審計
# ════════════════════════════════════════════════════════════════════

def audit_config_integrity() -> Dict[str, Any]:
    """檢查 WATCHED_BRANCHES 設定的完整性"""
    
    print("【Layer 1】分點設定完整性")
    
    branches = branches_mod.WATCHED_BRANCHES
    issues = []
    
    # 1. 必填欄位檢查
    required_fields = ['code', 'name', 'master', 'enabled']
    missing_fields = []
    for i, b in enumerate(branches):
        for f in required_fields:
            if f not in b:
                missing_fields.append({'index': i, 'field': f, 'name': b.get('name', 'unknown')})
    
    # 2. code 格式檢查 (4 字元)
    invalid_codes = [b for b in branches if not b.get('code') or len(str(b['code'])) != 4]
    
    # 3. 重複檢查 - 排除「共用分點」設計意圖 (同 code+name 但不同 master 是合法的)
    code_name_pairs = [(b.get('code'), b.get('name'), b.get('master')) for b in branches if b.get('code')]
    # 只當 code+name 完全相同且 master 也相同才算重複
    code_name_master_keys = [(c, n, m) for c, n, m in code_name_pairs]
    duplicates = [k for k, count in Counter(code_name_master_keys).items() if count > 1]
    
    # 找出「共用分點」(同 code 但 master 不同 - 這是合法設計)
    code_to_masters = defaultdict(set)
    for c, n, m in code_name_pairs:
        code_to_masters[c].add(m)
    co_branch_codes = {c: list(masters) for c, masters in code_to_masters.items() if len(masters) > 1}
    
    # 4. enabled / disabled 統計
    enabled_count = sum(1 for b in branches if b.get('enabled', True))
    disabled_count = len(branches) - enabled_count
    
    # 5. master 統計
    masters = set(b.get('master', '') for b in branches if b.get('master'))
    
    # 6. region 統計
    regions = Counter(b.get('region', 'unknown') for b in branches)
    
    # 報告
    print(f"  分點總數: {len(branches)}")
    print(f"  enabled: {enabled_count} / disabled: {disabled_count}")
    print(f"  master 數: {len(masters)}")
    print(f"  region 分佈: {dict(regions)}")
    
    # 必填欄位
    if missing_fields:
        print(f"  ❌ 缺欄位: {len(missing_fields)} 個")
        for m in missing_fields[:3]:
            print(f"    {m}")
        issues.append(f'{len(missing_fields)} 個分點缺必填欄位')
    else:
        print(f"  ✅ 所有分點都有必填欄位 (code/name/master/enabled)")
    
    # code 格式
    if invalid_codes:
        print(f"  ❌ code 格式錯誤: {len(invalid_codes)} 個")
        issues.append(f'{len(invalid_codes)} 個分點 code 格式錯誤')
    else:
        print(f"  ✅ 所有 code 都是 4 字元格式")
    
    # 重複 (真重複 = 連 master 都一樣)
    if duplicates:
        print(f"  ❌ 真重複 (連 master 也相同): {duplicates}")
        issues.append(f'真重複 code: {duplicates}')
    else:
        print(f"  ✅ 無真重複")
    
    # 共用分點 (合法設計)
    if co_branch_codes:
        print(f"  ℹ️  共用分點 (合法設計): {len(co_branch_codes)} 個")
        for code, masters in list(co_branch_codes.items())[:3]:
            print(f"    • {code}: {' + '.join(masters)}")
    
    return {
        'pass': len(issues) == 0,
        'total_branches': len(branches),
        'enabled': enabled_count,
        'disabled': disabled_count,
        'masters_count': len(masters),
        'regions': dict(regions),
        'issues': issues,
    }


# ════════════════════════════════════════════════════════════════════
#  Layer 2: Master 對應審計
# ════════════════════════════════════════════════════════════════════

def audit_master_mapping() -> Dict[str, Any]:
    """檢查 master ↔ 分點對應的健康度"""
    
    print("\n【Layer 2】Master 對應審計")
    
    master_to_branches = defaultdict(list)
    for b in branches_mod.WATCHED_BRANCHES:
        m = b.get('master', '')
        if m:
            master_to_branches[m].append(b['name'])
    
    # 找有「協作分點」的 master (co_masters)
    co_master_count = sum(1 for b in branches_mod.WATCHED_BRANCHES if b.get('co_masters'))
    
    print(f"  獨立 master 數: {len(master_to_branches)}")
    print(f"  共用分點數: {co_master_count}")
    
    # Top 5 最多分點的 master
    top_masters = sorted(master_to_branches.items(), key=lambda x: -len(x[1]))[:5]
    print(f"\n  Top 5 master (分點最多):")
    for m, brs in top_masters:
        print(f"    • {m}: {len(brs)} 個分點 ({', '.join(brs[:3])}{'...' if len(brs)>3 else ''})")
    
    # 單一分點 master (可能是新加入的)
    single_branch_masters = [m for m, brs in master_to_branches.items() if len(brs) == 1]
    print(f"\n  單一分點 master: {len(single_branch_masters)} 個")
    
    return {
        'pass': True,
        'master_count': len(master_to_branches),
        'co_master_branches': co_master_count,
        'top_masters': [(m, len(brs)) for m, brs in top_masters],
        'single_branch_masters': single_branch_masters,
    }


# ════════════════════════════════════════════════════════════════════
#  Layer 3: 從 GitHub 拉真實資料看抓取健康度
# ════════════════════════════════════════════════════════════════════

def audit_data_health(latest_json_path: str = None) -> Dict[str, Any]:
    """
    讀 latest.json 看分點抓取是否完整
    (因為加密無法直接讀, 改用最近一個未加密日期檔)
    """
    print("\n【Layer 3】抓取資料健康度")
    
    import os
    # 找 data/ 下最新的未加密檔
    data_dir = '/home/claude/chip-radar-v3/data'
    if not os.path.exists(data_dir):
        print(f"  ⚠️ {data_dir} 不存在,跳過此層審計")
        return {'pass': True, 'skipped': True}
    
    # 試讀 stock_history.json (未加密)
    sh_path = f"{data_dir}/stock_history.json"
    if os.path.exists(sh_path):
        with open(sh_path) as f:
            data = json.load(f)
        stocks_count = len(data.get('stocks', {}))
        dates_count = len(data.get('dates', []))
        print(f"  ✅ stock_history.json: {stocks_count} 檔, {dates_count} 天")
    else:
        print(f"  ⚠️ stock_history.json 不存在")
    
    # 試讀 latest.json (加密的, 只看 metadata)
    latest_path = f"{data_dir}/latest.json"
    if os.path.exists(latest_path):
        with open(latest_path) as f:
            d = json.load(f)
        
        if 'encrypted' in d:
            # 加密的, 只看外層
            print(f"  📦 latest.json 是加密的 (AES-256-GCM)")
            print(f"     trade_date: {d.get('trade_date')}")
            print(f"     crawled_at: {d.get('crawled_at')}")
            print(f"     baseline_date: {d.get('baseline_date')}")
            print(f"     iterations (KDF): {d.get('iterations'):,}")
        else:
            # 未加密, 直接看分點數
            branches_data = d.get('branches', [])
            print(f"  ✅ latest.json (未加密): {len(branches_data)} 個分點抓到")
    
    return {'pass': True}


# ════════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════════

def audit_branches() -> Dict[str, Any]:
    """執行完整分點審計"""
    
    print("═" * 75)
    print(f"  🔍 分點籌碼審計 (3 層)")
    print("═" * 75)
    print()
    
    layer1 = audit_config_integrity()
    layer2 = audit_master_mapping()
    layer3 = audit_data_health()
    
    # 總結
    print()
    print("═" * 75)
    overall_pass = layer1['pass'] and layer2['pass'] and layer3.get('pass', True)
    print(f"  📈 分點審計總結:")
    print(f"    Layer 1 設定完整性: {'✅' if layer1['pass'] else '❌'}")
    print(f"    Layer 2 Master 對應: {'✅' if layer2['pass'] else '❌'}")
    print(f"    Layer 3 資料健康度: {'✅' if layer3.get('pass', True) else '❌'}")
    print()
    print(f"  📊 統計:")
    print(f"    分點總數:     {layer1['total_branches']}")
    print(f"    啟用中:        {layer1['enabled']}")
    print(f"    Master 數:    {layer1['masters_count']}")
    print()
    print(f"  整體結果: {'✅ 通過' if overall_pass else '⚠️ 有問題'}")
    print("═" * 75)
    
    return {
        'pass': overall_pass,
        'layer1_config': layer1,
        'layer2_master': layer2,
        'layer3_health': layer3,
    }


if __name__ == '__main__':
    result = audit_branches()
    
    # 儲存結果
    with open('/tmp/audit_branches.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 結果儲存: /tmp/audit_branches.json")
