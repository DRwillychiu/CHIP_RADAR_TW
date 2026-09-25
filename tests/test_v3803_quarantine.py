# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, re, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.3 已知錯誤分點日排除清單 (data/quarantine.json + src/core/quarantine.py) — 離線

A. 清單本身: 52 個分點日, 代號大小寫精確比對, 9/24 已由雲端重抓修好不在清單
B. filter_day: 只清空被排除的那筆, 不動其他分點, 不改輸入物件
C. 防漏: 任何解密每日檔的程式都必須經過 filter_day, 除非列在 ALLOW 並寫明理由
"""
import quarantine as q

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.80.3 分點日排除清單")
print("=" * 72)

# ── A ──
print("\nA. 清單內容")
t = q.load()
check("兩個代號: 9A9g / 9A9G", set(t) == {'9A9g', '9A9G'}, sorted(t))
check("共 52 個分點日 (9A9g 14 + 9A9G 38)", (len(t.get('9A9g', {})), len(t.get('9A9G', {}))) == (14, 38),
      (len(t.get('9A9g', {})), len(t.get('9A9G', {}))))
check("大小寫精確: 9A9g@0609 排除, 9A9G@0609 不排除",
      q.is_quarantined('9A9g', '20260609') and not q.is_quarantined('9A9G', '20260609'))
check("20260924 不在清單 (447cc3f 已用修正版重抓)", not q.is_quarantined('9A9g', '20260924') and not q.is_quarantined('9A9G', '20260924'))
check("日期格式全是 YYYYMMDD", all(re.fullmatch(r'\d{8}', d) for m in t.values() for d in m))

# ── B ──
print("\nB. filter_day")
day = {'trade_date': '20260623', 'branches': [
    {'code': '9A9g', 'name': '永豐金-內湖', 'master': '陳族元', 'buys': [{'code': '2330'}], 'sells': [{'code': '2317'}], 'error': None},
    {'code': '9A9G', 'name': '永豐金-天母', 'master': '永豐天母(老錢)', 'buys': [{'code': '2454'}], 'sells': [], 'error': None},
    {'code': '9216', 'name': '凱基-信義', 'master': '林滄海', 'buys': [{'code': '2603'}], 'sells': [], 'error': None},
]}
snapshot = json.dumps(day, ensure_ascii=False, sort_keys=True)
out = q.filter_day(day, '20260623')
by = {b['code']: b for b in out['branches']}
check("0623 兩個都被排除 (當天兩邊互換)", by['9A9g']['quarantined'] and by['9A9G']['quarantined'])
check("被排除的: buys/sells 清空, error 註明, code/master 保留",
      by['9A9g']['buys'] == [] and by['9A9g']['sells'] == [] and by['9A9g']['error'].startswith('quarantined:')
      and by['9A9g']['master'] == '陳族元')
check("其他分點原封不動", by['9216'] is day['branches'][2])
check("輸入物件沒被改", json.dumps(day, ensure_ascii=False, sort_keys=True) == snapshot)
check("未指定 date → 用 trade_date", q.filter_day(day)['branches'][0].get('quarantined') is True)
clean = {'trade_date': '20260624', 'branches': day['branches']}
check("沒命中的日子回傳同一物件 (零成本)", q.filter_day(clean, '20260624') is clean)
check("非日檔結構原樣回傳", q.filter_day({'x': 1}, '20260623') == {'x': 1} and q.filter_day(None) is None)

# ── D ──
print("\nD. DB: 寫入時跳過, 已存在的錯列在下次寫入時刪掉 (in-memory, 合成資料)")
import db_pipeline as dbp
conn = dbp.init_db(':memory:')
stk = {'code': '2330', 'name': 'T', 'buy_lot': 1, 'sell_lot': 0, 'buy_amt': 10, 'sell_amt': 0, 'net_amt': 10,
       'net_lot': 1, 'buy_avg': 10.0, 'sell_avg': 0.0, 'is_limit_up': False, 'trade_style': 'overnight'}
def mkday(td):
    return {'trade_date': td, 'branches': [
        {'code': '9A9g', 'name': '永豐金-內湖', 'master': '陳族元', 'buys': [dict(stk)], 'sells': []},
        {'code': '9A9G', 'name': '永豐金-天母', 'master': '永豐天母(老錢)', 'buys': [dict(stk)], 'sells': []},
        {'code': '9216', 'name': '凱基-信義', 'master': '林滄海', 'buys': [dict(stk)], 'sells': []}]}
def rows(td, code):
    a = conn.execute("SELECT COUNT(*) FROM daily_chips c JOIN branches b ON b.id=c.branch_id WHERE c.date=? AND b.code=?", (td, code)).fetchone()[0]
    b = conn.execute("SELECT COUNT(*) FROM daily_records WHERE date=? AND branch_code=?", (td, code)).fetchone()[0]
    return a, b
_real_load = q.load
q.load = lambda path=None: {}                 # 模擬 v3.80.3 以前: 錯列照樣寫進 DB
dbp.upsert_from_raw_dict(conn, mkday('20260623'))
q.load = _real_load
check("前置: 舊版寫入後 0623 的 9A9g 有列", rows('20260623', '9A9g')[0] > 0, rows('20260623', '9A9g'))
st = dbp.upsert_from_raw_dict(conn, mkday('20260624'))   # 任何一次新寫入都會先清
check("下一次寫入後 0623 的 9A9g / 9A9G 列被刪光",
      rows('20260623', '9A9g') == (0, 0) and rows('20260623', '9A9G') == (0, 0), st.get('quarantine_purged'))
check("同一天其他分點 (9216) 不受影響", rows('20260623', '9216')[0] > 0)
check("非排除日 0624 的 9A9g 照常寫入", rows('20260624', '9A9g')[0] > 0)
dbp.upsert_from_raw_dict(conn, mkday('20260609'))        # 0609 只有 9A9g 在清單
check("直接寫排除日: 0609 的 9A9g 不寫入、9A9G 照寫",
      rows('20260609', '9A9g') == (0, 0) and rows('20260609', '9A9G')[0] > 0)
conn.close()

# ── C ──
print("\nC. 防漏: 解密每日檔的程式都要經過 filter_day")
ALLOW = {
    'src/pipelines/crawler_output.py': 'defines encrypt/decrypt; writes today only',
    'src/pipelines/archive_manager.py': 'moves/compresses files; content must stay byte-identical',
    'src/pipelines/crawler_pipeline.py': 'decrypts positions.json (FIFO state), not a day file',
    'src/audit/excel_strict_verify.py': 'audits raw latest.json against the Excel',
    'src/audit/histock_branch_audit.py': 'audits raw latest.json against histock',
    'src/audit/stress_test_data_integrity.py': 'raw-data integrity audit; must see what is stored',
    'scripts/sanity_check_618.py': 'one-off raw sanity check of 20260618',
}
readers = []
for p in [ROOT / 'crawler.py'] + sorted((ROOT / 'src').rglob('*.py')) + sorted((ROOT / 'scripts').rglob('*.py')):
    rel = p.relative_to(ROOT).as_posix()
    txt = p.read_text(encoding='utf-8', errors='replace')
    if 'decrypt_data' in txt and rel != 'src/core/quarantine.py':
        readers.append((rel, txt))
missing = [rel for rel, txt in readers if rel not in ALLOW and 'filter_day' not in txt]
check(f"{len(readers)} 個解密每日檔的程式, 未經 filter_day 且不在 ALLOW 的 = 0", not missing, missing)
stale = [a for a in ALLOW if not (ROOT / a).exists()]
check("ALLOW 裡沒有已不存在的檔案", not stale, stale)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
