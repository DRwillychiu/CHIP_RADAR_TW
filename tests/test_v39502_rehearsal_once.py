# v3.95.2 one-shot rehearsal: one TEST run of the nightly crawl on 2026-10-11 - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-10 "A": rehearse the whole crawl this weekend with a one-day scheduler on main.
Delete this test together with .github/workflows/rehearsal-once.yml on 2026-10-12."""
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


wf = yaml.safe_load(open(ROOT / '.github/workflows/rehearsal-once.yml', encoding='utf-8'))
steps = wf['jobs']['dispatch']['steps']
run_all = '\n'.join(s.get('run', '') for s in steps)
print("=" * 72)
print("  v3.95.2 週末預演: 10/11 一次 TEST run (離線)")
print("=" * 72)
crons = [c['cron'] for c in wf[True]['schedule']]
check("只在 10/11: 09:00 主跑、13:00 備援 (UTC 01:00 / 05:00)", crons == ['0 1 11 10 *', '0 5 11 10 *'], crons)
check("其他日期什麼都不做 (RUN_ON = 20261011)", wf['env'].get('RUN_ON') == '20261011' and '[ "$TODAY" = "$RUN_ON" ]' in run_all)
check("只在 07:00-20:00 派 (TEST run 自己 20:30-07:00 會拒絕)", '-ge 700' in run_all and '-lt 2000' in run_all)
check("當天已有 dev TEST run 就不再派 (備援不重複)", "--event workflow_dispatch" in run_all and 'select(.createdAt >= "2026-10-10T23:00:00Z")' in run_all
      and steps[-1].get('if', '').endswith("steps.dup.outputs.go == 'true'"))
check("只派 dev 的 TEST run", '--ref dev' in run_all and '-f test_run=true' in run_all and 'daily-full.yml' in run_all)
check("只要 actions: write (不寫 repo 內容)", wf['permissions'] == {'actions': 'write', 'contents': 'read'}, wf['permissions'])
print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
