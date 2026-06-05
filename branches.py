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
     "co_masters": ["強森"],   # v3.31.18 使用者確認共用
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
    # 迷你哥/松山哥（v3.31.7: 縮為 1 個分點, 移除 9200/9600 因那是「整家證券公司」非分行）
    # ─────────────────────────────────────────────────────────
    {"code": "9217", "name": "凱基-松山", "master": "迷你哥/松山哥",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    # v3.31.7 拆: 9200 凱基證券 / 9600 富邦證券 是整個證券公司加總 (含全分行散戶+大戶),
    #              不該歸給「迷你哥」個人大戶 → 改 master = 公司本身, style=company_total (排除分析)
    {"code": "9200", "name": "凱基證券", "master": "凱基證券",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "company_total"},
    {"code": "9600", "name": "富邦證券", "master": "富邦證券",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "company_total"},
 
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
    # 竹科主力分點（2 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "700V", "name": "兆豐-新竹", "master": "竹科主力分點",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9647", "name": "富邦-新竹", "master": "竹科主力分點",
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

    # ─────────────────────────────────────────────────────────
    # 志誠資本（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "779v", "name": "國票-台中", "master": "志誠資本",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},

    # ─────────────────────────────────────────────────────────
    # 謝明彧大哥(華南永昌)（3 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9307", "name": "華南永昌-大安", "master": "謝明彧大哥(華南永昌)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9309", "name": "華南永昌-古亭", "master": "謝明彧大哥(華南永昌)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9347", "name": "華南永昌-敦南", "master": "謝明彧大哥(華南永昌)",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},

    # ─────────────────────────────────────────────────────────
    # 林適中（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9614", "name": "富邦-基隆", "master": "林適中",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
 
 
    # ═════════════════════════════════════════════════════════
    # v3.31.18: 使用者 Excel「分點人之秘密」交叉比對新增 (25 個分點)
    # ═════════════════════════════════════════════════════════

    # ─── 有明確 master 的新分點 (15 個) ───
    {"code": "779u", "name": "國票-長城", "master": "宋福祥",
     "tags_personal": ["AES-KY董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "585Q", "name": "統一-三多", "master": "呂金發",
     "tags_personal": ["太普高董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "962Q", "name": "富邦-北高雄", "master": "陳光裕",
     "tags_personal": ["世德董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9676", "name": "富邦-仁愛", "master": "謝孟恭(股癌)",
     "tags_personal": ["股癌"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9A9J", "name": "永豐金-板新", "master": "丁凌全",
     "tags_personal": ["時碩工業董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "700S", "name": "兆豐-大同", "master": "何莎",
     "tags_personal": ["廣達董娘"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "888A", "name": "國泰-館前", "master": "江士勳",
     "tags_personal": ["金山電子董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "913Y", "name": "群益金鼎-館前", "master": "江士勳",
     "tags_personal": ["金山電子董事長"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "7003", "name": "兆豐-台中", "master": "劉子豪",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "700r", "name": "兆豐-寶成", "master": "陳泊澔",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9874", "name": "元大-雙和", "master": "東億資本",
     "tags_personal": ["高東億本人"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9692", "name": "富邦-嘉義", "master": "嘉義幫",
     "tags_personal": ["隔日沖"], "tags_market": [],
     "enabled": True, "region": "domestic"},
    # 既有 master 擴分點
    {"code": "585c", "name": "統一-仁愛", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "700c", "name": "兆豐-民生", "master": "陳律師",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},
    {"code": "9A8F", "name": "永豐金-敦南", "master": "布哥/n_nchang",
     "tags_personal": [], "tags_market": [],
     "enabled": True, "region": "domestic"},

    # ─── 地緣/特色分點 (無個人 master, 用描述性名稱, style=area_hotspot 排除分析) ───
    {"code": "585U", "name": "統一-南京", "master": "統一南京(強勢未知)",
     "tags_personal": ["強勢分點人名未知"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "8888", "name": "國泰-敦南", "master": "國泰敦南(散戶混合)",
     "tags_personal": ["散戶多但有大戶藏裡面"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "980K", "name": "元大-竹科", "master": "竹科強勢地緣",
     "tags_personal": ["竹科強勢地緣分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "700I", "name": "兆豐-北高雄", "master": "兆豐北高雄(強勢地緣)",
     "tags_personal": ["強勢地緣分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "9268", "name": "凱基-台北", "master": "凱基台北(當沖高手聚集)",
     "tags_personal": ["JACK等高手聚集", "強勢當沖分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "9275", "name": "凱基-三多", "master": "凱基三多(波段千金股)",
     "tags_personal": ["專買千金股", "波段強勢分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "9359", "name": "華南永昌-中正", "master": "華南永昌中正(未知大哥)",
     "tags_personal": ["強勢未知大哥分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "913R", "name": "群益-北高雄", "master": "群益北高雄(強勢地緣)",
     "tags_personal": ["強勢地緣分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "918e", "name": "群益金鼎-大安", "master": "群益大安(強勢波段)",
     "tags_personal": ["強勢波段分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},
    {"code": "9A9G", "name": "永豐金-天母", "master": "永豐天母(老錢)",
     "tags_personal": ["天母老錢分點"], "tags_market": [],
     "enabled": True, "region": "area_hotspot"},

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
 
 
# ════════════════════════════════════════════════════════════════════
#  v3.12 Master 風格檔案（手動標記 + 可自行擴充）
# ════════════════════════════════════════════════════════════════════
#
# 為什麼獨立欄位：
#   - 同一 master 可以有多種風格（如「隔日沖 + 當沖」）
#   - 一個人不同時期策略也可能不同
#   - 用陣列比單一風格更貼近真實
#
# 風格定義:
#   day_trader       🔥 當沖：買賣同日結清
#   next_day_flipper ⚡ 隔日沖：買入後隔天賣
#   swing            🌙 波段：持股數日~數週
#   longterm         💎 長線：持股數月以上
#   foreign_ib       🌏 外資 IB
#   public           🏛️ 官股
#
# 使用方法:
#   1. 若要加新風格：加到下面 STYLE_LABELS 字典
#   2. 若要改某 master 風格：改下面 MASTER_STYLES 字典（改完 commit 即生效）
#   3. UI 的「漲停狙擊」頁會重點追蹤 next_day_flipper + day_trader
# ════════════════════════════════════════════════════════════════════
 
STYLE_LABELS = {
    "day_trader":       {"icon": "🔥", "label": "當沖", "color": "#fb923c"},
    "next_day_flipper": {"icon": "⚡", "label": "隔日沖", "color": "#f87171"},
    "swing":            {"icon": "🌙", "label": "波段", "color": "#60a5fa"},
    "longterm":         {"icon": "💎", "label": "長線", "color": "#22d3ee"},
    "foreign_ib":       {"icon": "🌏", "label": "外資 IB", "color": "#a78bfa"},
    "public":           {"icon": "🏛️", "label": "官股", "color": "#d8b4fe"},
    "unknown":          {"icon": "❓", "label": "未分類", "color": "#64748b"},
}
 
MASTER_STYLES = {
    # 🇹🇼 國內高手
    "民哥": ["swing"],
    "林滄海": ["swing", "longterm"],
    "張濬安(航海王)": ["swing"],
    "陳族元": ["swing"],
    "陳律師": ["swing"],
    "迷你哥/松山哥": ["day_trader"],
    "布哥/n_nchang": ["swing"],
    "強森": ["swing"],
    "Tradow": ["next_day_flipper"],
    "巨人傑": ["next_day_flipper", "day_trader"],
    "蔣承翰": ["next_day_flipper"],   # ⭐ 你明確指定為隔日沖
    "大牌分析師": ["swing"],
    "優式資本": ["longterm"],
    "東億資本": ["longterm"],
    "志誠資本": ["longterm"],                   # v3.31.8 補 (使用者 6/3 confirm)
    "Krenz(再多一位數本人)": ["swing"],             # v3.31.13 使用者校正: 波段不是當沖
    "林適中": ["swing"],                         # v3.31.8 補
    "竹科主力分點": ["swing"],                   # v3.31.8 補
    "謝明彧大哥(華南永昌)": ["swing"],          # v3.31.8 補
    # 🌏 外資
    "高盛": ["foreign_ib"],
    "美林": ["foreign_ib"],
    "摩根士丹利": ["foreign_ib"],
    "摩根大通": ["foreign_ib"],
    "花旗環球": ["foreign_ib"],
    "瑞銀": ["foreign_ib"],
    "匯豐 HSBC": ["foreign_ib"],
    "麥格理": ["foreign_ib"],
    # 🏛️ 官股
    "臺銀證券": ["public"],
    "兆豐證券": ["public"],
    # v3.31.18: 使用者 Excel「分點人之秘密」交叉比對新增 (12 個新 master)
    "宋福祥": ["longterm"],                   # AES-KY 董事長, 國票長城
    "呂金發": ["swing"],                      # 太普高董事長, 統一三多
    "陳光裕": ["longterm"],                   # 世德董事長, 富邦北高雄
    "謝孟恭(股癌)": ["longterm"],              # 股癌, 富邦仁愛
    "丁凌全": ["longterm"],                   # 時碩工業董事長, 永豐板新
    "何莎": ["swing"],                        # 廣達董娘, 兆豐大同
    "江士勳": ["swing"],                      # 金山電子董事長, 國泰館前+群益館前
    "劉子豪": ["swing"],                      # 兆豐台中
    "陳泊澔": ["swing"],                      # 兆豐寶成
    "嘉義幫": ["next_day_flipper"],            # 富邦嘉義, 隔日沖
    # 🏢 地緣/特色分點 (area_hotspot, 排除 master_profile 分析)
    "統一南京(強勢未知)": ["area_hotspot"],
    "國泰敦南(散戶混合)": ["area_hotspot"],
    "竹科強勢地緣": ["area_hotspot"],
    "兆豐北高雄(強勢地緣)": ["area_hotspot"],
    "凱基台北(當沖高手聚集)": ["area_hotspot"],
    "凱基三多(波段千金股)": ["area_hotspot"],
    "華南永昌中正(未知大哥)": ["area_hotspot"],
    "群益北高雄(強勢地緣)": ["area_hotspot"],
    "群益大安(強勢波段)": ["area_hotspot"],
    "永豐天母(老錢)": ["area_hotspot"],
    # 🏢 整家證券公司 (v3.31.7 拆出: 9200/9600 是公司加總, 非個人大戶分行)
    "凱基證券": ["company_total"],
    "富邦證券": ["company_total"],
}
 
 
def get_master_styles(master_name):
    """取得某 master 的風格陣列"""
    return MASTER_STYLES.get(master_name, ["unknown"])
 
 
def is_master_of_style(master_name, style):
    """判斷某 master 是否屬於某個風格"""
    return style in MASTER_STYLES.get(master_name, [])
 
 
def get_masters_of_style(style):
    """取得屬於某風格的所有 master"""
    return [m for m, styles in MASTER_STYLES.items() if style in styles]
 
 
# ════════════════════════════════════════════════════════════════════
#  v3.12 漲停股定義
# ════════════════════════════════════════════════════════════════════
 
LIMIT_UP_THRESHOLD = 9.5   # 漲跌幅 >= 9.5% 視為漲停
NEAR_LIMIT_UP_THRESHOLD = 7.0  # >= 7% 視為接近漲停（隔日沖預備狙擊）
