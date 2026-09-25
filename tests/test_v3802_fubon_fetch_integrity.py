# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.1 / v3.80.2 富邦分點抓取完整性 — 離線 (合成頁面, 不打網路)

2026-09-25 逐列對帳發現的四類錯誤, 各自釘一個測試:
  A. 代號大小寫碰撞: 9A9g (永豐金-內湖) 被當成 9A9G (永豐金-天母) → 要送 hex
  B. 頁面身分: 頁面自報的分點 id != 送出的 → 必須失敗, 不可收下別人的資料
  C. 金額頁/張數頁截在前 30 → 第 31~50 名的真值被估算覆蓋; 列的集合不可變
  D. 張數頁寫 0 (零股) 是真值 → crawler.py 只能對「沒出現在該頁」的欄位反推
"""
import crawler_fetch as cf

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def row(code, v1, v2, v3):
    return (f"<tr>\n<td class=\"t4t1\" id=\"oAddCheckbox\"><SCRIPT LANGUAGE=javascript>\n<!--\n"
            f"GenLink2stk('AS{code}','S{code}');\n//-->\n</SCRIPT></td>\n"
            f"<td class=\"t3n1\">{v1:,}</td>\n<td class=\"t3n1\">{v2:,}</td>\n<td class=\"t3n1\">{v3:,}</td>\n</tr>\n")


def page(echo, buys, sells=()):
    marker = f"SetBrokerDefault('{echo}','{echo}','frm');" if echo else ''
    body = ('<html><title>x</title>資料日期：20260924 ' + marker + '<td class="t2">買超</td>'
            + ''.join(row(*r) for r in buys) + '<td class="t2">賣超</td>' + ''.join(row(*r) for r in sells))
    return body + '<!-- ' + 'x' * 6000 + ' -->'


class FakeResp:
    def __init__(self, html):
        self.status_code = 200
        self.content = html.encode('big5')


HANDLER = {}


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, timeout=None):
        HANDLER['urls'].append(url)
        return FakeResp(HANDLER['fn'](url))


cf.requests.Session = FakeSession
cf.time.sleep = lambda *_: None

print("=" * 72)
print("  v3.80.2 富邦分點抓取完整性 (離線)")
print("=" * 72)

# ── A. hex bno ──
print("\nA. 含英文字母的代號送 hex (富邦券商清單的寫法)")
check("9A9g → 0039004100390067", cf.fubon_bno('9A9g') == '0039004100390067', cf.fubon_bno('9A9g'))
check("9A9G → 0039004100390047 (與 9A9g 不同)", cf.fubon_bno('9A9G') == '0039004100390047')
check("884F → 0038003800340046 (大寫也編碼, 同清單)", cf.fubon_bno('884F') == '0038003800340046')
check("純數字 8562 不變", cf.fubon_bno('8562') == '8562')
HANDLER.update(urls=[], fn=lambda u: page('0039004100390067', [('2330', 100, 50, 50)]))
cf.fetch_branch_mode('9A9g', 'B')
check("送出的 URL 用 hex", 'b=0039004100390067' in HANDLER['urls'][0], HANDLER['urls'][0][-60:])

# ── B. identity ──
print("\nB. 頁面自報的分點 id 必須等於送出的")
HANDLER.update(urls=[], fn=lambda u: page('0039004100390067', [('2330', 100, 50, 50)]))
r = cf.fetch_branch_mode('9A9g', 'B')
check("一致 → 收下, identity=verified", r['error'] is None and r['identity'] == 'verified' and len(r['buys']) == 1, r.get('identity'))
HANDLER.update(urls=[], fn=lambda u: page('9A9G', [('2330', 100, 50, 50)]))   # 2026-09-25 實際發生的情形
r = cf.fetch_branch_mode('9A9g', 'B')
check("不一致 → error, 不給任何列", r['error'] and 'identity mismatch' in r['error'] and r['buys'] == [], r['error'])
check("不一致會重試 3 次", len(HANDLER['urls']) == 3, len(HANDLER['urls']))
HANDLER.update(urls=[], fn=lambda u: page(None, [('2330', 100, 50, 50)]))
r = cf.fetch_branch_mode('8562', 'B')
check("頁面沒有 id 標記 → 仍收下但標 unverified", r['error'] is None and r['identity'] == 'unverified')
HANDLER.update(urls=[], fn=lambda u: page('8562' if 'c=B' in u else '9999', [('2330', 100, 50, 50)]))
r = cf.fetch_branch_combined('8562')
check("金額頁對、張數頁錯 → 分點仍成功 (無張數), 不混入別人的張數",
      r['error'] is None and r['buys'] and r['buys'][0]['buy_lot'] == 0 and r['buys'][0]['lot_listed'] is False)

# ── C. full page lookup, row set unchanged ──
print("\nC. 金額頁/張數頁整頁查表, 列的集合 = 金額前30 ∪ 張數前30")
amt = [(f'A{i:03d}', 10000 - i, 10, 9990 - i) for i in range(45)]          # A000..A044 金額排名
lot = [(f'L{i:03d}', 900 - i, 1, 899 - i) for i in range(40)]              # L000..L039 張數排名
lot.insert(34, ('A005', 42, 3, 39))     # A005: 金額第 6 名, 張數第 35 名 (舊版被截掉 → 被估算)
amt.insert(33, ('L002', 777, 5, 772))   # L002: 張數第 3 名, 金額第 34 名 (舊版金額被估算)
amt.insert(36, ('L035', 555, 0, 555))   # L035: 兩頁都在 30 名外 → 不該成為一列
HANDLER.update(urls=[], fn=lambda u: page('8562', amt if 'c=B' in u else lot))
r = cf.fetch_branch_combined('8562')
rows = {s['code']: s for s in r['buys']}
expect = {c for c, *_ in amt[:30]} | {c for c, *_ in lot[:30]}
check("列的集合不變", set(rows) == expect, f"{len(rows)} vs {len(expect)}")
a5 = rows.get('A005', {})
check("A005 張數用真值 42/3 (張數頁第 35 名)", (a5.get('buy_lot'), a5.get('sell_lot')) == (42, 3), (a5.get('buy_lot'), a5.get('sell_lot')))
check("A005 均價 = 金額/真張數", a5.get('buy_avg') == round(9995 / 42, 2), a5.get('buy_avg'))
l2 = rows.get('L002', {})
check("L002 金額用真值 777 (金額頁第 34 名)", l2.get('buy_amt') == 777 and l2.get('amt_listed') is True, l2.get('buy_amt'))
check("L035 (兩頁都在 30 名外) 不成為一列", 'L035' not in rows)
check("只在金額頁的股票 lot_listed=False", rows['A010']['lot_listed'] is False and rows['A010']['amt_listed'] is True)

# ── D. crawler.py 只反推沒出現在頁上的欄位 ──
print("\nD. crawler.py 反推張數/金額前必須先看 lot_listed / amt_listed")
src_text = (ROOT / 'crawler.py').read_text(encoding='utf-8')
check("張數反推 2 處都有 not lot_listed", src_text.count('and not s.get("lot_listed", False)') == 2)
check("金額反推 2 處都有 not amt_listed", src_text.count('and not s.get("amt_listed", False)') == 2)
_id = cf.fubon_bno('9B25')   # lettered code → page echoes the hex id
HANDLER.update(urls=[], fn=lambda u: page(_id, [('2330', 25906, 879, 25027)] if 'c=B' in u else [('2330', 10, 0, 10)]))
r = cf.fetch_branch_combined('9B25')
s = r['buys'][0]
check("張數頁寫 0 (零股) → sell_lot=0 且 lot_listed=True (不會被改成 1 張)",
      s['sell_lot'] == 0 and s['lot_listed'] is True, (s['sell_lot'], s['lot_listed']))

# ── E. registry ──
print("\nE. 分點名稱與官方登記一致的已知修正")
from branches import get_branch_by_code, WATCHED_BRANCHES
check("962Q = 富邦-港都 (官方名; 舊寫法 富邦-北高雄 為同一分點)", get_branch_by_code('962Q')['name'] == '富邦-港都')
names = {}
for b in WATCHED_BRANCHES:
    names.setdefault(b['code'], set()).add(b['name'])
check("同一代號只有一個名稱", all(len(v) == 1 for v in names.values()), [c for c, v in names.items() if len(v) > 1])

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
