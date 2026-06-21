# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.30.1 safe_fetch size limit 測試"""
import sys
import io
sys.path.insert(0, '.')

import requests
from unittest.mock import patch, MagicMock
from safe_fetch import safe_get, safe_post, ResponseTooLargeError


def _make_mock_response(content_chunks, url='http://test.example/', status_code=200):
    """構造 mock response 用 iter_content 餵 chunks.
    v3.40.0 B5: 加 status_code (backoff 需要)."""
    mock = MagicMock(spec=requests.Response)
    mock.url = url
    mock.status_code = status_code   # v3.40.0 B5
    mock.iter_content = MagicMock(return_value=iter(content_chunks))
    mock.close = MagicMock()
    mock._content = None
    return mock


all_pass = True
print("=" * 60)
print("  v3.30.1 safe_fetch size limit 測試")
print("=" * 60)

# 1. 小 response (1 KB) 應該 OK
print("\n1. 小 response (1 KB) → 正常通過")
small_chunks = [b'a' * 1024]
mock_r = _make_mock_response(small_chunks)
with patch('requests.get', return_value=mock_r):
    try:
        r = safe_get('http://test/', max_bytes=10 * 1024 * 1024)
        ok = r._content == b'a' * 1024
        print(f"  {'✅' if ok else '❌'} content len={len(r._content)} (expect 1024)")
        if not ok:
            all_pass = False
    except Exception as e:
        print(f"  ❌ unexpected exception: {e}")
        all_pass = False

# 2. 大 response (超過 limit) 應該 raise
print("\n2. 大 response (10 MB, limit 1 MB) → 應 raise ResponseTooLargeError")
big_chunks = [b'b' * (64 * 1024)] * 200  # 200 × 64KB = 12.8 MB total
mock_r = _make_mock_response(big_chunks)
with patch('requests.get', return_value=mock_r):
    try:
        r = safe_get('http://test/', max_bytes=1 * 1024 * 1024)  # 1 MB limit
        print(f"  ❌ 應 raise 卻沒 raise, content len={len(r._content)}")
        all_pass = False
    except ResponseTooLargeError as e:
        print(f"  ✅ Correctly raised: {str(e)[:100]}...")
        # 確認 close 被叫過
        if mock_r.close.called:
            print(f"  ✅ response.close() 被呼叫 (連線釋放)")
        else:
            print(f"  ❌ response.close() 沒被呼叫")
            all_pass = False

# 3. Boundary case: 剛好等於 limit
print("\n3. 邊界 case (剛好 1 MB, limit 1 MB) → 正常通過")
boundary_chunks = [b'c' * (64 * 1024)] * 16  # 16 × 64KB = 1 MB exactly
mock_r = _make_mock_response(boundary_chunks)
with patch('requests.get', return_value=mock_r):
    try:
        r = safe_get('http://test/', max_bytes=1 * 1024 * 1024)
        ok = len(r._content) == 1024 * 1024
        print(f"  {'✅' if ok else '❌'} content len={len(r._content)} (expect 1048576)")
        if not ok:
            all_pass = False
    except ResponseTooLargeError as e:
        print(f"  ❌ 邊界 case 不該 raise: {e}")
        all_pass = False

# 4. safe_post 同樣行為
print("\n4. safe_post 同 GET 行為")
mock_r = _make_mock_response([b'd' * 500])
with patch('requests.post', return_value=mock_r):
    try:
        r = safe_post('http://test/', max_bytes=10 * 1024 * 1024)
        ok = len(r._content) == 500
        print(f"  {'✅' if ok else '❌'} POST content len={len(r._content)}")
        if not ok:
            all_pass = False
    except Exception as e:
        print(f"  ❌ unexpected: {e}")
        all_pass = False

# 5. Default max_bytes 50 MB sanity
print("\n5. 預設 max_bytes 50 MB 合理性")
from safe_fetch import DEFAULT_MAX_BYTES
ok = DEFAULT_MAX_BYTES == 50 * 1024 * 1024
print(f"  {'✅' if ok else '❌'} DEFAULT_MAX_BYTES = {DEFAULT_MAX_BYTES / 1024 / 1024:.0f} MB")
if not ok:
    all_pass = False

print()
print("─" * 60)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
