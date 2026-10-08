# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.26 雲端主機固定 Ubuntu 24.04 + 資安掃描拿掉 Safety (使用者 2026-10-08 選 C) — 離線

  A. ubuntu-latest 2026-10-19 起換成 Ubuntu 26 → 所有 workflow 固定 ubuntu-24.04,
     Ubuntu 26 另外驗證後再換
  B. security-audit 連紅 7 週: Safety 自己的依賴 (nltk) 被裝進掃描環境 → 掃到不屬於專案的 CVE;
     Safety `check` 指令官方已停止支援. 改成只用 pip-audit, 專案依賴裝在乾淨 venv 再掃
  C. 每一條 --ignore-vuln 都要在 docs/SECURITY_EXCEPTIONS.md 有理由
"""
ROOT = pathlib.Path(__file__).resolve().parent.parent
WF = ROOT / '.github' / 'workflows'
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.26 runner 固定 + 資安掃描 (離線)")
print("=" * 72)
print("\nA. runs-on")
runs = {}
for f in sorted(WF.glob('*.yml')):
    for v in re.findall(r'runs-on:\s*(\S+)', f.read_text(encoding='utf-8')):
        runs.setdefault(v, []).append(f.name)
check("沒有 ubuntu-latest", 'ubuntu-latest' not in runs, runs.get('ubuntu-latest'))
check("全部 runs-on = ubuntu-24.04", set(runs) == {'ubuntu-24.04'}, sorted(runs))

print("\nB. security-audit.yml")
sa = (WF / 'security-audit.yml').read_text(encoding='utf-8')
cmds = '\n'.join(l for l in sa.splitlines() if not l.strip().startswith('#'))
check("不再安裝或執行 Safety", 'safety' not in cmds.lower(), [l for l in cmds.splitlines() if 'safety' in l.lower()])
check("全環境掃描: 專案依賴裝在乾淨 venv, 掃 freeze 清單",
      'python -m venv /tmp/proj' in sa and '/tmp/proj/bin/pip freeze > /tmp/frozen.txt' in sa
      and '--requirement /tmp/frozen.txt --no-deps --disable-pip' in sa)
check("requirements.txt 單掃仍在", 'pip-audit --requirement requirements.txt' in sa)

print("\nC. ignore 清單都有書面理由")
ids = sorted(set(re.findall(r'--ignore-vuln\s+(\S+)', cmds)))   # commands only, not comments
doc = (ROOT / 'docs' / 'SECURITY_EXCEPTIONS.md').read_text(encoding='utf-8')
missing = [i for i in ids if i not in doc]
check(f"{len(ids)} 條 --ignore-vuln 都寫在 SECURITY_EXCEPTIONS.md", ids and not missing, missing or ids)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
