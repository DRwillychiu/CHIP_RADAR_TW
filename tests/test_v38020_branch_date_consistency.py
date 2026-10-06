# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, copy, inspect
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.20 一輪裡每個分點的資料日期必須一致 (使用者 2026-10-06 選 A) — 離線

2026-10-06 16:24 dev 測試 run 跨過富邦 10/05 → 10/06 換日: trade_date 只取第一個
分點 (10/05), 後面分點已是 10/06 → 兩天混在一起標成 20261005, 來源比對 74 列不符.
  A. 日期一致 → 不重抓、不動資料
  B. 混日 → 以最新日期為準; 舊日期分點重抓, 換上新資料或清空記失敗 (寧缺勿混)
  C. 重抓後是新日期但沒有進出 → 當成「無資料」, 不算失敗
  D. crawler.main 在同輪補抓之後做這一步, 並以最新日期當 trade_date
"""
import crawler

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


CLS = lambda code, name: {'category': 'listed', 'category_simple': 'listed',
                          'category_basic': 'listed', 'industry': '測試', 'is_ky': False}
NO_SLEEP = lambda s: None


def br(code, date, rows=True, error=None):
    return {'code': code, 'master': 'm', 'name': f'n{code}', 'date': date, 'error': error,
            'buys': [{'code': '2330', 'name': '台積電', 'buy_amt': 1}] if rows else [], 'sells': []}


def page(date, rows=True, error=None):
    return {'date': date, 'error': error,
            'buys': [{'code': '2454', 'name': '聯發科', 'buy_amt': 2}] if rows else [], 'sells': []}


print("=" * 72)
print("  v3.80.20 分點資料日期一致性 (離線)")
print("=" * 72)

print("\nA. 日期一致")
res = [br('A', '20261006'), br('B', '20261006'), br('D', None, rows=False, error='timeout')]
before = copy.deepcopy(res)
out = crawler.reconcile_branch_dates(res, lambda c: (_ for _ in ()).throw(AssertionError(c)), CLS,
                                     sleep_fn=NO_SLEEP)
check("回傳 (0, 0, 0, 最新日期), 不重抓", out == (0, 0, 0, '20261006'), out)
check("資料完全不動", res == before)
check("全部沒資料 → (0, 0, 0, None)",
      crawler.reconcile_branch_dates([br('E', None, rows=False)], None, CLS, sleep_fn=NO_SLEEP) == (0, 0, 0, None))

print("\nB. 混日 (重現 10/06 16:24: 第一個分點 10/05, 後面 10/06)")
res = [br('A', '20261005'), br('B', '20261006'), br('C', '20261005'),
       br('D', None, rows=False, error='Read timed out'), br('E', None, rows=False), br('F', '20261005')]
fetched = []
def fetch(code):
    fetched.append(code)
    return {'A': page('20261006'), 'C': page('20261005'),
            'F': page(None, rows=False, error='Read timed out')}[code]
out = crawler.reconcile_branch_dates(res, fetch, CLS, sleep_fn=NO_SLEEP)
check("只重抓舊日期且有資料的分點 (A, C, F); 不碰最新的 B、失敗的 D、無資料的 E",
      fetched == ['A', 'C', 'F'], fetched)
check("回傳: 換上 1 (A) / 不收 2 (C 仍舊日期, F 逾時) / 無資料 0 / 最新 20261006",
      out == (1, 2, 0, '20261006'), out)
check("A 換成 10/06 的資料, 有分類, 記下原本日期",
      res[0]['date'] == '20261006' and res[0]['buys'][0]['code'] == '2454'
      and res[0]['buys'][0].get('market_type') == 'listed' and res[0].get('refetched_from_date') == '20261005',
      res[0])
check("C 仍是 10/05 → 清空 + error (寧缺勿混)",
      res[2]['error'] and 'stale data date 20261005' in res[2]['error'] and not res[2]['buys']
      and res[2].get('stale_date') == '20261005', res[2].get('error'))
check("F 重抓逾時 → 也清空 + error", res[5]['error'] and not res[5]['buys'], res[5].get('error'))
check("B / D / E 完全不動", res[1] == br('B', '20261006') and res[3]['error'] == 'Read timed out'
      and res[4] == br('E', None, rows=False))
left = {r['date'] for r in res if not r['error'] and (r['buys'] or r['sells'])}
check("留下的有資料分點全部是 20261006", left == {'20261006'}, left)

print("\nC. 重抓後是新日期但當天沒有進出")
res = [br('A', '20261006'), br('G', '20261005')]
out = crawler.reconcile_branch_dates(res, lambda c: page('20261006', rows=False), CLS, sleep_fn=NO_SLEEP)
check("算「無資料」(0, 0, 1, 最新), 不算失敗", out == (0, 0, 1, '20261006'), out)
check("G: 無 error、無資料、日期改為 20261006",
      res[1]['error'] is None and not res[1]['buys'] and res[1]['date'] == '20261006', res[1])

print("\nD. crawler.main 的接線")
src_main = inspect.getsource(crawler.main)
i_retry = src_main.index('retry_failed_branches(')
i_rec = src_main.index('reconcile_branch_dates(')
check("同輪補抓之後才做日期一致性 (補回的分點也要檢查)", i_retry < i_rec)
check("trade_date 改用最新日期", 'trade_date = _newest' in src_main[i_rec:])
check("不收的分點計入失敗, 無資料的計入無資料",
      'fail_count += _stale' in src_main and 'empty_count += _emptied' in src_main)
check("在「全部失敗/假日」判斷之前", i_rec < src_main.index('假日 / 全部失敗'))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
