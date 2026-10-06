"""v3.67.2 Phase 2.7: 萃取手機摘要為純文字 → stdout

用途: GitHub Actions daily-full 跑完後, 取手機摘要純文字作為 email body.
      v3.80.13 起讀 data/reports/mobile_summary.txt; 沒有時退回讀 latest.xlsx 的
      「📱 手機摘要」sheet (舊月檔).

執行: python scripts/extract_mobile_summary_text.py [path/to/latest.xlsx]
      預設 path = data/reports/latest.xlsx
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

xlsx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data' / 'reports' / 'latest.xlsx'

# v3.80.13: 手機摘要不再是 Excel 頁籤; 產表時同步寫出 reports/mobile_summary.txt
# (excel_report.mobile_summary_text, 與下方舊邏輯相同). 有它就直接用.
txt_path = xlsx_path.parent / 'mobile_summary.txt'
if len(sys.argv) <= 1 and txt_path.exists():
    text = txt_path.read_text(encoding='utf-8').strip()
    if text:
        print(text)
        sys.exit(0)

# fallback: v3.80.12 以前的月檔仍有「📱 手機摘要」sheet
try:
    from openpyxl import load_workbook
    wb = load_workbook(str(xlsx_path), data_only=True)
except Exception as e:
    print(f"(無法讀取 latest.xlsx: {e})", file=sys.stderr)
    sys.exit(1)

MOBILE_SHEET = "📱 手機摘要"
if MOBILE_SHEET not in wb.sheetnames:
    print(f"(找不到 {MOBILE_SHEET} sheet, 可用: {wb.sheetnames[:5]})", file=sys.stderr)
    sys.exit(1)

ws = wb[MOBILE_SHEET]

# 內容都在 C 欄, row 2 起算
lines = []
for r in range(1, ws.max_row + 1):
    v = ws[f'C{r}'].value
    if v is None:
        lines.append('')   # 保留空行 (作為 section 分隔)
    else:
        lines.append(str(v))

# 去除頭尾空行, 中間連續多個空行壓成 1 個
while lines and lines[0] == '':
    lines.pop(0)
while lines and lines[-1] == '':
    lines.pop()

# 連續空行壓縮
out_lines = []
prev_blank = False
for ln in lines:
    if ln == '':
        if not prev_blank:
            out_lines.append('')
        prev_blank = True
    else:
        out_lines.append(ln)
        prev_blank = False

print('\n'.join(out_lines))
