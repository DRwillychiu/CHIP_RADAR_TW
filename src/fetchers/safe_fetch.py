"""safe_fetch.py — v3.40.0 升級 (B5 機構級 ToS 合規 + exponential backoff)

歷史:
  v3.30.1 (A.3): HTTP response size limit defense (50 MB)
  v3.40.0 (B5): 加 exponential backoff + per-source quota log + retry

防禦場景:
  1. TWSE / TAIFEX / MOPS 任一端點被 compromised 或 misconfigured,
     回傳極大 response (e.g. 數百 MB) → crawler OOM / workflow 卡死.
  2. 七層 margin-refresh 邊緣 → IP 被封整站當機 → 違反 ToS 法律風險

設計:
  - thin wrapper over requests.get / post
  - stream=True 逐 chunk 累積, 超過 max_bytes 立刻 raise
  - B5: exponential backoff (1s → 2s → 4s → 8s) on 429/503
  - B5: per-source daily quota log (data/fetch_quota.json)
  - 預設 50 MB 上限 (一般 TWSE 全市場 STOCK_DAY_ALL ~ 2 MB, 50 MB 為 ~25x 緩衝)

用法:
  from safe_fetch import safe_get, safe_post, ResponseTooLargeError, RateLimitedError

  text = safe_get(url, timeout=20, max_bytes=50_000_000).text
  r = safe_post(url, data=payload, max_bytes=10_000_000)

  # 機構級 (B5): 加 source_id, 自動 backoff + quota 紀錄
  text = safe_get(url, source_id='TWSE_MI_INDEX', max_retries=4).text
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import requests

DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_BYTES_TWSE_FULL = 100 * 1024 * 1024  # 100 MB

# B5: backoff 參數
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 1.0      # 1s → 2s → 4s → 8s
DEFAULT_BACKOFF_FACTOR = 2.0

# B5: 各源 daily 軟 quota (僅紀錄不限, 觸發即印 ::warning::)
DEFAULT_SOFT_QUOTAS = {
    'TWSE': 200,       # OpenAPI 一般 < 50 次/日; 七層 margin 全跑也 < 100
    'TPEx': 100,
    'TAIFEX': 100,
    'TDCC': 5,         # 週頻 + 兜底 → 約 2-4 次/週
    'chengwaye': 10,   # 日頻 + cache TTL 1 天
    'histock': 100,    # 個股 audit + 偶用
    'MOPS': 200,
    'unknown': 1000,
}

TW_TZ = timezone(timedelta(hours=8))


class ResponseTooLargeError(Exception):
    """v3.30.1: response 超過 max_bytes 上限"""
    pass


class RateLimitedError(Exception):
    """v3.40.0 B5: 多次 backoff 後仍 429/503"""
    pass


def _read_with_limit(response: requests.Response, max_bytes: int) -> bytes:
    """逐 chunk 讀, 超過上限立刻關連線 + raise."""
    total = 0
    chunks = []
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise ResponseTooLargeError(
                f"Response from {response.url} exceeded {max_bytes / 1024 / 1024:.1f} MB "
                f"(reached {total / 1024 / 1024:.1f} MB) — aborted to prevent OOM"
            )
        chunks.append(chunk)
    return b''.join(chunks)


def _log_fetch_quota(source_id: str, data_dir: str = 'data') -> int:
    """B5: per-source daily quota 紀錄. 回傳今日累計次數."""
    today = datetime.now(TW_TZ).strftime('%Y%m%d')
    quota_file = Path(data_dir) / 'fetch_quota.json'
    quota = {}
    if quota_file.exists():
        try:
            quota = json.loads(quota_file.read_text(encoding='utf-8'))
        except Exception:
            quota = {}
    # 清舊日 (僅留今日 + 昨日)
    yesterday = (datetime.now(TW_TZ) - timedelta(days=1)).strftime('%Y%m%d')
    quota = {d: counts for d, counts in quota.items() if d in (today, yesterday)}
    today_counts = quota.setdefault(today, {})
    today_counts[source_id] = today_counts.get(source_id, 0) + 1
    count = today_counts[source_id]
    # 寫回 (atomic via temp)
    try:
        quota_file.parent.mkdir(exist_ok=True)
        tmp = quota_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(quota, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(quota_file)
    except Exception:
        pass   # 不影響主流程

    # 軟 quota 提示
    src_root = source_id.split('_', 1)[0]   # TWSE_MI_INDEX → TWSE
    quota_limit = DEFAULT_SOFT_QUOTAS.get(src_root, DEFAULT_SOFT_QUOTAS['unknown'])
    if count >= quota_limit:
        print(f"::warning title=B5 quota exceeded::{source_id} today={count} (soft limit {quota_limit})")
    return count


def _fetch_with_backoff(method: str, url: str,
                         source_id: Optional[str], max_retries: int,
                         max_bytes: int, **kwargs) -> requests.Response:
    """B5: 內部 exponential backoff 實作."""
    kwargs.setdefault('timeout', 30)
    kwargs['stream'] = True
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = (requests.get if method == 'GET' else requests.post)(url, **kwargs)
            if r.status_code in (429, 503):
                last_err = f"HTTP {r.status_code}"
                r.close()
                if attempt < max_retries:
                    wait = DEFAULT_BACKOFF_BASE_S * (DEFAULT_BACKOFF_FACTOR ** attempt)
                    print(f"  [B5 backoff] {source_id or url[:50]} HTTP {r.status_code}, "
                          f"retry {attempt+1}/{max_retries} after {wait:.1f}s")
                    time.sleep(wait)
                    continue
                raise RateLimitedError(
                    f"B5: {source_id or url} HTTP {r.status_code} after {max_retries+1} attempts"
                )
            content = _read_with_limit(r, max_bytes)
            r._content = content
            return r
        except (requests.RequestException, ResponseTooLargeError) as e:
            last_err = e
            if isinstance(e, ResponseTooLargeError):
                raise   # 不重試 OOM 防護
            if attempt < max_retries:
                wait = DEFAULT_BACKOFF_BASE_S * (DEFAULT_BACKOFF_FACTOR ** attempt)
                print(f"  [B5 backoff] {source_id or url[:50]} {type(e).__name__}, "
                      f"retry {attempt+1}/{max_retries} after {wait:.1f}s")
                time.sleep(wait)
                continue
            raise
    raise RateLimitedError(f"B5 unexpected fall-through: {last_err}")


def safe_get(url: str, max_bytes: int = DEFAULT_MAX_BYTES,
              source_id: Optional[str] = None,
              max_retries: int = DEFAULT_MAX_RETRIES,
              data_dir: str = 'data', **kwargs) -> requests.Response:
    """GET with size limit + (B5) backoff + quota log.
    source_id=None 時 backoff 仍生效, 但不記 quota."""
    if source_id:
        _log_fetch_quota(source_id, data_dir)
    return _fetch_with_backoff('GET', url, source_id, max_retries, max_bytes, **kwargs)


def safe_post(url: str, max_bytes: int = DEFAULT_MAX_BYTES,
               source_id: Optional[str] = None,
               max_retries: int = DEFAULT_MAX_RETRIES,
               data_dir: str = 'data', **kwargs) -> requests.Response:
    """POST with size limit + (B5) backoff + quota log."""
    if source_id:
        _log_fetch_quota(source_id, data_dir)
    return _fetch_with_backoff('POST', url, source_id, max_retries, max_bytes, **kwargs)
