# v3.85.8 Fubon pages decoded as cp950, not big5 (立碁 8111) - offline
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-09: "8111 名稱是立碁". Python's big5 codec has no cp950
extension row F9D6-F9FE, so 碁 / 恒 became U+FFFD and shifted the next bytes."""
from src.core.fubon_codec import decode_fubon, FUBON_ENCODING

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True
BAD = '�'


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.85.8 富邦網頁 cp950 解碼 (離線)")
print("=" * 72)

# A. names seen broken on 2026-10-08, as the page bytes would carry them
NAMES = ['立碁', '宏碁', '安碁', '啟碁', '富邦恒生國企正2', '統一恒生正2']
print("\n[A] 實際壞掉的名稱")
check("FUBON_ENCODING 是 cp950", FUBON_ENCODING == 'cp950', FUBON_ENCODING)
for n in NAMES:
    page = f'<td>{n}</td><td>1,234</td>'.encode('cp950')
    got = decode_fubon(page)
    old = page.decode('big5', errors='replace')
    check(f"{n}: cp950 解回原名, big5 會壞", n in got and BAD not in got and n not in old, ascii(old[4:16]))

# B. no Fubon path decodes on its own any more
print("\n[B] 每條富邦路徑都走 decode_fubon")
BAN = re.compile(r"""decode\(\s*['"]big5['"]|\.apparent_encoding""")
offenders = []
fubon_files = []
for p in [ROOT / 'crawler.py', *ROOT.glob('src/**/*.py'), *ROOT.glob('scripts/**/*.py')]:
    if '.bak_' in p.name:
        continue
    s = p.read_text(encoding='utf-8', errors='replace')
    if BAN.search(s):
        offenders.append(str(p.relative_to(ROOT)))
    if 'fbs.com.tw' in s and re.search(r"""\.decode\(|\.text\b""", s):
        fubon_files.append(p)
check("沒有任何程式自己用 big5 或 apparent_encoding 解碼", not offenders, offenders)
missing = [str(p.relative_to(ROOT)) for p in fubon_files
           if 'decode_fubon' not in p.read_text(encoding='utf-8', errors='replace')
           and p.name != 'fubon_codec.py']
for must in ['src/pipelines/crawler_fetch.py', 'src/fetchers/stock_branch_ranking.py', 'src/audit/source_audit.py']:
    check(f"{must} 用 decode_fubon", 'decode_fubon(' in (ROOT / must).read_text(encoding='utf-8'))
check("其他抓富邦又解碼的檔案也都用 decode_fubon", not missing, missing)

# C. the per-stock page parser keeps the cp950 name end to end
print("\n[C] zco 解析器拿到正確名稱")
from src.fetchers.stock_branch_ranking import parse_fubon_stock_page
row = ('<TR><TD class="t4t1"><a href="x?a=8111&b=9A00&">恒碁-測試</a></TD>'
       '<TD>10</TD><TD>2</TD><TD>8</TD><TD>1.0%</TD>'
       '<TD class="t4t1"><a href="x?a=8111&b=9A01&">立碁-測試</a></TD>'
       '<TD>1</TD><TD>9</TD><TD>8</TD><TD>1.0%</TD></tr>')
parsed = parse_fubon_stock_page(decode_fubon(('2026/10/08' + row).encode('cp950')), '8111')
names = [r['name'] for r in (parsed or {}).get('buys', []) + (parsed or {}).get('sells', [])]
check("買賣兩側名稱都完整", names == ['恒碁-測試', '立碁-測試'], names)

# D. names already stored broken get repaired (stock_name only, never branch names)
print("\n[D] 已存的亂碼股名修正")
from src.core.fubon_codec import repair_stock_names, is_broken
NAMES_OK = {'8111': '立碁', '2353': '宏碁', '1440': '南紡'}
pos = {'branches': {'1440': {'branch_name': '美' + BAD * 2, 'master': '美林',
                             'stocks': {'8111': {'stock_name': '立' + BAD * 2},
                                        '2353': {'stock_name': '宏碁'},
                                        '00665L': {'stock_name': '富邦' + BAD + '琪肭碪囓' + BAD + '2'}}}}}
n = repair_stock_names(pos, NAMES_OK)
st = pos['branches']['1440']['stocks']
check("持倉: 用上層代號修好 8111", st['8111']['stock_name'] == '立碁' and n == 1, (n, st['8111']))
check("分點名稱不碰 (1440 美林 ≠ 1440 南紡)", pos['branches']['1440']['branch_name'] == '美' + BAD * 2)
check("沒有乾淨名稱的 (00665L) 先留著, 不亂填", is_broken(st['00665L']['stock_name']))
mp = {'masters': [{'holdings': [{'stock_code': '8111', 'stock_name': '立' + BAD * 2}],
                   'trades': [{'branch_code': '1440', 'stock_code': '2353', 'stock_name': '宏' + BAD * 2}]}]}
n = repair_stock_names(mp, NAMES_OK)
check("大戶畫像: 用 stock_code 修好持股與交易", n == 2 and mp['masters'][0]['holdings'][0]['stock_name'] == '立碁'
      and mp['masters'][0]['trades'][0]['stock_name'] == '宏碁', n)
check("壞的備用名稱不會蓋上去", repair_stock_names({'8111': {'stock_name': '立' + BAD}}, {'8111': '立' + BAD * 2}) == 0)

# E. stock_history: broken name replaced, by tonight's rows or by the official list
print("\n[E] stock_history 亂碼名稱會被換掉")
import json, tempfile
from unittest.mock import patch
import src.fetchers.history as hist
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    old = {'stocks': {'8111': {'name': '立' + BAD * 2, 'industry': '26', 'daily': {}},
                      '2353': {'name': '宏' + BAD * 2, 'industry': '28', 'daily': {}},
                      '00665L': {'name': '富邦' + BAD, 'industry': '', 'daily': {}}},
           'updated_at': None, 'max_days': 60, 'dates': [], 'industry_avg': {}, 'market': {}, 'futures': {}}
    (tdp / hist.HISTORY_FILE).write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    rows = [{'buys': [{'code': '2353', 'name': '宏碁'}], 'sells': []}]
    with patch.object(hist, '_fetch_taiex_fmtqik', return_value=None), \
         patch.object(hist, '_fetch_taiex_index', return_value=None):
        hist.update_history(tdp, '20261012', {'2353': {'close': 30.0, 'change_pct': 1.0}}, {},
                            branches_results=rows, official_names={'8111': '立碁'})
    new = json.loads((tdp / hist.HISTORY_FILE).read_text(encoding='utf-8'))['stocks']
    check("今晚有交易: 用今晚乾淨名稱換掉 (2353 宏碁)", new['2353']['name'] == '宏碁', new['2353']['name'])
    check("今晚沒交易: 用官方名稱換掉 (8111 立碁)", new['8111']['name'] == '立碁', new['8111']['name'])
    check("兩邊都沒有乾淨名稱: 原樣保留", new['00665L']['name'] == '富邦' + BAD, ascii(new['00665L']['name']))

# F. the crawler wires the repair in at every durable write
print("\n[F] crawler 三個寫入點都會修名")
cs = (ROOT / 'crawler.py').read_text(encoding='utf-8')
check("master_profiles 寫檔前修名",
      re.search(r"repair_stock_names\(mp_result, _repair_names_map\(data_dir\)\)", cs) is not None)
check("positions 存檔前修名",
      re.search(r"repair_stock_names\(positions, _repair_names_map\(data_dir, results\)\)(?:.*\n){1,8}\s*save_positions\(", cs) is not None)
check("stock_history 拿到官方名稱表", "official_names=_repair_names_map(data_dir, results)" in cs)
import crawler
with tempfile.TemporaryDirectory() as td:
    got = crawler._repair_names_map(td, [{'buys': [{'code': '8111', 'name': '立碁'}, {'code': '2353', 'name': '宏' + BAD}]}])
    check("修正表: 今晚乾淨名稱收, 亂碼不收", got == {'8111': '立碁'}, got)
    check("修正表壞資料不會讓抓取中斷 (回傳空表)", crawler._repair_names_map(td, [None]) == {})

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
