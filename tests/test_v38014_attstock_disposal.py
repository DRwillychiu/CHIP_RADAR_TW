# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, json, tempfile, importlib.util
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.14 處置股資料 (attstock) — 離線

2026-08-21 ~ 10-06 data/disposal_attstock.json 沒更新過 (簡寫 UA 被 403), Email
「明日恐處置」一直寄 8/21 的清單; 「處置中」更是從來都是 0 (讀錯 API).
  A. 處置中來自 /disposal (起日 <= 今天 <= 迄日), 明日恐處置來自 /risk
  B. 403/429 不重試; 送完整 Chrome UA + Referer
  C. Excel/Email 只採用「該交易日當天或之後」抓到的清單, 過期就註明不列
  D. daily-full: 先抓處置股, 再做最後一次產表
"""
import openpyxl
import yaml
import excel_report as er

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('ra', ROOT / 'scripts' / 'refresh_attstock_disposal.py')
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.14 處置股資料 (離線)")
print("=" * 72)

print("\nA. 處置中 / 明日恐處置")
disposal = [{'code': '6526', 'name': '達發', 'disposal_start_date': '2026-09-30', 'disposal_end_date': '2026-10-06'},
            {'code': '1111', 'name': '已結束', 'disposal_start_date': '2026-09-20', 'disposal_end_date': '2026-10-01'},
            {'code': '2222', 'name': '還沒開始', 'disposal_start_date': '2026-10-08', 'disposal_end_date': '2026-10-14'}]
risk = [{'code': '3094', 'name': '聯傑', 'status': 'risk', 'analysis': {'minDaysToDisposal': 1}},
        {'code': '6526', 'name': '達發', 'status': 'risk', 'analysis': {'minDaysToDisposal': 1}},
        {'code': '5555', 'name': '兩天後', 'status': 'risk', 'analysis': {'minDaysToDisposal': 2}}]
ind, pend, _ = ra.summarize(risk, disposal, '2026-10-06')
check("處置中 = 起迄區間含今天的 /disposal 列 (已結束、未開始的不算)", ind == ['6526'], ind)
check("明日恐處置 = /risk minDaysToDisposal == 1, 已在處置中的不重複列", pend == ['3094'], pend)

print("\nB. 抓取")
check("完整 Chrome UA + Accept + Referer", 'Chrome/' in ra.HEADERS['User-Agent']
      and ra.HEADERS.get('Referer') == 'https://attstock.tw/' and 'Accept' in ra.HEADERS)
calls = []
class R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)
    def json(self):
        return self._b
ra.time.sleep = lambda *_: None
ra.requests.get = lambda url, **k: (calls.append(url), R(403))[1]
try:
    ra.fetch('https://attstock.tw/api/stocks/risk'); err = None
except PermissionError as e:
    err = e
check("403 → 立即 PermissionError, 只打 1 次 (不重試)", err is not None and len(calls) == 1, (err, len(calls)))
ra.requests.get = lambda url, **k: R(200, [{'code': '1'}])
check("200 → 回傳 list", ra.fetch('x') == [{'code': '1'}])

print("\nC. 過期清單不列 (Excel / Email)")
def mobile_text(fetched_at):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / 'disposal_attstock.json').write_text(json.dumps({
        'fetched_at': fetched_at, 'count_in_disposal': 1, 'count_pending_1d': 1,
        'codes_in_disposal': ['6526'], 'codes_pending_1d': ['3094']}), encoding='utf-8')
    ws = openpyxl.Workbook().active
    er.build_mobile_summary_sheet(ws, [], '20261005', data_dir=d)
    return er.mobile_summary_text(ws)
stale = mobile_text('2026-08-21T16:25:20.422924')
fresh = mobile_text('2026-10-05T21:40:00+08:00')
check("8/21 抓的清單在 10/05 → 註明「處置股資料未更新 (最後 2026-08-21)」",
      '處置股資料未更新 (最後 2026-08-21)' in stale, stale[-160:])
check("過期時不列出代號", '3094' not in stale and '6526' not in stale)
check("當天抓的清單 → 列出 處置中 / 明日恐處置", '處置中 1 檔 (6526)' in fresh and '明日恐處置 1 檔 (3094)' in fresh)
dd = pathlib.Path(tempfile.mkdtemp())
(dd / 'disposal_attstock.json').write_text(json.dumps({'fetched_at': '2026-10-06T00:30:00+08:00'}), encoding='utf-8')
got, last = er._fresh_attstock(dd, '20261005')
check("隔天 00:30 抓的 (10/05 晚上的延遲排程) 算 10/05 的", got is not None and last is None, (got, last))
got, last = er._fresh_attstock(dd, '20261007')
check("但對 10/07 而言是過期的", got is None and last == '2026-10-06', (got, last))

print("\nD. daily-full 步驟順序")
steps = [s.get('name') for s in yaml.safe_load(open(ROOT / '.github/workflows/daily-full.yml', encoding='utf-8'))['jobs']['crawl']['steps']]
i_att = steps.index('Refresh attstock disposal')
i_regen = steps.index('Update Phase 3.2 rolling backtest + regen Excel')
check("先抓處置股, 再做最後一次產表 (Email 用的就是這份)", i_att < i_regen, steps)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
