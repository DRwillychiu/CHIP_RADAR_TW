"""
excel_report.py — v3.22 老闆版 Excel 日報生成器

需求:
  • 每日 Daily Full Crawl 跑完後自動生成
  • 56 個關注分點各列出買超金額 Top 10
  • 老闆友善排版 (千分位 / 顏色標示 / 凍結首列)

輸出:
  data/reports/chip_radar_YYYYMMDD.xlsx
  data/reports/latest.xlsx (符號連結到最新)

Sheet 結構:
  Sheet 1: 「總覽」- 56 個分點 × Top 10 (橫向排列)
  Sheet 2: 「分點明細」- 全部分點完整買賣超 (1 sheet 條列式)
"""

import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════
#  樣式常數 (老闆友善)
# ════════════════════════════════════════════════════════════════════

# 字體
FONT_TITLE = lambda: Font(name='微軟正黑體', size=12, bold=True, color='FFFFFF')
FONT_HEADER = lambda: Font(name='微軟正黑體', size=10, bold=True, color='FFFFFF')
FONT_BRANCH = lambda: Font(name='微軟正黑體', size=11, bold=True, color='1F2937')
FONT_BODY = lambda: Font(name='微軟正黑體', size=10)
FONT_BUY = lambda: Font(name='微軟正黑體', size=10, color='C00000', bold=True)   # 紅 (買超)
FONT_SELL = lambda: Font(name='微軟正黑體', size=10, color='006100', bold=True)  # 綠 (賣超, 台股慣例)

# 填色
FILL_TITLE = lambda: PatternFill('solid', start_color='1F2A48')      # 深藍
FILL_HEADER = lambda: PatternFill('solid', start_color='3B82F6')     # 藍
FILL_BRANCH = lambda: PatternFill('solid', start_color='FCD34D')     # 金黃 (分點標題列)
FILL_ROW_ALT = lambda: PatternFill('solid', start_color='F3F4F6')    # 淺灰 (隔行)

# 對齊
ALIGN_CENTER = lambda: Alignment(horizontal='center', vertical='center', wrap_text=True)
ALIGN_LEFT = lambda: Alignment(horizontal='left', vertical='center')
ALIGN_RIGHT = lambda: Alignment(horizontal='right', vertical='center')

# 邊框
BORDER_THIN = lambda: Border(
    left=Side(style='thin', color='D1D5DB'),
    right=Side(style='thin', color='D1D5DB'),
    top=Side(style='thin', color='D1D5DB'),
    bottom=Side(style='thin', color='D1D5DB'),
)


# ════════════════════════════════════════════════════════════════════
#  Sheet 1: 總覽 (橫向排列, 老闆愛看的格式)
# ════════════════════════════════════════════════════════════════════

def build_overview_sheet(wb, branches_data: List[Dict], trade_date: str):
    """
    Sheet 1: 56 個分點 × Top 10 買超 (橫向排列)
    
    每個分點佔 4 欄: [排名, 股票, 買超金額, 買超張數]
    分點之間留 1 空白欄
    """
    ws = wb.active
    ws.title = "總覽"
    
    # 第 1 列:大標題
    title = f"Chip Radar 分點籌碼日報 · {trade_date}"
    ws['A1'] = title
    ws['A1'].font = Font(name='微軟正黑體', size=14, bold=True, color='FFFFFF')
    ws['A1'].fill = FILL_TITLE()
    ws['A1'].alignment = ALIGN_CENTER()
    
    # 第 2 列:副標
    ws['A2'] = f"關注分點當日買超金額前 10 名 ｜ 共 {len(branches_data)} 個分點 ｜ 自動生成"
    ws['A2'].font = Font(name='微軟正黑體', size=10, italic=True, color='6B7280')
    ws['A2'].alignment = ALIGN_LEFT()
    
    # 過濾 enabled 且有 buys 的分點
    valid_branches = [b for b in branches_data if b.get('buys')]
    
    # 排序: master + 分點名 (穩定順序)
    valid_branches.sort(key=lambda b: (b.get('master', ''), b.get('name', '')))
    
    # 從第 4 列開始放分點 (留第 3 列空白)
    HEADER_ROW = 4
    DATA_START_ROW = 5
    COLS_PER_BRANCH = 5  # 排名/股票/買超金額/買超張數/空白
    TOP_N = 10
    
    # 合併第 1 列大標題 (跨 56*5 欄但太多, 改跨 20 欄就好)
    total_cols_visible = min(20, len(valid_branches) * COLS_PER_BRANCH)
    if total_cols_visible > 1:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols_visible)
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols_visible)
    
    # 每個分點佔一個 column block
    for bi, branch in enumerate(valid_branches):
        col_start = bi * COLS_PER_BRANCH + 1  # 1-indexed
        
        master_name = branch.get('master', '?')
        branch_name = branch.get('name', '?')
        branch_code = branch.get('code', '')
        
        # 分點標題列 (合併 4 欄)
        title_cell = ws.cell(row=HEADER_ROW - 1, column=col_start)  # 第 3 列
        title_cell.value = f"{master_name} · {branch_name} ({branch_code})"
        title_cell.font = FONT_BRANCH()
        title_cell.fill = FILL_BRANCH()
        title_cell.alignment = ALIGN_CENTER()
        title_cell.border = BORDER_THIN()
        ws.merge_cells(
            start_row=HEADER_ROW - 1, start_column=col_start,
            end_row=HEADER_ROW - 1, end_column=col_start + 3
        )
        
        # 表頭列
        headers = ['#', '股票', '買超金額(仟)', '買超張數']
        for hi, h in enumerate(headers):
            c = ws.cell(row=HEADER_ROW, column=col_start + hi)
            c.value = h
            c.font = FONT_HEADER()
            c.fill = FILL_HEADER()
            c.alignment = ALIGN_CENTER()
            c.border = BORDER_THIN()
        
        # Top 10 資料
        buys = sorted(branch.get('buys', []), key=lambda x: x.get('net_amt', 0), reverse=True)[:TOP_N]
        for ri, item in enumerate(buys):
            row = DATA_START_ROW + ri
            
            # 隔行底色
            row_fill = FILL_ROW_ALT() if ri % 2 == 1 else None
            
            # # 欄位
            c = ws.cell(row=row, column=col_start)
            c.value = ri + 1
            c.font = FONT_BODY()
            c.alignment = ALIGN_CENTER()
            c.border = BORDER_THIN()
            if row_fill: c.fill = row_fill
            
            # 股票
            c = ws.cell(row=row, column=col_start + 1)
            c.value = f"{item.get('code', '')} {item.get('name', '')}"
            c.font = FONT_BODY()
            c.alignment = ALIGN_LEFT()
            c.border = BORDER_THIN()
            if row_fill: c.fill = row_fill
            
            # 買超金額 (仟元)
            c = ws.cell(row=row, column=col_start + 2)
            net_amt = item.get('net_amt', 0)
            c.value = net_amt
            c.number_format = '#,##0;[Red]-#,##0;-'
            c.font = FONT_BUY() if net_amt > 0 else (FONT_SELL() if net_amt < 0 else FONT_BODY())
            c.alignment = ALIGN_RIGHT()
            c.border = BORDER_THIN()
            if row_fill: c.fill = row_fill
            
            # 買超張數
            c = ws.cell(row=row, column=col_start + 3)
            net_lot = item.get('net_lot', 0)
            c.value = net_lot
            c.number_format = '#,##0;[Red]-#,##0;-'
            c.font = FONT_BODY()
            c.alignment = ALIGN_RIGHT()
            c.border = BORDER_THIN()
            if row_fill: c.fill = row_fill
        
        # 空欄不夠 10 筆時, 補空白格
        for ri in range(len(buys), TOP_N):
            row = DATA_START_ROW + ri
            for hi in range(4):
                c = ws.cell(row=row, column=col_start + hi)
                c.border = BORDER_THIN()
        
        # 設欄寬
        ws.column_dimensions[get_column_letter(col_start)].width = 4    # #
        ws.column_dimensions[get_column_letter(col_start + 1)].width = 16  # 股票
        ws.column_dimensions[get_column_letter(col_start + 2)].width = 13  # 買超金額
        ws.column_dimensions[get_column_letter(col_start + 3)].width = 11  # 張數
        ws.column_dimensions[get_column_letter(col_start + 4)].width = 2   # 空白分隔
    
    # 凍結
    ws.freeze_panes = ws.cell(row=DATA_START_ROW, column=1)
    
    # 列高
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[HEADER_ROW - 1].height = 22  # 分點名稱
    ws.row_dimensions[HEADER_ROW].height = 20      # 表頭


# ════════════════════════════════════════════════════════════════════
#  Sheet 2: 分點明細 (條列式, 完整資料)
# ════════════════════════════════════════════════════════════════════

def build_detail_sheet(wb, branches_data: List[Dict], trade_date: str):
    """
    Sheet 2: 分點明細 (條列式)
    每個分點 + 個股一筆, 含完整買賣超資料
    """
    ws = wb.create_sheet(title="分點明細")
    
    # 標題
    title = f"分點明細 · {trade_date}"
    ws['A1'] = title
    ws['A1'].font = Font(name='微軟正黑體', size=14, bold=True, color='FFFFFF')
    ws['A1'].fill = FILL_TITLE()
    ws['A1'].alignment = ALIGN_CENTER()
    ws.merge_cells('A1:K1')
    
    # 表頭
    headers = ['Master', '分點代號', '分點名稱', '股票代號', '股票名稱',
               '買進金額(仟)', '賣出金額(仟)', '買賣超金額(仟)',
               '買進張數', '賣出張數', '買賣超張數']
    for ci, h in enumerate(headers):
        c = ws.cell(row=2, column=ci + 1)
        c.value = h
        c.font = FONT_HEADER()
        c.fill = FILL_HEADER()
        c.alignment = ALIGN_CENTER()
        c.border = BORDER_THIN()
    
    # 資料: 每個分點的 buys + sells 全列
    valid_branches = [b for b in branches_data if b.get('buys') or b.get('sells')]
    valid_branches.sort(key=lambda b: (b.get('master', ''), b.get('name', '')))
    
    row = 3
    for branch in valid_branches:
        master = branch.get('master', '')
        b_code = branch.get('code', '')
        b_name = branch.get('name', '')
        
        # 把買 + 賣 合併,用 net_amt 排序
        all_items = []
        for item in branch.get('buys', []):
            all_items.append({**item, '_side': 'buy'})
        for item in branch.get('sells', []):
            all_items.append({**item, '_side': 'sell'})
        
        # 用絕對值排序 (買賣超大的排前面)
        all_items.sort(key=lambda x: abs(x.get('net_amt', 0)), reverse=True)
        
        for item in all_items:
            net_amt = item.get('net_amt', 0)
            net_lot = item.get('net_lot', 0)
            
            ws.cell(row=row, column=1, value=master).font = FONT_BODY()
            ws.cell(row=row, column=2, value=b_code).font = FONT_BODY()
            ws.cell(row=row, column=3, value=b_name).font = FONT_BODY()
            ws.cell(row=row, column=4, value=item.get('code', '')).font = FONT_BODY()
            ws.cell(row=row, column=5, value=item.get('name', '')).font = FONT_BODY()
            
            ws.cell(row=row, column=6, value=item.get('buy_amt', 0)).number_format = '#,##0'
            ws.cell(row=row, column=7, value=item.get('sell_amt', 0)).number_format = '#,##0'
            
            net_cell = ws.cell(row=row, column=8, value=net_amt)
            net_cell.number_format = '#,##0;[Red]-#,##0;-'
            net_cell.font = FONT_BUY() if net_amt > 0 else (FONT_SELL() if net_amt < 0 else FONT_BODY())
            
            ws.cell(row=row, column=9, value=item.get('buy_lot', 0)).number_format = '#,##0'
            ws.cell(row=row, column=10, value=item.get('sell_lot', 0)).number_format = '#,##0'
            
            net_lot_cell = ws.cell(row=row, column=11, value=net_lot)
            net_lot_cell.number_format = '#,##0;[Red]-#,##0;-'
            
            # 邊框 + 對齊
            for ci in range(1, 12):
                c = ws.cell(row=row, column=ci)
                c.border = BORDER_THIN()
                if ci <= 5:
                    c.alignment = ALIGN_LEFT()
                else:
                    c.alignment = ALIGN_RIGHT()
                # 隔行底色
                if (row - 3) % 2 == 1:
                    c.fill = FILL_ROW_ALT()
            
            row += 1
    
    # 欄寬
    widths = [16, 8, 18, 9, 14, 13, 13, 14, 10, 10, 11]
    for ci, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(ci + 1)].width = w
    
    # 凍結
    ws.freeze_panes = 'A3'
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 22


# ════════════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════════════

def generate_excel_report(branches_data: List[Dict], trade_date: str, 
                          output_dir: str = "data/reports") -> Optional[str]:
    """
    生成 Excel 日報
    
    Args:
        branches_data: 分點資料列表 (含 buys/sells)
        trade_date: 交易日 (YYYYMMDD, e.g. '20260507')
        output_dir: 輸出目錄 (預設 data/reports)
    
    Returns:
        生成的檔案路徑 (失敗回 None)
    
    輸出檔名 (3 個):
        • chip_radar_2026-05-07.xlsx       (清楚日期格式)
        • latest.xlsx                       (永遠是最新, 老闆書籤用)
        • README.md (列表所有歷史檔)
    """
    if not OPENPYXL_AVAILABLE:
        print("  ⚠️ openpyxl 未安裝, 跳過 Excel 生成")
        return None
    
    if not branches_data:
        print("  ⚠️ 無分點資料, 跳過 Excel 生成")
        return None
    
    # 建立輸出目錄
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 檔名:用易讀格式 chip_radar_2026-05-07.xlsx
    if len(trade_date) == 8 and trade_date.isdigit():
        # YYYYMMDD → YYYY-MM-DD
        readable_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    else:
        readable_date = trade_date
    
    file_path = out_dir / f"chip_radar_{readable_date}.xlsx"
    latest_path = out_dir / "latest.xlsx"
    
    # 顯示檔案是否已存在 (重跑會覆蓋)
    is_overwrite = file_path.exists()
    if is_overwrite:
        print(f"  [Excel] 偵測到當日檔案存在, 將覆蓋更新")
    
    print(f"  [Excel] 生成中... ({len(branches_data)} 個分點, 日期 {readable_date})")
    
    # 建立 Workbook
    wb = Workbook()
    
    try:
        build_overview_sheet(wb, branches_data, trade_date)
        build_detail_sheet(wb, branches_data, trade_date)
        wb.save(str(file_path))
        
        # 也存一份 latest (覆蓋舊的, 老闆永遠開最新)
        wb.save(str(latest_path))
        
        # 更新 README (歷史檔列表)
        _update_reports_readme(out_dir)
        
        size_kb = file_path.stat().st_size / 1024
        print(f"  ✅ Excel 報告 ({size_kb:.1f} KB):")
        print(f"     • {file_path.name}")
        print(f"     • latest.xlsx (永遠最新)")
        if is_overwrite:
            print(f"     ↻ 覆蓋更新成功")
        return str(file_path)
    
    except Exception as e:
        print(f"  ❌ Excel 生成失敗: {e}")
        import traceback; traceback.print_exc()
        return None


def _update_reports_readme(reports_dir: Path):
    """更新 reports/README.md - 歷史檔索引"""
    try:
        excel_files = sorted(
            reports_dir.glob("chip_radar_*.xlsx"),
            key=lambda p: p.name,
            reverse=True
        )
        
        readme = reports_dir / "README.md"
        lines = [
            "# 📊 Chip Radar 老闆版 Excel 日報歷史",
            "",
            "**自動生成** - 每日 Daily Full Crawl 跑完後自動更新",
            "",
            "## 📥 直接下載最新版",
            "",
            "[**latest.xlsx**](./latest.xlsx) — 永遠是最新一日 (建議書籤)",
            "",
            "## 📚 歷史檔",
            "",
            f"共 {len(excel_files)} 個交易日:",
            "",
            "| 檔名 | 大小 | 連結 |",
            "|------|------|------|",
        ]
        for p in excel_files[:30]:  # 最多顯示 30 天
            size_kb = p.stat().st_size / 1024
            lines.append(f"| {p.name} | {size_kb:.1f} KB | [下載](./{p.name}) |")
        
        if len(excel_files) > 30:
            lines.append(f"")
            lines.append(f"...及更舊的 {len(excel_files) - 30} 個檔案")
        
        lines.extend([
            "",
            "---",
            "",
            "## 📋 Excel 結構",
            "",
            "**Sheet 1「總覽」**: 56 個關注分點 × 各 Top 10 買超個股 (橫向排列)",
            "",
            "**Sheet 2「分點明細」**: 完整買賣超 (每筆: Master/分點/股票/買進/賣出/淨額)",
            "",
            "## 🎨 配色",
            "",
            "- 🔴 **紅色** = 買超 (台股慣例)",
            "- 🟢 **綠色** = 賣超 (台股慣例)",
            "",
            "---",
            "",
            f"*Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])
        
        readme.write_text('\n'.join(lines), encoding='utf-8')
    except Exception as e:
        print(f"  ⚠️ README 更新失敗: {e}")


# ════════════════════════════════════════════════════════════════════
#  CLI 測試 (用 mock 資料)
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Mock 分點資料
    mock = [
        {
            'code': '9B25', 'name': '台新-五權西', 'master': '民哥',
            'buys': [
                {'code': '2330', 'name': '台積電', 'buy_amt': 50000, 'sell_amt': 5000, 'net_amt': 45000, 'buy_lot': 50, 'sell_lot': 5, 'net_lot': 45},
                {'code': '2317', 'name': '鴻海', 'buy_amt': 30000, 'sell_amt': 2000, 'net_amt': 28000, 'buy_lot': 30, 'sell_lot': 2, 'net_lot': 28},
                {'code': '2454', 'name': '聯發科', 'buy_amt': 25000, 'sell_amt': 1000, 'net_amt': 24000, 'buy_lot': 25, 'sell_lot': 1, 'net_lot': 24},
            ],
            'sells': [
                {'code': '6505', 'name': '台塑化', 'buy_amt': 1000, 'sell_amt': 15000, 'net_amt': -14000, 'buy_lot': 1, 'sell_lot': 15, 'net_lot': -14},
            ],
        },
        {
            'code': 'F002', 'name': '兆豐-民生', 'master': '陳律師',
            'buys': [
                {'code': '2330', 'name': '台積電', 'buy_amt': 80000, 'sell_amt': 3000, 'net_amt': 77000, 'buy_lot': 80, 'sell_lot': 3, 'net_lot': 77},
                {'code': '2603', 'name': '長榮', 'buy_amt': 40000, 'sell_amt': 2000, 'net_amt': 38000, 'buy_lot': 200, 'sell_lot': 10, 'net_lot': 190},
            ],
            'sells': [],
        },
    ]
    
    result = generate_excel_report(mock, '20260506', output_dir='/tmp/test_reports')
    if result:
        print(f"\n  📊 測試成功!")
        print(f"     開啟看看: {result}")
