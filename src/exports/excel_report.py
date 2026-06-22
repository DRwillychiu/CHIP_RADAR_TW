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

# v3.62.0 (Sprint 25 → v3.62.1): 用戶決定把 E1-E4 4 個 section 全合 1 sheet
# 月檔結構: [📋 今日 Dashboard (含全 4 section)] + 日期 sheet desc
DASHBOARD_SHEET_NAME = "📋 今日 Dashboard"
ENRICHMENT_SHEETS = [DASHBOARD_SHEET_NAME]
# 舊 sheet 名 (給 cleanup 移除舊月檔殘留)
LEGACY_ENRICHMENT_NAMES = ["📋 今日摘要", "🚨 異常警報", "📦 連續囤貨", "⚠️ 風險警示"]

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

    # 先全 block 套 body (淡), L 欄(12)留白給色階 conditional formatting
    for r in data_rows:
        for c in range(1, cols + 1):
            if c == 12:
                continue
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


# v3.63.2: Dashboard 追蹤範圍 — 嚴格鎖定 MASTER_MAPPING 內的大戶
# 使用者要求: 沒放在 Excel 每日籌碼分點觀察清單 (= MASTER_MAPPING) 中的大戶,
# 絕對禁止出現在 Dashboard.
TRACKED_MASTERS: set = {m["name"] for m in MASTER_MAPPING}


def _is_tracked_master(name: Optional[str]) -> bool:
    """Dashboard filter: 該 master 是否在每日 Excel 追蹤清單內."""
    return bool(name) and name in TRACKED_MASTERS


def _filter_tracked_branches(branches_data: List[Dict]) -> List[Dict]:
    """只保留 master 在追蹤清單內的 branch."""
    return [b for b in branches_data if _is_tracked_master(b.get('master'))]


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
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=True, color="FF000000")


def _font_pnl_pos() -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=True, color="FFFFFFFF")


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
        c_l.font = _font_pnl_pos()


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

    # v3.63.0 (E6): freeze A 欄 (master name) + B 欄 (分點 name) → 'C2'
    #   滾右仍能看到 master + 分點對應, header 第 1 row 也固定
    ws.freeze_panes = 'C2'
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


def _section_header(ws, row: int, title: str, span_cols: int = 9, color: str = 'FFD4AF37'):
    """共用 section header row."""
    section_font = Font(name='Noto Sans TC', size=12, bold=True, color='FF000000')
    section_fill = _summary_fill(color)
    end_col = chr(ord('B') + span_cols - 1)
    ws.merge_cells(f'B{row}:{end_col}{row}')
    c = ws[f'B{row}']
    c.value = title
    c.font = section_font
    c.fill = section_fill
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[row].height = 22


def _build_section_consensus(ws, branches_data, data_dir, start_row):
    """v3.63.2 ★ Section 0: 今日追蹤大戶共同買超 (置於 Dashboard 最前).

    定義: ≥2 個追蹤清單內「分點」淨買 > 0 同一檔股票即視為共識.
    (同一大戶不同分點也算 — 例如 民哥 同時用 台新-五權西 + 富邦-南屯 買 2330)

    精準度做法: 不讀預算 signals.consensus (含非追蹤大戶), 而是從 branches_data
              (已過濾為追蹤範圍) 獨立計算 net_amt > 0 by branch by stock,
              100% 對齊使用者實際追蹤的分點.

    排序: 涉及大戶數 desc → 同買分點數 desc → 合計淨買 desc.
    v3.63.6 篩選: 涉及大戶數 ≥ 10 (使用者調強訊號 — 13 位追蹤大戶中 ≥77% 共識才入榜).
    取 Top 30 (soft cap).
    """
    MIN_MASTER_COUNT = 10   # v3.63.6: 強共識門檻 — ≥10 位追蹤大戶同買才入榜
    MAX_PICKS = 30          # 軟上限
    TOP_MASTERS_SHOWN = 5   # 大戶清單只顯示前 5 大金額, 其餘以「+N 位」概括
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    sub_font = Font(name='Noto Sans TC', size=11, bold=True)
    hdr_fill = _summary_fill('FFFEE2E2')   # 淡紅 = high attention
    rank_fill_top = _summary_fill('FFFEF3C7')  # 金 = top 3

    row = start_row
    _section_header(ws, row,
                     f"★ 0. 今日強共識買超 (≥{MIN_MASTER_COUNT} 位追蹤大戶共同淨買, 個股 only — 必看)",
                     color='FFDC2626'); row += 1

    # v3.63.9: 註腳說明 ⚠️ 標記意義 (用戶要求)
    note_cell = ws.cell(row, 2,
                         "ⓘ 排序: 合計淨買金額 ↓  |  ⚠️ 名稱前 = 領頭大戶獨佔 ≥50% (1 人獨大, 真共識訊號被稀釋, hover 名稱看詳細%)")
    ws.merge_cells(f'B{row}:N{row}')
    note_cell.font = Font(name='Noto Sans TC', size=10, italic=True, color='FF7C2D12')
    note_cell.fill = _summary_fill('FFFFF7ED')   # 極淡橙底
    note_cell.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[row].height = 18
    row += 1

    # Build code -> {name, branches: [{branch_code, branch_name, master, net_amt}]}
    stock_map: Dict[str, Dict] = {}
    for b in branches_data:
        m = b.get('master')
        if not m:
            continue
        b_code = b.get('code', '')
        b_name = b.get('name', '')
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            code = s.get('code')
            if not code:
                continue
            # v3.63.7: 排除 ETF — code 以 '00' 開頭 (00712 / 00632R / 0050 / 0056 ...)
            # 使用者目標: Section 0 只看「大戶共識買的個股」, 不含 ETF
            # 已驗證 stock_categories.json: 沒有任何 listed/otc/emerging 股票 code 起始 '00'
            if code.startswith('00'):
                continue
            buy_amt = s.get('buy_amt') or 0
            sell_amt = s.get('sell_amt') or 0
            net_amt = buy_amt - sell_amt
            if net_amt <= 0:
                continue   # 必須該分點該股淨買超
            entry = stock_map.setdefault(code, {
                'name': s.get('name', ''),
                'branches': [],   # 每個分點一筆 (允許同 master 多分點)
            })
            if not entry['name'] and s.get('name'):
                entry['name'] = s.get('name')
            entry['branches'].append({
                'branch_code': b_code,
                'branch_name': b_name,
                'master': m,
                'net_amt': net_amt,
            })

    # 過濾: ≥2 個分點 AND ≥MIN_MASTER_COUNT 位大戶 (v3.63.6)
    consensus_list = []
    for code, info in stock_map.items():
        if len(info['branches']) < 2:
            continue
        master_set = {br['master'] for br in info['branches']}
        if len(master_set) < MIN_MASTER_COUNT:
            continue
        total_net = sum(br['net_amt'] for br in info['branches'])
        consensus_list.append({
            'code': code,
            'name': info['name'],
            'branches': info['branches'],
            'branch_count': len(info['branches']),
            'master_count': len(master_set),
            'masters': master_set,
            'total_net_amt': total_net,
        })
    # v3.63.9 (用戶決定): 改主排序為 total_net_amt DESC (資金規模 = 真實共識深度)
    # tie-breaker: master_count DESC → branch_count DESC
    # 已有 master_count >= 10 硬門檻保證廣度, 排序時用金額反映深度.
    # 案例: 群聯 7.4 億 (10 master) 在舊版 rank 9, 新版 rank 2; 彩晶 7591 萬 在舊版 rank 1, 新版 rank 8
    consensus_list.sort(key=lambda x: (-x['total_net_amt'], -x['master_count'],
                                        -x['branch_count']))

    # v3.63.8 Excel-native 13 欄佈局: 一格一值, 金額為 int + 千分位 number_format
    # B=#, C=代號, D=名稱, E=大戶數, F=分點數, G=領頭大戶, H=領頭金額(萬),
    # I=#2 大戶, J=#2 金額, K=#3 大戶, L=#3 金額, M=+更多, N=合計淨買(萬)
    headers = [
        ('B', '#', 5),    ('C', '代號', 9),    ('D', '名稱', 18),
        ('E', '大戶數', 9), ('F', '分點數', 9),
        ('G', '領頭大戶', 14),  ('H', '領頭金額(萬)', 13),
        ('I', '#2 大戶', 14),   ('J', '#2 金額(萬)', 13),
        ('K', '#3 大戶', 14),   ('L', '#3 金額(萬)', 13),
        ('M', '+更多', 8),
        ('N', '合計淨買(萬)', 14),
    ]
    header_row = row
    for col_l, h, w in headers:
        cell = ws[f'{col_l}{row}']
        cell.value = h
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[col_l].width = w
    row += 1

    # ── Data rows ──
    num_fmt = '#,##0'
    muted_font = Font(name='Noto Sans TC', size=10, italic=True, color='FF888888')
    leader_font = Font(name='Noto Sans TC', size=11, bold=True)
    total_font = Font(name='Noto Sans TC', size=11, bold=True)

    start_data = row
    for i, item in enumerate(consensus_list[:MAX_PICKS]):
        c_b = ws.cell(row, 2, i + 1)
        if i < 3:
            c_b.fill = rank_fill_top
            c_b.font = sub_font
        ws.cell(row, 3, item['code'])

        # 排序大戶 by 該大戶在此股總 net_amt desc
        master_total = {}
        for br in item['branches']:
            master_total[br['master']] = master_total.get(br['master'], 0) + br['net_amt']
        masters_sorted = sorted(master_total.items(), key=lambda kv: -kv[1])

        # v3.63.9 用戶決定: 領頭大戶佔合計 ≥50% → 加 ⚠️ 警示 (假共識防呆)
        # 名義 ≥10 大戶共識 但 1 大戶獨大 → 真共識訊號被稀釋
        leader_amt = masters_sorted[0][1] if masters_sorted else 0
        total_net = item['total_net_amt']
        leader_pct = leader_amt / total_net if total_net > 0 else 0
        is_outlier = leader_pct >= 0.5
        display_name = item['name'] or '—'
        if is_outlier:
            display_name = f"⚠️ {display_name}"
        c_name = ws.cell(row, 4, display_name)
        if is_outlier:
            # 領頭佔比高 → 名稱 cell 淡橙底警示
            c_name.fill = _summary_fill('FFFED7AA')   # 淡橙
            c_name.font = Font(name='Noto Sans TC', size=11, bold=True, color='FF7C2D12')
            # v3.63.9: hover comment 顯示詳細%
            try:
                from openpyxl.comments import Comment
                leader_name = masters_sorted[0][0] if masters_sorted else '?'
                comment_text = (
                    f"⚠️ 假共識警示\n"
                    f"領頭大戶「{leader_name}」獨佔比 {leader_pct*100:.1f}%\n"
                    f"  • 領頭金額 {int(leader_amt/10):,} 萬\n"
                    f"  • 合計淨買 {int(total_net/10):,} 萬\n"
                    f"  • 大戶數 {item['master_count']} 位 (名義共識)\n\n"
                    f"判讀: 名義 {item['master_count']} 位大戶共識,\n"
                    f"實質 1 人下注佔 {leader_pct*100:.0f}%,\n"
                    f"剩餘 {item['master_count']-1} 位為陪襯小單,\n"
                    f"真共識訊號被稀釋.")
                c = Comment(comment_text, 'Chip Radar')
                c.width = 280
                c.height = 180
                c_name.comment = c
            except Exception:
                pass

        c_e = ws.cell(row, 5, item['master_count'])
        c_e.font = sub_font
        c_e.alignment = Alignment(horizontal='center')
        c_f = ws.cell(row, 6, item['branch_count'])
        c_f.alignment = Alignment(horizontal='center')

        # 短名稱去括號內容讓欄位緊湊 (例: "張濬安(航海王)" → "張濬安")
        def _short(m):
            return m.split('(')[0].split('/')[0]

        # G/H = 領頭 (Top 1)
        # I/J = #2
        # K/L = #3
        slot_cols = [('G', 'H'), ('I', 'J'), ('K', 'L')]
        for slot_idx, (name_col, amt_col) in enumerate(slot_cols):
            if slot_idx < len(masters_sorted):
                m_name, m_amt = masters_sorted[slot_idx]
                c_name = ws[f'{name_col}{row}']
                c_name.value = _short(m_name)
                c_amt = ws[f'{amt_col}{row}']
                c_amt.value = int(round(m_amt / 10))   # int → 可 sort/sum
                c_amt.number_format = num_fmt
                c_amt.alignment = Alignment(horizontal='right')
                if slot_idx == 0:
                    c_name.font = leader_font
                    c_amt.font = leader_font
            else:
                ws[f'{name_col}{row}'].value = ''
                ws[f'{amt_col}{row}'].value = None

        # M = +更多 (剩餘大戶數, 用 int 而非字串, 0 顯示為空)
        tail = max(0, len(masters_sorted) - 3)
        c_m = ws.cell(row, 13, tail if tail > 0 else None)
        c_m.font = muted_font
        c_m.alignment = Alignment(horizontal='center')

        # N = 合計淨買(萬), 粗體 + 千分位
        c_n = ws.cell(row, 14, int(round(item['total_net_amt'] / 10)))
        c_n.number_format = num_fmt
        c_n.font = total_font
        c_n.alignment = Alignment(horizontal='right')

        row += 1

    if row == start_data:
        ws.cell(row, 2, f'⚪ 今日無 ≥{MIN_MASTER_COUNT} 位追蹤大戶共同淨買的個股')
        ws.merge_cells(f'B{row}:N{row}')
        row += 1
    else:
        # v3.63.8: 把資料區包成 Excel Table → 原生 sort/filter 下拉
        try:
            from openpyxl.worksheet.table import Table, TableStyleInfo
            table_range = f'B{header_row}:N{row - 1}'
            tbl = Table(displayName=f"ConsensusTbl_{header_row}", ref=table_range)
            tbl.tableStyleInfo = TableStyleInfo(
                name="TableStyleLight1", showFirstColumn=False,
                showLastColumn=False, showRowStripes=True, showColumnStripes=False,
            )
            ws.add_table(tbl)
        except Exception:
            pass   # Table 失敗不影響資料正確性
    row += 1   # 空一行
    return row


def _build_section_summary(ws, branches_data, trade_date, data_dir, start_row):
    """Section A: 規模統計 + Top 5 master + Top 5 個股 + 籌碼溫度.
    Returns: next available row."""
    label_font = Font(name='Noto Sans TC', size=10, color='FF666666')
    val_font = Font(name='Noto Sans TC', size=14, bold=True)
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    hdr_fill = _summary_fill('FFF0F0F0')

    row = start_row
    _section_header(ws, row, "▍ A. 規模統計"); row += 1

    total_buy = sum((s.get('buy_amt') or 0) for b in branches_data for s in (b.get('buys') or []))
    total_master_active = len({b.get('master') for b in branches_data
                                if (b.get('buys') or []) and b.get('master')})
    distinct_stocks = len({s.get('code') for b in branches_data
                            for s in (b.get('buys') or []) if s.get('code')})
    limit_up_buys = sum(1 for b in branches_data for s in (b.get('buys') or [])
                         if s.get('is_limit_up'))
    stats = [
        ('B', '活躍 Master', total_master_active, '位'),
        ('D', '個股涉及', distinct_stocks, '檔'),
        ('F', '總買進金額', f"{total_buy/100000:.2f}", '億元'),
        ('H', '漲停買進', limit_up_buys, '筆'),
    ]
    for col_l, label, val, unit in stats:
        col_v = chr(ord(col_l) + 1)
        ws[f'{col_l}{row}'] = label
        ws[f'{col_l}{row}'].font = label_font
        ws[f'{col_l}{row}'].alignment = Alignment(horizontal='right', vertical='center')
        ws[f'{col_v}{row}'] = f"{val} {unit}"
        ws[f'{col_v}{row}'].font = val_font
        ws[f'{col_v}{row}'].alignment = Alignment(horizontal='left', vertical='center')
    row += 2

    # Top master + Top stocks 並排
    ws.merge_cells(f'B{row}:E{row}')
    s2 = ws[f'B{row}']
    s2.value = "▍ B. Top 5 高手(按今日總買金額)"
    s2.font = Font(name='Noto Sans TC', size=11, bold=True)
    s2.fill = _summary_fill('FFE8F5E9')
    s2.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.merge_cells(f'F{row}:I{row}')
    s3 = ws[f'F{row}']
    s3.value = "▍ C. Top 5 熱門個股(按今日淨買金額)"
    s3.font = Font(name='Noto Sans TC', size=11, bold=True)
    s3.fill = _summary_fill('FFE3F2FD')
    s3.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    row += 1

    master_amt = {}
    for b in branches_data:
        m = b.get('master')
        if not m: continue
        amt = sum((s.get('buy_amt') or 0) for s in (b.get('buys') or []))
        master_amt[m] = master_amt.get(m, 0) + amt
    top_masters = sorted(master_amt.items(), key=lambda x: -x[1])[:5]
    stock_net = {}
    stock_name = {}
    for b in branches_data:
        for s in (b.get('buys') or []):
            c = s.get('code')
            if not c: continue
            stock_net[c] = stock_net.get(c, 0) + (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
            stock_name[c] = s.get('name', '')
    top_stocks = sorted(stock_net.items(), key=lambda x: -x[1])[:5]

    # headers (兩組並排)
    for col_letter, txt in [('B', '#'), ('C', 'Master'), ('D', '買進(萬元)'), ('E', '佔比%'),
                              ('F', '#'), ('G', '個股'), ('H', '代號'), ('I', '淨買(萬元)')]:
        ws[f'{col_letter}{row}'] = txt
        ws[f'{col_letter}{row}'].font = hdr_font
        ws[f'{col_letter}{row}'].fill = hdr_fill
    row += 1

    total_all = sum(master_amt.values()) or 1
    for i in range(5):
        m_item = top_masters[i] if i < len(top_masters) else None
        s_item = top_stocks[i] if i < len(top_stocks) else None
        if m_item:
            ws[f'B{row}'] = i + 1
            ws[f'C{row}'] = m_item[0]
            ws[f'C{row}'].font = Font(name='Noto Sans TC', size=11, bold=True)
            ws[f'D{row}'] = round(m_item[1] / 10, 0)
            ws[f'E{row}'] = f"{m_item[1]/total_all*100:.1f}%"
        if s_item:
            ws[f'F{row}'] = i + 1
            ws[f'G{row}'] = stock_name.get(s_item[0], '')
            ws[f'H{row}'] = s_item[0]
            ws[f'I{row}'] = round(s_item[1] / 10, 0)
        row += 1
    row += 1

    # 籌碼溫度
    daily_signal = _read_json_safely(data_dir / 'daily_signal.json')
    if daily_signal:
        _section_header(ws, row, "▍ D. 籌碼溫度 + 信號", color='FFFDE68A'); row += 1
        ws[f'B{row}'] = '溫度等級'
        ws[f'C{row}'] = daily_signal.get('temperature_level', '—')
        ws[f'C{row}'].font = val_font
        ws[f'D{row}'] = '溫度分數'
        ws[f'E{row}'] = daily_signal.get('temperature_score', '—')
        ws[f'F{row}'] = '主信號'
        sigs = daily_signal.get('top_signals') or []
        ws[f'G{row}'] = sigs[0].get('name', '—') if sigs else '—'
        for col_l in [f'B{row}', f'D{row}', f'F{row}']:
            ws[col_l].font = label_font
            ws[col_l].alignment = Alignment(horizontal='right', vertical='center')
        row += 1
    return row


def _build_section_alerts(ws, data_dir, start_row):
    """Section E: 紅綠燈異常警報. Returns next row."""
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    hdr_fill = _summary_fill('FFFEE2E2')

    row = start_row + 1   # 留一行空白
    _section_header(ws, row, "▍ E. 異常警報 (anomaly / consensus / accumulation)",
                     color='FFEF4444'); row += 1
    headers = ['類型', 'Master / 個股', '嚴重度', '說明', '金額(萬)']
    for i, h in enumerate(headers):
        cell = ws.cell(row, 2 + i, h)
        cell.font = hdr_font; cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1

    signals = _read_json_safely(data_dir / 'daily_trading_signals.json')
    start_data = row
    if signals:
        # v3.63.2: 修 4 個資料結構 bug + 追蹤範圍 filter
        # (1) anomalies: amount_wan -> today_buy_amt_wan, 過濾非追蹤 master
        anomalies = [s for s in (signals.get('anomalies') or [])
                     if _is_tracked_master(s.get('master'))][:15]
        for sig in anomalies:
            ws.cell(row, 2, '🔴 異常')
            ws.cell(row, 3, sig.get('master', '—'))
            ws.cell(row, 4, _severity_from_z(sig.get('z_score')))
            ws.cell(row, 5, sig.get('description', '—'))
            ws.cell(row, 6, _round_safe(sig.get('today_buy_amt_wan')))
            row += 1
        # (2) consensus: 結構是 faction_members list + buyer_count/total_buy_amt_wan;
        #     至少一位追蹤 master 在 faction_members 才顯示
        consensus_filtered = []
        for s in (signals.get('consensus') or []):
            members = s.get('faction_members') or []
            tracked_in_faction = [m for m in members if _is_tracked_master(m)]
            if tracked_in_faction:
                consensus_filtered.append((s, tracked_in_faction))
        for sig, tracked in consensus_filtered[:15]:
            ws.cell(row, 2, '🟡 共識')
            ws.cell(row, 3, sig.get('stock_code', '—'))
            ws.cell(row, 4, 'high' if sig.get('buyer_count', 0) >= 5 else 'medium')
            ws.cell(row, 5,
                    sig.get('description',
                            f"{sig.get('buyer_count', '?')} 位高手同買 (追蹤內:{len(tracked)})"))
            ws.cell(row, 6, _round_safe(sig.get('total_buy_amt_wan')))
            row += 1
        # (3) accumulations (複數): 過濾追蹤 master, 改用正確欄位名
        acc_list = [s for s in (signals.get('accumulations') or [])
                    if _is_tracked_master(s.get('master'))][:15]
        for sig in acc_list:
            ws.cell(row, 2, '🟢 連續加碼')
            ws.cell(row, 3, f"{sig.get('master', '?')} → {sig.get('stock_code', '?')}")
            days = sig.get('consecutive_days', 0)
            ws.cell(row, 4, 'high' if days >= 10 else 'medium')
            ws.cell(row, 5, sig.get('description', f"連續 {days} 天加碼"))
            ws.cell(row, 6, _round_safe(sig.get('total_buy_amt_wan')))
            row += 1
    if row == start_data:
        ws.cell(row, 2, '✅ 今日無異常警報 (追蹤範圍內)')
        ws.merge_cells(f'B{row}:F{row}')
        row += 1
    return row


def _severity_from_z(z_score) -> str:
    """v3.63.2: z_score -> severity 標籤 (anomaly 用)."""
    try:
        z = abs(float(z_score or 0))
        if z >= 3.0: return 'high'
        if z >= 2.0: return 'medium'
        return 'low'
    except (TypeError, ValueError):
        return 'medium'


def _round_safe(v):
    """v3.63.2: 安全 round int(萬), 失敗回 '—'."""
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return '—'


def _build_section_accumulation(ws, data_dir, start_row):
    """Section F: 跨日連續囤貨 (top 30 by 連續天數). Returns next row.

    v3.63.2: 兩 bug 修復
      (a) 舊版讀 master_profiles.json 的 master_profiles.<m>.op.consecutive_accumulation
          → 結構已重構, 改讀 daily_trading_signals.json 的 accumulations (與 Section E 同源)
      (b) 過濾非追蹤 master
    與 Section E 差異: E 顯示 top 15 (新鮮事), F 顯示 top 30 + 按天數深排序 (深度表).
    """
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    hdr_fill = _summary_fill('FFE8F5E9')

    row = start_row + 1
    _section_header(ws, row, "▍ F. 跨日連續囤貨 Top 30 (按連續天數排序)",
                     color='FF10B981'); row += 1
    # v3.63.2: headers 改為實際存在的欄位 (移除 stock_name/latest_date/is_active —
    # daily_trading_signals.json accumulations 沒這些欄位)
    headers = ['Master', '股票代號', '連續天數', '累計買金額(萬)', '說明']
    for i, h in enumerate(headers):
        cell = ws.cell(row, 2 + i, h)
        cell.font = hdr_font; cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1

    signals = _read_json_safely(data_dir / 'daily_trading_signals.json')
    start_data = row
    if signals:
        acc_list = [s for s in (signals.get('accumulations') or [])
                    if _is_tracked_master(s.get('master'))]
        acc_list.sort(key=lambda x: -x.get('consecutive_days', 0))
        for s in acc_list[:30]:
            ws.cell(row, 2, s.get('master', '—'))
            ws.cell(row, 3, s.get('stock_code', '—'))
            ws.cell(row, 4, s.get('consecutive_days', 0))
            ws.cell(row, 5, _round_safe(s.get('total_buy_amt_wan')))
            ws.cell(row, 6, s.get('description', '—'))
            row += 1
    if row == start_data:
        ws.cell(row, 2, '尚無連續囤貨紀錄 (追蹤範圍內)')
        ws.merge_cells(f'B{row}:F{row}')
        row += 1
    return row


def _build_section_pivot(ws, branches_data, start_row):
    """E7 (v3.63.0): Section J Master × Top 3 個股 cross-table.

    每個 master 一 row, 把該 master 今日 buys 按 buy_amt sort top 3, 寬展開為 6 cols
    (個股1+金額, 個股2+金額, 個股3+金額) + 總額.
    """
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    hdr_fill = _summary_fill('FFE0E7FF')

    row = start_row + 1
    _section_header(ws, row, "▍ J. Master × Top 3 個股 cross-table (今日)",
                     color='FF6366F1'); row += 1
    # headers
    for h_col, h in [('B', 'Master'), ('C', '今日總買(萬)'),
                      ('D', 'Top1 個股'), ('E', 'Top1 金額'),
                      ('F', 'Top2 個股'), ('G', 'Top2 金額'),
                      ('H', 'Top3 個股'), ('I', 'Top3 金額')]:
        cell = ws[f'{h_col}{row}']
        cell.value = h
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    row += 1

    # 算每個 master 的 today's stocks
    master_stocks = {}
    for b in branches_data:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []):
            code = s.get('code')
            if not code: continue
            master_stocks.setdefault(m, {})
            key = (code, s.get('name', ''))
            master_stocks[m][key] = master_stocks[m].get(key, 0) + (s.get('buy_amt') or 0)

    # 每 master sorted top 3
    rows_data = []
    for master, stocks in master_stocks.items():
        sorted_s = sorted(stocks.items(), key=lambda kv: -kv[1])
        total = sum(stocks.values())
        rows_data.append({
            'master': master,
            'total': total,
            'top': sorted_s[:3],
        })
    rows_data.sort(key=lambda x: -x['total'])

    start_data = row
    for d in rows_data[:30]:
        ws.cell(row, 2, d['master'])
        ws.cell(row, 2).font = Font(name='Noto Sans TC', size=11, bold=True)
        ws.cell(row, 3, round(d['total'] / 10, 0))
        for i, ((code, name), amt) in enumerate(d['top']):
            col_name = chr(ord('D') + i * 2)  # D, F, H
            col_amt = chr(ord('E') + i * 2)   # E, G, I
            ws.cell(row, ord(col_name) - 64, f"{name}({code})")
            ws.cell(row, ord(col_amt) - 64, round(amt / 10, 0))
        row += 1
    if row == start_data:
        ws.cell(row, 2, '今日無 master 有買進資料')
        ws.merge_cells(f'B{row}:I{row}'); row += 1
    return row


def _build_section_risk(ws, data_dir, start_row):
    """Section G+H+I: 注意股 + 借券 + 除權息. Returns next row."""
    hdr_font = Font(name='Noto Sans TC', size=10, bold=True)
    sub_font = Font(name='Noto Sans TC', size=11, bold=True)

    row = start_row + 1
    _section_header(ws, row, "▍ G. 注意股", color='FFFB923C'); row += 1
    attention = _read_json_safely(data_dir / 'attention_map.json')
    for h_col, h in [('B', '代號'), ('C', '名稱'), ('D', '累計次數'), ('E', '收盤價'), ('F', '本益比')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = hdr_font
        cell.fill = _summary_fill('FFFEF3C7')
        cell.alignment = Alignment(horizontal='center')
    row += 1
    by_code = (attention or {}).get('by_code') or {}
    if by_code:
        for code, info in list(by_code.items())[:15]:
            ws.cell(row, 2, code); ws.cell(row, 3, info.get('name', '—'))
            ws.cell(row, 4, info.get('cumulative_count', 0))
            ws.cell(row, 5, info.get('close', '—'))
            ws.cell(row, 6, info.get('pe', '—'))
            row += 1
    else:
        ws.cell(row, 2, '今日無注意股')
        ws.merge_cells(f'B{row}:F{row}'); row += 1

    row += 1
    _section_header(ws, row, "▍ H. 借券賣出 Top 15 (機構級反向力量)", color='FFDC2626'); row += 1
    short_lending = _read_json_safely(data_dir / 'short_lending.json')
    for h_col, h in [('B', '代號'), ('C', '名稱'), ('D', '借券張數'), ('E', '融券張數'), ('F', 'ratio')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = hdr_font
        cell.fill = _summary_fill('FFFEE2E2')
        cell.alignment = Alignment(horizontal='center')
    row += 1
    top_borrow = ((short_lending or {}).get('top_borrow_sell') or [])
    if top_borrow:
        for item in top_borrow[:15]:
            ws.cell(row, 2, item.get('code', '—'))
            ws.cell(row, 3, item.get('name', '—'))
            ws.cell(row, 4, item.get('borrow_sell_lot', 0))
            ws.cell(row, 5, item.get('short_sell_lot', 0))
            ws.cell(row, 6, item.get('borrow_vs_short_ratio', '—'))
            row += 1
    else:
        ws.cell(row, 2, '今日無借券資料')
        ws.merge_cells(f'B{row}:F{row}'); row += 1

    row += 1
    dividend = _read_json_safely(data_dir / 'dividend_calendar.json')
    upcoming = (dividend or {}).get('upcoming_30d') or []
    _section_header(ws, row, f"▍ I. 未來 30 天除權息 ({len(upcoming)} 檔)",
                     color='FFFBBF24'); row += 1
    for h_col, h in [('B', '除權息日'), ('C', '代號'), ('D', '名稱'), ('E', '類型'), ('F', '現金股利')]:
        cell = ws[f'{h_col}{row}']; cell.value = h; cell.font = hdr_font
        cell.fill = _summary_fill('FFFEF3C7')
        cell.alignment = Alignment(horizontal='center')
    row += 1
    if upcoming:
        for item in upcoming[:15]:
            ws.cell(row, 2, item.get('ex_date', '—'))
            ws.cell(row, 3, item.get('code', '—'))
            ws.cell(row, 4, item.get('name', '—'))
            ws.cell(row, 5, item.get('type', '—'))
            ws.cell(row, 6, item.get('cash_dividend', '—'))
            row += 1
    else:
        ws.cell(row, 2, '未來 30 天無除權息')
        ws.merge_cells(f'B{row}:F{row}'); row += 1
    return row


def build_dashboard_sheet(ws: "Worksheet", branches_data: List[Dict], trade_date: str,
                            data_dir: Optional[Path] = None):
    """v3.62.1: 把 E1-E4 4 個 section 全部寫到單一 sheet (用戶要求).
    順序: A 規模 → B Top master → C Top stocks → D 籌碼溫度
        → E 異常警報 → F 連續囤貨 → G 注意股 → H 借券 → I 除權息
    """
    data_dir = data_dir or Path('data')
    title_fill = _summary_fill('FF1F2A48')
    title_font = _summary_font_header()

    # v3.63.2: 嚴格只保留追蹤清單內的大戶 (MASTER_MAPPING)
    branches_data = _filter_tracked_branches(branches_data)

    for col, w in [('A', 4), ('B', 22), ('C', 18), ('D', 22), ('E', 16),
                    ('F', 22), ('G', 18), ('H', 22), ('I', 16)]:
        ws.column_dimensions[col].width = w

    # ── 大標題 ──
    ws.merge_cells('B2:I2')
    c = ws['B2']
    c.value = (f"📋 Chip Radar 今日 Dashboard — "
                f"{trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:]} "
                f"(追蹤 {len(TRACKED_MASTERS)} 位大戶)")
    c.font = title_font
    c.fill = title_fill
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 30

    # ── 各 section ──
    row = 4
    # v3.63.2: ★ Section 0 — 今日共同買超 (置於最前, 使用者最關注)
    row = _build_section_consensus(ws, branches_data, data_dir, row)
    row = _build_section_summary(ws, branches_data, trade_date, data_dir, row)
    row = _build_section_alerts(ws, data_dir, row)
    row = _build_section_accumulation(ws, data_dir, row)
    row = _build_section_pivot(ws, branches_data, row)   # v3.63.0 E7 Pivot
    row = _build_section_risk(ws, data_dir, row)

    # v3.63.0 (E6): freeze pane — title row 不滾走
    ws.freeze_panes = 'A3'


# v3.62.0 → v3.62.1 backward compat: 舊 builder name 保留但呼叫 dashboard
def build_summary_sheet(ws, branches_data, trade_date, data_dir=None):
    """DEPRECATED v3.62.1: 用戶要求合 dashboard. 此 fn 仍 alias 給 build_dashboard_sheet."""
    return build_dashboard_sheet(ws, branches_data, trade_date, data_dir)


def apply_pnl_color_scale(ws: "Worksheet", first_row: int, last_row: int, col_letter: str = 'L'):
    """E5: 損益欄 L 加紅綠色階 conditional formatting.
    v3.63.1: 端點改深紅/深綠 (C62828 / 2E7D32) 與白字粗體配對, 手機/筆電都高對比."""
    if last_row < first_row:
        return
    rule = ColorScaleRule(
        start_type='num', start_value=-10, start_color='FFC62828',
        mid_type='num', mid_value=0, mid_color='FFFFFFFF',
        end_type='num', end_value=10, end_color='FF2E7D32',
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

    # v3.62.1: 清舊版本殘留 (從 v3.62.0 升級時) — 4 個舊 sheet 移除
    for legacy_name in LEGACY_ENRICHMENT_NAMES:
        if legacy_name in wb.sheetnames:
            wb.remove(wb[legacy_name])

    # v3.62.1: rebuild 1 個 dashboard sheet (E1-E4 全 section)
    data_dir = monthly_path.parent.parent if monthly_path.parent.name == 'reports' else Path('data')
    if DASHBOARD_SHEET_NAME in wb.sheetnames:
        wb.remove(wb[DASHBOARD_SHEET_NAME])
    dashboard_ws = wb.create_sheet(title=DASHBOARD_SHEET_NAME)
    try:
        build_dashboard_sheet(dashboard_ws, branches_data, trade_date, data_dir)
    except Exception as _be:
        print(f"  [Excel] dashboard sheet build 失敗: {type(_be).__name__}: {_be}")

    # 排序: dashboard 在前, 日期 sheets 按 desc
    other_sheets = sorted([s for s in wb.sheetnames if s != DASHBOARD_SHEET_NAME],
                            reverse=True)
    order = ([DASHBOARD_SHEET_NAME] if DASHBOARD_SHEET_NAME in wb.sheetnames else []) + other_sheets
    wb._sheets = [wb[name] for name in order]

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
