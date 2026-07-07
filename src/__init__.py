"""
src/ - 機構級 Data Analyst 結構 (v3.51.0 重整)

8 個子目錄:
  fetchers/  - 抓資料 (TWSE/TPEx/TDCC/chengwaye APIs)
  analyzers/ - 分析計算 (master_profile, signal_engine, ...)
  pipelines/ - 編排流程 (crawler_*, db_pipeline, ...)
  backtest/  - 回測驗證
  audit/     - 稽核品質 (audit_*, cross_check, ...)
  alerts/    - 警報通知
  exports/   - 輸出報告 (excel, reasoning, ...)
  core/      - 共用工具 (branches, price_utils, ...)

Import 策略 (backward compat):
  Entry points (crawler.py / heartbeat_check.py / ...) 直接 `import src`
  即會自動把 8 個子目錄加進 sys.path. 既有 `import attention_fetcher` 仍 work.
"""
import os
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _SRC_ROOT.parent

# Load .env (不依賴 python-dotenv)
_dotenv = _PROJECT_ROOT / ".env"
if _dotenv.is_file():
    for line in _dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if not os.environ.get(k):
                os.environ[k] = v
_SUBDIRS = ['fetchers', 'analyzers', 'pipelines', 'backtest',
             'audit', 'alerts', 'exports', 'core']

# 把 src/* 全部加進 sys.path 前端 (let `import attention_fetcher` 直接 work)
for sub in _SUBDIRS:
    _p = str(_SRC_ROOT / sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
