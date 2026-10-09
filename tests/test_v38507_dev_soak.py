# v3.85.7 dev soak: one TEST run of dev every weekday 08:30 during the soak week - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-09: "先在dev環境跑一周再說". Schedules only run on main, so a
small workflow on main dispatches daily-full on ref dev with test_run=true."""
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


wf = yaml.safe_load(open(ROOT / '.github/workflows/dev-soak.yml', encoding='utf-8'))
steps = wf['jobs']['dispatch']['steps']
run_all = '\n'.join(s.get('run', '') for s in steps)
print("=" * 72)
print("  v3.85.7 dev soak (離線)")
print("=" * 72)
crons = [c['cron'] for c in wf[True]['schedule']]
check("平日 08:30 台北 (UTC 00:30 一~五), 在測試跑允許時段 07:00-20:30 內", crons == ['30 0 * * 1-5'], crons)
check("只派 dev 的 TEST run", '--ref dev' in run_all and '-f test_run=true' in run_all and 'daily-full.yml' in run_all)
check("只要 actions: write (不寫 repo 內容)", wf['permissions'] == {'actions': 'write', 'contents': 'read'}, wf['permissions'])
check("試跑週結束後自動不做事", wf['env'].get('SOAK_END', '').isdigit() and '-le "$SOAK_END"' in run_all
      and steps[1].get('if') == "steps.win.outputs.run == 'true'")


def inside(today, end):
    return int(today) <= int(end)


end = wf['env']['SOAK_END']
check("結束日當天仍跑、隔天起停", inside(end, end) and not inside(str(int(end) + 1), end))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
