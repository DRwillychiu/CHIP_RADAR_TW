# tests/conftest.py
# v3.51.0 機構級重整: tests/ 子目錄需把 repo root + src/* 加入 sys.path
# 這樣 test_*.py 直接 `import master_profile` / `from src.analyzers import x` 都能 work.
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Phase 1: 加 repo root (Phase 2 前的 backward compat — root 還有 .py)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Phase 2 起: 加 src/* 子目錄 (讓 tests 不需改 import)
_SRC_ROOT = _REPO_ROOT / 'src'
if _SRC_ROOT.exists():
    for sub in _SRC_ROOT.iterdir():
        if sub.is_dir() and not sub.name.startswith('_'):
            sys.path.insert(0, str(sub))

# v3.71.9 A5: tests/ 用 home-grown print-based runner + module-level sys.exit()
# pytest 跑 collection 時 import module → 遇 sys.exit 直接 abort 整個 session
# 解法: pytest 跳過 home-grown tests; 改用 `python tests/run_all.py` 跑全套
# (44 個 test 全改 pytest assert style 是大工程, 此 collect_ignore 是 5min 務實解)
collect_ignore_glob = ['test_*.py']
