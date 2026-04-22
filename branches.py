"""
========================================================================
Module: branches.py  (v3.10 升級)
功能：分點清單 + 個人標記 + 市場公認標記
 
設計原則：
  - 純資料模組，不含邏輯
  - 隨時可以新增/修改/刪除分點與標記
  - 標記分三層：個人 / 市場公認 / 系統自動
 
v3.10 新增：
  - co_masters 欄位：同分點的其他 master（多人共用分點的情境）
  - 例：凱基-信義 主要歸屬林滄海，但陳族元也使用此分點
  - 前端顯示時會同時呈現 master + co_masters
  - 同向率/績效計算會把分點資料歸入所有相關 master
 
v3.8 架構：
  - enabled 欄位：分點是否啟用（停用 = 爬蟲仍爬但 UI 不顯示）
  - region 欄位：地區分組（domestic / public / us / eu / asia）
  - 8 個外資分點 + 2 個官股 + 38 個國內
========================================================================
"""
 
# ════════════════════════════════════════════════════════════════════
#  分點主清單 (WATCHED_BRANCHES)
# ════════════════════════════════════════════════════════════════════
#
# 欄位說明:
#   code:          券商分點代碼（4 碼字母+數字）
#   name:          券商-分點名稱
#   master:        主要 master（字串）
#   co_masters:    其他共用此分點的 master（陣列，選填）
#                  v3.10 新增，預設空陣列
#   tags_personal: 你的私人標記
#   tags_market:   市場公認標記
#   enabled:       是否啟用顯示（預設 True；False = 隱藏但仍爬蟲）
#   region:        地區分組（domestic / public / us / eu / asia）
#
# ════════════════════════════════════════════════════════════════════
 
WATCHED_BRANCHES = [
    # ─────────────────────────────────────────────────────────
    # 民哥（3 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B25", "name": "台新-五權西", "master": "民哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9666", "name": "富邦-南屯", "master": "民哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "779W", "name": "國票-彰化", "master": "民哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 林滄海（4 個分點；9216 凱基-信義與陳族元共用）
    # ─────────────────────────────────────────────────────────
    {"code": "9658", "name": "富邦-建國", "master": "林滄海",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9309", "name": "華南永昌-古亭", "master": "林滄海",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "1260", "name": "宏遠證券", "master": "林滄海",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9216", "name": "凱基-信義", "master": "林滄海",
     "co_masters": ["陳族元"],
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 張濬安(航海王)（6 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "779Z", "name": "國票-安和", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9B2E", "name": "台新-城中", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "920F", "name": "凱基-站前", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "6167", "name": "中國信託-松江", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "961M", "name": "富邦-木柵", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9100", "name": "群益金鼎證券", "master": "張濬安(航海王)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 陳族元（4 個獨立分點，+ 林滄海 9216 共用）
    # ─────────────────────────────────────────────────────────
    {"code": "8880", "name": "國泰證券", "master": "陳族元",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9300", "name": "華南永昌證券", "master": "陳族元",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9661", "name": "富邦-新店", "master": "陳族元",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9A9g", "name": "永豐金-內湖", "master": "陳族元",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 陳律師（4 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "700c", "name": "兆豐-民生", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "8450", "name": "康和總公司", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9A9R", "name": "永豐金-信義", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "585c", "name": "統一-仁愛", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 迷你哥/松山哥（3 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9217", "name": "凱基-松山", "master": "迷你哥/松山哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9200", "name": "凱基證券", "master": "迷你哥/松山哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9600", "name": "富邦證券", "master": "迷你哥/松山哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 布哥/n_nchang（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9A8F", "name": "永豐金-敦南", "master": "布哥/n_nchang",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 強森（5 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2r", "name": "台新-城東", "master": "強森",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "984K", "name": "元大-館前", "master": "強森",
     "co_masters": ["巨人傑"],
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "989N", "name": "元大-內湖", "master": "強森",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9215", "name": "凱基-高美館", "master": "強森",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9B2D", "name": "台新-大昌", "master": "強森",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # Tradow（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2a", "name": "台新-松德", "master": "Tradow",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 巨人傑（2 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2n", "name": "台新-西松", "master": "巨人傑",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9B2z", "name": "台新-文心", "master": "巨人傑",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 蔣承翰（2 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9227", "name": "凱基-城中", "master": "蔣承翰",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9B18", "name": "台新-建北", "master": "蔣承翰",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 大牌分析師（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "8563", "name": "新光-新竹", "master": "大牌分析師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 優式資本（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "779c", "name": "國票-敦北法人", "master": "優式資本",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # 東億資本（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9874", "name": "元大-雙和", "master": "東億資本",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ─────────────────────────────────────────────────────────
    # Krenz(再多一位數本人)（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "884F", "name": "玉山-桃園", "master": "Krenz(再多一位數本人)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
    # ═════════════════════════════════════════════════════════
    # 🌏 外資分點（v3.8 新增，來源：富邦 zco 頁面）
    # ═════════════════════════════════════════════════════════
 
    # ─── 🇺🇸 美系外資（5 個）
    {"code": "1480", "name": "美商高盛", "master": "高盛",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "us"},
    {"code": "1440", "name": "美林", "master": "美林",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "us"},
    {"code": "1470", "name": "台灣摩根士丹利", "master": "摩根士丹利",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "us"},
    {"code": "8440", "name": "摩根大通", "master": "摩根大通",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "us"},
    {"code": "1590", "name": "花旗環球", "master": "花旗環球",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "us"},
 
    # ─── 🇪🇺 歐系外資（1 個）
    {"code": "1650", "name": "新加坡商瑞銀", "master": "瑞銀",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "eu"},
 
    # ─── 🌏 亞系外資（2 個）
    {"code": "8960", "name": "香港上海匯豐", "master": "匯豐 HSBC",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "asia"},
    {"code": "1360", "name": "港商麥格理", "master": "麥格理",
     "tags_personal": [], "tags_market": ["外資IB"],
     "enabled": True, "region": "asia"},
 
    # ═════════════════════════════════════════════════════════
    # 🏛️ 官股分點（v3.9 新增）
    # ═════════════════════════════════════════════════════════
    {"code": "1040", "name": "臺銀", "master": "臺銀證券",
     "tags_personal": [], "tags_market": ["官股"],
     "enabled": True, "region": "public"},
    {"code": "7000", "name": "兆豐證券", "master": "兆豐證券",
     "tags_personal": [], "tags_market": ["官股"],
     "enabled": True, "region": "public"},
 
]
 
 
# ════════════════════════════════════════════════════════════════════
#  輔助函數
# ════════════════════════════════════════════════════════════════════
 
def get_unique_branches():
    """去除重複分點代碼，回傳唯一清單"""
    seen = set()
    unique = []
    for b in WATCHED_BRANCHES:
        if b["code"] not in seen:
            seen.add(b["code"])
            unique.append(b)
    return unique
 
 
def get_enabled_branches():
    """v3.8：只取 enabled=True 的分點"""
    return [b for b in WATCHED_BRANCHES if b.get("enabled", True)]
 
 
def get_all_masters_for_branch(branch):
    """v3.10：取得某分點的所有相關 master（主 + 共用）"""
    masters = [branch.get("master", "")]
    masters.extend(branch.get("co_masters", []) or [])
    return [m for m in masters if m]
 
 
def get_branches_by_master(master_name, include_disabled=False, include_co=True):
    """
    取得某高手的所有分點
    v3.10：include_co=True 會包含 co_masters 含此人的分點
    """
    result = []
    for b in WATCHED_BRANCHES:
        if not include_disabled and not b.get("enabled", True):
            continue
        if b.get("master") == master_name:
            result.append(b)
        elif include_co and master_name in (b.get("co_masters") or []):
            result.append(b)
    return result
 
 
def get_all_masters(include_disabled=False):
    """取得所有不同的 master 名稱（含 co_masters 提到的人）"""
    pool = WATCHED_BRANCHES if include_disabled else get_enabled_branches()
    masters = []
    seen = set()
    for b in pool:
        for m in get_all_masters_for_branch(b):
            if m and m not in seen:
                seen.add(m)
                masters.append(m)
    return masters
 
 
def get_branch_by_code(code):
    """以代碼查詢分點"""
    for b in WATCHED_BRANCHES:
        if b["code"] == code:
            return b
    return None
 
 
def get_branches_by_region(region, include_disabled=False):
    """依地區分組取分點"""
    pool = WATCHED_BRANCHES if include_disabled else get_enabled_branches()
    return [b for b in pool if b.get("region", "domestic") == region]
 
 
def get_foreign_branches(include_disabled=False):
    """取所有外資分點"""
    pool = WATCHED_BRANCHES if include_disabled else get_enabled_branches()
    return [b for b in pool if b.get("region", "domestic") not in ("domestic", "public")]
 
 
def get_domestic_branches(include_disabled=False):
    """取所有國內分點（不含官股）"""
    pool = WATCHED_BRANCHES if include_disabled else get_enabled_branches()
    return [b for b in pool if b.get("region", "domestic") == "domestic"]
 
 
def get_branches_by_tag(tag, tag_type="all"):
    """依標籤過濾分點"""
    result = []
    for b in WATCHED_BRANCHES:
        if tag_type == "personal" and tag in b.get("tags_personal", []):
            result.append(b)
        elif tag_type == "market" and tag in b.get("tags_market", []):
            result.append(b)
        elif tag_type == "all":
            if tag in b.get("tags_personal", []) or tag in b.get("tags_market", []):
                result.append(b)
    return result
 
 
def get_all_personal_tags():
    """取得所有用過的個人標籤"""
    tags = set()
    for b in WATCHED_BRANCHES:
        tags.update(b.get("tags_personal", []))
    return sorted(tags)
 
 
def get_all_market_tags():
    """取得所有用過的市場標籤"""
    tags = set()
    for b in WATCHED_BRANCHES:
        tags.update(b.get("tags_market", []))
    return sorted(tags)
 
 
# ════════════════════════════════════════════════════════════════════
#  地區標籤（給 UI 用）
# ════════════════════════════════════════════════════════════════════
 
REGION_LABELS = {
    "domestic": "🇹🇼 國內",
    "public":   "🏛️ 官股",
    "us":       "🇺🇸 美系",
    "eu":       "🇪🇺 歐系",
    "asia":     "🌏 亞系",
}
 
