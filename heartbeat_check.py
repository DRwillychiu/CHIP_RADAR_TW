# v3.51.0 機構級重整: sys.path 注入
import src  # noqa: F401
"""
========================================================================
Module: heartbeat_check.py  (v3.30.3 新增)
功能：資料新鮮度心跳檢查 — 主動偵測「今天爬蟲沒跑」

背景 (5/27-5/28 事故):
  連兩天 21:17 GitHub cron 塞車沒觸發 + Windows Task Scheduler 也沒跑,
  latest.json / Excel 停在前一天,但 workflow 顯示綠燈 (crawler step
  continue-on-error + Excel exception 被吞),沒有任何告警 → 用戶自己發現。

設計:
  latest.json 外層的 crawled_at / trade_date 是「明文」(不在加密 token 內),
  所以本檢查 **不需要 password、不需要解密、不需要 cryptography 依賴**,
  超輕量,可獨立排程跑。

判斷邏輯 (age = 距 crawled_at 幾小時):
  age <= 28h                      → PASS  (今天或昨天有跑)
  平日 (Mon-Fri) 且 age > 28h     → FAIL  (漏跑交易日;若今天國定假日可忽略)
  age > 100h (>4 天)              → FAIL  (連最長連假都該結束,鐵定有問題)
  其他 age > 50h                  → WARN  (跨假日?建議看一眼)

輸出:
  data/heartbeat.json + stdout verdict + GitHub Actions ::error/::warning::
  CLI exit code: PASS=0, WARN=0, FAIL=1 (讓 workflow step 可選擇 fail)

CLI:
  python heartbeat_check.py                          # 檢查 data/latest.json
  python heartbeat_check.py --latest path/to.json
  python heartbeat_check.py --fail-on-warn           # WARN 也 exit 1
========================================================================
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# v3.77.0: Windows 主控台預設 cp950, 印 emoji 會 UnicodeEncodeError —
# 本檔在 GH Actions (UTF-8) 正常但本機手動跑一定炸, 導致無法在本機驗證心跳.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

TW_TZ = timezone(timedelta(hours=8))

# Thresholds (hours)
FRESH_MAX_H = 28        # <= 28h 視為新鮮
WEEKDAY_FAIL_H = 28     # 平日超過此值 = 漏跑交易日
HARD_FAIL_H = 100       # 無論假日,超過此值鐵定有問題 (>4 天)
WARN_H = 50             # 跨假日提醒


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _parse_iso(ts: str) -> Optional[datetime]:
    """parse ISO timestamp (含 tz),容錯。"""
    if not ts:
        return None
    try:
        # 處理 'Z' 結尾
        ts2 = ts.replace('Z', '+00:00')
        dt = datetime.fromisoformat(ts2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TW_TZ)
        return dt
    except (ValueError, TypeError):
        return None


def check_freshness(crawled_at: Optional[str],
                    trade_date: Optional[str] = None,
                    now: Optional[datetime] = None) -> Tuple[str, str, float]:
    """
    核心新鮮度判斷.

    Args:
        crawled_at: latest.json 外層明文 crawled_at (ISO string)
        trade_date: latest.json 外層明文 trade_date (YYYYMMDD), 輔助訊息用
        now: 現在時間 (預設 now_tw, 測試可注入)

    Returns:
        (verdict, message, age_hours)
        verdict ∈ {PASS, WARN, FAIL}
    """
    if now is None:
        now = now_tw()

    dt = _parse_iso(crawled_at)
    if dt is None:
        return 'FAIL', f'無法解析 crawled_at: {crawled_at!r}', -1.0

    age_h = (now - dt).total_seconds() / 3600.0
    wd = now.weekday()  # 0=Mon ... 6=Sun
    is_weekday = wd <= 4
    td_str = f' (trade_date={trade_date})' if trade_date else ''

    # 未來時間 (clock skew) — 視為新鮮
    if age_h < 0:
        return 'PASS', f'資料時間在未來 {abs(age_h):.1f}h (clock skew),視為新鮮{td_str}', age_h

    # 硬上限:連最長連假都該結束
    if age_h > HARD_FAIL_H:
        return 'FAIL', f'資料 {age_h:.0f}h ({age_h/24:.1f} 天) 未更新 — 連長假都該結束,鐵定異常{td_str}', age_h

    # 平日漏跑
    if is_weekday and age_h > WEEKDAY_FAIL_H:
        wd_name = ['一', '二', '三', '四', '五'][wd]
        return 'FAIL', (
            f'平日(週{wd_name}) 資料 {age_h:.0f}h 未更新 — 漏跑至少一個交易日。'
            f'若今天為國定假日可忽略{td_str}'
        ), age_h

    # 跨假日提醒
    if age_h > WARN_H:
        return 'WARN', f'資料 {age_h:.0f}h 未更新 (跨假日?),建議確認{td_str}', age_h

    # 新鮮
    if age_h <= FRESH_MAX_H:
        return 'PASS', f'資料新鮮 ({age_h:.1f}h 前更新){td_str}', age_h

    # 28~50h 之間,週末
    return 'PASS', f'資料 {age_h:.1f}h 前 (週末/假日範圍內,正常){td_str}', age_h


# ════════════════════════════════════════════════════════════════════
#  v3.77.0 資料自我一致性檢查 (純本機, 不打網路)
# ════════════════════════════════════════════════════════════════════
#  起因: v3.76.0 揭穿 stock_history.market 有 78% 的紀錄日期慢一天 —
#  TWSE 尚未更新時 API 回前一交易日, 被貼上今天的標籤寫入.
#  這類錯誤**不會拋例外、workflow 不會變紅、資料看起來完全正常**,
#  無人值守跑一個月會累積到無法回溯.
#
#  唯一能主動抓到它的方法: 每筆資料自帶來源日期戳, 並檢查它與 key 是否一致.
#  v3.76.0 起 market 每筆都寫 quote_date (民國), 這裡就是那道驗證.

def check_data_integrity(stock_history_path: str = 'data/stock_history.json'
                         ) -> Dict[str, Any]:
    """market 日期自我一致性 — 回 {'verdict', 'issues', 'stats'}.

    FAIL 條件 (靜默資料汙染, 必須擋):
      · 有紀錄缺 quote_date        → 無法驗證新鮮度, 等同 v3.76.0 前的狀態
      · quote_date 與 key 日期不符 → 日期錯位本體
    WARN 條件:
      · market 最新日 < 個股最新日 → 大盤落後個股 (可能又遇到 TWSE 未更新)
    """
    p = Path(stock_history_path)
    if not p.exists():
        return {'verdict': 'PASS', 'issues': [], 'stats': {'note': 'stock_history 不存在, 跳過'}}
    try:
        sh = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        return {'verdict': 'WARN', 'issues': [f'stock_history 解析失敗: {type(e).__name__}'],
                'stats': {}}

    market = sh.get('market') or {}
    issues, missing_qd, misaligned = [], [], []
    for d, v in market.items():
        qd = str((v or {}).get('quote_date') or '')
        if not qd:
            missing_qd.append(d)
            continue
        if len(qd) == 7 and f'{int(qd[:3]) + 1911}{qd[3:]}' != d:
            misaligned.append(f'{d}(quote={qd})')

    if missing_qd:
        issues.append(f'market {len(missing_qd)} 筆缺 quote_date — 無法驗證新鮮度: '
                      f'{missing_qd[:5]}')
    if misaligned:
        issues.append(f'market {len(misaligned)} 筆日期錯位 (key ≠ quote_date): '
                      f'{misaligned[:5]}')

    verdict = 'FAIL' if issues else 'PASS'

    # 大盤 vs 個股 最新日落差 (軟性)
    stocks = sh.get('stocks') or {}
    stock_dates = set()
    for rec in list(stocks.values())[:50]:
        stock_dates |= set((rec or {}).get('daily') or {})
    if market and stock_dates:
        m_last, s_last = max(market), max(stock_dates)
        if m_last < s_last:
            issues.append(f'大盤最新 {m_last} 落後個股最新 {s_last} — 疑 TWSE 未更新')
            if verdict == 'PASS':
                verdict = 'WARN'

    return {
        'verdict': verdict,
        'issues': issues,
        'stats': {
            'market_records': len(market),
            'missing_quote_date': len(missing_qd),
            'misaligned': len(misaligned),
        },
    }


def load_latest_metadata(latest_path: str) -> Dict[str, Any]:
    """讀 latest.json 外層明文 metadata (不解密)。"""
    with open(latest_path, 'r', encoding='utf-8') as f:
        enc = json.load(f)
    return {
        'crawled_at': enc.get('crawled_at'),
        'trade_date': enc.get('trade_date'),
        'encrypted': enc.get('encrypted'),
        'stage': enc.get('stage'),
        'last_margin_update_at': enc.get('last_margin_update_at'),
    }


def run_check(latest_path: str = 'data/latest.json',
              output_path: Optional[str] = 'data/heartbeat.json',
              now: Optional[datetime] = None,
              verbose: bool = True) -> Dict[str, Any]:
    """主檢查流程 + 寫 heartbeat.json。"""
    if now is None:
        now = now_tw()

    if not Path(latest_path).exists():
        result = {
            'verdict': 'FAIL',
            'message': f'latest.json 不存在: {latest_path}',
            'checked_at': now.isoformat(),
            'age_hours': -1,
        }
    else:
        meta = load_latest_metadata(latest_path)
        verdict, message, age_h = check_freshness(
            meta['crawled_at'], meta['trade_date'], now=now
        )
        result = {
            'verdict': verdict,
            'message': message,
            'checked_at': now.isoformat(),
            'crawled_at': meta['crawled_at'],
            'trade_date': meta['trade_date'],
            'age_hours': round(age_h, 2),
        }

    # v3.77.0: 疊加資料自我一致性檢查 (日期錯位這類靜默汙染)
    integ = check_data_integrity()
    result['data_integrity'] = integ
    if integ['verdict'] == 'FAIL':
        result['verdict'] = 'FAIL'
        result['message'] = (result['message'] + ' | 資料完整性 FAIL: '
                             + '; '.join(integ['issues']))
    elif integ['verdict'] == 'WARN' and result['verdict'] == 'PASS':
        result['verdict'] = 'WARN'
        result['message'] = result['message'] + ' | ' + '; '.join(integ['issues'])

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    if verbose:
        mark = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(result['verdict'], '?')
        print(f"[Heartbeat] {mark} {result['verdict']}: {result['message']}")

    return result


def main():
    parser = argparse.ArgumentParser(description='資料新鮮度心跳檢查')
    parser.add_argument('--latest', default='data/latest.json')
    parser.add_argument('--output', default='data/heartbeat.json')
    parser.add_argument('--fail-on-warn', action='store_true',
                        help='WARN 也 exit 1')
    args = parser.parse_args()

    result = run_check(args.latest, args.output)
    verdict = result['verdict']

    # GitHub Actions annotations
    if verdict == 'FAIL':
        print(f"::error title=資料未更新::{result['message']}")
        sys.exit(1)
    elif verdict == 'WARN':
        print(f"::warning title=資料新鮮度::{result['message']}")
        sys.exit(1 if args.fail_on_warn else 0)
    else:
        print(f"::notice title=Heartbeat OK::{result['message']}")
        sys.exit(0)


if __name__ == '__main__':
    main()
