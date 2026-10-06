# -*- coding: utf-8 -*-
"""Master 分層的**唯一真相來源** (v3.79.0)

起因 (2026-08-30 P2 稽核) — 同一個概念散在 4 個檔案, 已經產生 3 個實際缺陷:

  ① PREMIUM_MASTERS 完全漂移
     scripts/bootstrap_multiday_backtest.py:40 硬寫 {陳律師, 竹科主力分點, 陳族元}
     (2026-06-26 凍結的小樣本名單), 但 v3.75.0 起 excel_report 已改成依實測
     LOO 動態計算, 現值是 {巨人傑} — **兩者零交集**.
     → 每週 multiday backtest 的「Premium tier」在算三個已不符資格的人.

  ② SNIPER_MASTERS 兩份定義不同
     crawler.py:780            {'蔣承翰'}
     audit/histock_branch_audit:80  {'蔣承翰','迷你哥','Tradow','巨人傑'}

  ③ '迷你哥' 這個名字**不存在** — MASTER_STYLES 的正式名稱是 '迷你哥/松山哥'
     → audit 的 `br.get('master') in SNIPER_MASTERS` 對他永遠不成立,
       是個完全沒有錯誤訊息的 silent no-op.

  ③ 正是這陣子一直在抓的那類 bug: 不拋例外 / 不變紅 / 看起來正常, 只是沒作用.
  所以這裡除了集中定義, 還在 **import 時就驗證每個名字真的存在於 MASTER_STYLES**.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, Set


# ════════════════════════════════════════════════════════════════════
#  名稱驗證 — 打錯名字必須當場被抓到, 而不是變成 silent no-op
# ════════════════════════════════════════════════════════════════════
def _known_masters() -> Set[str]:
    try:
        from src.core.branches import MASTER_STYLES
    except ImportError:                      # src/ 已在 sys.path 的情境
        from branches import MASTER_STYLES   # type: ignore
    return set(MASTER_STYLES)


def validate_master_names(names: Iterable[str], ctx: str,
                          strict: bool = True) -> Set[str]:
    """檢查名字是否都存在於 MASTER_STYLES.

    strict=True  → 不存在就 raise (用於本檔的靜態常數, 打錯要立刻炸)
    strict=False → 只回傳未知名單 (用於外部傳入的動態名字)
    """
    names = set(names or ())
    unknown = names - _known_masters()
    if unknown and strict:
        raise ValueError(
            f"[master_tiers] {ctx} 含未知 master 名稱 {sorted(unknown)} — "
            f"MASTER_STYLES 內查無此人. 常見原因是簡寫 "
            f"(例: '迷你哥' 的正式名稱是 '迷你哥/松山哥'). "
            f"名字錯不會拋錯只會靜默不匹配, 所以這裡直接擋下."
        )
    return unknown


# ════════════════════════════════════════════════════════════════════
#  1. 漲停狙擊型 master — 風格分類, 用於 audit / 分析
# ════════════════════════════════════════════════════════════════════
#  ⚠️ 這跟下面的 TOP_BUYER_HIGHLIGHT_MASTERS **是兩個不同概念**, 不要合併:
#     這裡是「誰的風格是搶漲停」(描述), 下面是「哪些人要標黃底」(功能).
#     原本兩邊都叫 SNIPER_MASTERS 但內容不同, 才會沒人發現已經分歧.
LIMIT_UP_SNIPERS: Set[str] = {
    '蔣承翰',
    '迷你哥/松山哥',      # ← 原 audit 寫 '迷你哥', 永遠匹配不到
    'Tradow',
    '巨人傑',
}

# ════════════════════════════════════════════════════════════════════
#  2. Top-buyer 黃底 highlight 對象 — 功能性範圍, 由用戶指定
# ════════════════════════════════════════════════════════════════════
#  v3.72.x 用戶要求: 蔣承翰買的漲停股, 若他是該股「全市場」買超第一 → 標黃底.
#  刻意維持只有蔣承翰 — 擴大範圍會改變 Excel 呈現, 屬用戶決定而非技術債.
TOP_BUYER_HIGHLIGHT_MASTERS: Set[str] = {'蔣承翰'}

# 向後相容: crawler.py / audit 舊名 (兩邊語意不同, 各自指向正確的那個)
SNIPER_MASTERS = TOP_BUYER_HIGHLIGHT_MASTERS


# ════════════════════════════════════════════════════════════════════
#  3. Premium tier — 動態, 由實測 LOO 決定 (v3.75.0 起不再用凍結名單)
# ════════════════════════════════════════════════════════════════════
#  v3.75.0 決議背景: 原名單是 2026-06-26 用 n=6~18 的小樣本凍結的.
#  用凍結的小樣本名單標 ⭐⭐, 會讓使用者對已失效的訊號加重下注.
PREMIUM_MIN_N = 20         # 樣本門檻 (與 LOO 一致)
PREMIUM_MIN_HIT_PCT = 60   # 命中率門檻 (原 77% 係小樣本產物)

# 靜態 fallback — 僅在 master_contribution.json 不存在時使用
PREMIUM_MASTERS_FALLBACK: Set[str] = set()

_PREMIUM_CACHE: dict = {}
_DEFAULT_DATA = Path(__file__).resolve().parents[2] / 'data'


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def get_premium_masters(data_dir=None) -> Set[str]:
    """依實測 LOO 動態決定 premium tier.

    三個條件皆須成立:
      1. n_with >= PREMIUM_MIN_N            樣本足夠
      2. hr_with_pct >= PREMIUM_MIN_HIT_PCT
      3. Wilson CI 下界 > 整體 baseline     優勢達統計顯著

    資料源 data/master_contribution.json; 取不到 → 空集合
    (寧可不標 ⭐⭐, 也不標錯的)
    """
    d = Path(data_dir) if data_dir else _DEFAULT_DATA
    key = str(d)
    if key in _PREMIUM_CACHE:
        return _PREMIUM_CACHE[key]
    result = set(PREMIUM_MASTERS_FALLBACK)
    mc = _read_json(d / 'master_contribution.json')
    if mc and mc.get('per_master'):
        base = (mc.get('baseline') or {}).get('hit_rate_pct')
        picked = set()
        for r in mc['per_master']:
            if r.get('n_with', 0) < PREMIUM_MIN_N:
                continue
            if (r.get('hr_with_pct') or 0) < PREMIUM_MIN_HIT_PCT:
                continue
            lo = r.get('ci_lo_pct')
            if base is not None and lo is not None and lo <= base:
                continue          # CI 下界未超過整體 → 優勢不顯著
            picked.add(r['master'])
        result = picked
    _PREMIUM_CACHE[key] = result
    return result


def refresh_premium_masters(data_dir=None) -> Set[str]:
    """清 cache 重算 — crawler 重寫 master_contribution.json 後應呼叫.

    ⚠️ 不可在 module import 時求值: crawler 順序是
    「跑完 quad → 重算 master_contribution → 產 Excel」,
    import 當下凍結會讓 Excel 拿到上一輪的名單.
    """
    _PREMIUM_CACHE.clear()
    return get_premium_masters(data_dir)


class _LazyPremiumSet:
    """向後相容 shim — 讓 `masters & PREMIUM_MASTERS` 仍可運作, 且每次反映最新值.

    ⚠️ 不可繼承 frozenset: CPython 對 set/frozenset 子類的 `&` 走內建 C 實作
    而不呼叫 __rand__, 會導致 `some_set & PREMIUM_MASTERS` 靜默回空集合.
    改用純物件 + 完整 dunder 代理.
    """
    def _live(self):             return get_premium_masters()
    def __and__(self, o):        return self._live() & set(o)
    def __rand__(self, o):       return set(o) & self._live()
    def __or__(self, o):         return self._live() | set(o)
    def __ror__(self, o):        return set(o) | self._live()
    def __sub__(self, o):        return self._live() - set(o)
    def __rsub__(self, o):       return set(o) - self._live()
    def __contains__(self, x):   return x in self._live()
    def __iter__(self):          return iter(self._live())
    def __len__(self):           return len(self._live())
    def __bool__(self):          return bool(self._live())
    def __eq__(self, o):
        return (self._live() == set(o)
                if isinstance(o, (set, frozenset, _LazyPremiumSet)) else NotImplemented)
    def __hash__(self):          return hash(frozenset(self._live()))
    def issubset(self, o):       return self._live().issubset(o)
    def intersection(self, *o):  return self._live().intersection(*o)
    def union(self, *o):         return self._live().union(*o)
    def __repr__(self):          return repr(self._live())


PREMIUM_MASTERS = _LazyPremiumSet()


# ════════════════════════════════════════════════════════════════════
#  import 時驗證 — 打錯名字當場炸, 不留給 silent no-op
# ════════════════════════════════════════════════════════════════════
validate_master_names(LIMIT_UP_SNIPERS, 'LIMIT_UP_SNIPERS')
validate_master_names(TOP_BUYER_HIGHLIGHT_MASTERS, 'TOP_BUYER_HIGHLIGHT_MASTERS')


# ════════════════════════════════════════════════════════════════════
#  4. Premium 的「時點快照」— 回測專用, 不可用上面的動態值取代
# ════════════════════════════════════════════════════════════════════
#  ⚠️ 這一段是 P2 稽核中差點做錯的地方, 留下完整理由:
#
#  第一直覺是把 bootstrap_multiday_backtest.py 的硬編碼名單換成上面的動態
#  PREMIUM_MASTERS — 畢竟「單一真相來源」嘛. **但那樣會毀掉那支回測**.
#
#  原因: 回測用 master 名單去篩歷史 picks, 而該名單本身是**依績效挑出來的**.
#  用「今天算出來的」名單去篩「全部歷史」= 完整的 look-ahead —
#  等於先知道誰後來表現好, 再回頭說他們表現好.
#
#  該回測已有 IS/OOS 切分 (is_cutoff_date=20260624, 60/40),
#  而凍結名單是 2026-06-26 依當時資料選出的 → 對 cutoff 之後的 OOS 段
#  基本上是合法的前瞻測試. 換成動態名單 (資料到 2026-08-28) 會讓
#  整個 OOS 視窗都被污染, OOS 數字就失去意義.
#
#  → 回測要的是**時點快照 (point-in-time)**, 儀表板要的是**當前值**.
#    兩者都需要, 所以兩個都留, 但名字必須說清楚是哪一種.
PREMIUM_SNAPSHOT_DATE = '20260626'
PREMIUM_MASTERS_SNAPSHOT: Set[str] = {'陳律師', '竹科主力分點', '陳族元'}
#  當時的樣本 (n=6~18, 已知偏小): 竹科主力 9 picks 88.9% / 陳族元 6 picks 83.3%
#  / 陳律師 18 picks 77.8%. 2026-08-23 複查後三位全數反轉 → 這正是為何
#  **儀表板**不再用它 (v3.75.0 改動態), 但**回測**仍必須用它 (時點正確性).

validate_master_names(PREMIUM_MASTERS_SNAPSHOT, 'PREMIUM_MASTERS_SNAPSHOT')


def check_snapshot_leakage(is_cutoff_date: Optional[str]) -> Optional[str]:
    """回測 OOS 視窗是否早於快照日 → 該段有 look-ahead 污染.

    回傳警告字串, 沒問題則 None.
    """
    if not is_cutoff_date:
        return None
    if str(is_cutoff_date) < PREMIUM_SNAPSHOT_DATE:
        return (f"OOS 起點 {is_cutoff_date} 早於 premium 快照日 "
                f"{PREMIUM_SNAPSHOT_DATE} → {is_cutoff_date}~{PREMIUM_SNAPSHOT_DATE} "
                f"之間的 picks 屬 look-ahead 污染, OOS 數字需打折看待")
    return None
