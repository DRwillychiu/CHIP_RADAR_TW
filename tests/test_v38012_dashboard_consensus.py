# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.10 / v3.80.12 📋 今日 Dashboard = 今日強共識買超清單 (離線, 合成資料)

使用者 2026-10-05:
  - 只呈現「≥10 位追蹤大戶共同淨買」清單, 欄位 個股 / 代號 / 領頭大戶 / 領頭金額(萬)
  - 凱基-城中 (9227) 也是優式資本 (UC) 的分點 → 蔣承翰顯示「蔣承翰(UC)」
"""
import openpyxl
import excel_report as er

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def br(code, master, buys):
    return {'code': code, 'name': code, 'master': master, 'buys': buys, 'sells': []}


def s(code, name, net_k):           # net in 仟元
    return {'code': code, 'name': name, 'buy_amt': net_k + 100, 'sell_amt': 100}


masters = [m['name'] for m in er.MASTER_MAPPING]
others = [m for m in masters if m != '蔣承翰'][:10]
data = [br('9227', '蔣承翰', [s('2492', '華新科', 104310), s('1111', '九檔股', 50)])]
for i, m in enumerate(others):
    data.append(br(f'B{i:03d}', m, [s('2492', '華新科', 1000 + i),
                                    s('00961', 'FT臺灣永續高息', 900),           # ETF: 排除
                                    s('1111', '九檔股', 50)] if i < 8 else      # 只有 9 位 → 不入榜
                                   [s('2492', '華新科', 1000 + i), s('00961', 'FT臺灣永續高息', 900)]))


def build(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    er.build_dashboard_sheet(ws, rows, '20261005', data_dir=pathlib.Path(tempfile.mkdtemp()),
                             update_timeseries=False)
    return ws


print("=" * 72)
print("  v3.80.12 Dashboard 強共識清單 (離線)")
print("=" * 72)
ws = build(data)
hdr = [ws.cell(5, c).value for c in range(2, 6)]
body = [[ws.cell(r, c).value for c in range(2, 6)] for r in range(6, ws.max_row + 1) if ws.cell(r, 3).value]
print("\nA. 版面")
check("表頭 個股 / 代號 / 領頭大戶 / 領頭金額(萬)", hdr == ['個股', '代號', '領頭大戶', '領頭金額(萬)'], hdr)
check("標題含日期", '2026/10/05' in str(ws['B2'].value), ws['B2'].value)
print("\nB. 名單規則")
check("11 位大戶共買的 2492 入榜", [r[1] for r in body] == ['2492'], body)
check("只有 9 位大戶的 1111 不入榜; 00 開頭 ETF 不入榜", all(r[1] not in ('1111', '00961') for r in body))
print("\nC. 領頭大戶與金額")
row = body[0] if body else [None] * 4
check("領頭大戶顯示「蔣承翰(UC)」(凱基-城中也是優式資本分點)", row[2] == '蔣承翰(UC)', row)
check("領頭金額 = 104,310 仟元 → 10,431 萬", row[3] == 10431, row)
check("UC 名單由 branches.py 分點名稱推得 = {蔣承翰}", er.UC_SHARED_MASTERS == {'蔣承翰'}, er.UC_SHARED_MASTERS)
data2 = [b for b in data if b['master'] != '蔣承翰'] + [br('9227', '蔣承翰', [s('2492', '華新科', 10)])]
row2 = [ws2_row for ws2_row in [[build(data2).cell(6, c).value for c in range(2, 6)]]][0]
check("領頭不是蔣承翰時照常顯示原名 (無 UC)", row2[2] in others and '(UC)' not in str(row2[2]), row2)
print("\nD. 空的一天")
ws3 = build([])
check("顯示「(今日無強共識股)」", ws3.cell(6, 2).value == '(今日無強共識股)', ws3.cell(6, 2).value)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
