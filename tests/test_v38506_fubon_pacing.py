# v3.85.6 Fubon pacing: one source, 1.6 s floor everywhere, measured and checked weekly
import sys, pathlib, inspect, json, os, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""Owner 2026-10-08: never below 1.6 s. Owner 2026-10-09: the audit paths used
1.1 s -> unified, and "定時每周驗證是否間隔時間有改變". Offline."""
import yaml

from src.core import fubon_pacing as fp
from src.pipelines import crawler_fetch as cf
from src.audit import source_audit as sa
from src.fetchers import stock_branch_ranking as sbr

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.85.6 富邦請求間隔: 單一來源 / 底線 1.6 s / 實測 / 每週檢查 (離線)")
print("=" * 72)

print("\nA. 常數 (靜態)")
check("底線 FUBON_MIN_GAP_S >= 1.6", fp.FUBON_MIN_GAP_S >= 1.6, fp.FUBON_MIN_GAP_S)
check("主爬蟲 DELAY_MIN 取自單一來源", cf.DELAY_MIN == fp.FUBON_MIN_GAP_S and cf.DELAY_MAX >= cf.DELAY_MIN,
      (cf.DELAY_MIN, cf.DELAY_MAX))
check("來源比對 / 輕量驗證 / 轉帳觀察的 pacer = 1.6 s (原 1.1 s)",
      sa.FUBON_GAP_S == fp.FUBON_MIN_GAP_S
      and inspect.signature(sa._Pacer.__init__).parameters['gap_s'].default == fp.FUBON_MIN_GAP_S, sa.FUBON_GAP_S)
d = inspect.signature(sbr.fetch_stock_branch_ranking).parameters['delay_range'].default
check("個股分點榜 zco 最小延遲 >= 1.6 s (原 1.5 s)", d[0] >= fp.FUBON_MIN_GAP_S, d)

print("\nB. 任何會連富邦的程式都必須接單一來源")
offenders = []
for p in list(ROOT.glob('src/**/*.py')) + list(ROOT.glob('scripts/*.py')) + list(ROOT.glob('*.py')):
    txt = p.read_text(encoding='utf-8', errors='ignore')
    if 'fbs.com.tw' in txt and 'fubon_pacing' not in txt:
        offenders.append(str(p.relative_to(ROOT)))
check("含 fbs.com.tw 的檔案都 import fubon_pacing", not offenders, offenders)

print("\nC. 實測間隔 (假時鐘)")
fp.reset()
t = [100.0]
for gap in (0, 1.7, 1.6, 1.59, 2.0, 1.5):
    t[0] += gap
    fp.note_request(clock=lambda: t[0])
s = fp.summary()
check("6 次請求、5 個間隔", s['requests'] == 6, s)
check("最小間隔 1.5", s['min_gap_s'] == 1.5, s)
check("低於底線 (1.6 - 0.02 容差) 只算 1.5 那一次; 1.59 在容差內", s['below_floor'] == 1, s)
fp.reset()
slept = []
pacer = sa._Pacer(slept.append, lambda: 0.0, 10.0)
for _ in range(3):
    pacer.before_request()
check("audit pacer 每次請求都記錄 + 每次間隔睡 1.6 s",
      fp.summary()['requests'] == 3 and slept == [fp.FUBON_MIN_GAP_S] * 2, (fp.summary(), slept))

print("\nD. 寫紀錄檔")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, 'log.json')
    os.environ.pop('GITHUB_ACTIONS', None)
    check("本機 (非 Actions) 不寫 data/", fp.append_log('crawler', path) is None and not os.path.exists(path))
    fp.append_log('crawler', path, force=True)
    for i in range(fp.LOG_KEEP + 5):
        fp.append_log('source_audit', path, force=True)
    log = json.load(open(path, encoding='utf-8'))
    check(f"只保留最後 {fp.LOG_KEEP} 筆", len(log) == fp.LOG_KEEP, len(log))
    fp.reset()
    check("沒有發任何富邦請求就不寫", fp.append_log('crawler', path, force=True) is None)

print("\nE. 每週檢查的判定")
sys.path.insert(0, str(ROOT / 'scripts'))
import check_fubon_pacing as cfp  # noqa: E402
TW = timezone(timedelta(hours=8))
now = datetime(2026, 10, 18, 21, 0, tzinfo=TW)
good = [{"at": "2026-10-13 21:40", "component": "crawler", "requests": 264, "min_gap_s": 1.61, "below_floor": 0},
        {"at": "2026-10-13 21:55", "component": "source_audit", "requests": 100, "min_gap_s": 1.6, "below_floor": 0}]
days = ["20261012", "20261013", "20261014"]
check("全部 >= 底線 → 通過", cfp.check(good, days, now)[0] is True)
bad = good + [{"at": "2026-10-14 22:00", "component": "source_audit", "requests": 90, "min_gap_s": 1.1, "below_floor": 89}]
check("有一筆 1.1 s → 不通過", cfp.check(bad, days, now)[0] is False)
check("有交易日卻沒有主爬蟲紀錄 (沉默) → 不通過", cfp.check(good[1:], days, now)[0] is False)
check("7 天前的紀錄不算", cfp.check([{**good[0], "at": "2026-10-01 21:40"}], [], now)[0] is True)
check("整週休市且無紀錄 → 通過", cfp.check([], [], now)[0] is True)
first = datetime(2026, 10, 11, 21, 0, tzinfo=TW)   # v3.95.0 the first weekly run, before any production log
check("量測上線 (10/12) 前的交易日不算沉默 → 第一次週檢查不誤報",
      cfp.check([], ["20261005", "20261006", "20261007", "20261008"], first)[0] is True)
check("上線後的交易日沒紀錄 → 仍然不通過", cfp.check([], ["20261012", "20261013"], now)[0] is False)

print("\nF. 排程")
wf = yaml.safe_load(open(ROOT / '.github/workflows/fubon-pacing-weekly.yml', encoding='utf-8'))
crons = [c['cron'] for c in wf[True]['schedule']]
check("每週日 21:00 台北 (UTC 13:00 週日)", crons == ['0 13 * * 0'], crons)
steps = wf['jobs']['check']['steps']
check("跑 check_fubon_pacing.py, 失敗開 Issue",
      any('check_fubon_pacing.py' in (s.get('run') or '') for s in steps)
      and any(s.get('if') == 'failure()' and 'issues.create' in s.get('with', {}).get('script', '') for s in steps))

print("\nG. dev 試跑一週 (v3.85.7): 測試跑把實測間隔寫進執行摘要與 artifact")
df = yaml.safe_load(open(ROOT / '.github/workflows/daily-full.yml', encoding='utf-8'))
cs = {s.get('name'): s for s in df['jobs']['crawl']['steps']}
summ = cs.get('Test run - Fubon pacing summary') or {}
check("測試跑有間隔摘要步驟 (失敗也要寫)", 'always()' in str(summ.get('if')) and "TEST_RUN == 'true'" in str(summ.get('if'))
      and 'GITHUB_STEP_SUMMARY' in summ.get('run', '') and 'fubon_pacing_log.json' in summ.get('run', ''))
up = cs.get('Test run - upload outputs') or {}
check("測試跑 artifact 帶 fubon_pacing_log.json", 'data/fubon_pacing_log.json' in up.get('with', {}).get('path', ''))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
