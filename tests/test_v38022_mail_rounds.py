# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, json, os, importlib.util
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.22 每晚寄信輪次 (使用者 2026-10-07 選 1) — 離線

2026-10-06 一晚 5 封同樣標題的信: 21:47 那封 465 列 (跑的是焦家上線前的程式),
22:37 起 495 列, 清晨 3 封內容與 22:37 相同; 信上看不出哪封是最終版.
  A. 21:17 / 22:37 (workflow_dispatch) 一定寄; 標題 + 第一行 = 第 N 輪 + 比上一輪多/少幾列
  B. 清晨 schedule 補跑: 日表內容和上一輪相同就不寄, 不同才寄
  C. 換交易日從第 1 輪重算; TEST run 一律寄且不寫狀態檔
  D. 出錯一律照寄 (寧可多一封, 不可少一封)
  E. daily-full.yml 接線
"""
import openpyxl
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mail_round', ROOT / 'scripts' / 'mail_round.py')
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)
TW = timezone(timedelta(hours=8))
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def rows_for(branches):
    """branches: [(master, branch, bno, n_rows, base)] -> parse_day_sheet-like rows."""
    out = []
    for master, branch, bno, n, base in branches:
        for i in range(n):
            out.append({'master': master, 'branch': branch, 'bno': bno, 'stock': f'S{i}({1000 + i})',
                        'buy_lot': base + i, 'sell_lot': 0, 'buy_wan': base * 10 + i, 'sell_wan': 0})
    return out


OLD = [(f'M{k}', f'分點{k}', f'B{k:02d}', 10, k) for k in range(46)] + [('強森', '元大-館前', '984K', 5, 99)]
JIAO = [('焦家', '元大-館前', '984K', 10, 7), ('焦家', '元大-內湖', '989N', 10, 8),
        ('焦家', '統一-內湖', '585b', 10, 9)]
r1, r2 = rows_for(OLD), rows_for(OLD + JIAO)


def at(h, m, day=6):
    return datetime(2026, 10, day, h, m, tzinfo=TW)


def step(state, rows, event, now, trade='20261006', test=False):
    c, h, b = mr.summarize(rows)
    return mr.decide(state, trade, c, h, b, event, test, now)


print("=" * 72)
print("  v3.80.22 每晚寄信輪次 (離線)")
print("=" * 72)
print("\nA. 準點兩輪一定寄, 標輪次與差異")
s, o = step({}, r1, 'workflow_dispatch', at(21, 47))
check("第 1 輪寄信, 第一行 = 第 1 輪 (21:47): 465 列", o['send'] and o['line'] == '🔁 第 1 輪（21:47）：465 列', o)
check("標題尾 = · 第1輪", o['tag'] == ' · 第1輪', o['tag'])
s, o = step(s, r2, 'workflow_dispatch', at(23, 5))
check("第 2 輪寄信, 比上一輪多 30 列, 列出 3 個變動分點",
      o['send'] and o['line'] == '🔁 第 2 輪（23:05）：495 列，比上一輪多 30 列（變動：元大-館前、元大-內湖、統一-內湖）',
      o['line'])
check("標題尾 = · 第2輪 +30列", o['tag'] == ' · 第2輪 +30列', o['tag'])

print("\nB. 清晨 schedule 補跑")
s, o = step(s, r2, 'schedule', at(3, 20, 7))
check("內容相同 → 不寄, 但記成第 3 輪", o['send'] is False and o['round'] == 3 and len(s['rounds']) == 3, o)
r3 = [dict(x) for x in r2]
r3[0]['buy_lot'] += 1
s, o = step(s, r3, 'schedule', at(4, 8, 7))
check("列數相同但數字變了 → 寄, 說明列數相同但內容有變動",
      o['send'] and '列數相同但內容有變動（變動：分點0）' in o['line'] and o['tag'] == ' · 第4輪 內容有變', o)
s, o = step(s, r3[:-5], 'schedule', at(4, 57, 7))
check("少列 → 寄, 比上一輪少 5 列", o['send'] and '比上一輪少 5 列' in o['line'] and o['tag'] == ' · 第5輪 -5列', o)
s2, o = step(s, r3[:-5], 'workflow_dispatch', at(22, 0, 7))
check("準點輪即使內容相同也寄, 寫「與上一輪相同」",
      o['send'] and o['line'].endswith('：490 列，與上一輪相同') and o['tag'] == ' · 第6輪 無變化', o)
check("狀態檔 rounds 記 mailed", [r['mailed'] for r in s2['rounds']] == [True, True, False, True, True, True],
      [r['mailed'] for r in s2['rounds']])
many = rows_for([(f'X{k}', f'新{k}', f'N{k}', 1, 1) for k in range(5)])
_, o = step(s2, r3[:-5] + many, 'schedule', at(5, 30, 7))
check("超過 3 個分點變動 → 只列 3 個 + 等 N 個分點", '等 5 個分點' in o['line'], o['line'])

print("\nC. 換交易日 / TEST")
s, o = step(s2, r1, 'workflow_dispatch', at(21, 47, 7), trade='20261007')
check("新交易日重新從第 1 輪算, 沒有「比上一輪」", o['round'] == 1 and o['tag'] == ' · 第1輪'
      and '上一輪' not in o['line'] and s['trade_date'] == '20261007' and len(s['rounds']) == 1, o)
_, o = step(s2, r3[:-5], 'schedule', at(5, 0, 7), test=True)
check("TEST run 內容相同也寄", o['send'] is True, o)


print("\nD. CLI: 真的讀 Excel, 寫 GITHUB_OUTPUT; 出錯照寄")
tmp = pathlib.Path(tempfile.mkdtemp())
xlsx = tmp / 'latest.xlsx'
wb = openpyxl.Workbook()
ws = wb.active
ws.title = '20261006'
ws.append(['高手', '分點', '代號', '標的', '買進(張)', '賣出(張)', '買進(萬元)', '賣出(萬元)'])
ws.append(['民哥', '台新-五權西', '9B25', '南亞(1303)', 536, 482, 15401, 13316])
ws.append([None, None, None, '聯發科(2454)', 28, 2, 14062, 1008])
ws.append(['焦家', '統一-內湖', '585b', '華新科(2492)', 35, 0, 400, 0])
wb.create_sheet('20261005')
wb.save(xlsx)
state = tmp / 'mail_rounds.json'
gh = tmp / 'gh_out.txt'
os.environ['GITHUB_OUTPUT'] = str(gh)
try:
    mr.main(['--event', 'workflow_dispatch', '--xlsx', str(xlsx), '--state', str(state)])
    out1 = gh.read_text(encoding='utf-8')
    st = json.loads(state.read_text(encoding='utf-8'))
    check("取最新日表 20261006, 3 列 (與來源比對同一套解析)", st['trade_date'] == '20261006'
          and st['rounds'][0]['rows'] == 3, st.get('rounds'))
    check("GITHUB_OUTPUT 有 send / round / line / tag", 'send=true\n' in out1 and 'round=1\n' in out1
          and 'line=🔁 第 1 輪' in out1 and 'tag= · 第1輪\n' in out1, out1)
    gh.write_text('', encoding='utf-8')
    mr.main(['--event', 'schedule', '--xlsx', str(xlsx), '--state', str(state)])
    check("同一份 Excel 再跑 schedule → send=false", 'send=false\n' in gh.read_text(encoding='utf-8'))
    before = state.read_text(encoding='utf-8')
    gh.write_text('', encoding='utf-8')
    mr.main(['--event', 'push', '--test', '--xlsx', str(xlsx), '--state', str(state)])
    check("--test 不寫狀態檔", state.read_text(encoding='utf-8') == before)
    gh.write_text('', encoding='utf-8')
    rc = mr.main(['--event', 'schedule', '--xlsx', str(tmp / 'missing.xlsx'), '--state', str(state)])
    out = gh.read_text(encoding='utf-8')
    check("讀不到 Excel → exit 0, send=true, 第一行寫輪次判斷失敗",
          rc == 0 and 'send=true\n' in out and '輪次判斷失敗' in out and 'tag=\n' in out, out)
finally:
    os.environ.pop('GITHUB_OUTPUT', None)

print("\nE. daily-full.yml 接線")
wf = (ROOT / '.github' / 'workflows' / 'daily-full.yml').read_text(encoding='utf-8')
i_round, i_commit = wf.find('- name: Mail round'), wf.find('- name: Commit and push data')
check("Mail round 步驟在 commit 之前 (狀態檔跟資料一起 commit)", 0 < i_round < i_commit)
check("Mail round 傳 event 與 TEST 旗標", 'mail_round.py --event "${{ github.event_name }}"' in wf
      and "'--test'" in wf)
check("production send_mail 由 mail_round 決定, 失敗時預設寄", 'SEND="${{ steps.round.outputs.send }}"' in wf
      and 'send_mail=${SEND:-true}' in wf)
check("第一行 = 輪次, 標題尾 = tag", 'ROUND_LINE="${{ steps.round.outputs.line }}"' in wf
      and '摘要${{ steps.round.outputs.tag }}"' in wf)
check("舊註解「git diff --quiet 自動 no-op,零成本」已移除", 'no-op,零成本' not in wf)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
