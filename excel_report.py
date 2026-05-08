"""
excel_report.py - v3.23 Excel daily report generator (template-aligned)

Template format (matching user's manual report):
  - Single sheet per day (sheet name = YYYYMMDD)
  - Vertical layout: each branch = 1 header row + 10 data rows
  - 12 columns: A-L
  - Master grouping with merged cells in column A
  - Branch name/code merged vertically in columns B/C
  - Blue header rows per branch section
  - Loss column with formula, negative in red

Output:
  data/reports/chip_radar_YYYY-MM-DD.xlsx
  data/reports/latest.xlsx (always latest, for bookmarking)
  data/reports/README.md (history index)
"""

import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ============================================================
#  Style constants (matching template)
# ============================================================

# Header row: blue background, white bold text
FILL_HEADER = lambda: PatternFill('solid', start_color='4472C4')
FONT_HEADER = lambda: Font(name='Microsoft JhengHei', size=10, bold=True, color='FFFFFF')
FONT_HEADER_LABEL = lambda: Font(name='Microsoft JhengHei', size=10, bold=True)

# Master/branch label font
FONT_MASTER = lambda: Font(name='Microsoft JhengHei', size=11, bold=True)
FONT_BRANCH = lambda: Font(name='Microsoft JhengHei', size=10, bold=True)

# Data font
FONT_DATA = lambda: Font(name='Microsoft JhengHei', size=10)

# Loss column: negative values get red font + pink background
FILL_LOSS_NEG = lambda: PatternFill('solid', start_color='FFC7CE')
FONT_LOSS_NEG = lambda: Font(name='Microsoft JhengHei', size=10, color='C00000')
FONT_LOSS_POS = lambda: Font(name='Microsoft JhengHei', size=10)

# Alignment
ALIGN_CENTER = lambda: Alignment(horizontal='center', vertical='center')
ALIGN_LEFT = lambda: Alignment(horizontal='left', vertical='center')
ALIGN_RIGHT = lambda: Alignment(horizontal='right', vertical='center')

# Border
BORDER_THIN = lambda: Border(
    left=Side(style='thin', color='B4C6E7'),
    right=Side(style='thin', color='B4C6E7'),
    top=Side(style='thin', color='B4C6E7'),
    bottom=Side(style='thin', color='B4C6E7'),
)

# Column widths (matching template)
COL_WIDTHS = {
    'A': 19.3,   # master
    'B': 18.3,   # branch name
    'C': 11.9,   # branch code
    'D': 20.3,   # stock name(code)
    'E': 13.0,   # buy lots
    'F': 13.0,   # sell lots
    'G': 16.0,   # buy amount
    'H': 16.0,   # sell amount
    'I': 18.0,   # net buy diff
    'J': 13.1,   # buy avg
    'K': 11.4,   # sell avg
    'L': 15.6,   # pnl
}

HEADER_LABELS = [
    'master',       # A - only on first branch of each master group
    'branch',       # B
    'code',         # C
    'target',       # D
    'buy_lot',      # E
    'sell_lot',     # F
    'buy_amt',      # G
    'sell_amt',     # H
    'net_diff',     # I
    'buy_avg',      # J
    'sell_avg',     # K
    'pnl',          # L
]

MAX_STOCKS = 10  # max stocks per branch (cap at 10)


# ============================================================
#  Build single-day sheet (template format)
# ============================================================

def build_day_sheet(ws, branches_data: List[Dict], trade_date: str):
    """
    Build one sheet matching the template layout.

    Layout per branch section (11 rows):
      Row 0: header labels (blue bg)
      Row 1-10: top 10 stocks by buy amount desc

    Column A: master name (merged across all branches of same master)
    Column B: branch name (merged across 10 data rows)
    Column C: branch code (merged across 10 data rows)
    Column D-L: stock data
    """

    # -- Group and sort branches by master --
    valid = [b for b in branches_data if b.get('buys') or b.get('sells')]
    valid.sort(key=lambda b: (b.get('master', ''), b.get('name', '')))

    # Group by master (preserve order)
    master_groups = []
    current_master = None
    current_list = []
    for b in valid:
        m = b.get('master', '')
        if m != current_master:
            if current_list:
                master_groups.append((current_master, current_list))
            current_master = m
            current_list = [b]
        else:
            current_list.append(b)
    if current_list:
        master_groups.append((current_master, current_list))

    # -- Set column widths --
    for col_letter, width in COL_WIDTHS.items():
        ws.column_dimensions[col_letter].width = width

    # -- Write data --
    row = 1  # current row (1-indexed)
    master_merge_ranges = []  # (start_row, end_row, master_name)

    for gi, (master_name, branches) in enumerate(master_groups):
        master_start_row = row + 1  # first data row of this master group

        for bi, branch in enumerate(branches):
            branch_name = branch.get('name', '')
            branch_code = branch.get('code', '')

            # -- Header row --
            is_first_of_master = (bi == 0)

            # A column header label
            ha = ws.cell(row=row, column=1)
            if is_first_of_master:
                ha.value = 'master'
                ha.font = FONT_HEADER_LABEL()
            # leave blank for subsequent branches

            # B-C header labels
            ws.cell(row=row, column=2).value = 'branch'
            ws.cell(row=row, column=3).value = 'code'

            # D-L header labels
            d_headers = [
                'target', 'buy_lot', 'sell_lot',
                'buy_amt_w', 'sell_amt_w', 'net_diff_w',
                'buy_avg', 'sell_avg', 'pnl_w'
            ]
            for ci, label in enumerate(d_headers):
                ws.cell(row=row, column=4 + ci).value = label

            # Apply header style (blue bg, white text) to D-L
            for ci in range(4, 13):  # D=4 to L=12
                c = ws.cell(row=row, column=ci)
                c.fill = FILL_HEADER()
                c.font = FONT_HEADER()
                c.alignment = ALIGN_CENTER()
                c.border = BORDER_THIN()

            # Style for A-C headers (no fill, bold)
            for ci in range(1, 4):
                c = ws.cell(row=row, column=ci)
                c.font = FONT_HEADER_LABEL()
                c.alignment = ALIGN_CENTER()
                c.border = BORDER_THIN()

            row += 1  # move to first data row

            # -- Prepare stock data --
            all_stocks = []
            for item in branch.get('buys', []):
                all_stocks.append(item)
            for item in branch.get('sells', []):
                all_stocks.append(item)

            # Deduplicate by stock code (in case same stock appears in both)
            seen = {}
            for s in all_stocks:
                code = s.get('code', '')
                if code not in seen:
                    seen[code] = s

            # Sort by buy_amt descending (top buyers first)
            sorted_stocks = sorted(
                seen.values(),
                key=lambda x: x.get('buy_amt', 0),
                reverse=True
            )[:MAX_STOCKS]

            num_stocks = len(sorted_stocks)
            if num_stocks == 0:
                num_stocks = 1  # at least 1 row for branch name display

            data_start = row
            data_end = row + num_stocks - 1

            # -- Write data rows (only as many as we have) --
            for ri in range(num_stocks):
                r = row + ri
                if ri < len(sorted_stocks):
                    s = sorted_stocks[ri]
                    s_code = s.get('code', '')
                    s_name = s.get('name', '')
                    buy_lot = s.get('buy_lot', 0)
                    sell_lot = s.get('sell_lot', 0)
                    buy_amt = s.get('buy_amt', 0)  # in 仟元
                    sell_amt = s.get('sell_amt', 0)  # in 仟元

                    # Unit conversion: 仟元 -> 萬元 (divide by 10)
                    buy_amt_w = round(buy_amt / 10, 0) if buy_amt else 0
                    sell_amt_w = round(sell_amt / 10, 0) if sell_amt else 0
                    net_diff_w = buy_amt_w - sell_amt_w

                    # Average price: 金額(仟元) / 張數 = TWD/share
                    buy_avg = round(buy_amt / buy_lot, 2) if buy_lot > 0 and buy_amt > 0 else 0
                    sell_avg = round(sell_amt / sell_lot, 2) if sell_lot > 0 and sell_amt > 0 else 0

                    # D: stock name(code) format
                    ws.cell(row=r, column=4).value = f"{s_name}({s_code})"
                    ws.cell(row=r, column=4).font = FONT_DATA()
                    ws.cell(row=r, column=4).alignment = ALIGN_LEFT()

                    # E: buy lots
                    ws.cell(row=r, column=5).value = buy_lot
                    ws.cell(row=r, column=5).number_format = '#,##0'

                    # F: sell lots
                    ws.cell(row=r, column=6).value = sell_lot
                    ws.cell(row=r, column=6).number_format = '#,##0'

                    # G: buy amount (萬元)
                    ws.cell(row=r, column=7).value = int(buy_amt_w)
                    ws.cell(row=r, column=7).number_format = '#,##0'

                    # H: sell amount (萬元)
                    ws.cell(row=r, column=8).value = int(sell_amt_w)
                    ws.cell(row=r, column=8).number_format = '#,##0'

                    # I: net buy diff (萬元)
                    c_net = ws.cell(row=r, column=9)
                    c_net.value = int(net_diff_w)
                    c_net.number_format = '#,##0;[Red]-#,##0;-'

                    # J: buy avg price
                    ws.cell(row=r, column=10).value = buy_avg
                    ws.cell(row=r, column=10).number_format = '#,##0.00'

                    # K: sell avg price
                    ws.cell(row=r, column=11).value = sell_avg
                    ws.cell(row=r, column=11).number_format = '#,##0.00'

                    # L: P&L formula =F*(K-J)
                    pnl_formula = f'=F{r}*(K{r}-J{r})'
                    c_pnl = ws.cell(row=r, column=12)
                    c_pnl.value = pnl_formula
                    c_pnl.number_format = '0.00_ ;[Red]\\-0.00 '

                    # Compute actual P&L value for conditional formatting
                    pnl_val = sell_lot * (sell_avg - buy_avg)
                    if pnl_val < 0:
                        c_pnl.fill = FILL_LOSS_NEG()
                        c_pnl.font = FONT_LOSS_NEG()
                    else:
                        c_pnl.font = FONT_LOSS_POS()

                # Apply font/border/alignment to data cells E-L
                for ci in range(5, 13):
                    c = ws.cell(row=r, column=ci)
                    if not c.font or c.font == Font():
                        c.font = FONT_DATA()
                    c.alignment = ALIGN_RIGHT()
                    c.border = BORDER_THIN()

                # Border for D too
                ws.cell(row=r, column=4).border = BORDER_THIN()

            # -- Merge branch name (B) and code (C) across data rows --
            if num_stocks > 1:
                ws.merge_cells(
                    start_row=data_start, start_column=2,
                    end_row=data_end, end_column=2
                )
                ws.merge_cells(
                    start_row=data_start, start_column=3,
                    end_row=data_end, end_column=3
                )

            # Write branch name and code in first data row (merged cell)
            c_bn = ws.cell(row=data_start, column=2)
            c_bn.value = branch_name
            c_bn.font = FONT_BRANCH()
            c_bn.alignment = ALIGN_CENTER()
            c_bn.border = BORDER_THIN()

            c_bc = ws.cell(row=data_start, column=3)
            c_bc.value = branch_code
            c_bc.font = FONT_BRANCH()
            c_bc.alignment = ALIGN_CENTER()
            c_bc.border = BORDER_THIN()

            # Border for A column data rows
            for ri in range(num_stocks):
                ws.cell(row=data_start + ri, column=1).border = BORDER_THIN()

            row = data_end + 1  # next branch starts here

        # -- Merge master name (A) across all branches of this master --
        master_end_row = row - 1  # last data row of this master group
        if master_start_row <= master_end_row:
            ws.merge_cells(
                start_row=master_start_row, start_column=1,
                end_row=master_end_row, end_column=1
            )
            c_m = ws.cell(row=master_start_row, column=1)
            c_m.value = master_name
            c_m.font = FONT_MASTER()
            c_m.alignment = ALIGN_CENTER()

    # -- Now replace placeholder header labels with Chinese --
    # Walk through all header rows and set proper labels
    header_labels_zh = {
        'A': {'first': 'master', 'rest': ''},  # handled by master merge
        'B': 'branch',
        'C': 'code',
    }
    d_labels_zh = ['target', 'buy_lot', 'sell_lot',
                   'buy_amt_w', 'sell_amt_w', 'net_diff_w',
                   'buy_avg', 'sell_avg', 'pnl_w']

    # Second pass: replace English placeholder labels with Chinese
    for r in range(1, row + 1):
        d_val = ws.cell(row=r, column=4).value
        if d_val == 'target':
            # This is a header row - replace labels
            a_val = ws.cell(row=r, column=1).value
            if a_val == 'master':
                ws.cell(row=r, column=1).value = 'master'
            ws.cell(row=r, column=2).value = 'branch'
            ws.cell(row=r, column=3).value = 'code'
            ws.cell(row=r, column=4).value = 'target'
            ws.cell(row=r, column=5).value = 'buy_lot'
            ws.cell(row=r, column=6).value = 'sell_lot'
            ws.cell(row=r, column=7).value = 'buy_amt_w'
            ws.cell(row=r, column=8).value = 'sell_amt_w'
            ws.cell(row=r, column=9).value = 'net_diff_w'
            ws.cell(row=r, column=10).value = 'buy_avg'
            ws.cell(row=r, column=11).value = 'sell_avg'
            ws.cell(row=r, column=12).value = 'pnl_w'

    # Final pass: set actual Chinese labels
    for r in range(1, row + 1):
        d_val = ws.cell(row=r, column=4).value
        if d_val == 'target':
            a_cell = ws.cell(row=r, column=1)
            if a_cell.value == 'master':
                a_cell.value = '高手'  # 高手

            ws.cell(row=r, column=2).value = '分點'  # 分點
            ws.cell(row=r, column=3).value = '代號'  # 代號
            ws.cell(row=r, column=4).value = '標的'  # 標的
            ws.cell(row=r, column=5).value = '買進(張)'  # 買進(張)
            ws.cell(row=r, column=6).value = '賣出(張)'  # 賣出(張)
            ws.cell(row=r, column=7).value = '買進(萬元)'  # 買進(萬元)
            ws.cell(row=r, column=8).value = '賣出(萬元)'  # 賣出(萬元)
            ws.cell(row=r, column=9).value = '淨買差(萬元)'  # 淨買差(萬元)
            ws.cell(row=r, column=10).value = '買均'  # 買均
            ws.cell(row=r, column=11).value = '賣均'  # 賣均
            ws.cell(row=r, column=12).value = '損益(萬)'  # 損益(萬)

    return row  # total rows written


# ============================================================
#  Main entry point
# ============================================================

def generate_excel_report(branches_data: List[Dict], trade_date: str,
                          output_dir: str = "data/reports") -> Optional[str]:
    """
    Generate Excel daily report.

    Args:
        branches_data: list of branch dicts (with buys/sells)
        trade_date: trading day (YYYYMMDD, e.g. '20260507')
        output_dir: output directory (default data/reports)

    Returns:
        file path on success, None on failure
    """
    if not OPENPYXL_AVAILABLE:
        print("  [Excel] openpyxl not installed, skipping")
        return None

    if not branches_data:
        print("  [Excel] no branch data, skipping")
        return None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # File name: chip_radar_YYYY-MM-DD.xlsx
    if len(trade_date) == 8 and trade_date.isdigit():
        readable_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    else:
        readable_date = trade_date

    file_path = out_dir / f"chip_radar_{readable_date}.xlsx"
    latest_path = out_dir / "latest.xlsx"

    is_overwrite = file_path.exists()
    if is_overwrite:
        print(f"  [Excel] existing file detected, will overwrite")

    valid_count = len([b for b in branches_data if b.get('buys') or b.get('sells')])
    print(f"  [Excel] generating... ({valid_count} branches, date {readable_date})")

    wb = Workbook()
    ws = wb.active
    ws.title = trade_date  # sheet name = YYYYMMDD

    try:
        total_rows = build_day_sheet(ws, branches_data, trade_date)
        wb.save(str(file_path))
        wb.save(str(latest_path))

        _update_reports_readme(out_dir)

        size_kb = file_path.stat().st_size / 1024
        print(f"  [Excel] OK ({size_kb:.1f} KB):")
        print(f"     {file_path.name}")
        print(f"     latest.xlsx")
        if is_overwrite:
            print(f"     (overwritten)")
        return str(file_path)

    except Exception as e:
        print(f"  [Excel] FAILED: {e}")
        import traceback; traceback.print_exc()
        return None


def _update_reports_readme(reports_dir: Path):
    """Update reports/README.md with file index"""
    try:
        excel_files = sorted(
            reports_dir.glob("chip_radar_*.xlsx"),
            key=lambda p: p.name,
            reverse=True
        )

        readme = reports_dir / "README.md"
        lines = [
            "# Chip Radar Excel Daily Report",
            "",
            "Auto-generated after each Daily Full Crawl.",
            "",
            "## Latest",
            "",
            "[**latest.xlsx**](./latest.xlsx) - always the most recent day",
            "",
            "## History",
            "",
            f"{len(excel_files)} trading days:",
            "",
            "| File | Size | Link |",
            "|------|------|------|",
        ]
        for p in excel_files[:30]:
            size_kb = p.stat().st_size / 1024
            lines.append(f"| {p.name} | {size_kb:.1f} KB | [Download](./{p.name}) |")

        if len(excel_files) > 30:
            lines.append(f"")
            lines.append(f"...and {len(excel_files) - 30} older files")

        lines.extend([
            "",
            "---",
            "",
            "## Structure",
            "",
            "Single sheet per day (YYYYMMDD), vertical layout:",
            "- Each branch: header row + top 10 stocks by buy amount",
            "- 12 columns: Master / Branch / Code / Stock / Buy lots / Sell lots / "
            "Buy amt / Sell amt / Net diff / Buy avg / Sell avg / P&L",
            "",
            f"*Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])

        readme.write_text('\n'.join(lines), encoding='utf-8')
    except Exception as e:
        print(f"  [Excel] README update failed: {e}")


# ============================================================
#  CLI test (mock data)
# ============================================================
if __name__ == '__main__':
    mock = [
        {
            'code': '9B25', 'name': '元富-台中', 'master': '民哥',
            'buys': [
                {'code': '2454', 'name': '聯發科', 'buy_amt': 213521, 'sell_amt': 51477, 'net_amt': 162044, 'buy_lot': 102, 'sell_lot': 25, 'net_lot': 77},
                {'code': '2303', 'name': '聯電', 'buy_amt': 58370, 'sell_amt': 17660, 'net_amt': 40710, 'buy_lot': 755, 'sell_lot': 224, 'net_lot': 531},
                {'code': '3189', 'name': '景碩', 'buy_amt': 45350, 'sell_amt': 7000, 'net_amt': 38350, 'buy_lot': 108, 'sell_lot': 16, 'net_lot': 92},
                {'code': '6182', 'name': '合晶', 'buy_amt': 39910, 'sell_amt': 40320, 'net_amt': -410, 'buy_lot': 1021, 'sell_lot': 1030, 'net_lot': -9},
                {'code': '5483', 'name': '中美晶', 'buy_amt': 27160, 'sell_amt': 1670, 'net_amt': 25490, 'buy_lot': 202, 'sell_lot': 12, 'net_lot': 190},
                {'code': '4977', 'name': '眾達-KY', 'buy_amt': 26940, 'sell_amt': 2030, 'net_amt': 24910, 'buy_lot': 111, 'sell_lot': 8, 'net_lot': 103},
                {'code': '8046', 'name': '南電', 'buy_amt': 22960, 'sell_amt': 2440, 'net_amt': 20520, 'buy_lot': 29, 'sell_lot': 3, 'net_lot': 26},
                {'code': '5439', 'name': '高技', 'buy_amt': 22100, 'sell_amt': 6130, 'net_amt': 15970, 'buy_lot': 50, 'sell_lot': 14, 'net_lot': 36},
                {'code': '3105', 'name': '穩懋', 'buy_amt': 18920, 'sell_amt': 121830, 'net_amt': -102910, 'buy_lot': 32, 'sell_lot': 209, 'net_lot': -177},
                {'code': '3037', 'name': '欣興', 'buy_amt': 15480, 'sell_amt': 1530, 'net_amt': 13950, 'buy_lot': 22, 'sell_lot': 2, 'net_lot': 20},
            ],
            'sells': [],
        },
        {
            'code': '9666', 'name': '富邦-南屯', 'master': '民哥',
            'buys': [
                {'code': '8074', 'name': '鉅橡', 'buy_amt': 130080, 'sell_amt': 23180, 'net_amt': 106900, 'buy_lot': 1662, 'sell_lot': 303, 'net_lot': 1359},
                {'code': '8046', 'name': '南電', 'buy_amt': 120320, 'sell_amt': 50670, 'net_amt': 69650, 'buy_lot': 151, 'sell_lot': 64, 'net_lot': 87},
                {'code': '3081', 'name': '聯亞', 'buy_amt': 88660, 'sell_amt': 81410, 'net_amt': 7250, 'buy_lot': 31, 'sell_lot': 29, 'net_lot': 2},
                {'code': '8299', 'name': '群聯', 'buy_amt': 66520, 'sell_amt': 9300, 'net_amt': 57220, 'buy_lot': 41, 'sell_lot': 5, 'net_lot': 36},
                {'code': '6213', 'name': '聯茂', 'buy_amt': 54720, 'sell_amt': 30410, 'net_amt': 24310, 'buy_lot': 193, 'sell_lot': 107, 'net_lot': 86},
                {'code': '2330', 'name': '台積電', 'buy_amt': 45000, 'sell_amt': 13550, 'net_amt': 31450, 'buy_lot': 22, 'sell_lot': 6, 'net_lot': 16},
                {'code': '6182', 'name': '合晶', 'buy_amt': 42320, 'sell_amt': 38710, 'net_amt': 3610, 'buy_lot': 1076, 'sell_lot': 985, 'net_lot': 91},
                {'code': '3653', 'name': '健策', 'buy_amt': 35110, 'sell_amt': 820, 'net_amt': 34290, 'buy_lot': 7, 'sell_lot': 0, 'net_lot': 7},
                {'code': '5347', 'name': '世界', 'buy_amt': 32260, 'sell_amt': 32290, 'net_amt': -30, 'buy_lot': 223, 'sell_lot': 228, 'net_lot': -5},
                {'code': '5439', 'name': '高技', 'buy_amt': 31760, 'sell_amt': 15170, 'net_amt': 16590, 'buy_lot': 72, 'sell_lot': 35, 'net_lot': 37},
            ],
            'sells': [],
        },
        {
            'code': '779W', 'name': '國票彰化', 'master': '民哥',
            'buys': [
                {'code': '6531', 'name': '愛普*', 'buy_amt': 12560, 'sell_amt': 4800, 'net_amt': 7760, 'buy_lot': 18, 'sell_lot': 7, 'net_lot': 11},
                {'code': '1802', 'name': '台玻', 'buy_amt': 12040, 'sell_amt': 10980, 'net_amt': 1060, 'buy_lot': 163, 'sell_lot': 148, 'net_lot': 15},
                {'code': '7769', 'name': '鴻勁', 'buy_amt': 9640, 'sell_amt': 9000, 'net_amt': 640, 'buy_lot': 2, 'sell_lot': 2, 'net_lot': 0},
            ],
            'sells': [],
        },
        {
            'code': '9658', 'name': '富邦-建國', 'master': '林滄海',
            'buys': [
                {'code': '2330', 'name': '台積電', 'buy_amt': 268770, 'sell_amt': 172890, 'net_amt': 95880, 'buy_lot': 131, 'sell_lot': 84, 'net_lot': 47},
                {'code': '2454', 'name': '聯發科', 'buy_amt': 120000, 'sell_amt': 30000, 'net_amt': 90000, 'buy_lot': 60, 'sell_lot': 15, 'net_lot': 45},
            ],
            'sells': [],
        },
    ]

    result = generate_excel_report(mock, '20260507', output_dir='data/reports')
    if result:
        print(f"\n  Test OK: {result}")
