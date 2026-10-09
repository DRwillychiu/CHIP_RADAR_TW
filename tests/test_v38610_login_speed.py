# v3.86.1 login speed: summary-first unlock, lazy tabs, HEAD revalidate - offline
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-09: "網站登錄超級慢的。優先研究解決". Measured: GitHub Pages ~40 KB/s
from Taipei (3 Singapore edges, all MISS); latest.json 2.1 MB took 40-65 s and login
waited for it. Lab at 50 KB/s with real AES-GCM: old page 56.4 s to unlock, new 0.41 s;
wrong password 0.33 s; revalidate = 1 HEAD instead of 2.8 MB."""

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def body(src, head, stop='\n}\n'):
    i = src.index(head)
    return src[i:src.index(stop, i) + len(stop)]


h = (ROOT / 'index.html').read_text(encoding='utf-8').replace('\r\n', '\n')
if 'id="panel-summary"' not in h and (ROOT / 'preview' / 'index.html').exists():
    h = (ROOT / 'preview' / 'index.html').read_text(encoding='utf-8').replace('\r\n', '\n')
print("=" * 72)
print("  v3.86.1 登入速度 (離線)")
print("=" * 72)

print("\n[A] 登入先驗證 2 KB 的總整理")
un = body(h, 'async function attemptUnlock(')
i_sum, i_latest = un.find('_fetchSummaryEnvelope()'), un.find('/latest.json')
check("先抓 daily_summary.json, 再考慮 latest.json", 0 <= i_sum < i_latest, (i_sum, i_latest))
seg = un[i_sum:i_latest]
check("總整理解得開 → 立刻顯示第一頁、背景載日資料、直接 return",
      'renderDailySummary();' in seg and '_loadDayDataInBackground();' in seg and 'return;' in seg
      and "classList.add('unlocked')" in seg and 'SESSION_PASSWORD = password;' in seg)
check("沒有總整理檔 → 舊流程照走 (latest.json)", "const r = await fetchWithTimeout(`${DATA_BASE}/latest.json" in un[i_latest - 60:])
fe = body(h, 'async function _fetchSummaryEnvelope(')
check("總整理檔 404 / 壞掉 → 回 null (不擋登入)", 'return null' in fe and 'catch' in fe)
bg = body(h, 'function _loadDayDataInBackground(')
check("背景載入: 只跑一次、跑完 init、失敗可重試",
      'if (_DAY_LOADING) return _DAY_LOADING;' in bg and 'init()' in bg and "_setDataStatus('fail')" in bg and '_DAY_LOADING = null' in bg)
check("日資料一到就收起「下載中」標籤 (不等持倉)", re.search(r"while \(!CURRENT_DATA && !finished\)[\s\S]{0,120}_setDataStatus\(CURRENT_DATA \? 'ok' : 'fail'\)", bg) is not None)
lk = body(h, 'function lockApp(')
check("鎖定時清掉背景載入狀態和總整理", '_DAY_LOADING = null' in lk and 'DAILY_SUMMARY = null' in lk)

print("\n[B] 看不到的分頁不先畫")
ra = body(h, 'function renderAll() {')
eager = [f for f in ['renderToday3();', 'renderOverview();', 'renderBranches();', 'renderStockTrace();', 'renderMasterPref();'] if f in ra]
check("renderAll 不再直接畫 5 個隱藏分頁 (含抓 4 天日檔的 renderMasterPref)", not eager, eager)
check("renderAll 只畫畫面上那一頁", 'renderTabNow(_active)' in ra and "querySelector('.tab.active')" in ra)
rt = body(h, 'function renderTabNow(tab) {')
tabs = re.findall(r'data-tab="(\w+)" role="tab"', h)
own_hook = {'masterprofile', 'holdings', 'watchlist'}          # these tabs have their own click hooks
missing = [t for t in tabs if t not in own_hook and f"tab === '{t}'" not in rt]
check("每個分頁都有自己的畫法 (點開時畫)", not missing, missing)
click = h[h.index("document.querySelectorAll('.tab').forEach(btn => {"):]
click = click[:click.index('\n  });') + 5]
check("點分頁和 renderAll 用同一個 renderTabNow", 'renderTabNow(tab);' in click)

print("\n[C] 每 5 分鐘的檢查先送 HEAD")
rv = body(h, 'async function revalidateCache() {')
i_head, i_get = rv.find('_latestStamp()'), rv.find('/latest.json')
check("先 HEAD, 版本沒變就 return, 有變才下載", 0 <= i_head < i_get and 'stamp === CURRENT_LATEST_ETAG) return;' in rv)
check("日資料還在背景載入時不檢查", 'if (!CURRENT_CRAWLED_AT) return;' in rv)
ls = body(h, 'async function _latestStamp() {')
check("HEAD 不下載內容, 讀 ETag / Last-Modified", "method: 'HEAD'" in ls and "get('etag')" in ls and "get('last-modified')" in ls)

print("\n[D] 同一個檔案同時只抓一次")
ld = body(h, 'function loadDate(date) {')
check("loadDate 共用進行中的請求", 'if (!_DAY_INFLIGHT[date]) _DAY_INFLIGHT[date] = _loadDate(date)' in ld and 'return _DAY_INFLIGHT[date];' in ld)
sh = body(h, 'function loadStockHistory() {')
check("loadStockHistory (9.5 MB) 共用進行中的請求", 'if (!_SH_INFLIGHT) _SH_INFLIGHT = _loadStockHistory()' in sh and 'return _SH_INFLIGHT;' in sh)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
