# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, re
from types import SimpleNamespace as NS
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.19 dev 環境 (使用者 2026-10-06): push 到 dev = 測試模式跑 daily-full — 離線

正式排程 (main) 絕不能被測試模式影響:
  A. 觸發: 只有 dev 的 push 會觸發; 3 個正式排程不變
  B. 每種觸發情境實際算出 TEST_RUN 與 concurrency group (把 GitHub 表達式轉成 Python 計算)
  C. 測試模式不寫回: 不 commit、不上傳 DB、不開 Issue; 信件/Excel 標【測試】
"""
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def gh_eval(expr, github, inputs):
    """Evaluate a ${{ }} expression of the subset used here (==, !=, &&, ||, (), '')."""
    body = re.fullmatch(r'\$\{\{\s*(.*?)\s*\}\}', expr.strip(), re.S).group(1)
    py = body.replace('&&', ' and ').replace('||', ' or ')
    return eval(py, {'__builtins__': {}}, {'github': github, 'inputs': inputs})


wf = yaml.safe_load(open(ROOT / '.github/workflows/daily-full.yml', encoding='utf-8'))
on = wf[True]
job = wf['jobs']['crawl']
steps = {s.get('name'): s for s in job['steps']}

print("=" * 72)
print("  v3.80.19 dev 環境 / 測試模式 (離線)")
print("=" * 72)

print("\nA. 觸發")
check("push 只限 dev 分支", on.get('push') == {'branches': ['dev']}, on.get('push'))
check("正式排程仍是 21:17 / 22:37 / 23:47 (平日)",
      [c['cron'] for c in on.get('schedule', [])] == ['17 13 * * 1-5', '37 14 * * 1-5', '47 15 * * 1-5'])
check("手動觸發有 test_run 選項, 預設 false",
      (on['workflow_dispatch']['inputs'].get('test_run') or {}).get('default') == 'false')

print("\nB. 每種情境: 是否測試模式 / 排隊群組")
NO_INPUT = NS(test_run=None)                    # schedule / push: inputs is empty
CASES = [
    ('正式排程 (main)',                 NS(ref='refs/heads/main', event_name='schedule'), NO_INPUT, False),
    ('手動觸發 main, 不勾 test_run',     NS(ref='refs/heads/main', event_name='workflow_dispatch'), NS(test_run='false'), False),
    ('手動觸發 main, test_run=true',    NS(ref='refs/heads/main', event_name='workflow_dispatch'), NS(test_run='true'), True),
    ('push 到 dev',                     NS(ref='refs/heads/dev', event_name='push'), NO_INPUT, True),
    ('手動觸發 dev, 不勾 test_run',      NS(ref='refs/heads/dev', event_name='workflow_dispatch'), NS(test_run='false'), True),
]
for label, g, i, want in CASES:
    test_run = bool(gh_eval(job['env']['TEST_RUN'], g, i))
    group = gh_eval(wf['concurrency']['group'], g, i)
    want_group = 'daily-full-test' if want else 'daily-full-crawl'
    check(f"{label} → 測試模式={want}, 群組 {want_group}", test_run is want and group == want_group,
          (test_run, group))
check("同群組不砍正在跑的 (cancel-in-progress=false)", wf['concurrency'].get('cancel-in-progress') is False)

print("\nC. 測試模式不寫回, 並標示清楚")
commit = steps['Commit and push data']['run']
check("commit 步驟: 測試模式在 git add 之前就 exit 0",
      'env.TEST_RUN' in commit and commit.index('exit 0') < commit.index('git add data/'))
check("測試模式: data_changed=false, send_mail=true",
      commit.index('data_changed=false') < commit.index('git add') and 'send_mail=true' in commit[:commit.index('git add')])
# v3.80.22: production send_mail = mail_round verdict (default true), only after data_changed=true
check("正式模式有資料變動才決定 send_mail (v3.80.22 由 mail_round 決定)",
      commit.count('send_mail=true') == 1 and commit.index('send_mail=${SEND:-true}') > commit.index('data_changed=true'))
check("DB artifact: 測試模式不上傳", "env.TEST_RUN != 'true'" in str(steps['Upload DB artifact'].get('if')))
for n in ('Email failure alert (GitHub Issue)', 'Source audit mismatch alert (GitHub Issue)'):
    check(f"{n}: 只在 data_changed (測試模式恆 false)", "data_changed == 'true'" in str(steps[n].get('if')))
mail = steps['Send daily summary email']
check("信件主旨: 測試模式加【測試】", '【測試】' in mail['with']['subject'] and 'env.TEST_RUN' in mail['with']['subject'])
check("附件: 測試模式改附標示過的 Excel", 'TEST_chip_radar_latest.xlsx' in mail['with']['attachments'])
check("信件內文第一段是測試聲明 (在來源比對那行之前)",
      '測試階段' in steps['Extract mobile summary']['run'])
over = steps["Test run - use main's latest data"]
check("非 main 的測試: 用 main 最新的 data/ (dev 的 data 可能是舊的)",
      'FETCH_HEAD -- data/' in over['run'] and "github.ref != 'refs/heads/main'" in over['if'])
names = [s.get('name') for s in job['steps']]
check("main 資料覆蓋在 checkout 之後、爬蟲之前",
      names.index('Checkout repo') < names.index("Test run - use main's latest data") < names.index('Run full crawler'))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
