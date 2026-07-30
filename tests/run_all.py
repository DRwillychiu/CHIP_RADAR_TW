"""v3.71.9 A5: 跑 tests/ 所有 home-grown test_*.py 並統計 pass/fail.

tests/ 是 home-grown print-based runner + module-level sys.exit() 的格式.
pytest 無法直接 collect (會 abort), 改用本 script 跑.

執行: python tests/run_all.py
退出碼: 0 = 全 pass, 1 = 有 fail
"""
import subprocess, sys, os
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Windows default stdout cp950 會炸 emoji; force utf-8 給 subprocess
ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

ROOT = Path(__file__).parent
test_files = sorted(ROOT.glob('test_*.py'))

passed = 0
failed = 0
fail_list = []

print(f"=== Running {len(test_files)} home-grown tests ===\n")
for f in test_files:
    result = subprocess.run(
        [sys.executable, str(f)],
        capture_output=True, text=True,
        encoding='utf-8', errors='replace',
        env=ENV,
        cwd=str(ROOT.parent),   # repo root
    )
    if result.returncode == 0:
        passed += 1
        print(f"  ✅ {f.name}")
    else:
        failed += 1
        fail_list.append(f.name)
        print(f"  ❌ {f.name}  (exit {result.returncode})")
        # 顯示 last 5 lines of stderr / stdout 助診斷
        tail = (result.stdout + result.stderr).splitlines()[-5:]
        for ln in tail:
            print(f"      {ln}")

print(f"\n=== Summary: {passed}/{len(test_files)} passed, {failed} failed ===")
if fail_list:
    print(f"FAIL: {', '.join(fail_list)}")
sys.exit(0 if failed == 0 else 1)
