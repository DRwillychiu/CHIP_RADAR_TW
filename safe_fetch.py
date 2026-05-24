"""safe_fetch.py — v3.30.1 專業審視 A.3: HTTP response size limit defense

防禦場景:
  TWSE / TAIFEX / MOPS 任一端點被 compromised 或 misconfigured,
  回傳極大 response (e.g. 數百 MB) → crawler OOM / workflow 卡死.

設計:
  - thin wrapper over requests.get / post
  - stream=True 逐 chunk 累積, 超過 max_bytes 立刻 raise
  - 預設 50 MB 上限 (一般 TWSE 全市場 STOCK_DAY_ALL ~ 2 MB, 50 MB 為 ~25x 緩衝)
  - 不取代既有 requests 呼叫 (避免 mass refactor), 只在最暴露的端點手動 migrate

用法:
  from safe_fetch import safe_get, safe_post

  text = safe_get(url, timeout=20, max_bytes=50_000_000).text
  r = safe_post(url, data=payload, max_bytes=10_000_000)
"""
import requests
from typing import Optional


DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_BYTES_TWSE_FULL = 100 * 1024 * 1024  # 100 MB (allow STOCK_DAY_ALL extra headroom)


class ResponseTooLargeError(Exception):
    """v3.30.1: response 超過 max_bytes 上限"""
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


def safe_get(url: str, max_bytes: int = DEFAULT_MAX_BYTES, **kwargs) -> requests.Response:
    """GET with size limit. 回傳的 Response 物件 .content 已被填好 (一次性讀完)."""
    kwargs.setdefault('timeout', 30)
    # 強制 stream=True 以便逐 chunk 監控
    kwargs['stream'] = True
    r = requests.get(url, **kwargs)
    content = _read_with_limit(r, max_bytes)
    # Backfill response.content (requests 內部 _content cache)
    r._content = content
    return r


def safe_post(url: str, max_bytes: int = DEFAULT_MAX_BYTES, **kwargs) -> requests.Response:
    """POST with size limit. 同 safe_get."""
    kwargs.setdefault('timeout', 30)
    kwargs['stream'] = True
    r = requests.post(url, **kwargs)
    content = _read_with_limit(r, max_bytes)
    r._content = content
    return r
