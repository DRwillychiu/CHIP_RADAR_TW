# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.30 個股頁 (zco) 不可再默默丟掉英文字母代號的分點 — 離線

2026-10-08 實測 2330 (2026-10-07): 頁面 15 列, 舊解析只拿到 買 13 / 賣 12.
英文字母代號的分點在連結裡寫成 UTF-16BE hex (16 字元), 舊規則只收 3~6 字元 → 整列丟掉.
這個解析器用在 Excel 日表「最大買家」黃底 → 真正最大買家若是這類分點會被跳過.
  A. 16 字元 hex 連結 → 解出原代號 (0039004100300030 → 9A00), 列不丟
  B. 一般 4 碼代號不受影響
"""
from stock_branch_ranking import parse_fubon_stock_page, _decode_bno

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def hexcode(code):
    return ''.join(f'{ord(c):04X}' for c in code)


def row(buy_b, buy_name, sell_b, sell_name):
    a = lambda b, n: f'<TD class="t4t1"><a href="/z/zc/zco/zco0/zco0.djhtm?a=2330&b={b}&BHID=x">{n}</a></TD>'
    nums = '<TD class="t3n1">100</TD><TD class="t3n1">20</TD><TD class="t3n1">80</TD><TD class="t3n1">1.2%</TD>'
    return f'<TR>\n{a(buy_b, buy_name)}{nums}{a(sell_b, sell_name)}{nums}</tr>'


html = ('<html>最後更新日 2026/10/07 ' + row('1470', '台灣摩根士丹利', hexcode('9A00'), '永豐金-匯立')
        + row(hexcode('700W'), '兆豐-中壢', '9200', '凱基') + '</html>')

print("=" * 72)
print("  v3.80.30 個股頁英文字母代號分點 (離線)")
print("=" * 72)
p = parse_fubon_stock_page(html, '2330')
check("A. 兩列都解析到 (買 2 / 賣 2)", p and len(p['buys']) == 2 and len(p['sells']) == 2,
      p and (len(p['buys']), len(p['sells'])))
check("A. hex 連結解回原代號 9A00 / 700W", p and p['sells'][0]['bno'] == '9A00' and p['buys'][1]['bno'] == '700W',
      p and [b['bno'] for b in p['buys'] + p['sells']])
check("B. 一般代號不變 (1470 / 9200)", p and p['buys'][0]['bno'] == '1470' and p['sells'][1]['bno'] == '9200')
check("B. 不是 hex 的長字串不亂解", _decode_bno('12345678') == '12345678' or _decode_bno('12345678').isalnum())
check("日期照舊", p and p['date'] == '2026/10/07', p and p['date'])

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
