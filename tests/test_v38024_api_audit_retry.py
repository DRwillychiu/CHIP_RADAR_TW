# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, importlib.util, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.24 每週 API 欄位稽核: 抓取暫時失敗不再讓整個週稽核變紅 — 離線

weekly-loop-audit 連 7 週 failure: 「API 欄位漂移稽核」把任何抓取失敗都算 CRITICAL
(TPEx daily_close_quotes 25 秒單次抓取常斷 ChunkedEncodingError), 又因為它在
Commit results 之前, combo / multiday / pinned 等回測檔停在 2026-09-20.
  A. probe 重試 3 次 (60 秒 timeout), 中間成功就用
  B. 重試完仍失敗 = 抓取失敗 (::warning), 不算 CRITICAL, 不讓步驟變紅
  C. 欄位真的不見 = CRITICAL, 照樣 exit 1 (守門本意不變)
  D. Commit results 在稽核紅燈時仍執行
"""
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('audit_api_fields', ROOT / 'scripts' / 'audit_api_fields.py')
aa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aa)
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def reset():
    aa.FAIL = aa.WARN = aa.OK = aa.FETCH = 0


print("=" * 72)
print("  v3.80.24 每週 API 欄位稽核重試 (離線)")
print("=" * 72)
orig_get, orig_sleep = requests.get, time.sleep
time.sleep = lambda s: None
try:
    print("\nA. 重試")
    calls = []

    def flaky(url, headers=None, timeout=None):
        calls.append(timeout)
        if len(calls) < 3:
            raise requests.exceptions.ChunkedEncodingError('Connection broken')
        return Resp([{'a': 1}])
    requests.get = flaky
    check("前兩次斷線、第三次成功 → 拿到資料", aa.probe('u', sleep=lambda s: None) == [{'a': 1}] and len(calls) == 3,
          calls)
    check("timeout = 60 秒", calls and calls[0] == 60, calls[:1])

    print("\nB. 一直抓不到 = 抓取失敗, 不是 CRITICAL")

    def down(url, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError('down')
    requests.get = down
    reset()
    rc = aa.main()
    n = len(aa.REGISTRY) + len(aa.REGISTRY_RWD)
    check("全部抓不到 → exit 0, 抓取失敗計數 = 端點數, CRITICAL = 0", rc == 0 and aa.FETCH == n and aa.FAIL == 0,
          (rc, aa.FETCH, n, aa.FAIL))

    print("\nC. 欄位不見仍是 CRITICAL")
    requests.get = lambda url, headers=None, timeout=None: Resp([{'unrelated': 1}])
    reset()
    aa.REGISTRY_RWD_SAVE, aa.REGISTRY_RWD = aa.REGISTRY_RWD, []
    try:
        rc = aa.main()
    finally:
        aa.REGISTRY_RWD = aa.REGISTRY_RWD_SAVE
    need = sum(1 for r in aa.REGISTRY if r[3] and r[4])
    check("上游欄位消失 → CRITICAL > 0 且 exit 1", need > 0 and aa.FAIL >= need and rc == 1, (need, aa.FAIL, rc))
finally:
    requests.get, time.sleep = orig_get, orig_sleep

print("\nD. weekly-loop-audit.yml")
wf = (ROOT / '.github' / 'workflows' / 'weekly-loop-audit.yml').read_text(encoding='utf-8')
i = wf.find('- name: Commit results')
check("Commit results 有 if: success() || failure()", i > 0 and 'if: success() || failure()' in wf[i:i + 120])
check("Commit results 在 API 稽核之後 (稽核紅燈也會 commit)", wf.find('- name: API 欄位漂移稽核') < i)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
