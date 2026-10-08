# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, json, os, importlib.util
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.31 清晨補跑改成輕量驗證 (使用者 2026-10-08) — 離線

清晨的 schedule 補跑原本整套重爬 (~264 次富邦請求、~20 分/輪, 一晚 3 輪).
  A. 只有「已存的這一天乾淨」才走輕量: 同一交易日、最後一輪來源比對 ok、最後一次爬蟲 0 個失敗分點
  B. 輕量 = 拿已存的 Excel 再跟富邦原始頁比一次; 全部相符 → verified (不爬、不 commit、不寄信)
  C. 不符 / 日期不對 / 出錯 → full (照舊整套重爬, 補跑的保險功能不變)
  D. 每一輪的比對結果與失敗分點數會被記下來 (mail_rounds.json / crawl_timing.json)
  E. workflow: light job 只在 main 的 schedule 跑; crawl 只有 verdict=verified 才跳過
"""
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


lv = load('light_verify', 'scripts/light_verify.py')
mr = load('mail_round', 'scripts/mail_round.py')
import phase_timer as pt

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def rounds(td='20261008', audit='ok'):
    return {'trade_date': td, 'rounds': [{'round': 1, 'rows': 499, 'audit': 'mismatch'},
                                         {'round': 2, 'rows': 499, 'audit': audit}]}


def timing(td='20261008', fail=0, crawl=True):
    run = {'trade_date': td}
    if crawl:
        run['crawl'] = {'success': 83, 'fail': fail, 'empty': 0}
    return {'runs': [{'trade_date': '20261007', 'crawl': {'fail': 0}}, run]}


print("=" * 72)
print("  v3.80.31 清晨補跑輕量驗證 (離線)")
print("=" * 72)
print("\nA. 什麼時候可以走輕量")
E = lv.eligibility
check("同日、最後一輪比對 ok、0 失敗 → 可以", E('20261008', rounds(), timing())[0])
check("存的是別天 → 不行", not E('20261009', rounds(), timing())[0], E('20261009', rounds(), timing())[1])
check("最後一輪比對不是 ok → 不行 (例: 10/08 03:51 那種 mismatch)",
      not E('20261008', rounds(audit='mismatch'), timing())[0])
check("舊格式沒有 audit 欄 → 不行", not E('20261008', {'trade_date': '20261008', 'rounds': [{'round': 1}]},
                                            timing())[0])
check("最後一次爬蟲有失敗分點 → 不行", not E('20261008', rounds(), timing(fail=2))[0])
check("沒有爬蟲結果紀錄 → 不行", not E('20261008', rounds(), timing(crawl=False))[0])
check("gate 沒給日期 → 不行", not E('', rounds(), timing())[0])

print("\nB/C. 輕量驗證結果")
d = pathlib.Path(tempfile.mkdtemp())
(d / 'reports').mkdir()
(d / 'reports' / 'mail_rounds.json').write_text(json.dumps(rounds()), encoding='utf-8')
(d / 'crawl_timing.json').write_text(json.dumps(timing()), encoding='utf-8')
gh = d / 'gh.txt'
os.environ['GITHUB_OUTPUT'] = str(gh)
logs = []
try:
    v = lv.main(['--session', '20261008', '--data', str(d)],
                audit=lambda p: {'trade_date': '20261008', 'status': 'ok', 'rows': 499}, log=logs.append)
    check("全部相符 → verified, GITHUB_OUTPUT 有 verdict=verified",
          v == 'verified' and 'verdict=verified\n' in gh.read_text(encoding='utf-8')
          and logs[-1].startswith('::notice title=Light verification OK::499 rows'), logs[-1:])
    for label, fake in [("再比一次有不符 → full", lambda p: {'trade_date': '20261008', 'status': 'mismatch'}),
                        ("Excel 日表不是這天 → full", lambda p: {'trade_date': '20261007', 'status': 'ok'}),
                        ("比對程式出錯 → full", lambda p: 1 / 0)]:
        check(label, lv.main(['--session', '20261008', '--data', str(d)], audit=fake, log=logs.append) == 'full',
              logs[-1])
    called = []
    v = lv.main(['--session', '20261008', '--data', str(d / 'none')], audit=lambda p: called.append(p),
                log=logs.append)
    check("沒有狀態檔 → full, 而且根本不去打富邦", v == 'full' and not called, logs[-1])
finally:
    os.environ.pop('GITHUB_OUTPUT', None)

print("\nD. 每一輪記下比對結果 / 失敗分點")
TW = timezone(timedelta(hours=8))
st, _ = mr.decide({}, '20261008', 499, 'h', {}, 'workflow_dispatch', False, datetime(2026, 10, 8, 21, 46, tzinfo=TW),
                  audit='ok')
check("mail_rounds 的 round 記 audit=ok", st['rounds'][-1]['audit'] == 'ok', st['rounds'][-1])
st, _ = mr.decide(st, '20261008', 499, 'h', {}, 'schedule', False, datetime(2026, 10, 9, 3, 0, tzinfo=TW))
check("沒傳比對結果 → audit=None (不會被當成 ok)", st['rounds'][-1]['audit'] is None)
tmp = pathlib.Path(tempfile.mkdtemp())
pt.PhaseTimer().report({}, tmp, '20261008', log=lambda *_: None, crawl={'success': 83, 'fail': 0, 'empty': 0})
run = json.loads((tmp / 'crawl_timing.json').read_text(encoding='utf-8'))['runs'][-1]
check("crawl_timing 記 success/fail/empty", run['crawl'] == {'success': 83, 'fail': 0, 'empty': 0}, run.get('crawl'))
crawler_src = (ROOT / 'crawler.py').read_text(encoding='utf-8')
check("crawler 把成功/失敗/無資料分點數交給 report",
      'crawl={"success": success_count, "fail": fail_count, "empty": empty_count}' in crawler_src)

print("\nE. daily-full.yml 接線")
import yaml
wf_txt = (ROOT / '.github' / 'workflows' / 'daily-full.yml').read_text(encoding='utf-8')
jobs = yaml.safe_load(wf_txt)['jobs']
lif = jobs['light']['if']
check("light job 只在 main 的 schedule、且 gate 說今天要跑", "github.event_name == 'schedule'" in lif
      and "github.ref == 'refs/heads/main'" in lif and "needs.gate.outputs.run == 'true'" in lif, lif)
check("light 的驗證步驟 continue-on-error (出錯 → 沒有 verdict → 照爬)",
      any(s.get('id') == 'light' and s.get('continue-on-error') for s in jobs['light']['steps']))
cif = jobs['crawl']['if']
check("crawl needs [gate, light], 只有 verdict == verified 才跳過",
      jobs['crawl']['needs'] == ['gate', 'light'] and "needs.light.outputs.verdict != 'verified'" in cif
      and cif.startswith('${{ !cancelled()'), cif)
check("mail_round 收到這輪的比對結果", '--audit-status "${{ steps.audit.outputs.status }}"' in wf_txt)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
