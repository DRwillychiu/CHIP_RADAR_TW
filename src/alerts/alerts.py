"""
alerts.py — v3.20 主動推播警報系統

用途:
  把 Daily Full Crawl 跑完的資料 → 偵測異常 → 推 Discord / Telegram

推播管道 (各自獨立, 有 token 就推):
  • Discord  — 只在偵測到警報時推 (v3.20 起行為未變)
  • Telegram — 每個交易日固定推一則 digest: 執行狀態 + 籌碼摘要 + 警報 (v3.55.0)
               無警報也推, 讓使用者不必盯 GitHub Actions 就知道 crawler 跑完了。
               兜底排程重跑會跳過, 見 is_redundant_rerun()。

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
import html as _html
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
#  v3.54.0 (Sprint 16 長2): Telegram Bot 推播
#
#  Token 使用機制 (BotFather workflow):
#    1. Telegram 跟 @BotFather 對話 → /newbot → 拿 token (format `123456789:ABC...`)
#    2. 跟自己的 bot 發任意訊息 → 跟 @userinfobot 拿你的 chat_id
#    3. GitHub Repo → Settings → Secrets → 加 2 個 secret:
#         - TELEGRAM_BOT_TOKEN = <上面拿的 token>
#         - TELEGRAM_CHAT_ID   = <個人 chat_id 或群組 chat_id>
#    4. crawler 跑時自動讀 env var → POST 到 telegram API
#    5. 沒設兩個之一 → 走 test mode (只 print)
#
#  訊息 format: Markdown (Telegram 支援 *bold* _italic_ `code` [link](url))
#  限制: 單則 4096 字元 (我們不會超過, alert 通常 < 1000 字)
# ════════════════════════════════════════════════════════════════════

def send_telegram(text: str,
                    parse_mode: str = 'Markdown',
                    bot_token: Optional[str] = None,
                    chat_id: Optional[str] = None) -> Optional[bool]:
    """發送 Telegram 訊息.

    Args:
      text: 訊息正文 (支援 Markdown, *bold* _italic_ `code`)
      parse_mode: 'Markdown' / 'HTML' / None
      bot_token: 覆蓋環境變數 TELEGRAM_BOT_TOKEN
      chat_id: 覆蓋環境變數 TELEGRAM_CHAT_ID

    Returns:
      True 成功 / False 失敗 / None test mode (未設 token 或 chat_id)
    """
    token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    cid = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '').strip()

    if not token or not cid:
        # Test mode: 只 print 不發送
        print(f"\n  [TEST MODE] 模擬 Telegram 推播 (TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設):")
        print(f"  {'─' * 60}")
        for line in text.split('\n'):
            print(f"  | {line}")
        print(f"  {'─' * 60}")
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': cid,
        'text': text[:4096],   # Telegram 上限 4096 字
        'parse_mode': parse_mode,
        'disable_web_page_preview': True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"  ✓ Telegram 推播成功")
            return True
        else:
            print(f"  ⚠️ Telegram 推播失敗: HTTP {r.status_code}, {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  ⚠️ Telegram 推播例外: {e}")
        return False


def _format_telegram_alert(detected: List[Dict[str, Any]], trade_date: str) -> str:
    """把 detected alerts list 格式化為 Telegram Markdown 訊息.

    跟 Discord embed 風格對應, 但純文字 + emoji + Markdown.
    """
    if not detected:
        return f"📊 *Chip Radar* {trade_date}\n\n今日無重大警報訊號"

    lines = [f"📊 *Chip Radar* {trade_date}", ""]
    by_type = _count_by_type(detected)
    summary = " / ".join(f"{k}: {v}" for k, v in by_type.items())
    lines.append(f"_共 {len(detected)} 則警報_  ({summary})")
    lines.append("")
    # 最多顯示 8 則細節 (避免訊息太長)
    for d in detected[:8]:
        title = d.get('title', d.get('type', 'alert'))
        msg = d.get('message', '')
        lines.append(f"▸ *{title}*")
        if msg:
            lines.append(f"  {msg[:200]}")
    if len(detected) > 8:
        lines.append(f"\n_...另 {len(detected) - 8} 則, 詳見網站 / Discord_")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
#  v3.55.0: 每日 Telegram 摘要 (執行狀態 + 籌碼摘要 + 警報)
#
#  跟舊的 _format_telegram_alert 差別:
#    舊: 只在「有警報」時推, 內容只有警報
#    新: 每個交易日固定推一則, 內容 = 爬蟲跑得如何 + 當日籌碼重點 + 警報
#        → 沒警報的日子也能確知 crawler 有跑完 (取代盯 GitHub Actions 綠燈)
#
#  parse_mode 用 HTML 不用 Markdown:
#    股票名稱/分點名稱可能含 _ * ` [ 等 Markdown 元字元, 未轉義會 HTTP 400
#    (見 docs/TELEGRAM_BOT_SETUP.md 故障排除表)。HTML 只需 escape 3 個字元。
# ════════════════════════════════════════════════════════════════════

def _esc(v: Any) -> str:
    """HTML escape — Telegram parse_mode=HTML 僅允許少數 tag, 其餘須轉義."""
    return _html.escape(str(v), quote=False)


def _signed(n: Any) -> str:
    """帶正負號的千分位 (買超 +5,500 / 賣超 -7,512)."""
    try:
        return f"{int(n):+,}"
    except (TypeError, ValueError):
        return str(n)


def is_redundant_rerun(trade_date: Any) -> bool:
    """本次是否為兜底排程的重複跑?

    daily-full 有 21:17 / 22:37 / 23:47 三層兜底排程 (見 daily-full.yml),
    每一層都會完整跑一次 crawler — 主排程成功後兜底仍照跑, 只是 commit 時
    git diff --quiet 變 no-op。若不去重, 同一天會收到 3 則幾乎一樣的推播。

    機制: 呼叫端 (workflow / scheduler.ps1) 在 crawler 跑之前先讀舊 latest.json
    的 trade_date, 傳成 CHIP_RADAR_PREV_TRADE_DATE 環境變數。若它等於本次的
    trade_date, 表示今天已經成功跑過並推播過 → 這次是兜底 → 跳過推播。

    未設此 env var → 一律回 False (保守: 寧可多推也不要漏推)。
    """
    prev = os.environ.get('CHIP_RADAR_PREV_TRADE_DATE', '').strip()
    if not prev or not trade_date:
        return False
    # trade_date 在不同路徑有 20260729 / 2026-07-29 / 2026/07/29 幾種寫法, 正規化再比
    norm = lambda s: ''.join(ch for ch in str(s) if ch.isdigit())
    return bool(norm(prev)) and norm(prev) == norm(trade_date)


def _digest_exec_status(d: Dict[str, Any]) -> List[str]:
    """執行狀態區塊: 分點成功/失敗數 + 個股/法人筆數 + 完成時間."""
    ok = d.get('success')
    failed = d.get('failed') or 0
    empty = d.get('empty') or 0
    stage = d.get('stage') or 'full'

    # crawled_at 是 ISO 字串, 取 HH:MM
    hhmm = ''
    crawled = d.get('crawled_at') or ''
    if len(crawled) >= 16 and crawled[10] == 'T':
        hhmm = f" · {crawled[11:16]}"

    if ok is None:
        return [f"❓ 執行狀態未知 ({_esc(stage)}){hhmm}"]

    total = ok + failed + empty
    head = "✅ 爬蟲完成" if failed == 0 else "⚠️ 爬蟲部分失敗"
    lines = [f"{head} ({_esc(stage)}){hhmm}"]

    detail = f"分點 {ok}/{total}"
    if failed:
        detail += f" · {failed} 失敗"
    if empty:
        detail += f" · {empty} 空"
    if d.get('quotes_count'):
        detail += f" · 個股 {d['quotes_count']:,}"
    if d.get('institutional_count'):
        detail += f" · 法人 {d['institutional_count']:,}"
    lines.append(detail)
    return lines


def _digest_chip_summary(d: Dict[str, Any]) -> List[str]:
    """籌碼摘要區塊.

    每一行獨立 try — 任何一個資料源掛掉 (期貨常抓不到) 只少一行,
    不會讓整則推播失敗。爬蟲本身就是 continue-on-error, 推播更該容錯。
    """
    lines: List[str] = []

    # 外資現貨淨買賣超 (v3.55.0 修好 total_net_lots 後才有值)
    try:
        foreign = (d.get('institutional_rankings') or {}).get('foreign') or {}
        net = foreign.get('total_net_lots')
        if net is not None:
            lines.append(f"🦅 外資現貨 {_signed(net)} 張")
    except Exception:
        pass

    # 期貨: 外資未平倉 + P/C Ratio
    try:
        fs = (d.get('futures_data') or {}).get('summary') or {}
        oi = fs.get('foreign_equivalent_net_oi')
        if oi is not None:
            lines.append(f"📈 外資期貨未平倉 {_signed(oi)} 口")
        pcr = fs.get('pc_ratio_oi')
        if pcr is not None:
            lines.append(f"📊 P/C Ratio {pcr}")
    except Exception:
        pass

    # 漲停家數
    try:
        stocks = (d.get('limit_up_summary') or {}).get('limit_up_stocks') or []
        if stocks:
            lines.append(f"🔥 漲停 {len(stocks)} 檔")
    except Exception:
        pass

    # 融資維持率風險分布 (高風險 120-130% / 斷頭 <120%)
    try:
        counts = ((d.get('margin_maintenance_summary') or {}).get('counts')) or {}
        hr, mc = counts.get('high_risk', 0), counts.get('margin_call', 0)
        if hr or mc:
            lines.append(f"💰 融資高風險 {hr} 檔 · 斷頭 {mc} 檔")
    except Exception:
        pass

    return lines


def _digest_alerts(detected: List[Dict[str, Any]]) -> List[str]:
    """警報區塊 (HTML). 標題本身已含分類 emoji, 前綴再加嚴重度顏色."""
    if not detected:
        return ["今日無重大警報訊號"]

    lines = []
    for sig in detected[:8]:
        dot = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(sig.get('severity'), '⚪')
        lines.append(f"{dot} <b>{_esc(sig.get('title') or sig.get('type') or 'alert')}</b>")
        msg = sig.get('message') or ''
        if msg:
            lines.append(f"　　{_esc(msg[:200])}")
    if len(detected) > 8:
        lines.append(f"<i>…另 {len(detected) - 8} 則,詳見網站</i>")
    return lines


def build_daily_digest(latest_data: Dict[str, Any],
                        detected: Optional[List[Dict[str, Any]]] = None) -> str:
    """組每日 Telegram 摘要 (HTML): 執行狀態 + 籌碼摘要 + 警報."""
    d = latest_data or {}
    detected = detected or []
    trade_date = d.get('trade_date') or date.today().strftime('%Y%m%d')

    parts = [f"📊 <b>Chip Radar</b> · {_esc(trade_date)}", ""]
    parts += _digest_exec_status(d)

    chip = _digest_chip_summary(d)
    if chip:
        parts += ["", "━━ 今日籌碼 ━━"] + chip

    parts += ["", f"━━ 警報 {len(detected)} 則 ━━" if detected else "━━ 警報 ━━"]
    parts += _digest_alerts(detected)

    return "\n".join(parts)


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
    
    # v3.41.0 C1: 引入 EventLogger 統一 SIEM-ready format
    try:
        from event_logger import emit_event
        from reasoning import build_reasoning
        _has_logger = True
    except ImportError:
        _has_logger = False

    # 訊號 1-4 (從 latest_data)
    for fn, label, category in [
        (lambda: detect_foreign_extreme(latest_data.get('institutional_rankings')), '外資', 'foreign_extreme'),
        (lambda: detect_pcr_extreme(latest_data.get('futures_data')), 'PCR', 'pcr_extreme'),
        (lambda: detect_limit_up_overheat(latest_data.get('limit_up_summary')), '漲停', 'limit_up_overheat'),
        (lambda: detect_settlement_reminder(latest_data.get('futures_data')), '結算', 'settlement_reminder'),
    ]:
        try:
            sig = fn()
            if sig:
                detected.append(sig)
                print(f"  ✓ [{label}] {sig['title']}: {sig['message']}")
                # C1: 同時 emit 到 event_logger (SIEM-ready)
                if _has_logger:
                    emit_event(
                        module='alerts', category=category,
                        severity=sig.get('severity', 'info'),
                        reasoning=build_reasoning(
                            conditions=[sig.get('message', '')],
                            conclusion=sig.get('title', ''),
                            evidence=[],
                            severity=sig.get('severity', 'info'),
                            category=category,
                        ),
                        detail=sig,
                    )
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
    
    today_str = latest_data.get('trade_date') or date.today().strftime('%Y/%m/%d')

    if dry_run:
        print(f"\n  🧪 dry_run 模式,共偵測 {len(detected)} 個訊號 (不推播)")
        return {'detected': detected, 'pushed': False, 'count_by_type': _count_by_type(detected),
                'pushed_telegram': False, 'pushed_telegram_test_mode': True,
                'telegram_skipped_rerun': False}

    # ────────────────────────────────────────────────────────────────
    # Telegram: v3.55.0 起「每個交易日固定推一則」
    #   內容 = 執行狀態 + 籌碼摘要 + 警報 (無警報也推, 讓使用者確知 crawler 跑完)
    #   例外 = 兜底排程重跑 → 跳過, 否則一天會收到 3 則
    # ────────────────────────────────────────────────────────────────
    tg_skipped = is_redundant_rerun(today_str)
    if tg_skipped:
        print(f"\n  ⏭️ 兜底排程重跑 (資料已是 {today_str}),跳過 Telegram 推播")
        tg_result = None
    else:
        tg_result = send_telegram(build_daily_digest(latest_data, detected),
                                    parse_mode='HTML')

    # ────────────────────────────────────────────────────────────────
    # Discord: 維持 v3.20 原行為 — 只在偵測到警報時推
    # ────────────────────────────────────────────────────────────────
    push_result = None
    if not detected:
        print("\n  📭 今日無異常,Discord 不推播")
    else:
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
        push_result = send_discord('\n'.join(content_lines))

    return {
        'detected': detected,
        'pushed': push_result is True,
        'pushed_test_mode': push_result is None,
        'count_by_type': _count_by_type(detected),
        # v3.54.0: Telegram 推播狀態 (跟 Discord 各自獨立)
        'pushed_telegram': tg_result is True,
        'pushed_telegram_test_mode': tg_result is None,
        # v3.55.0: 是否因兜底重跑而跳過 (區分「沒推因為沒 token」vs「沒推因為重複」)
        'telegram_skipped_rerun': tg_skipped,
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
    # Mock 資料測試 — 欄位刻意對齊 crawler.py raw_output 的真實形狀,
    # 免得再出現 v3.55.0 修掉的那種「mock 有、生產沒有」的假通過。
    mock_data = {
        'trade_date': '20260430',
        'crawled_at': '2026-04-30T21:23:11+08:00',
        'stage': 'full',
        'success': 81, 'failed': 0, 'empty': 0,
        'quotes_count': 1842, 'institutional_count': 1795,
        'institutional_rankings': {
            # build_inst_ranking() 回傳 buy/sell/total_net_lots 三個 key
            'foreign': {'buy': [], 'sell': [], 'total_net_lots': -7500},
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
        'margin_maintenance_summary': {
            'counts': {'healthy': 900, 'watch': 120, 'high_risk': 12, 'margin_call': 3},
        },
    }

    result = run_alerts(mock_data)
    print(f"\n總結: 偵測 {len(result['detected'])} 個訊號")
    print(f"  分類: {result['count_by_type']}")
    print(f"\n{'═' * 60}\n每日 digest 預覽:\n{'═' * 60}")
    print(build_daily_digest(mock_data, result['detected']))
