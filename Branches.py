"""
========================================================================
Module: branches.py
功能：分點清單 + 個人標記 + 市場公認標記

設計原則：
  - 純資料模組，不含邏輯
  - 隨時可以新增/修改/刪除分點與標記
  - 標記分三層：個人 / 市場公認 / 系統自動（自動的在 styles.py）
========================================================================
"""

# ════════════════════════════════════════════════════════════════════
#  分點主清單 (WATCHED_BRANCHES)
# ════════════════════════════════════════════════════════════════════
#
# 欄位說明:
#   code:          券商分點代碼（4 碼字母+數字）
#   name:          券商-分點名稱
#   master:        操盤人/暱稱
#   tags_personal: 你的私人標記（你最了解的事）
#   tags_market:   市場公認標記（網路常見討論）
#
# 標記範例:
#   個人標記: ["當沖王", "電子權值", "AI 概念", "我跟過"]
#   市場公認: ["主力分點", "隔日沖", "波段", "中實戶"]
#
# 使用提示:
#   - 標記用中文好讀，但避免特殊符號（'"<>&）
#   - 一個分點可有多個標籤
#   - 不知道就留空 [] 即可
#
# ════════════════════════════════════════════════════════════════════

WATCHED_BRANCHES = [
    # ─────────────────────────────────────────────────────────
    # 民哥（3 個分點）
    # ─────────────────────────────────────────────────────────
    {
        "code": "9B25", "name": "台新-五權西", "master": "民哥",
        "tags_personal": [],          # 👈 你的私人標記寫這裡
        "tags_market":   [],          # 👈 市場公認標記寫這裡
    },
    {
        "code": "9666", "name": "富邦-南屯", "master": "民哥",
        "tags_personal": [],
        "tags_market":   [],
    },
    {
        "code": "779W", "name": "國票-彰化", "master": "民哥",
        "tags_personal": [],
        "tags_market":   [],
    },

    # ─────────────────────────────────────────────────────────
    # 林滄海（4 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9658", "name": "富邦-建國",     "master": "林滄海", "tags_personal": [], "tags_market": []},
    {"code": "9309", "name": "華南永昌-古亭", "master": "林滄海", "tags_personal": [], "tags_market": []},
    {"code": "1260", "name": "宏遠證券",      "master": "林滄海", "tags_personal": [], "tags_market": []},
    {"code": "9216", "name": "凱基-信義",     "master": "林滄海", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 張濬安/航海王（6 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "779Z", "name": "國票-安和",      "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},
    {"code": "9B2E", "name": "台新-城中",      "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},
    {"code": "920F", "name": "凱基-站前",      "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},
    {"code": "6167", "name": "中國信託-松江",  "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},
    {"code": "961M", "name": "富邦-木柵",      "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},
    {"code": "9100", "name": "群益金鼎證券",   "master": "張濬安(航海王)", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 陳族元（5 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "8880", "name": "國泰證券",     "master": "陳族元", "tags_personal": [], "tags_market": []},
    {"code": "9300", "name": "華南永昌證券", "master": "陳族元", "tags_personal": [], "tags_market": []},
    {"code": "9661", "name": "富邦-新店",    "master": "陳族元", "tags_personal": [], "tags_market": []},
    {"code": "9216", "name": "凱基-信義",     "master": "林滄海", "tags_personal": [], "tags_market": []},
    {"code": "9A9g", "name": "永豐金-內湖",  "master": "陳族元", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 陳律師（4 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "700c", "name": "兆豐-民生",   "master": "陳律師", "tags_personal": [], "tags_market": []},
    {"code": "8450", "name": "康和總公司",  "master": "陳律師", "tags_personal": [], "tags_market": []},
    {"code": "9A9R", "name": "永豐金-信義", "master": "陳律師", "tags_personal": [], "tags_market": []},
    {"code": "585c", "name": "統一-仁愛",   "master": "陳律師", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 迷你哥/松山哥（3 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9217", "name": "凱基-松山", "master": "迷你哥/松山哥", "tags_personal": [], "tags_market": []},
    {"code": "9200", "name": "凱基證券",  "master": "迷你哥/松山哥", "tags_personal": [], "tags_market": []},
    {"code": "9600", "name": "富邦證券",  "master": "迷你哥/松山哥", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 布哥/n_nchang（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9A8F", "name": "永豐金-敦南", "master": "布哥/n_nchang", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 強森（5 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2r", "name": "台新-城東",   "master": "強森", "tags_personal": [], "tags_market": []},
    {"code": "984K", "name": "元大-館前",   "master": "強森", "tags_personal": [], "tags_market": []},
    {"code": "989N", "name": "元大-內湖",   "master": "強森", "tags_personal": [], "tags_market": []},
    {"code": "9215", "name": "凱基-高美館", "master": "強森", "tags_personal": [], "tags_market": []},
    {"code": "9B2D", "name": "台新-大昌",   "master": "強森", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # Tradow（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2a", "name": "台新-松德", "master": "Tradow", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 巨人傑（2 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9B2n", "name": "台新-西松", "master": "巨人傑", "tags_personal": [], "tags_market": []},
    {"code": "9B2z", "name": "台新-文心", "master": "巨人傑", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 蔣承翰（2 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9227", "name": "凱基-城中", "master": "蔣承翰", "tags_personal": [], "tags_market": []},
    {"code": "9B18", "name": "台新-建北", "master": "蔣承翰", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 大牌分析師（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "8563", "name": "新光-新竹", "master": "大牌分析師", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # 東億資本（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "9874", "name": "元大-雙和", "master": "東億資本", "tags_personal": [], "tags_market": []},

    # ─────────────────────────────────────────────────────────
    # Krenz/再多一位數本人（1 個分點）
    # ─────────────────────────────────────────────────────────
    {"code": "884F", "name": "玉山-桃園", "master": "Krenz(再多一位數本人)", "tags_personal": [], "tags_market": []},
]


# ════════════════════════════════════════════════════════════════════
# 個人標記範例（給你參考用，目前都是空的）
# ════════════════════════════════════════════════════════════════════
#
# 假設你想為民哥加標記，在上面找到 9B25 那筆改成：
#
#     {
#         "code": "9B25", "name": "台新-五權西", "master": "民哥",
#         "tags_personal": ["當沖王", "我跟過", "權值股"],
#         "tags_market":   ["主力分點", "中部大戶"],
#     },
#
# 標籤建議分類：
#   ▸ 操作風格：當沖王 / 隔日沖 / 短線 / 波段 / 長線
#   ▸ 標的偏好：權值股 / 中小型 / 電子 / 傳產 / 金融 / AI / 航運 / 軍工
#   ▸ 規模描述：主力分點 / 中實戶 / 散戶代表
#   ▸ 你的評價：我跟過 / 跟到賺 / 跟到賠 / 不要跟
#   ▸ 地理屬性：南部 / 北部 / 中部
#
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


def get_branches_by_master(master_name):
    """取得某高手的所有分點"""
    return [b for b in WATCHED_BRANCHES if b["master"] == master_name]


def get_all_masters():
    """取得所有不同的高手名稱"""
    return list(dict.fromkeys(b["master"] for b in WATCHED_BRANCHES))


def get_branch_by_code(code):
    """以代碼查詢分點"""
    for b in WATCHED_BRANCHES:
        if b["code"] == code:
            return b
    return None


def get_branches_by_tag(tag, tag_type="all"):
    """
    依標籤過濾分點
    tag_type: "personal" / "market" / "all"
    """
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
