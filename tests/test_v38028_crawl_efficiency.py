# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, json, sqlite3, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.28 爬蟲效率 (使用者 2026-10-08 選 A + 富邦停頓「絕對要多留 0.5 秒」) — 離線

2026-10-08 dev 實測 (run 37720476840): 爬蟲 21m39s = 富邦分點頁 8m55s (網路 1m24s,
停頓 7m31s) + MOPS 4m15s + DB 快照 4m11s + 其他.
  A. 富邦停頓: 實證下限 1.1 秒 (來源比對) + 0.5 秒 = 絕不低於 1.6 秒; 出錯後整輪加倍
  B. 董監持股是月資料 → 每檔每月只抓一次 (快取), 失敗不快取
  C. DB 快照: DB 內容沒變就不重跑; 每個查詢計時
"""
import crawler_fetch as cf
import insiders
import query_db
import phase_timer as pt

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.28 爬蟲效率 (離線)")
print("=" * 72)
print("\nA. 富邦停頓")
cf.FETCH_STATS['slow_factor'] = 1.0
gaps = [cf.polite_gap() for _ in range(5000)]
check("停頓絕不低於 1.6 秒 (1.1 實證 + 0.5)", min(gaps) >= 1.6 and cf.DELAY_MIN == 1.6, round(min(gaps), 3))
check("停頓上限 2.1 秒", max(gaps) <= 2.1 and cf.DELAY_MAX == 2.1, round(max(gaps), 3))
cf.slow_down(); cf.slow_down(); cf.slow_down()
slow = [cf.polite_gap() for _ in range(2000)]
check("出錯後加倍且封頂 x2 (3.2-4.2 秒, 不低於舊的 2-4 秒)", cf.FETCH_STATS['slow_factor'] == 2.0
      and min(slow) >= 3.2 and max(slow) <= 4.2, (round(min(slow), 2), round(max(slow), 2)))
text, _ = pt.PhaseTimer().lines(dict(cf.FETCH_STATS))
check("計時 notice 會寫出「slowed x2」", 'slowed x2 after errors' in text, text[-60:])
cf.FETCH_STATS['slow_factor'] = 1.0
fetch_src = (ROOT / 'src' / 'pipelines' / 'crawler_fetch.py').read_text(encoding='utf-8')
crawl_src = (ROOT / 'crawler.py').read_text(encoding='utf-8')
check("同分點兩頁之間、分點之間、補抓/日期一致都用 polite_gap",
      'pause(polite_gap())' in fetch_src and '_fetch_pause(polite_gap())' in crawl_src
      and crawl_src.count('sleep_fn(polite_gap())') == 2 and 'uniform(1.5, 2.5)' not in fetch_src)
check("重試時呼叫 slow_down", 'FETCH_STATS["retries"] += 1\n            slow_down()' in fetch_src)

print("\nB. 董監持股月快取")
cache = pathlib.Path(tempfile.mkdtemp()) / 'cache' / 'director_holdings.json'
calls, sleeps = [], []


def fake_fetch(code, y, m):
    calls.append((code, y, m))
    return None if code == '9999' else {'code': code, 'directors_count': 10, 'total_pledge_ratio': 0.1,
                                        'high_pledge_count': 0}
out, st = insiders.fetch_director_holdings_cached(['2330', '2317', '9999'], 2026, 10, cache,
                                                  fetch=fake_fetch, sleep=sleeps.append)
check("第一次: 3 檔都去 MOPS, 9999 失敗; 請求之間停 2 秒 (2 次)",
      len(calls) == 3 and st == {'cached': 0, 'fetched': 2, 'failed': 1} and sleeps == [2.0, 2.0], (st, sleeps))
calls.clear(); sleeps.clear()
out, st = insiders.fetch_director_holdings_cached(['2330', '2317', '9999', '2454'], 2026, 10, cache,
                                                  fetch=fake_fetch, sleep=sleeps.append)
check("同月第二輪: 2330/2317 用快取, 只重抓 9999 (失敗不快取) 與新的 2454",
      [c[0] for c in calls] == ['9999', '2454'] and st == {'cached': 2, 'fetched': 1, 'failed': 1}
      and sorted(out) == ['2317', '2330', '2454'] and sleeps == [2.0], (calls, st, sleeps))
calls.clear()
out, st = insiders.fetch_director_holdings_cached(['2330'], 2026, 11, cache, fetch=fake_fetch, sleep=sleeps.append)
check("換月: 快取作廢, 重新抓", calls == [('2330', 2026, 11)] and st['fetched'] == 1
      and json.loads(cache.read_text(encoding='utf-8'))['month'] == '202611', (calls, st))
check("crawler 改呼叫快取版, 檔案在 data/cache/director_holdings.json",
      "insiders.fetch_director_holdings_cached(" in crawl_src
      and "data_dir / 'cache' / 'director_holdings.json'" in crawl_src
      and 'insiders.fetch_director_holdings(code' not in crawl_src)

print("\nC. DB 快照: 沒變不跑 + 每個查詢計時")
tmp = pathlib.Path(tempfile.mkdtemp())
db = tmp / 'chip_radar_v2.db'
conn = sqlite3.connect(db)
conn.executescript("""
CREATE TABLE traders (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE daily_chips (id INTEGER PRIMARY KEY, date TEXT, trader_id INT, branch_id INT, stock_id INT,
  buy_lots INT, sell_lots INT, net_lots INT, buy_amt REAL, sell_amt REAL, net_amt REAL);
INSERT INTO traders(name) VALUES ('A'), ('B');
INSERT INTO daily_chips(date, trader_id, buy_lots, sell_lots, net_amt) VALUES ('20261007', 1, 83, 64, 957);
""")
conn.commit(); conn.close()
saved = query_db.PRESETS
query_db.PRESETS = {1: ('Traders', 'SELECT name FROM traders ORDER BY name'),
                    2: ('bad', 'SELECT nope FROM missing_table')}
logs = []
snap = tmp / 'db_query_snapshot.json'
try:
    r1 = query_db.export_all_snapshot(str(snap), str(db), log=logs.append)
    s1 = json.loads(snap.read_text(encoding='utf-8'))
    check("第一次寫出, 每個查詢有 elapsed_s, 有 DB 指紋", r1 == 'written' and 'elapsed_s' in s1['queries']['1']
          and s1['db_signature'] and s1['failed'][0]['q'] == 2, s1.get('failed'))
    check("最慢的查詢進 ::notice", any(l.startswith('::notice title=DB snapshot::total') for l in logs), logs[-1:])
    r2 = query_db.export_all_snapshot(str(snap), str(db), log=logs.append)
    check("DB 沒變 → 跳過, 不重寫", r2 == 'skipped' and json.loads(snap.read_text(encoding='utf-8')) == s1)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE daily_chips SET buy_lots = 0")      # 10/08 03:51 那種: 列數同、張數變
    conn.commit(); conn.close()
    r3 = query_db.export_all_snapshot(str(snap), str(db), log=logs.append)
    check("列數相同但張數變了 → 指紋不同, 重跑", r3 == 'written')
    r4 = query_db.export_all_snapshot(str(snap), str(tmp / 'none.db'), log=logs.append)
    check("DB 讀不到 → 不會誤判成「沒變」", r4 == 'written')
finally:
    query_db.PRESETS = saved

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
