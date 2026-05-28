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
