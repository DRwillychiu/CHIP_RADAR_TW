"""
alerts.py — v3.20 主動推播警報系統

用途:
  把 Daily Full Crawl 跑完的資料 → 偵測異常 → 推 Discord
  
5 種訊號:
  1. 外資現貨 ±5,000 張極端
  2. P/C Ratio > 1.8 或 < 0.6 (散戶極端情緒)
  3. 漲停家數 ≥ 30 (市場過熱)
  4. 結算日前 3 天提醒
  5. 內部人/重大訊息 籌碼信號

模式:
  • test mode (DISCORD_WEBHOOK_URL 未設) → 只 print 到 log
  • production (有 webhook) → 真的推 Discord
"""

import os
import json
import time
import requests
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

# ════════════════════════════════════════════════════════════════════
#  訊號條件 (可調整閾值)
# ════════════════════════════════════════════════════════════════════

THRESHOLDS = {
    'foreign_extreme_lots': 5000,        # 外資現貨 ±N 張視為極端
    'pcr_high': 1.8,                     # PCR > N 視為散戶極端看空
    'pcr_low': 0.6,                      # PCR < N 視為散戶極端看多
    'limit_up_overheat': 30,             # 漲停家數 ≥ N 視為過熱
    'days_before_settlement': 3,         # 結算前 N 天提醒
    'insider_sell_lots': 1000,           # 內部人申讓 ≥ N 張警報
    'insider_pledge_ratio': 30,          # 設質比例 ≥ N% 警報
}


# ════════════════════════════════════════════════════════════════════
#  Discord webhook
# ════════════════════════════════════════════════════════════════════

def send_discord(content: str, embeds: Optional[List[Dict]] = None, webhook_url: Optional[str] = None) -> bool:
    """
    發送 Discord 訊息
    
    Args:
        content: 訊息正文 (支援 markdown)
        embeds: Discord embed 物件列表 (可選)
        webhook_url: 覆蓋環境變數
    
    Returns:
        True 成功 / False 失敗 / None test mode
    """
    url = webhook_url or os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    
    if not url:
        # Test mode: 只 print 不發送
        print(f"\n  [TEST MODE] 模擬 Discord 推播:")
        print(f"  {'─' * 60}")
        for line in content.split('\n'):
            print(f"  | {line}")
        if embeds:
            for embed in embeds:
                print(f"  | [Embed] {embed.get('title', '')}")
                for f in embed.get('fields', []):
                    print(f"  |   {f.get('name')}: {f.get('value')[:80]}")
        print(f"  {'─' * 60}")
        return None
    
    try:
        payload = {'content': content[:2000]}  # Discord 上限 2000 字
        if embeds:
            payload['embeds'] = embeds[:10]  # Discord 上限 10 個 embed
        
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in (200, 204):
            print(f"  ✓ Discord 推播成功")
            return True
        else:
            print(f"  ⚠️ Discord 推播失敗: HTTP {r.status_code}, {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  ⚠️ Discord 推播例外: {e}")
        return False


# ════════════════════════════════════════════════════════════════════
#  訊號偵測函數
# ════════════════════════════════════════════════════════════════════

def detect_foreign_extreme(institutional_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    訊號 1: 外資現貨 ±5,000 張極端
    """
    if not institutional_data:
        return None
    foreign = institutional_data.get('foreign', {})
    net_lots = foreign.get('total_net_lots', 0) or 0
    
    threshold = THRESHOLDS['foreign_extreme_lots']
    if abs(net_lots) < threshold:
        return None
    
    direction = '買超' if net_lots > 0 else '賣超'
    severity = 'high' if abs(net_lots) >= threshold * 2 else 'medium'
    
    return {
        'type': 'foreign_extreme',
        'severity': severity,
        'title': f'🦅 外資極端{direction}',
        'message': f'外資現貨{direction} {abs(net_lots):,} 張 (閾值 {threshold:,})',
        'value': net_lots,
    }


def detect_pcr_extreme(futures_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    訊號 2: P/C Ratio 極端
    """
    if not futures_data or not futures_data.get('summary'):
        return None
    pcr = futures_data['summary'].get('pc_ratio_oi')
    if pcr is None:
        return None
    
    if pcr > THRESHOLDS['pcr_high']:
        return {
            'type': 'pcr_extreme',
            'severity': 'high',
            'title': '📊 PCR 極端看空',
            'message': f'P/C Ratio = {pcr} (>{THRESHOLDS["pcr_high"]}), 散戶極度看空 → 反指標偏多',
            'value': pcr,
        }
    elif pcr < THRESHOLDS['pcr_low']:
        return {
            'type': 'pcr_extreme',
            'severity': 'high',
            'title': '📊 PCR 極端看多',
            'message': f'P/C Ratio = {pcr} (<{THRESHOLDS["pcr_low"]}), 散戶極度看多 → 反指標偏空',
            'value': pcr,
        }
    return None


def detect_limit_up_overheat(limit_up_summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    訊號 3: 漲停家數過熱
    """
    if not limit_up_summary:
        return None
    stocks = limit_up_summary.get('limit_up_stocks', [])
    count = len(stocks) if stocks else 0
    
    if count < THRESHOLDS['limit_up_overheat']:
        return None
    
    return {
        'type': 'limit_up_overheat',
        'severity': 'medium',
        'title': '🔥 漲停家數過熱',
        'message': f'今日漲停 {count} 檔 (閾值 {THRESHOLDS["limit_up_overheat"]}), 市場過熱要小心',
        'value': count,
    }


def detect_settlement_reminder(futures_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    訊號 4: 結算日前 3 天提醒
    台指期結算: 每月第 3 個週三
    """
    today = date.today()
    
    # 算當月第 3 個週三
    first_day = today.replace(day=1)
    days_to_first_wed = (2 - first_day.weekday()) % 7  # 0=Mon, 2=Wed
    third_wed = first_day + timedelta(days=days_to_first_wed + 14)
    
    days_until = (third_wed - today).days
    
    if 0 < days_until <= THRESHOLDS['days_before_settlement']:
        return {
            'type': 'settlement_reminder',
            'severity': 'low',
            'title': '📅 結算日將至',
            'message': f'台指期結算日: {third_wed.strftime("%m/%d")} (剩 {days_until} 天)',
            'value': days_until,
        }
    return None


def detect_insider_signals(insider_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    訊號 5: 內部人警報 (從 insiders.detect_insider_changes 拉)
    
    insider_data 格式:
      {'2330': {'directors': [...], 'alerts': [...], 'name': '台積電'}, ...}
    """
    if not insider_data:
        return []
    
    signals = []
    for code, info in (insider_data.items() if isinstance(insider_data, dict) else []):
        alerts = info.get('alerts', [])
        for a in alerts:
            if a.get('severity') in ('high', 'medium'):
                signals.append({
                    'type': f'insider_{a["type"]}',
                    'severity': a['severity'],
                    'title': f'⚠️ 內部人異動 ({code} {info.get("name", "")})',
                    'message': a['message'],
                    'code': code,
                })
    return signals


# ════════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════════

def run_alerts(latest_data: Dict[str, Any], insider_data: Optional[Dict] = None,
               announcements: Optional[List] = None, dry_run: bool = False) -> Dict[str, Any]:
    """
    主流程: 偵測所有訊號 → 推播
    
    Args:
        latest_data: latest.json 的解密內容 (含 institutional / futures / limit_up_summary)
        insider_data: insiders.py 抓的董監持股 + 警報 dict (可選)
        announcements: 重大訊息列表 (可選)
        dry_run: True = 只偵測不推播
    
    Returns:
        {
            'detected': [...],
            'pushed': bool,
            'count_by_type': {...},
        }
    """
    print("\n══════════════════════════════════════════════")
    print("  🚨 v3.20 推播警報系統運作中")
    print("══════════════════════════════════════════════")
    
    detected = []
    
    # 訊號 1-4 (從 latest_data)
    for fn, label in [
        (lambda: detect_foreign_extreme(latest_data.get('institutional_rankings')), '外資'),
        (lambda: detect_pcr_extreme(latest_data.get('futures_data')), 'PCR'),
        (lambda: detect_limit_up_overheat(latest_data.get('limit_up_summary')), '漲停'),
        (lambda: detect_settlement_reminder(latest_data.get('futures_data')), '結算'),
    ]:
        try:
            sig = fn()
            if sig:
                detected.append(sig)
                print(f"  ✓ [{label}] {sig['title']}: {sig['message']}")
            else:
                print(f"  · [{label}] 無異常")
        except Exception as e:
            print(f"  ⚠️ [{label}] 偵測失敗: {e}")
    
    # 訊號 5 (內部人)
    if insider_data:
        insider_sigs = detect_insider_signals(insider_data)
        for sig in insider_sigs[:5]:  # 限制最多 5 個避免訊息過多
            detected.append(sig)
            print(f"  ✓ [內部人] {sig['title']}: {sig['message']}")
    
    # 重大訊息 (high impact 才推)
    if announcements:
        high_impact = [a for a in announcements if a.get('classification', {}).get('impact') == 'high']
        if high_impact:
            print(f"  ✓ [重大訊息] {len(high_impact)} 則高影響度公告")
            detected.append({
                'type': 'announcements_high',
                'severity': 'medium',
                'title': f'📰 高影響度重大訊息 {len(high_impact)} 則',
                'message': ', '.join([f"{a['code']} {a['name']}" for a in high_impact[:5]]),
                'announcements': high_impact[:10],
            })
    
    # 推播
    if not detected:
        print("\n  📭 今日無異常,不推播")
        return {'detected': [], 'pushed': False, 'count_by_type': {}}
    
    if dry_run:
        print(f"\n  🧪 dry_run 模式,共偵測 {len(detected)} 個訊號 (不推播)")
        return {'detected': detected, 'pushed': False, 'count_by_type': _count_by_type(detected)}
    
    # 組推播訊息
    today_str = latest_data.get('trade_date') or date.today().strftime('%Y/%m/%d')
    content_lines = [
        f"📊 **Chip Radar 警報** · {today_str}",
        f"偵測到 **{len(detected)}** 個異常訊號",
        "",
    ]
    for sig in detected[:10]:  # 限制 10 個
        emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(sig.get('severity'), '⚪')
        content_lines.append(f"{emoji} **{sig['title']}**")
        content_lines.append(f"   {sig['message']}")
        content_lines.append("")
    
    content = '\n'.join(content_lines)
    push_result = send_discord(content)
    
    return {
        'detected': detected,
        'pushed': push_result is True,
        'pushed_test_mode': push_result is None,
        'count_by_type': _count_by_type(detected),
    }


def _count_by_type(detected: List[Dict]) -> Dict[str, int]:
    counts = {}
    for sig in detected:
        t = sig.get('type', 'unknown')
        counts[t] = counts.get(t, 0) + 1
    return counts


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Mock 資料測試
    mock_data = {
        'trade_date': '2026/04/30',
        'institutional_rankings': {
            'foreign': {'total_net_lots': -7500, 'name': '外資'},
        },
        'futures_data': {
            'summary': {
                'pc_ratio_oi': 1.85,
                'foreign_equivalent_net_oi': -42000,
            }
        },
        'limit_up_summary': {
            'limit_up_stocks': [{'code': str(i), 'name': f'股{i}'} for i in range(35)],
        },
    }
    
    result = run_alerts(mock_data)
    print(f"\n總結: 偵測 {len(result['detected'])} 個訊號")
    print(f"  分類: {result['count_by_type']}")
