# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, datetime as dt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.81.0 winrate Task 1.1 — 按日期抓分點歷史 (離線, 合成頁面)

實測 (2026-09-30) 釘住的行為:
  A. 指定日期用 e=f=那一天 (區間會被加總, 不可用), 代號仍送 hex
  B. 頁面日期 (資料日期：) 必須等於指定日期, 不符 → 重試後 error, 不收資料
  C. 休市日/週末/颱風假: 富邦回小頁面、沒有日期標記 → no_data=True, 不是錯誤
  D. 金額頁與張數頁都帶同一個日期; 分點身分檢查照舊
  E. 不給日期 = 每日爬蟲原本的行為 (d=1), 不受影響
"""
import crawler_fetch as cf

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


def page(echo, data_date, buys, sells=()):
    marker = f"SetBrokerDefault('{echo}','{echo}','frm');"
    if data_date is None:     # non-trading day: short page, no date, no tables (~11k chars live)
        return '<html>' + marker + '<!-- ' + 'x' * 11000 + ' -->'
    body = (f'<html>資料日期：{data_date} ' + marker + '<td class="t2">買超</td>'
            + ''.join(row(*r) for r in buys) + '<td class="t2">賣超</td>' + ''.join(row(*r) for r in sells))
    return body + '<!-- ' + 'x' * 6000 + ' -->'


class FakeResp:
    def __init__(self, html):
        self.status_code = 200
        self.content = html.encode('big5')


H = {}


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, timeout=None):
        H['urls'].append(url)
        return FakeResp(H['fn'](url))


cf.requests.Session = FakeSession
cf.time.sleep = lambda *_: None
ID = cf.fubon_bno('9A9g')

print("=" * 72)
print("  v3.81.0 Task 1.1 按日期抓分點歷史 (離線)")
print("=" * 72)

print("\nA. 網址")
H.update(urls=[], fn=lambda u: page(ID, '20260924', [('6213', 119595, 5181, 114414)]))
cf.fetch_branch_mode('9A9g', 'B', date='20260924')
u = H['urls'][0]
check("單日 e=f=2026-9-24, 不用 d=1", 'e=2026-9-24&f=2026-9-24' in u and 'd=1' not in u, u[-50:])
check("代號仍送 hex", f'a={ID}&b={ID}' in u)
check("日期可給 YYYYMMDD / YYYY-MM-DD / date 物件",
      cf._fubon_date('20260924') == cf._fubon_date('2026-09-24') == cf._fubon_date(dt.date(2026, 9, 24)) == '2026-9-24')

print("\nB. 頁面日期必須等於指定日期")
r = cf.fetch_branch_mode('9A9g', 'B', date='20260924')
check("相符 → 收下, date=20260924", r['error'] is None and r['date'] == '20260924' and len(r['buys']) == 1)
H.update(urls=[], fn=lambda u: page(ID, '20260930', [('6213', 1, 1, 0)]))
r = cf.fetch_branch_mode('9A9g', 'B', date='20260924')
check("不符 (給了最新一天) → error, 不給任何列", r['error'] and 'date mismatch' in r['error'] and r['buys'] == [], r['error'])
check("不符會重試 3 次", len(H['urls']) == 3, len(H['urls']))

print("\nC. 休市日 / 週末 / 颱風假")
H.update(urls=[], fn=lambda u: page(ID, None, []))
r = cf.fetch_branch_combined('9A9g', date='20260925')
check("no_data=True, error=None, 沒有列", r.get('no_data') is True and r['error'] is None and r['buys'] == [] and r['sells'] == [])
check("休市日只打一次 (金額頁就知道, 不再抓張數頁)", len(H['urls']) == 1, len(H['urls']))

print("\nD. 合併: 兩頁同一天, 身分檢查照舊")
H.update(urls=[], fn=lambda u: page(ID, '20260924', [('6213', 119595, 5181, 114414)] if 'c=B' in u else [('6213', 201, 9, 192)]))
r = cf.fetch_branch_combined('9A9g', date='20260924')
s = r['buys'][0] if r['buys'] else {}
check("金額頁、張數頁都帶 e=f=2026-9-24", all('e=2026-9-24&f=2026-9-24' in x for x in H['urls']) and len(H['urls']) == 2)
check("合併結果: 119595 仟元 / 201 張 / 均價 595.0",
      (s.get('buy_amt'), s.get('buy_lot'), s.get('buy_avg')) == (119595, 201, 595.0), (s.get('buy_amt'), s.get('buy_lot'), s.get('buy_avg')))
check("回傳 date=20260924, no_data 不成立", r['date'] == '20260924' and not r.get('no_data'))
H.update(urls=[], fn=lambda u: page('9A9G', '20260924', [('2330', 1, 1, 0)]))
r = cf.fetch_branch_combined('9A9g', date='20260924')
check("指定日期時頁面是別的分點 → error", r['error'] and 'identity mismatch' in r['error'])

print("\nE. 不給日期 = 每日爬蟲原本行為")
H.update(urls=[], fn=lambda u: page(ID, '20260930', [('3653', 100, 1, 99)]))
r = cf.fetch_branch_mode('9A9g', 'B')
check("網址用 d=1、沒有 e/f", H['urls'][0].endswith('&d=1') and '&e=' not in H['urls'][0])
check("回傳頁面上的日期, 不做日期比對", r['error'] is None and r['date'] == '20260930')

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
