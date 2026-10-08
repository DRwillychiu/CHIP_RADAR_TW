# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, json, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.27 爬蟲分段計時 (使用者 2026-10-08: 回到 A 的量測) — 離線

「Run full crawler」佔一輪 85% (19-25 分), 但 log 要登入才看得到.
  A. PhaseTimer: 每段耗時 → 一個 ::notice「Crawl timing」; 超過 3 分的段另出 ::warning
  B. data/crawl_timing.json 累積最近 60 輪, 可逐晚比較
  C. 富邦請求計數: 請求數 / 重試數 / 網路時間 / 刻意停頓時間
  D. crawler.main 的分段標記都在 main 的最外層, 結尾一定 report
"""
import phase_timer as pt
import crawler_fetch as cf
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


print("=" * 72)
print("  v3.80.27 爬蟲分段計時 (離線)")
print("=" * 72)
print("\nA. PhaseTimer")
c = Clock()
tm = pt.PhaseTimer(clock=c)
tm.phase('準備'); c.t += 5
tm.phase('富邦分點頁'); c.t += 560
tm.phase('FIFO部位'); c.t += 0.3
tm.phase('MOPS內部人+重訊'); c.t += 200
logs = []
d = pathlib.Path(tempfile.mkdtemp())
tm.report({'requests': 166, 'retries': 2, 'net_s': 95.2, 'sleep_s': 401.7}, d, '20261007', log=logs.append)
notice = [l for l in logs if l.startswith('::notice title=Crawl timing::')]
check("一個 Crawl timing notice, 依執行順序列出各段, 不到 1 秒的段省略",
      notice == ['::notice title=Crawl timing::total 12m45s | 準備 5s | 富邦分點頁 9m20s | MOPS內部人+重訊 3m20s'
                 ' || Fubon 166 req, 2 retries, net 1m35s, pauses 6m42s'], logs)
warn = [l for l in logs if l.startswith('::warning title=Slow stage::')]
check("超過 3 分的段各出一個 Slow stage warning (含佔比)",
      warn == ['::warning title=Slow stage::富邦分點頁 9m20s (73% of the crawl)',
               '::warning title=Slow stage::MOPS內部人+重訊 3m20s (26% of the crawl)'], warn)
run = json.loads((d / 'crawl_timing.json').read_text(encoding='utf-8'))['runs'][-1]
check("crawl_timing.json 記下 trade_date / total / 每段 (含 <1 秒段) / 富邦計數",
      run['trade_date'] == '20261007' and run['total_s'] == 765.3 and len(run['phases']) == 4
      and run['phases'][2] == ['FIFO部位', 0.3] and run['fubon']['requests'] == 166, run)

print("\nB. 只留最近 60 輪")
for _ in range(65):
    pt.PhaseTimer(clock=Clock()).report({}, d, 'x', log=lambda *_: None)
check("65 輪後檔案只剩 60 筆", len(json.loads((d / 'crawl_timing.json').read_text(encoding='utf-8'))['runs']) == 60)
pt.PhaseTimer(clock=Clock()).report({}, pathlib.Path(tempfile.mkdtemp()) / 'missing_dir', 'x',
                                    log=logs.append)
check("寫檔失敗不拋例外 (只印警告)", any('crawl timing report failed' in l for l in logs))

print("\nC. 富邦請求計數")
orig_session, orig_sleep = requests.Session, cf.time.sleep
cf.time.sleep = lambda s: None


class DeadSession:
    headers = {}

    def get(self, url, timeout=None):
        raise requests.exceptions.ConnectionError('down')
try:
    requests.Session = DeadSession
    for k in cf.FETCH_STATS:
        cf.FETCH_STATS[k] = 0 if k in ('requests', 'retries') else 0.0
    r = cf.fetch_branch_mode('9A9g', 'B', max_retries=3)
    st = dict(cf.FETCH_STATS)
    check("3 次都斷線: 3 個請求、2 次重試、停頓 3+6+9=18 秒", r['error'] and st['requests'] == 3
          and st['retries'] == 2 and st['sleep_s'] == 18, st)
    check("網路時間有計 (>= 0)", st['net_s'] >= 0, st)
finally:
    requests.Session, cf.time.sleep = orig_session, orig_sleep

print("\nD. crawler.main 接線")
src_txt = (ROOT / 'crawler.py').read_text(encoding='utf-8')
main = src_txt[src_txt.index('\ndef main():'):src_txt.index('\ndef main_margin_only():')]
marks = re.findall(r"^( *)_tm\.phase\('([^']+)'\)", main, re.M)
check("main 開頭建立 PhaseTimer 並從「準備」開始", "_tm = PhaseTimer()" in main and marks and marks[0][1] == '準備')
check("所有分段標記都在 main 最外層 (縮排 4)", marks and all(ind == '    ' for ind, _ in marks),
      [m for m in marks if m[0] != '    '])
names = [n for _, n in marks]
check("分段 >= 25 且不重複", len(names) >= 25 and len(set(names)) == len(names), len(names))
check("關鍵段落都有: 富邦分點頁 / 同輪補抓 / 三大法人 / 融資融券 / MOPS / Excel日報 / 歷史回補",
      all(n in names for n in ('富邦分點頁', '同輪補抓+日期一致', '三大法人+收盤行情', '融資融券',
                               'MOPS內部人+重訊', 'Excel日報', '歷史回補')))
i_rep, i_done = main.find('_tm.report(FETCH_STATS, data_dir, trade_date)'), main.find('✅ 完成！')
check("結尾 report 在「完成」之前", 0 < i_rep < i_done)
check("分點間停頓改用計數版 pause", '_fetch_pause(random.uniform(DELAY_MIN, DELAY_MAX))' in main
      and '_fetch_pause(COOL_DOWN_SECONDS)' in main)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
