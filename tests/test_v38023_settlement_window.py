# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, subprocess, os, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.23 settlement-tracking 結算窗口判斷 — 離線

settlement-tracking.yml 的窗口判斷在 repo 根目錄 `from crawler_pipeline import ...`,
但模組在 src/pipelines/ → ModuleNotFoundError, 又被 `|| echo in_window=false` 吞掉,
所以尾盤監控從沒跑過 (2026-09-16 結算日當天也是「非結算窗口」).
  A. workflow 裡那段 python 照原樣在 repo 根目錄執行 → 成功, 寫出 in_window
  B. 窗口判斷失敗時不可再假裝「非窗口」: 要出 ::error 並讓步驟失敗
  C. 窗口 = 結算日 D-3 ~ D+1 (2026-10 結算日 10/21)
"""
from crawler_pipeline import _days_to_settlement

ROOT = pathlib.Path(__file__).resolve().parent.parent
WF = ROOT / '.github' / 'workflows' / 'settlement-tracking.yml'
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.23 settlement-tracking 結算窗口判斷 (離線)")
print("=" * 72)
wf = WF.read_text(encoding='utf-8')
m = re.search(r'python -c "\n(.*?)\n\s*" \|\|', wf, re.S)
check("找得到窗口判斷的 python 區塊", m is not None)
code = '\n'.join(l.strip() and l[10:] or '' for l in m.group(1).split('\n')) if m else ''

print("\nA. 照 workflow 原樣在 repo 根目錄執行")
out = pathlib.Path(tempfile.mkdtemp()) / 'gh_out.txt'
env = dict(os.environ, GITHUB_OUTPUT=str(out), PYTHONIOENCODING='utf-8')
env.pop('PYTHONPATH', None)
p = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), env=env, capture_output=True, text=True,
                   encoding='utf-8')
check("exit 0 (沒有 ModuleNotFoundError)", p.returncode == 0, (p.stderr or '')[-200:])
txt = out.read_text(encoding='utf-8') if out.exists() else ''
check("GITHUB_OUTPUT 寫出 in_window=true/false", re.fullmatch(r'in_window=(true|false)\n', txt) is not None, repr(txt))

print("\nB. 失敗不可再被當成「非窗口」")
check("沒有 `|| echo \"in_window=false\"` 吞錯", '|| echo "in_window=false"' not in wf)
check("失敗時 ::error + exit 1", '::error title=Settlement window check failed' in wf and 'exit 1; }' in wf)

print("\nC. 窗口 D-3 ~ D+1 (2026-10 結算日 10/21)")
win = {d: -1 <= _days_to_settlement(d) <= 3 for d in
       ('20261016', '20261018', '20261019', '20261021', '20261022', '20261023')}
check("10/16 不在、10/18~10/22 在、10/23 不在",
      win == {'20261016': False, '20261018': True, '20261019': True, '20261021': True,
              '20261022': True, '20261023': False}, win)
check("2026-09-16 (結算日 D0) 在窗口", _days_to_settlement('20260916') == 0)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
