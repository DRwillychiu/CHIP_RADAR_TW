# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, tempfile, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.80.10 / v3.80.13 📋 今日 Dashboard + 頁籤 (離線, 合成資料)

使用者決定:
  2026-10-05  Dashboard 只呈現「≥10 位追蹤大戶共同淨買」清單
  2026-10-06  領頭欄 = 追蹤分點中「單一分點」單日淨買最多者 (不是大戶加總)
              頁籤只留 Dashboard / Pinned / 日期; 手機摘要改存純文字給 Email
"""
import openpyxl
import excel_report as er

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def br(code, master, buys, name=None):
    return {'code': code, 'name': name or code, 'master': master, 'buys': buys, 'sells': []}


def s(code, name, net_k):           # net in 仟元
    return {'code': code, 'name': name, 'buy_amt': net_k + 100, 'sell_amt': 100}


masters = [m['name'] for m in er.MASTER_MAPPING]
others = [m for m in masters if m not in ('蔣承翰', '全村希望資本_村長')][:9]
# 2492: 村長兩個分點各 6,000 萬 (大戶加總 12,000) vs 凱基-城中(UC) 單一分點 10,431 萬
data = [br('9227', '蔣承翰', [s('2492', '華新科', 104310)], '凱基-城中(UC)'),
        br('8562', '全村希望資本_村長', [s('2492', '華新科', 60000)], '新光-高雄'),
        br('8847', '全村希望資本_村長', [s('2492', '華新科', 60000)], '玉山-台南')]
for i, m in enumerate(others):
    data.append(br(f'B{i:03d}', m, [s('2492', '華新科', 1000 + i), s('00961', 'FT臺灣永續高息', 900)]
                   + ([s('1111', '九檔股', 50)] if i < 8 else [])))


def build(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    er.build_dashboard_sheet(ws, rows, '20261005', data_dir=pathlib.Path(tempfile.mkdtemp()),
                             update_timeseries=False)
    return ws


print("=" * 72)
print("  v3.80.13 Dashboard 強共識清單 + 頁籤 (離線)")
print("=" * 72)
def header_row(ws):
    # v3.80.16 report layout: '#' column first, header row located by its labels
    return next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 3).value == '個股')


ws = build(data)
H = header_row(ws)
hdr = [ws.cell(H, c).value for c in range(2, 7)]
body = [[ws.cell(r, c).value for c in range(3, 7)] for r in range(H + 1, ws.max_row + 1)
        if isinstance(ws.cell(r, 2).value, int)]
print("\nA. 版面")
check("表頭 # / 個股 / 代號 / 領頭分點 / 領頭金額(萬)", hdr == ['#', '個股', '代號', '領頭分點', '領頭金額(萬)'], hdr)
check("標題「今日強共識買超」, 日期在右側", ws['B2'].value == '今日強共識買超'
      and str(ws['E2'].value).startswith('2026/10/05'), (ws['B2'].value, ws['E2'].value))
check("KPI 卡: 入選 1 檔", ws['B6'].value == '1 檔', ws['B6'].value)
check("不顯示格線, 表頭以下凍結", ws.sheet_view.showGridLines is False and ws.freeze_panes == f'A{H + 1}',
      (ws.sheet_view.showGridLines, ws.freeze_panes))
print("\nB. 名單規則")
check("11 位大戶共買的 2492 入榜", [r[1] for r in body] == ['2492'], body)
check("只有 9 位大戶的 1111 不入榜; 00 開頭 ETF 不入榜", all(r[1] not in ('1111', '00961') for r in body))
print("\nC. 領頭分點 = 單一分點淨買最多 (不是大戶加總)")
row = body[0] if body else [None] * 4
check("村長兩分點加總 12,000 萬 > 凱基-城中(UC) 10,431 萬, 但領頭是單一分點最多的 凱基-城中(UC)",
      row[2] == '凱基-城中(UC)', row)
check("領頭金額 = 該分點自己的淨買 104,310 仟元 → 10,431 萬", row[3] == 10431, row)
check("(UC) 由分點名稱本身帶出", '(UC)' in str(row[2]))
print("\nD. 空的一天")
ws3 = build([])
H3 = header_row(ws3)
check("顯示「(今日無強共識股)」", ws3.cell(H3 + 1, 2).value == '(今日無強共識股)', ws3.cell(H3 + 1, 2).value)

print("\nE. 頁籤: 只留 Dashboard / Pinned / 日期; 手機摘要 → reports/mobile_summary.txt")
tmp = pathlib.Path(tempfile.mkdtemp()) / 'reports'
tmp.mkdir()
monthly = tmp / 'chip_radar_2026-10.xlsx'
wb0 = openpyxl.Workbook()
wb0.active.title = '20261002'
for n in (er.MOBILE_SHEET_NAME, er.QUAD_TRACK_SHEET_NAME, er.QUAD_FAIL_SHEET_NAME):
    wb0.create_sheet(n)                                   # 舊月檔殘留
wb0.save(monthly)
(tmp / er.MOBILE_SUMMARY_TXT).write_text('昨天的內容\n', encoding='utf-8')
orig = (er.build_day_sheet, er.build_dashboard_sheet, er.build_pinned_track_sheet, er.build_mobile_summary_sheet)
def fake_mobile(ws, *a, **k):
    for r, v in enumerate(['📋 Chip Radar · 2026/10/05', None, None, '🎯 強共識買超 Top 5', '⭐ 華新科 (2492)'], 1):
        ws.cell(r, 3, v)
er.build_day_sheet = lambda ws, *a, **k: 0
er.build_dashboard_sheet = lambda ws, *a, **k: None
er.build_pinned_track_sheet = lambda ws, *a, **k: None
er.build_mobile_summary_sheet = fake_mobile
try:
    er._update_monthly_workbook(monthly, [], '20261005')
finally:
    er.build_day_sheet, er.build_dashboard_sheet, er.build_pinned_track_sheet, er.build_mobile_summary_sheet = orig
names = openpyxl.load_workbook(monthly).sheetnames
check("頁籤順序 = Dashboard → Pinned → 20261005 → 20261002",
      names == [er.DASHBOARD_SHEET_NAME, er.PINNED_TRACK_SHEET_NAME, '20261005', '20261002'], names)
check("舊月檔的 手機摘要 / Quad 實戰追蹤 / Quad 失效歸因 被移除",
      not ({er.MOBILE_SHEET_NAME, er.QUAD_TRACK_SHEET_NAME, er.QUAD_FAIL_SHEET_NAME} & set(names)))
txt = (tmp / er.MOBILE_SUMMARY_TXT).read_text(encoding='utf-8')
check("mobile_summary.txt 是今天的內容 (空行壓縮規則同舊 Email)",
      txt == '📋 Chip Radar · 2026/10/05\n\n🎯 強共識買超 Top 5\n⭐ 華新科 (2492)\n', repr(txt))
out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'extract_mobile_summary_text.py')],
                     capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT))
check("Email 擷取 script 可執行 (讀 data/reports/mobile_summary.txt, 或退回舊頁籤)",
      out.returncode in (0, 1), out.returncode)

print("\nF. v3.80.16 Pinned 頁: 只留今日 Top 10 買進; 買張 = buy_lot 合計")
pm = sorted(er.PINNED_MASTERS)[0]
pin_data = [br('8563', pm, [{'code': '2327', 'name': '國巨*', 'buy_amt': 102425, 'buy_lot': 159,
                             'change_pct': 0.0},
                            {'code': '2454', 'name': '聯發科', 'buy_amt': 94562, 'buy_lot': 18,
                             'change_pct': 4.34},
                            {'code': '00918', 'name': 'ETF', 'buy_amt': 999999, 'buy_lot': 9}]),
            br('9999', pm, [{'code': '2327', 'name': '國巨*', 'buy_amt': 1000, 'buy_lot': 2,
                             'change_pct': 0.0}])]
wbp = openpyxl.Workbook()
wp = wbp.active
er.build_pinned_track_sheet(wp, pin_data, pathlib.Path(tempfile.mkdtemp()), trade_date='20261005')
blob = ' '.join(str(c.value) for r in wp.iter_rows() for c in r if c.value is not None)
HP = next(r for r in range(1, wp.max_row + 1) if wp.cell(r, 3).value == '代號')
prow = [[wp.cell(r, c).value for c in range(2, 8)] for r in range(HP + 1, wp.max_row + 1)
        if isinstance(wp.cell(r, 2).value, int)]
check("標題 = 大戶名 + 今日 Top 10 買進", wp['B2'].value == f"{pm}　今日 Top 10 買進", wp['B2'].value)
check("不再有 連續囤貨 / alpha 統計 / 敘述", '連續囤貨' not in blob and 'hit_1d' not in blob, blob[:120])
# 102,425 + 1,000 仟元 = 10,342.5 萬 -> round() (half to even, same as the day sheet) = 10,342
check("跨分點同股合計: 國巨 買金額 10,342 萬, 買張 159+2 = 161", prow and prow[0][1:5] == ['2327', '國巨*', 10342, 161],
      prow[:1])
check("ETF (00 開頭) 不列入", all(r[1] != '00918' for r in prow), prow)
check("漲跌% 以小數存 (4.34% → 0.0434)", len(prow) > 1 and abs(prow[1][5] - 0.0434) < 1e-9, prow[1:2])

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
