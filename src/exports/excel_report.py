"""
excel_report.py v3.26 - Style-aware Excel daily report

v3.26 change: 隔日沖 / 當沖 master 的資料源自動切換為「今天買的漲停股」,
波段 / 長線 master 維持原 Top 10 by 買超。視覺格式與手動版完全一致。

Strict mimicry of user's hand-curated Excel ("分點觀察" boss report).

Layout (per master block):
  Row 1: full header [高手|分點|代號|標的|...|損益(萬)]   ← A="高手" label
  Row 2: first data row of master's first branch          ← A=master_name (merged down)
  Rows 2-11: 10 data rows for branch #1 (padded blank if <10 stocks)
  Row 12: sub-header [(空)|分點|代號|標的|...]            ← A empty, under master merge
  Rows 13-22: 10 data rows for branch #2
  ...
  Next master: full header row again, A=高手 label

Visual style (matches manual file exactly):
  - Font: 新細明體 (PMingLiU), 12pt
  - All cells: center/center alignment
  - NO fills, NO borders
  - Header rows + master/branch/code labels: bold
  - L column: =F*(K-J), format '0.00_ ;[Red]\\-0.00\\ ' (red text on negative)

Data source routing (v3.26):
  - sniper master (next_day_flipper / day_trader) → top 10 漲停股 by buy_amt
  - other master (swing / longterm / unmapped)    → top 10 全部個股 by buy_amt (legacy)
  - sniper master with no limit-up buys today     → 10 blank rows (intentional, not fallback)

Outputs:
  data/reports/chip_radar_YYYY-MM-DD.xlsx  - single-sheet daily snapshot
  data/reports/latest.xlsx                  - multi-sheet, last 30 trading days
  data/reports/README.md                    - history index
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.formatting.rule import ColorScaleRule, IconSetRule, CellIsRule
    from openpyxl.worksheet.worksheet import Worksheet
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

# v3.62.0 (Sprint 25): 全域 enrichment sheet 名稱
# 月檔結構: [📋 摘要, 🚨 警報, 📦 連續囤貨, ⚠️ 風險警示] + 日期 sheet desc
SUMMARY_SHEET_NAME = "📋 今日摘要"
ALERTS_SHEET_NAME = "🚨 異常警報"
ACCUMULATION_SHEET_NAME = "📦 連續囤貨"
RISK_SHEET_NAME = "⚠️ 風險警示"
ENRICHMENT_SHEETS = [SUMMARY_SHEET_NAME, ALERTS_SHEET_NAME, ACCUMULATION_SHEET_NAME, RISK_SHEET_NAME]

try:
    from branches import MASTER_STYLES
except ImportError:
    MASTER_STYLES = {}

SNIPER_STYLES = {"next_day_flipper", "day_trader"}

# v3.30.5: 使用者要求 Excel 只有「蔣承翰」用漲停股抓取法。
# 原 v3.26 是「所有 next_day_flipper/day_trader style 的 master 都用漲停法」
# (蔣承翰 / 迷你哥-松山哥 / Tradow / 巨人傑),現縮為白名單僅蔣承翰一人,
# 其餘 sniper-style master 全部改回一般買超 Top N (其餘不變)。
# 未來要再加 sniper master,把名字加進這個 set 即可。
SNIPER_MASTER_WHITELIST = {"蔣承翰"}


# v3.31.1: 老闆版 Excel 色塊配色 (15 個個人大戶 + 法人類)
# 設計: 風格類別分大色系 + master 之內 lightness 微差
#   暖色 (紅/橘) = sniper (next_day_flipper / day_trader)
#   藍綠系     = swing (波段)
#   灰系       = longterm (長線)
#   外資/官股  = 中性灰 (不重點分析)
# header 較深 (master/branch label 列) + body 較淡 (data 列), 保留字型不刺眼
MASTER_BLOCK_COLORS = {
    # ── Sniper 暖色系 (5 個) ──
    "蔣承翰":                {"header": "FFE57373", "body": "FFFFEBEE"},  # 紅 (主 sniper, 漲停獵手)
    "巨人傑":                {"header": "FFEF9A9A", "body": "FFFFE5E5"},  # 淡紅 (雙風格)
    "Tradow":                {"header": "FFFFAB91", "body": "FFFFEDE7"},  # 橘紅
    "迷你哥/松山哥":         {"header": "FFFFB74D", "body": "FFFFF3E0"},  # 橘 (當沖)
    "Krenz(再多一位數本人)": {"header": "FFFFCC80", "body": "FFFFF8E1"},  # 淡橘
    # ── Swing 波段藍綠系 (8 個) ──
    "民哥":                  {"header": "FF81C784", "body": "FFE8F5E9"},  # 綠
    "林滄海":                {"header": "FFA5D6A7", "body": "FFEEF7EE"},  # 淡綠 (longterm tint)
    "張濬安(航海王)":        {"header": "FF64B5F6", "body": "FFE3F2FD"},  # 海藍 (航運王)
    "陳族元":                {"header": "FF90CAF9", "body": "FFE7F2FB"},  # 淡藍
    "陳律師":                {"header": "FFB39DDB", "body": "FFEDE7F6"},  # 紫
    "布哥/n_nchang":         {"header": "FF80DEEA", "body": "FFE0F7FA"},  # 青
    "強森":                  {"header": "FF80CBC4", "body": "FFE0F2F1"},  # 青綠
    "大牌分析師":            {"header": "FFAED581", "body": "FFF1F8E9"},  # 黃綠
    # ── Longterm 長線灰系 (2 個) ──
    "優式資本":              {"header": "FFBCAAA4", "body": "FFEFEBE9"},  # 灰棕
    "東億資本":              {"header": "FFB0BEC5", "body": "FFECEFF1"},  # 灰藍
}
DEFAULT_MASTER_COLOR = {"header": "FFD7D7D7", "body": "FFF5F5F5"}   # 未在表內的 fallback


def _apply_master_block_color(ws: "Worksheet",
                               header_rows: List[int],
                               data_rows: List[int],
                               master_anchor_row: int,
                               colors: Dict[str, str],
                               cols: int = 12) -> None:
    """v3.31.1: 對 master block 套色塊.
    header_rows: 高手/master label / sub-header 列 → 深色 header_fill
    data_rows:   stock data 列 → 淡色 body_fill
    master_anchor_row: A 欄 master name 的 merge anchor → 深色 (跨整個 block 視覺主色)
    cols: 套色欄數 (預設 A-L = 12)。"""
    if not colors:
        return
    try:
        body_fill = PatternFill("solid", fgColor=colors["body"])
        header_fill = PatternFill("solid", fgColor=colors["header"])
    except Exception:
        return  # color spec 壞掉就不套

    # 先全 block 套 body (淡)
    for r in data_rows:
        for c in range(1, cols + 1):
            ws.cell(row=r, column=c).fill = body_fill

    # 再套 header rows (深)
    for r in header_rows:
        for c in range(1, cols + 1):
            ws.cell(row=r, column=c).fill = header_fill

    # A 欄 master anchor 套 header (整個 block 主色, 覆寫 body)
    ws.cell(row=master_anchor_row, column=1).fill = header_fill


def _is_sniper_master(master_name: str) -> bool:
    """v3.26: 隔日沖 / 當沖 master → 改用漲停股資料源。
    v3.30.5: 限縮為白名單 (僅蔣承翰);不在名單者即使 style 符合也用一般買超 Top N。"""
    if master_name not in SNIPER_MASTER_WHITELIST:
        return False
    styles = MASTER_STYLES.get(master_name, [])
    return bool(SNIPER_STYLES.intersection(styles))


# ============================================================
#  Master mapping (extracted from user's manual file 5/8 version)
#  - 12 masters / 42 branch slots
#  - Branch codes are TWSE codes (authoritative)
#  - Branch names use canonical names from branches.py where possible
#  - header_label: "分點" or "常下分點" (matches manual section style)
# ============================================================

MASTER_MAPPING: List[Dict] = [
    {
        "name": "民哥",
        "header_label": "分點",
        "branches": [
            ("9B25", "台新-五權西"),
            ("9666", "富邦-南屯"),
            ("779W", "國票-彰化"),
        ],
    },
    {
        "name": "林滄海",
        "header_label": "常下分點",
        "branches": [
            ("9658", "富邦-建國"),
            ("9309", "華南永昌-古亭"),
            ("1260", "宏遠證券"),
            ("9216", "凱基-信義"),
        ],
    },
    {
        "name": "張濬安(航海王)",
        "header_label": "常下分點",
        "branches": [
            ("779Z", "國票-安和"),
            ("9B2E", "台新-城中"),
            ("920F", "凱基-站前"),
            ("6167", "中國信託-松江"),
            ("961M", "富邦-木柵"),
            ("9100", "群益金鼎證券"),
        ],
    },
    {
        # Manual file's first 5-branch block (A144:A198 with master name "陳族元")
        "name": "陳族元",
        "header_label": "常下分點",
        "branches": [
            ("8880", "國泰證券"),
            ("9300", "華南永昌證券"),
            ("9216", "凱基-信義"),
            ("9661", "富邦-新店"),
            ("9A9g", "永豐金-內湖"),
        ],
    },
    {
        # Manual file's unnamed 4-branch block (A200:A242 merge has no master name).
        # Maps to "陳律師" per branches.py canonical naming.
        "name": "陳律師",
        "header_label": "常下分點",
        "branches": [
            ("700c", "兆豐-民生"),
            ("8450", "康和總公司"),
            ("9A9R", "永豐金-信義"),
            ("585c", "統一-仁愛"),
        ],
    },
    {
        "name": "迷你哥/松山哥",
        "header_label": "常下分點",
        "branches": [
            ("9217", "凱基-松山"),
            ("9200", "凱基證券"),
            ("9600", "富邦證券"),
        ],
    },
    {
        "name": "布哥/n_nchang",
        "header_label": "常下分點",
        "branches": [
            ("9A8F", "永豐金-敦南"),
        ],
    },
    {
        "name": "強森",
        "header_label": "分點",
        "branches": [
            ("9B25", "台新-五權西"),
            ("9B2E", "台新-城中"),
            ("9B2r", "台新-城東"),
            ("984K", "元大-館前"),
            ("989N", "元大-內湖"),
            ("9215", "凱基-高美館"),
            ("9B2D", "台新-大昌"),
        ],
    },
    {
        "name": "Tradow",
        "header_label": "分點",
        "branches": [
            ("9B2a", "台新-松德"),
        ],
    },
    {
        "name": "巨人傑",
        "header_label": "分點",
        "branches": [
            ("9B2n", "台新-西松"),
            ("984K", "元大-館前"),
            ("9B2z", "台新-文心"),
        ],
    },
    {
        "name": "蔣承翰",
        "header_label": "分點",
        "branches": [
            ("9227", "凱基-城中"),
            ("9B18", "台新-建北"),
        ],
    },
    {
        "name": "大牌分析師",
        "header_label": "分點",
        "branches": [
            ("8563", "新光-新竹"),
        ],
    },
    {
        "name": "竹科主力分點",
        "header_label": "分點",
        "branches": [
            ("700V", "兆豐-新竹"),
            ("9647", "富邦-新竹"),
        ],
    },
]


# ============================================================
#  Layout constants (matching manual file exactly)
# ============================================================

FONT_NAME = "新細明體"  # PMingLiU - traditional Chinese serif (matches manual)
FONT_SIZE = 12
ROW_HEIGHT = 16.5

COL_WIDTHS = {
    "A": 19.28515625,
    "B": 18.28515625,
    "C": 11.85546875,
    "D": 20.28515625,
    "E": 18.42578125,
    "F": 21.140625,
    "G": 18.42578125,
    "H": 21.140625,
    "I": 13.0,
    "J": 13.140625,
    "K": 11.42578125,
    "L": 15.5703125,
}

STOCKS_PER_BRANCH = 10  # default: 10 rows per branch (pad blank if fewer)

# v3.29.5 (2026-05-23): per-branch override 客製化 row 數
# User 5/23 要求 大牌分析師 新光-新竹 (8563) 改 Top 20 (其他維持 10).
# TWSE 分點頁面 publish Top 15 買榜 + Top 15 賣榜 = 最多 30 unique 個股, Top 20 用既有資料就夠.
# 要再加分點就直接編這個 dict, e.g. {"8563": 20, "9227": 15} (蔣承翰城中改 15).
BRANCH_STOCK_OVERRIDES: Dict[str, int] = {
    "8563": 20,   # 大牌分析師 / 新光-新竹 → Top 20 (5/23 user request)
}


# v3.29.7 (2026-05-24): 排除非個股 — 老闆 Excel 只看個股
# v3.29.6 第一版漏掉:
#   1. market_classifier 回傳 lowercase 'etf' / 'etf_active', 之前用 {"ETF"} 不 match
#   2. heuristic 只擋 4-5 char ('0050', '00878'), 漏 6-char 期信 ETN ('00715L 期街口布蘭特正2', '00738U 期元大道瓊白銀')
# v3.29.7 修法:
#   - EXCLUDED_MARKET_TYPES 改 lowercase + 含 'etf_active'
#   - Heuristic 改成 code.startswith('00') (不限長度)
#     根據 market_classifier.py L72: 「所有 '00' 開頭 code 都歸類為 ETF」
# 未來要排除其他類型 (e.g. 'preferred' 特別股), 加進這個 set 即可
EXCLUDED_MARKET_TYPES: set = {"etf", "etf_active"}


def _branch_stocks_size(branch_code: str) -> int:
    """v3.29.5: 取得單一分點的 row 數 (override 優先, fallback default 10)."""
    return BRANCH_STOCK_OVERRIDES.get(branch_code, STOCKS_PER_BRANCH)


def _is_excluded_by_market_type(stock: Dict) -> bool:
    """v3.29.7: 判斷該 stock 是否為非個股 (ETF / 衍生 / 期信 / 商品) 應排除.

    判斷順序:
      1. stock['market_type'].lower() 在 EXCLUDED_MARKET_TYPES → 排除
         (crawler.py 主流程已注入 market_type, 此為最可靠來源)
      2. code 開頭 '00' → 排除 (heuristic, 不限長度)
         根據 market_classifier.py L72-76:
           「所有 '00' 開頭 code 都歸類為 ETF (含 etf_active)」
         涵蓋: 普通 ETF (0050, 00878, 00646), 6-char ETN/期信 (00715L, 00738U),
              主動型 ETF (006208A)
    """
    mt = (stock.get('market_type') or '').strip().lower()
    if mt in EXCLUDED_MARKET_TYPES:
        return True
    code = (stock.get('code') or '').strip()
    if code.startswith('00'):
        return True
    return False

NUMBER_FMT_INT = "#,##0"
NUMBER_FMT_PRICE = "0.00"
NUMBER_FMT_PNL = '0.00_ ;[Red]\\-0.00\\ '


def _font_bold() -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=True)


def _font_normal() -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=False)


def _font_pnl_neg() -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=False, color="FFFF0000")


def _align_center() -> Alignment:
    return Alignment(horizontal="center", vertical="center")


def _header_row(header_label: str, include_master_label: bool) -> List[str]:
    """
    12-column header.
      header_label: "分點" or "常下分點" (master section style)
      include_master_label: True for master's full header (A="高手"), False for sub-header (A=None)
    """
    code_col_label = "代號" if header_label == "分點" else "分點代號"
    return [
        "高手" if include_master_label else None,
        header_label,
        code_col_label,
        "標的",
        "買進(張)",
        "賣出(張)",
        "買進(萬元)",
        "賣出(萬元)",
        "淨買差(萬元)",
        "買均",
        "賣均",
        "損益(萬)",
    ]


# ============================================================
#  Stock selection: top 10 by buy_amt for a given branch
# ============================================================

def _top_stocks_for_branch(branch_data: Dict, sniper_mode: bool = False,
                            n_top: int = None) -> List[Dict]:
    """
    Combine buys + sells lists, dedupe by code, sort by buy_amt desc, take top 10.
    Returns list of stock dicts with keys: code, name, buy_lot, sell_lot, buy_amt, sell_amt
    (buy_amt/sell_amt in 仟元 = thousand TWD per crawler convention).

    v3.26: when sniper_mode=True, restrict to limit-up stocks only (is_limit_up True).
    v3.28.1: 修補 sniper 過濾遺漏 net-seller 問題。
      使用者 review 發現 5/13 蔣承翰兩個分點都顯示微星,但實際 微星 是淨賣超。
      根因:TWSE 分點頁面 publish 兩榜 (買榜 Top 15 + 賣榜 Top 15),
            一檔股票若 grossly traded 兩邊大量,會同時在兩榜出現。
            v3.26 只 filter is_limit_up,沒檢查 net_amt > 0,
            於是「淨賣 但 gross 進買榜」的漲停股仍被選入 sniper 區段。
      用戶定義的正確語意:「先挑漲停股、觀察分點 *買超* 哪幾檔」 →
            net_amt > 0 (或 net_lot > 0) 才是真正 sniper 動作。
    Returns empty list if sniper master had zero net-bought limit-up stocks today (intentional).
    """
    if not branch_data:
        return []
    seen: Dict[str, Dict] = {}
    for s in (branch_data.get("buys") or []):
        c = s.get("code", "")
        if c and c not in seen:
            seen[c] = s
    for s in (branch_data.get("sells") or []):
        c = s.get("code", "")
        if c and c not in seen:
            seen[c] = s
    candidates = list(seen.values())

    # v3.29.6: 排除 ETF 等非個股 (老闆 Excel 只看個股)
    # 必須在 net_buyer + sniper filter *之前* 跑, 避免 ETF 占用 Top N 名額.
    candidates = [s for s in candidates if not _is_excluded_by_market_type(s)]

    # v3.29.1: 對 *所有* master (包含 swing) 加 net_buyer filter
    # 5/19 用戶 review 發現: 大牌分析師-新光新竹 顯示 6257 但實際淨賣 -1412 萬。
    # 系統性掃描全 Excel: 359 row 有資料,48 row (13%) 是淨賣股被選入 (e.g. 航海王 國票安和 國巨* 淨賣 2.1 億).
    # 根因: v3.28.1 只對 sniper_mode 加 net filter, swing master 仍按 buy_amt desc 排序,
    #       gross buy_amt 高 但 net 為負的個股污染 Excel.
    # 修法: 所有 master 先 filter net > 0, sniper_mode 再額外限定 is_limit_up.
    candidates = [
        s for s in candidates
        if (s.get("net_amt", 0) or 0) > 0 or (s.get("net_lot", 0) or 0) > 0
    ]

    if sniper_mode:
        # sniper master 額外限定: 只看漲停股
        candidates = [s for s in candidates if s.get("is_limit_up")]
    sorted_stocks = sorted(
        candidates,
        key=lambda x: x.get("buy_amt", 0) or 0,
        reverse=True,
    )
    # v3.29.5: n_top 預設 STOCKS_PER_BRANCH, 但允許 per-branch override (e.g. 8563→20)
    limit = n_top if n_top is not None else STOCKS_PER_BRANCH
    return sorted_stocks[:limit]


# ============================================================
#  Cell writing helpers
# ============================================================

def _write_header_row(ws: "Worksheet", row: int, header_label: str, include_master_label: bool):
    """Write a 12-cell header row. All cells bold + centered."""
    labels = _header_row(header_label, include_master_label)
    for ci, val in enumerate(labels, start=1):
        c = ws.cell(row=row, column=ci)
        c.value = val
        c.font = _font_bold()
        c.alignment = _align_center()


def _write_stock_row(ws: "Worksheet", row: int, stock: Dict, sniper_mode: bool = False):
    """Write 9 data columns (D-L) for a single stock. E-I integer, J-K price, L formula.
    v3.27.4 L4: sniper_mode=True 時在標的欄顯示漲幅%, 讓使用者一眼驗證漲停。"""
    code = stock.get("code", "") or ""
    name = stock.get("name", "") or code
    buy_lot = stock.get("buy_lot", 0) or 0
    sell_lot = stock.get("sell_lot", 0) or 0
    buy_amt_k = stock.get("buy_amt", 0) or 0   # in 仟元
    sell_amt_k = stock.get("sell_amt", 0) or 0

    # 仟元 -> 萬元 (divide by 10, round to nearest)
    buy_amt_w = round(buy_amt_k / 10) if buy_amt_k else 0
    sell_amt_w = round(sell_amt_k / 10) if sell_amt_k else 0
    net_w = buy_amt_w - sell_amt_w

    # Average prices: buy_amt_k(仟元) / buy_lot(張) gives elem-wise TWD/張 in thousands;
    # but per manual convention, we want TWD per share. 1張=1000股.
    # Manual shows e.g. 買均=386.99 for 國巨 — that's TWD/share.
    # So: buy_avg = buy_amt_k * 1000 / (buy_lot * 1000) = buy_amt_k / buy_lot (TWD/share)
    buy_avg = round(buy_amt_k / buy_lot, 2) if (buy_lot > 0 and buy_amt_k > 0) else 0
    sell_avg = round(sell_amt_k / sell_lot, 2) if (sell_lot > 0 and sell_amt_k > 0) else 0

    # D: stock label "name(code)"
    # v3.29.4: 移除 v3.27.4 L4 的 ▲X.XX% 標籤 (user 5/22 review 不希望直接看漲幅)
    # 漲停驗證改為間接靠 buy_amt 趨勢 / 額外 audit 工具
    c_d = ws.cell(row=row, column=4)
    c_d.value = f"{name}({code})"
    c_d.font = _font_normal()
    c_d.alignment = _align_center()

    # E-I integer columns
    for ci, val in [(5, buy_lot), (6, sell_lot), (7, buy_amt_w), (8, sell_amt_w), (9, net_w)]:
        c = ws.cell(row=row, column=ci)
        c.value = val
        c.font = _font_normal()
        c.alignment = _align_center()
        c.number_format = NUMBER_FMT_INT

    # J/K price columns
    for ci, val in [(10, buy_avg), (11, sell_avg)]:
        c = ws.cell(row=row, column=ci)
        c.value = val if val else 0
        c.font = _font_normal()
        c.alignment = _align_center()
        c.number_format = NUMBER_FMT_PRICE

    # L: P&L formula, red on negative
    c_l = ws.cell(row=row, column=12)
    c_l.value = f"=F{row}*(K{row}-J{row})"
    c_l.alignment = _align_center()
    c_l.number_format = NUMBER_FMT_PNL
    pnl_value = sell_lot * (sell_avg - buy_avg)
    if pnl_value < 0:
        c_l.font = _font_pnl_neg()
    else:
        c_l.font = _font_normal()


def _write_blank_data_row(ws: "Worksheet", row: int):
    """For padding rows when branch has fewer than 10 stocks. Apply formatting only."""
    for ci in range(4, 13):  # D-L
        c = ws.cell(row=row, column=ci)
        c.font = _font_normal()
        c.alignment = _align_center()
        if ci in (5, 6, 7, 8, 9):
            c.number_format = NUMBER_FMT_INT
        elif ci in (10, 11):
            c.number_format = NUMBER_FMT_PRICE
        elif ci == 12:
            c.number_format = NUMBER_FMT_PNL


def _write_empty_branch_notice_row(ws: "Worksheet", row: int, sniper_mode: bool):
    """v3.29.2: 該分點有 TWSE 資料但 filter 後 *完全* 空白 (0 stocks) → 在 D 欄寫提示行.

    sniper_mode=True:  '⚪ 此分點今日未搶漲停'
    sniper_mode=False: '⚪ 此分點今日無淨買超個股'
    """
    notice = '⚪ 此分點今日未搶漲停' if sniper_mode else '⚪ 此分點今日無淨買超個股'
    _write_notice_row(ws, row, notice)


def _write_partial_branch_notice_row(ws: "Worksheet", row: int, n_stocks: int, sniper_mode: bool):
    """v3.29.4: 該分點 partial fill (1-9 stocks 入選) → 在第 N+1 列寫提示告訴老闆「就這樣」.

    用戶 5/22 反映「凱基-松山 9217 顯示 4 stocks 後 6 row 空白看起來像 bug」.
    這個提示行區分「sniper 沒搶更多漲停」vs「我們漏抓」.

    sniper_mode=True:  '⚪ 今日漲停僅 N 檔'
    sniper_mode=False: '⚪ 今日淨買僅 N 檔'
    """
    if sniper_mode:
        notice = f'⚪ 今日漲停僅 {n_stocks} 檔'
    else:
        notice = f'⚪ 今日淨買僅 {n_stocks} 檔'
    _write_notice_row(ws, row, notice)


def _write_notice_row(ws: "Worksheet", row: int, notice: str):
    """共用 helper: 在 D 欄寫灰色斜體提示, E-L 維持空白格式 (跟 _write_blank_data_row 同)."""
    c_d = ws.cell(row=row, column=4)
    c_d.value = notice
    c_d.font = Font(name=FONT_NAME, size=FONT_SIZE, bold=False, italic=True, color="FF808080")
    c_d.alignment = _align_center()
    # 其他欄 (E-L) 維持空白格式
    for ci in range(5, 13):
        c = ws.cell(row=row, column=ci)
        c.font = _font_normal()
        c.alignment = _align_center()
        if ci in (5, 6, 7, 8, 9):
            c.number_format = NUMBER_FMT_INT
        elif ci in (10, 11):
            c.number_format = NUMBER_FMT_PRICE
        elif ci == 12:
            c.number_format = NUMBER_FMT_PNL


# ============================================================
#  Build single-day sheet
# ============================================================

def build_day_sheet(ws: "Worksheet", branches_data: List[Dict], trade_date: str):
    """
    Build one sheet matching manual template.

    Args:
      ws: openpyxl Worksheet (will be populated, sheet title set externally)
      branches_data: list of branch dicts from crawler (each has code, name, buys, sells)
      trade_date: YYYYMMDD string (used only for fallback display)

    Returns:
      total_rows: number of rows written (1-indexed)
    """
    # Index branches by code for fast lookup
    by_code: Dict[str, Dict] = {}
    for b in branches_data:
        c = b.get("code")
        if c:
            by_code[c] = b

    # Apply column widths
    for col, width in COL_WIDTHS.items():
        ws.column_dimensions[col].width = width

    row = 1
    sniper_count = 0
    sniper_with_data = 0
    for master in MASTER_MAPPING:
        master_name = master["name"]
        header_label = master["header_label"]
        branches = master["branches"]
        if not branches:
            continue

        sniper_mode = _is_sniper_master(master_name)
        if sniper_mode:
            sniper_count += 1
            master_has_limit_up = False

        # v3.31.1: 記錄 master block 的 header rows 跟 data rows, 結束後套色
        block_header_rows: List[int] = []
        block_data_rows: List[int] = []

        # Full master header row (A="高手" label)
        _write_header_row(ws, row, header_label, include_master_label=True)
        block_header_rows.append(row)
        row += 1

        master_data_start = row  # first data row of this master block

        for bi, (branch_code, branch_canonical_name) in enumerate(branches):
            if bi > 0:
                # Sub-header before subsequent branches under same master
                _write_header_row(ws, row, header_label, include_master_label=False)
                block_header_rows.append(row)
                row += 1

            # v3.29.5: 該分點是否有 override row 數 (e.g. 8563→20, 其他→10)
            branch_size = _branch_stocks_size(branch_code)

            # Lookup live branch data
            bdata = by_code.get(branch_code, {})
            stocks = _top_stocks_for_branch(bdata, sniper_mode=sniper_mode, n_top=branch_size)
            if sniper_mode and stocks:
                master_has_limit_up = True

            # v3.29.2/v3.29.4: 判斷該分點空白狀態
            has_branch_data = bool(bdata and (bdata.get('buys') or bdata.get('sells')))
            n_stocks = len(stocks)

            branch_first_row = row
            branch_last_row = row + branch_size - 1

            # Write branch_size rows (data + notice + blank padding)
            for ri in range(branch_size):
                r = branch_first_row + ri
                block_data_rows.append(r)   # v3.31.1: 累積 data rows 給套色用
                if ri < n_stocks:
                    _write_stock_row(ws, r, stocks[ri], sniper_mode=sniper_mode)
                elif ri == n_stocks and has_branch_data:
                    # 第一個空白 row 加 by-design 提示
                    if n_stocks == 0:
                        _write_empty_branch_notice_row(ws, r, sniper_mode=sniper_mode)
                    else:
                        _write_partial_branch_notice_row(ws, r, n_stocks, sniper_mode=sniper_mode)
                else:
                    _write_blank_data_row(ws, r)

            # B column: branch name (merged across 10 rows)
            cb = ws.cell(row=branch_first_row, column=2)
            cb.value = branch_canonical_name
            cb.font = _font_bold()
            cb.alignment = _align_center()
            ws.merge_cells(
                start_row=branch_first_row, start_column=2,
                end_row=branch_last_row, end_column=2,
            )
            # C column: branch code (merged across 10 rows)
            cc = ws.cell(row=branch_first_row, column=3)
            cc.value = branch_code
            cc.font = _font_bold()
            cc.alignment = _align_center()
            ws.merge_cells(
                start_row=branch_first_row, start_column=3,
                end_row=branch_last_row, end_column=3,
            )

            row = branch_last_row + 1  # advance to next branch

        # A column: master name (merged from first data row to last data row)
        master_data_end = row - 1
        ws.merge_cells(
            start_row=master_data_start, start_column=1,
            end_row=master_data_end, end_column=1,
        )
        ca = ws.cell(row=master_data_start, column=1)
        ca.value = master_name
        ca.font = _font_bold()
        ca.alignment = _align_center()

        if sniper_mode and master_has_limit_up:
            sniper_with_data += 1

        # v3.31.1: 套色 master block (依 master_name 取色, 不在表內用 default)
        block_colors = MASTER_BLOCK_COLORS.get(master_name, DEFAULT_MASTER_COLOR)
        _apply_master_block_color(
            ws,
            header_rows=block_header_rows,
            data_rows=block_data_rows,
            master_anchor_row=master_data_start,
            colors=block_colors,
        )

    # Apply uniform row height
    for r in range(1, row):
        ws.row_dimensions[r].height = ROW_HEIGHT

    if sniper_count:
        print(f"  [Excel v3.26] sniper-mode masters: {sniper_with_data}/{sniper_count} "
              f"have limit-up buys today (others get blank rows)")

    return row - 1


# ============================================================
#  v3.31.0: 月檔 (一個月一份, chip_radar_YYYY-MM.xlsx)
# ============================================================

# ════════════════════════════════════════════════════════════════════
# v3.62.0 (Sprint 25 E1-E5): Enrichment sheet builders
# ════════════════════════════════════════════════════════════════════

def _read_json_safely(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        import json
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _summary_font_header() -> "Font":
    return Font(name='Noto Sans TC', size=12, bold=True, color='FFFFFFFF')


def _summary_fill(color: str) -> "PatternFill":
    return PatternFill('solid', fgColor=color)


def build_summary_sheet(ws: "Worksheet", branches_data: List[Dict], trade_date: str,
                          data_dir: Optional[Path] = None):
    """E1: 今日執行摘要. Crawler 完成後寫,一頁秒看重點."""
    data_dir = data_dir or Path('data')
    title_fill = _summary_fill('FF1F2A48')
    title_font = _summary_font_header()
    section_fill = _summary_fill('FFD4AF37')
    section_font = Font(name='Noto Sans TC', size=11, bold=True, color='FF000000')
    val_font = Font(name='Noto Sans TC', size=14, bold=True)
    label_font = Font(name='Noto Sans TC', size=10, color='FF666666')

    for col, w in [('A', 4), ('B', 22), ('C', 16), ('D', 22), ('E', 16),
                    ('F', 22), ('G', 16), ('H', 22), ('I', 16)]:
        ws.column_dimensions[col].width = w

    # ── Title row ──
    ws.merge_cells('B2:I2')
    c = ws['B2']
    c.value = f"📋 Chip Radar 今日摘要 — {trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:]}"
    c.font = title_font
    c.fill = title_fill
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 28

    # ── Section 1: 規模統計 (row 4-5) ──
    ws.merge_cells('B4:I4')
    s1 = ws['B4']; s1.value = "▍ 規模統計"; s1.font = section_font; s1.fill = section_fill
    s1.alignment = Alignment(horizontal='left', vertical='center', indent=1)

    total_buy = sum((s.get('buy_amt') or 0) for b in branches_data for s in (b.get('buys') or []))
    total_master_active = len({b.get('master') for b in branches_data
                                if (b.get('buys') or []) and b.get('master')})
    distinct_stocks = len({s.get('code') for b in branches_data
                            for s in (b.get('buys') or []) if s.get('code')})
    limit_up_buys = sum(1 for b in branches_data for s in (b.get('buys') or [])
                         if s.get('is_limit_up'))

    # total_buy 單位仟元 → 萬元 ÷ 10, → 億元 ÷ 100000
    stats = [
        ('B', '活躍 Master', total_master_active, '位'),
        ('D', '個股涉及', distinct_stocks, '檔'),
        ('F', '總買進金額', f"{total_buy/100000:.2f}", '億元'),
        ('H', '漲停買進', limit_up_buys, '筆'),
    ]
    for col_l, label, val, unit in stats:
        col_v = chr(ord(col_l) + 1)
        ws[f'{col_l}5'] = label
        ws[f'{col_l}5'].font = label_font
        ws[f'{col_l}5'].alignment = Alignment(horizontal='right', vertical='center')
        ws[f'{col_v}5'] = f"{val} {unit}"
        ws[f'{col_v}5'].font = val_font
        ws[f'{col_v}5'].alignment = Alignment(horizontal='left', vertical='center')

    # ── Section 2: Top 高手 + Top 個股 (row 7-15) ──
    ws.merge_cells('B7:E7')
    s2 = ws['B7']; s2.value = "▍ Top 5 高手(按今日總買金額)"; s2.font = section_font; s2.fill = section_fill
    s2.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.merge_cells('F7:I7')
    s3 = ws['F7']; s3.value = "▍ Top 5 熱門個股(按今日淨買金額)"; s3.font = section_font; s3.fill = section_fill
    s3.alignment = Alignment(horizontal='left', vertical='center', indent=1)

    # Top masters
    master_amt = {}
    for b in branches_data:
        m = b.get('master')
        if not m: continue
        amt = sum((s.get('buy_amt') or 0) for s in (b.get('buys') or []))
        master_amt[m] = master_amt.get(m, 0) + amt
    top_masters = sorted(master_amt.items(), key=lambda x: -x[1])[:5]

    hdr_row = 8
    for col_letter, txt in [('B', '#'), ('C', 'Master'), ('D', '買進(萬元)'), ('E', '佔比%')]:
        ws[f'{col_letter}{hdr_row}'] = txt
        ws[f'{col_letter}{hdr_row}'].font = Font(name='Noto Sans TC', size=10, bold=True)
        ws[f'{col_letter}{hdr_row}'].fill = _summary_fill('FFF0F0F0')
    total_all = sum(master_amt.values()) or 1
    for i, (m, amt) in enumerate(top_masters):
        r = hdr_row + 1 + i
        ws[f'B{r}'] = i + 1
        ws[f'C{r}'] = m
        ws[f'D{r}'] = round(amt / 10, 0)  # 仟 → 萬
        ws[f'E{r}'] = f"{amt/total_all*100:.1f}%"
        ws[f'C{r}'].font = Font(name='Noto Sans TC', size=11, bold=True)

    # Top stocks
    stock_net = {}
    stock_name = {}
    for b in branches_data:
        for s in (b.get('buys') or []):
            c = s.get('code')
            if not c: continue
            stock_net[c] = stock_net.get(c, 0) + (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
            stock_name[c] = s.get('name', '')
    top_stocks = sorted(stock_net.items(), key=lambda x: -x[1])[:5]

    for col_letter, txt in [('F', '#'), ('G', '個股'), ('H', '代號'), ('I', '淨買(萬元)')]:
        ws[f'{col_letter}{hdr_row}'] = txt
        ws[f'{col_letter}{hdr_row}'].font = Font(name='Noto Sans TC', size=10, bold=True)
        ws[f'{col_letter}{hdr_row}'].fill = _summary_fill('FFF0F0F0')
    for i, (c, net) in enumerate(top_stocks):
        r = hdr_row + 1 + i
        ws[f'F{r}'] = i + 1
        ws[f'G{r}'] = stock_name.get(c, '')
        ws[f'H{r}'] = c
        ws[f'I{r}'] = round(net / 10, 0)

    # ── Section 3: 籌碼溫度 (signal_engine) ──
    daily_signal = _read_json_safely(data_dir / 'daily_signal.json')
    if daily_signal:
        ws.merge_cells('B16:I16')
        s4 = ws['B16']; s4.value = "▍ 籌碼溫度 + 信號"; s4.font = section_font; s4.fill = section_fill
        s4.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws['B17'] = '溫度等級'
        ws['C17'] = daily_signal.get('temperature_level', '—')
        ws['C17'].font = val_font
        ws['D17'] = '溫度分數'
        ws['E17'] = daily_signal.get('temperature_score', '—')
        ws['F17'] = '主信號'
        ws['G17'] = (daily_signal.get('top_signals') or [{}])[0].get('name', '—') if daily_signal.get('top_signals') else '—'
        for col_l in ['B17', 'D17', 'F17']:
            ws[col_l].font = label_font
            ws[col_l].alignment = Alignment(horizontal='right', vertical='center')


def build_alerts_sheet(ws: "Worksheet", branches_data: List[Dict], trade_date: str,
                        data_dir: Optional[Path] = None):
    """E2: 紅綠燈異常警報. 從 daily_trading_signals.json + branches 內 red_flags."""
    data_dir = data_dir or Path('data')
    title_font = _summary_font_header()
    title_fill = _summary_fill('FF7C2D12')   # 暗紅
    header_font = Font(name='Noto Sans TC', size=11, bold=True)
    header_fill = _summary_fill('FFFEE2E2')

    for col, w in [('A', 4), ('B', 14), ('C', 22), ('D', 14), ('E', 50), ('F', 14)]:
        ws.column_dimensions[col].width = w

    ws.merge_cells('B2:F2')
    c = ws['B2']
    c.value = f"🚨 異常警報 — {trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:]}"
    c.font = title_font; c.fill = title_fill
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 28

    # Header
    headers = ['類型', 'Master / 個股', '嚴重度', '說明', '金額(萬)']
    for i, h in enumerate(headers):
        cell = ws.cell(4, 2 + i, h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # 抓 alerts data
    signals = _read_json_safely(data_dir / 'daily_trading_signals.json')
    row = 5
    if signals:
        for sig in (signals.get('anomalies') or [])[:20]:
            ws.cell(row, 2, '異常')
            ws.cell(row, 3, sig.get('master', '—'))
            ws.cell(row, 4, sig.get('severity', 'medium'))
            ws.cell(row, 5, sig.get('description', sig.get('reason', '—')))
            ws.cell(row, 6, sig.get('amount_wan', '—'))
            row += 1
        for sig in (signals.get('consensus') or [])[:20]:
            ws.cell(row, 2, '共識')
            ws.cell(row, 3, sig.get('stock_name', sig.get('code', '—')))
            ws.cell(row, 4, sig.get('severity', 'medium'))
            ws.cell(row, 5, sig.get('description', f"{sig.get('master_count', '?')} 位高手同買"))
            ws.cell(row, 6, sig.get('total_buy_wan', '—'))
            row += 1
        for sig in (signals.get('accumulation') or [])[:20]:
            ws.cell(row, 2, '連續加碼')
            ws.cell(row, 3, f"{sig.get('master', '?')} → {sig.get('stock_name', '?')}")
            ws.cell(row, 4, sig.get('severity', 'medium'))
            ws.cell(row, 5, sig.get('description',
                f"連續 {sig.get('days', '?')} 天加碼"))
            ws.cell(row, 6, sig.get('cum_buy_wan', '—'))
            row += 1
    if row == 5:
        ws.cell(5, 2, '✅')
        ws.cell(5, 3, '今日無異常警報')
        ws.merge_cells('C5:F5')


def build_accumulation_sheet(ws: "Worksheet", trade_date: str,
                               data_dir: Optional[Path] = None):
    """E3: 跨日連續囤貨 (master_profile.consecutive_accumulation)."""
    data_dir = data_dir or Path('data')
    title_font = _summary_font_header()
    title_fill = _summary_fill('FF1B5E20')   # 深綠
    header_font = Font(name='Noto Sans TC', size=11, bold=True)
    header_fill = _summary_fill('FFE8F5E9')

    for col, w in [('A', 4), ('B', 16), ('C', 12), ('D', 20), ('E', 12),
                    ('F', 14), ('G', 14), ('H', 10)]:
        ws.column_dimensions[col].width = w

    ws.merge_cells('B2:H2')
    c = ws['B2']
    c.value = f"📦 跨日連續囤貨 — {trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:]}"
    c.font = title_font; c.fill = title_fill
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 28

    headers = ['Master', '股票代號', '股票名稱', '連續天數', '截至日期', '累計買金額(萬)', '仍 active']
    for i, h in enumerate(headers):
        cell = ws.cell(4, 2 + i, h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    profiles = _read_json_safely(data_dir / 'master_profiles.json')
    row = 5
    if profiles:
        master_profiles = profiles.get('master_profiles') or {}
        all_acc = []
        for master, p in master_profiles.items():
            acc = (p.get('op') or {}).get('consecutive_accumulation') or {}
            for s in (acc.get('accumulation_stocks') or []):
                all_acc.append({'master': master, **s})
        all_acc.sort(key=lambda x: -x.get('max_consecutive_days', 0))
        for s in all_acc[:50]:
            ws.cell(row, 2, s['master'])
            ws.cell(row, 3, s.get('stock_code', '—'))
            ws.cell(row, 4, s.get('stock_name', '—'))
            ws.cell(row, 5, s.get('max_consecutive_days', 0))
            ws.cell(row, 6, s.get('latest_date', '—'))
            ws.cell(row, 7, round((s.get('total_buy_amt') or 0) / 10, 0))
            ws.cell(row, 8, '✓' if s.get('is_active') else '')
            row += 1
    if row == 5:
        ws.cell(5, 2, '尚無連續囤貨紀錄')
        ws.merge_cells('B5:H5')


def build_risk_sheet(ws: "Worksheet", trade_date: str, data_dir: Optional[Path] = None):
    """E4: 風險警示 — 注意股 / 借券 Top / 除權息預告."""
    data_dir = data_dir or Path('data')
    title_font = _summary_font_header()
    title_fill = _summary_fill('FF7C2D12')
    section_font = Font(name='Noto Sans TC', size=11, bold=True, color='FF000000')
    section_fill = _summary_fill('FFFCD34D')
    header_font = Font(name='Noto Sans TC', size=10, bold=True)
    header_fill = _summary_fill('FFF5F5F5')

    for col, w in [('A', 4), ('B', 12), ('C', 22), ('D', 14), ('E', 14), ('F', 14)]:
        ws.column_dimensions[col].width = w

    ws.merge_cells('B2:F2')
    c = ws['B2']
    c.value = f"⚠️ 風險警示 — {trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:]}"
    c.font = title_font; c.fill = title_fill
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 28

    row = 4
    # 注意股
    attention = _read_json_safely(data_dir / 'attention_map.json')
    ws.merge_cells(f'B{row}:F{row}')
    s = ws.cell(row, 2, f"▍ 注意股 ({(attention or {}).get('count', 0)} 檔)")
    s.font = section_font; s.fill = section_fill
    s.alignment = Alignment(horizontal='left', indent=1)
    row += 1
    for h_col, h in [('B', '代號'), ('C', '名稱'), ('D', '累計次數'), ('E', '收盤價'), ('F', '本益比')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1
    for code, info in list((attention or {}).get('by_code', {}).items())[:20]:
        ws.cell(row, 2, code); ws.cell(row, 3, info.get('name', '—'))
        ws.cell(row, 4, info.get('cumulative_count', 0))
        ws.cell(row, 5, info.get('close', '—'))
        ws.cell(row, 6, info.get('pe', '—'))
        row += 1
    if not (attention or {}).get('by_code'):
        ws.cell(row, 2, '今日無注意股'); ws.merge_cells(f'B{row}:F{row}'); row += 1

    # 借券 Top
    row += 1
    short_lending = _read_json_safely(data_dir / 'short_lending.json')
    ws.merge_cells(f'B{row}:F{row}')
    s = ws.cell(row, 2, "▍ 借券賣出 Top 15 (機構級反向力量)")
    s.font = section_font; s.fill = section_fill
    s.alignment = Alignment(horizontal='left', indent=1)
    row += 1
    for h_col, h in [('B', '代號'), ('C', '名稱'), ('D', '借券張數'), ('E', '融券張數'), ('F', 'ratio')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1
    for item in ((short_lending or {}).get('top_borrow_sell') or [])[:15]:
        ws.cell(row, 2, item.get('code', '—'))
        ws.cell(row, 3, item.get('name', '—'))
        ws.cell(row, 4, item.get('borrow_sell_lot', 0))
        ws.cell(row, 5, item.get('short_sell_lot', 0))
        ws.cell(row, 6, item.get('borrow_vs_short_ratio', '—'))
        row += 1

    # 除權息預告
    row += 1
    dividend = _read_json_safely(data_dir / 'dividend_calendar.json')
    ws.merge_cells(f'B{row}:F{row}')
    upcoming = (dividend or {}).get('upcoming_30d') or []
    s = ws.cell(row, 2, f"▍ 未來 30 天除權息 ({len(upcoming)} 檔)")
    s.font = section_font; s.fill = section_fill
    s.alignment = Alignment(horizontal='left', indent=1)
    row += 1
    for h_col, h in [('B', '除權息日'), ('C', '代號'), ('D', '名稱'), ('E', '類型'), ('F', '現金股利')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1
    for item in upcoming[:20]:
        ws.cell(row, 2, item.get('ex_date', '—'))
        ws.cell(row, 3, item.get('code', '—'))
        ws.cell(row, 4, item.get('name', '—'))
        ws.cell(row, 5, item.get('type', '—'))
        ws.cell(row, 6, item.get('cash_dividend', '—'))
        row += 1


def apply_pnl_color_scale(ws: "Worksheet", first_row: int, last_row: int, col_letter: str = 'L'):
    """E5: 損益欄 L 加紅綠色階 conditional formatting."""
    if last_row < first_row:
        return
    rule = ColorScaleRule(
        start_type='num', start_value=-100, start_color='FFE57373',
        mid_type='num', mid_value=0, mid_color='FFFFFFFF',
        end_type='num', end_value=100, end_color='FF81C784',
    )
    ws.conditional_formatting.add(f'{col_letter}{first_row}:{col_letter}{last_row}', rule)


def _update_monthly_workbook(monthly_path: Path, branches_data: List[Dict],
                              trade_date: str):
    """v3.31.0: 開啟既有月檔 (若有) 或新建, add/update 該日 sheet, save back.
    sheet 名 = trade_date (YYYYMMDD), 同日重跑會覆寫該 sheet, sheets 按日期 desc 排序."""
    if monthly_path.exists():
        try:
            wb = load_workbook(str(monthly_path))
        except Exception as e:
            print(f"  [Excel] 月檔 unreadable, recreating: {e}")
            wb = Workbook()
            if 'Sheet' in wb.sheetnames:
                wb.remove(wb['Sheet'])
    else:
        wb = Workbook()
        if 'Sheet' in wb.sheetnames:
            wb.remove(wb['Sheet'])

    # 若該日 sheet 已存在 → 移除 (重跑同日 → 覆寫)
    if trade_date in wb.sheetnames:
        wb.remove(wb[trade_date])

    # 新建該日 sheet (build_day_sheet 在 ws 內 render 老闆版)
    ws = wb.create_sheet(title=trade_date)
    total_rows = build_day_sheet(ws, branches_data, trade_date)
    # v3.62.0 (E5): L 欄損益色階
    try:
        apply_pnl_color_scale(ws, 2, total_rows or 50, 'L')
    except Exception as _cse:
        print(f"  [Excel] E5 color scale 失敗: {type(_cse).__name__}: {_cse}")

    # v3.62.0 (E1-E4): rebuild 4 enrichment sheets (覆蓋舊版本)
    data_dir = monthly_path.parent.parent if monthly_path.parent.name == 'reports' else Path('data')
    for sn, builder in [
        (SUMMARY_SHEET_NAME, lambda w: build_summary_sheet(w, branches_data, trade_date, data_dir)),
        (ALERTS_SHEET_NAME, lambda w: build_alerts_sheet(w, branches_data, trade_date, data_dir)),
        (ACCUMULATION_SHEET_NAME, lambda w: build_accumulation_sheet(w, trade_date, data_dir)),
        (RISK_SHEET_NAME, lambda w: build_risk_sheet(w, trade_date, data_dir)),
    ]:
        if sn in wb.sheetnames:
            wb.remove(wb[sn])
        new_ws = wb.create_sheet(title=sn)
        try:
            builder(new_ws)
        except Exception as _be:
            print(f"  [Excel] enrichment sheet {sn} build 失敗: {type(_be).__name__}: {_be}")

    # 排序: enrichment sheets 在前, 日期 sheets 按 desc
    enrichment_in_wb = [s for s in ENRICHMENT_SHEETS if s in wb.sheetnames]
    date_sheets = sorted([s for s in wb.sheetnames if s not in ENRICHMENT_SHEETS], reverse=True)
    wb._sheets = [wb[name] for name in enrichment_in_wb + date_sheets]

    wb.save(str(monthly_path))


# ============================================================
#  Multi-sheet latest.xlsx (legacy v3.30.x, retained for backfill/reference)
# ============================================================

def _update_latest_multi_sheet(latest_path: Path, branches_data: List[Dict],
                                trade_date: str, max_sheets: int = 30):
    """
    Update latest.xlsx to include current trade_date as a sheet.
    Keep only the most recent `max_sheets` sheets (by sheet name desc).
    Newest sheet is set as the active one.
    """
    if latest_path.exists():
        try:
            wb = load_workbook(str(latest_path))
        except Exception as e:
            print(f"  [Excel] latest.xlsx unreadable, recreating: {e}")
            wb = Workbook()
            # remove default sheet
            for s in list(wb.sheetnames):
                del wb[s]
    else:
        wb = Workbook()
        for s in list(wb.sheetnames):
            del wb[s]

    # Remove existing sheet with same name (will rebuild)
    if trade_date in wb.sheetnames:
        del wb[trade_date]

    # Create new sheet for trade_date
    ws = wb.create_sheet(title=trade_date)
    build_day_sheet(ws, branches_data, trade_date)

    # Sort sheets by name desc; trim to max_sheets
    sheet_names_sorted = sorted(wb.sheetnames, reverse=True)
    keep = sheet_names_sorted[:max_sheets]
    drop = sheet_names_sorted[max_sheets:]
    for n in drop:
        del wb[n]

    # Reorder so newest first
    wb._sheets = [wb[n] for n in keep]
    wb.active = 0  # show newest sheet on open

    wb.save(str(latest_path))


# ============================================================
#  Main entry point
# ============================================================

def generate_excel_report(branches_data: List[Dict], trade_date: str,
                           output_dir: str = "data/reports") -> Optional[str]:
    """
    Generate Excel daily report (mimics manual 「分點觀察」 layout).

    Args:
      branches_data: list of branch dicts from crawler (with buys/sells)
      trade_date: trading day in YYYYMMDD format (e.g. '20260508')
      output_dir: output directory (default 'data/reports')

    Returns:
      file path of the daily snapshot on success, None on failure.
    """
    if not OPENPYXL_AVAILABLE:
        print("  [Excel] openpyxl not installed, skipping")
        return None

    if not branches_data:
        print("  [Excel] no branch data, skipping")
        return None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if len(trade_date) == 8 and trade_date.isdigit():
        readable_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    else:
        readable_date = trade_date

    # v3.31.0: 月檔模式 ─ 一個月一份 chip_radar_YYYY-MM.xlsx (取代單日檔)
    #   latest.xlsx 永遠 = 當月月檔的 copy
    #   crawler 主流程每次 daily-full 跑完: 開啟月檔 → add/update 該日 sheet → save → copy latest
    year_month = readable_date[:7]   # "2026-06"
    monthly_path = out_dir / f"chip_radar_{year_month}.xlsx"
    latest_path = out_dir / "latest.xlsx"

    valid_count = sum(1 for b in branches_data if b.get("buys") or b.get("sells"))
    print(f"  [Excel] generating v3.31 monthly ({valid_count} branches, date {readable_date}, "
          f"month {year_month})")

    try:
        # 1. 月檔: 開啟既有 (若有) 或新建, add/update 該日 sheet
        _update_monthly_workbook(monthly_path, branches_data, trade_date)

        # 2. latest.xlsx = 當月月檔的 copy (前端下載按鈕指向不變)
        import shutil
        shutil.copy2(str(monthly_path), str(latest_path))

        # 3. Update README index
        _update_reports_readme(out_dir)

        size_kb = monthly_path.stat().st_size / 1024
        latest_size_kb = latest_path.stat().st_size / 1024
        sheet_count = len(load_workbook(str(monthly_path), read_only=True).sheetnames)
        print(f"  [Excel] OK")
        print(f"     {monthly_path.name} ({size_kb:.1f} KB, {sheet_count} daily sheets)")
        print(f"     latest.xlsx ({latest_size_kb:.1f} KB, = 當月月檔)")
        return str(monthly_path)

    except Exception as e:
        print(f"  [Excel] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def _update_reports_readme(reports_dir: Path):
    """Update reports/README.md with auto-generated file index."""
    try:
        excel_files = sorted(
            reports_dir.glob("chip_radar_*.xlsx"),
            key=lambda p: p.name,
            reverse=True,
        )

        readme = reports_dir / "README.md"
        master_count = len(MASTER_MAPPING)
        branch_count = sum(len(m["branches"]) for m in MASTER_MAPPING)

        lines = [
            "# Chip Radar 老闆版 Excel 日報",
            "",
            "由 `excel_report.py` v3.26 自動生成,模仿手動版「分點觀察」格式。",
            "",
            "## 最新檔案",
            "",
            "- [**latest.xlsx**](./latest.xlsx) — 多 sheet, 最近 30 個交易日",
            "  - 每個 sheet 命名 = `YYYYMMDD`,開啟時顯示最新一日",
            "",
            "## 結構",
            "",
            f"- {master_count} 位高手 / {branch_count} 個分點 slot (含跨高手共用分點)",
            "- 每分點固定 10 列 (不足以空白填補)",
            "- 12 欄: 高手 / 分點 / 代號 / 標的 / 買進(張) / 賣出(張) / "
            "買進(萬元) / 賣出(萬元) / 淨買差(萬元) / 買均 / 賣均 / 損益(萬)",
            "- L 欄公式: `=F*(K-J)` (賣出張數 × (賣均-買均)),負值紅字",
            "",
            "## v3.30.5 風格分流規則 (僅蔣承翰用漲停法)",
            "",
            "Excel 抓取法依 master 切換:",
            "",
            "| Master | Top N 資料源 |",
            "|---|---|",
            "| ⭐ 蔣承翰 (隔日沖) | **今日漲停股 by 買進金額** (漲跌幅 ≥ 9.5%) |",
            "| 其餘所有 master | 全部個股 by 買進金額 (淨買超 Top N) |",
            "",
            "蔣承翰今天若沒搶任何漲停股 → 整列空白 (不 fallback,維持風格純度)。",
            "(v3.26~v3.30.4 原為所有隔日沖/當沖 master 都用漲停法;v3.30.5 依使用者要求縮為僅蔣承翰)",
            "",
            "## 每日歷史",
            "",
        ]

        if excel_files:
            lines.append(f"近 {min(len(excel_files), 30)} 個交易日 (共 {len(excel_files)} 個檔案):")
            lines.append("")
            lines.append("| 日期 | 檔案 | 大小 |")
            lines.append("|------|------|------|")
            for p in excel_files[:30]:
                size_kb = p.stat().st_size / 1024
                # 從檔名抽日期
                stem = p.stem  # chip_radar_2026-05-08
                date_part = stem.replace("chip_radar_", "")
                lines.append(f"| {date_part} | [{p.name}](./{p.name}) | {size_kb:.1f} KB |")
            if len(excel_files) > 30:
                lines.append("")
                lines.append(f"…另有 {len(excel_files) - 30} 個更舊檔案")

        lines.extend([
            "",
            "---",
            "",
            f"*Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])

        readme.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        print(f"  [Excel] README update failed: {e}")
