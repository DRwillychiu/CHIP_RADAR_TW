# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, sqlite3, random, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.29 DB 快照兩個慢查詢 (使用者 2026-10-08 選 A) — 離線

雲端真實 DB (62.7 萬列 / 85 天, 2026-10-08 probe run 37726932296 / 37727612542):
  Q9  派系初探 185 秒 → 9.4 秒, 結果雜湊相同
  Q10 隔日沖驗證 65 秒 (其實配對「之後任何一天」150 萬列) → 0.46 秒, 真正的下一個交易日
  ANALYZE 從沒跑過, 0.5 秒
  A. 新 Q9 與舊 Q9 結果完全相同 (含同一大戶多分點買同一檔的重複列)
  B. 新 Q10 只配對下一個交易日的賣出
  C. 快照前跑 ANALYZE; DB 不存在時不會被建成空檔
"""
import query_db

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


OLD_Q9 = ("WITH pairs AS ("
          "  SELECT a.date, a.stock_id, a.trader_id AS t1, b.trader_id AS t2 "
          "  FROM daily_chips a JOIN daily_chips b "
          "  ON a.date=b.date AND a.stock_id=b.stock_id AND a.trader_id<b.trader_id "
          "  WHERE a.buy_lots>0 AND b.buy_lots>0 AND a.source='raw') "
          "SELECT t1.name AS master_a, t2.name AS master_b, "
          "COUNT(*) AS co_buy_count, COUNT(DISTINCT pairs.stock_id) AS distinct_stocks "
          "FROM pairs JOIN traders t1 ON pairs.t1=t1.id JOIN traders t2 ON pairs.t2=t2.id "
          "GROUP BY t1.name, t2.name ORDER BY co_buy_count DESC")

db = pathlib.Path(tempfile.mkdtemp()) / 'chip_radar_v2.db'
c = sqlite3.connect(db)
c.executescript("""
CREATE TABLE traders (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE stocks (id INTEGER PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE daily_chips (id INTEGER PRIMARY KEY, date TEXT, trader_id INT, branch_id INT, stock_id INT,
  buy_lots INT, sell_lots INT, net_amt REAL, is_limit_up INT, source TEXT);
CREATE INDEX idx_dc_date ON daily_chips(date);
CREATE INDEX idx_dc_stock_date ON daily_chips(stock_id, date);
CREATE INDEX idx_dc_trader_date ON daily_chips(trader_id, date);
""")
c.executemany("INSERT INTO traders(name) VALUES (?)", [(f'M{i}',) for i in range(1, 9)])
c.executemany("INSERT INTO stocks(code, name) VALUES (?, ?)", [(str(1000 + i), f'S{i}') for i in range(1, 21)])
rnd = random.Random(7)
rows = [(f'202609{d:02d}', rnd.randint(1, 8), rnd.randint(1, 3), rnd.randint(1, 20), rnd.choice([0, 5, 9]),
         rnd.choice([0, 4]), 0, 0, rnd.choice(['raw', 'raw', 'manual']))
        for d in (1, 2, 3, 4, 7, 8) for _ in range(80)]
c.executemany("INSERT INTO daily_chips(date, trader_id, branch_id, stock_id, buy_lots, sell_lots, net_amt, "
              "is_limit_up, source) VALUES (?,?,?,?,?,?,?,?,?)", rows)
# Q10 case: M1 buys limit-up S1 on 09/04; sells on 09/07 (next trading day) and on 09/08 (later)
c.executemany("INSERT INTO daily_chips(date, trader_id, branch_id, stock_id, buy_lots, sell_lots, net_amt, "
              "is_limit_up, source) VALUES (?,?,?,?,?,?,?,?,?)",
              [('20260904', 1, 9, 1, 100, 0, 0, 1, 'raw'), ('20260907', 1, 9, 1, 0, 60, 0, 0, 'raw'),
               ('20260908', 1, 9, 1, 0, 40, 0, 0, 'raw')])
c.commit()
dups = c.execute("SELECT COUNT(*) FROM (SELECT COUNT(*) n FROM daily_chips WHERE buy_lots>0 "
                 "GROUP BY date, stock_id, trader_id HAVING n > 1)").fetchone()[0]

print("=" * 72)
print("  v3.80.29 DB 快照兩個慢查詢 (離線)")
print("=" * 72)
print("\nA. Q9 新寫法 = 舊寫法")
new_q9 = query_db.PRESETS[9][1].replace(' LIMIT 20', '')
old = c.execute(OLD_Q9).fetchall()
new = c.execute(new_q9).fetchall()
check(f"測試資料含重複列 ({dups} 組同日同檔同大戶多列)", dups > 0)
check("全部配對與次數完全相同", sorted(old) == sorted(new) and len(old) > 10, (len(old), len(new)))
check("Top 20 次數序列相同", [r[2] for r in c.execute(OLD_Q9 + ' LIMIT 20')]
      == [r[2] for r in c.execute(query_db.PRESETS[9][1])])

print("\nB. Q10 只配對下一個交易日")
q10 = c.execute(query_db.PRESETS[10][1]).fetchall()
mine = [r for r in q10 if r[0] == 'M1' and r[1] == '1001' and r[3] == '20260904']
check("09/04 漲停買進 → 只配到下一個交易日 09/07 (跳過週末), 不配 09/08",
      len(mine) == 1 and mine[0][5] == '20260907' and mine[0][6] == 60 and mine[0][7] == 60.0, mine)
nxt = dict(zip(['20260901', '20260902', '20260903', '20260904', '20260907'],
               ['20260902', '20260903', '20260904', '20260907', '20260908']))
check("每一列的賣出日都是買進日的下一個交易日", q10 and all(nxt.get(r[3]) == r[5] for r in q10),
      [r for r in q10 if nxt.get(r[3]) != r[5]][:3])
c.close()

print("\nC. ANALYZE")
snap = db.parent / 'db_query_snapshot.json'
query_db.export_all_snapshot(str(snap), str(db), log=lambda *_: None)
c = sqlite3.connect(db)
check("快照後 DB 有 sqlite_stat1 (planner 統計)", c.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0] == 1)
c.close()
s = json.loads(snap.read_text(encoding='utf-8'))
check("Q9 / Q10 在快照裡都成功", '9' in s['queries'] and '10' in s['queries'], s.get('failed'))
missing = db.parent / 'nope.db'
query_db.export_all_snapshot(str(db.parent / 'x.json'), str(missing), log=lambda *_: None)
check("DB 不存在時不會被建成空檔", not missing.exists())

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
