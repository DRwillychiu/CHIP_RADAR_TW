# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, re, json, shutil, subprocess, tempfile, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.17 主力貢獻度 (data/master_contribution.json) 從 2026-08-29 起沒再更新 — 離線

原因: scripts/analyze_master_contribution.py 只把 src/ 加進 sys.path, 沒有 `import src`.
v3.79.0 (2026-08-30) 起 core/master_tiers.py 在 import 時就 `from branches import ...`,
找不到 branches → 每天的滾動更新 Step 3/4 都 ModuleNotFoundError, 檔案停在 08-29.
  A. 實跑: 在暫存目錄 (src/ + 這支 script + quad_hit_log.json) 執行, 必須寫出今天的結果
  B. 防漏: scripts/ 裡以套件路徑 import src 子模組 (from exports. / core. ...) 的檔案,
     都必須先 `import src`
"""
ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.17 主力貢獻度 script 可執行 + scripts import 防漏 (離線)")
print("=" * 72)

print("\nA. analyze_master_contribution.py 在乾淨目錄實跑")
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copytree(ROOT / 'src', tmp / 'src', ignore=shutil.ignore_patterns('__pycache__'))
(tmp / 'scripts').mkdir()
shutil.copy2(ROOT / 'scripts' / 'analyze_master_contribution.py', tmp / 'scripts')
(tmp / 'data').mkdir()
shutil.copy2(ROOT / 'data' / 'quad_hit_log.json', tmp / 'data')
r = subprocess.run([sys.executable, str(tmp / 'scripts' / 'analyze_master_contribution.py')],
                   capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(tmp),
                   env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
check("exit 0 (08-30 起是 ModuleNotFoundError: branches)", r.returncode == 0,
      (r.stdout + r.stderr).strip().splitlines()[-1:] if r.returncode else '')
out = tmp / 'data' / 'master_contribution.json'
mc = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
src_ts = json.loads((tmp / 'data' / 'quad_hit_log.json').read_text(encoding='utf-8')).get('updated_at')
check("寫出 master_contribution.json, source_updated_at = quad_hit_log 的 updated_at",
      mc.get('source_updated_at') == src_ts, (mc.get('source_updated_at'), src_ts))
check("per_master 有內容", bool(mc.get('per_master')), len(mc.get('per_master') or []))
shutil.rmtree(tmp, ignore_errors=True)

print("\nB. scripts/ 以套件路徑 import src 子模組的檔案都先 import src")
PKG = re.compile(r'^\s*from (exports|core|analyzers|pipelines|fetchers|alerts|audit|backtest)\.\w+ import',
                 re.M)
HAS_SRC = re.compile(r'^\s*(import src\b|from src(\.| import))', re.M)
bad = []
for f in sorted((ROOT / 'scripts').glob('*.py')):
    t = f.read_text(encoding='utf-8', errors='replace')
    if PKG.search(t) and not HAS_SRC.search(t):
        bad.append(f.name)
check("沒有只加 src/ 進 sys.path 就 from exports./core. import 的 script", not bad, bad)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
