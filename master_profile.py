"""
========================================================================
Module: master_profile.py  (v3.30.8 新增)
籌碼大戶深度操作分析 + 策略標籤 (規則式, 零 API 成本)

使用者要求 (5/29):
  個別針對每個籌碼大戶分析操作習慣 + 給策略操作之定義標籤。
  優先序: (1) 操作類型 → (2) 進出場規律 → (3) 績效面 → (4) 聯動面。

Phase 1 (本檔涵蓋, v3.30.8):
  維度 1 - 操作類型: 風格分布 (隔日沖/當沖/波段) + 漲停命中 + 集中度 + 一致性
  維度 2 - 進出場規律: 活躍天數比 + 週分布 + 連續性 (streaks)
Phase 2 (待後續, v3.31+):
  維度 3 - 績效面: 次日報酬 / 隔日沖勝率 / 漲停股 N 日後表現 (需 stock_history)
  維度 4 - 聯動面: 跟其他 master 同向率 / 共識個股 / 派系

分析對象: 15 個個人大戶 (排除外資法人 8 個 + 官股 2 個, 那些是法人單向流動,
              不適合「操作習慣」分類)

策略標籤 (規則式, 基於 metric 閾值):
  風格類: 漲停獵手 / 短打型 / 當沖客 / 波段囤貨
  集中度: 集中投資 / 分散布局
  一致性: 風格純粹 / 多變策略
  進出場: 高頻交易 / 精選出手 / 持續進場

CLI:
  CHIP_RADAR_PASSWORD=<prod> python master_profile.py
  python master_profile.py --window 28              # 自動偵測, 預設用全部可用
  python master_profile.py --master 蔣承翰          # 單一 debug
  python master_profile.py --data-dir data --output data/master_profiles.json

輸出 data/master_profiles.json:
  {
    "trade_date_range": ["20260421", "20260529"],
    "window_days": 28,
    "generated_at": "...",
    "masters": {
      "蔣承翰": {
        "declared_styles": ["next_day_flipper"],
        "operation_metrics": {...},
        "timing_metrics": {...},
        "strategy_labels": ["漲停獵手", "短打型", "集中投資"],
        "narrative": "..."
      },
      ...
    }
  }
========================================================================
"""
import os
import sys
import json
import argparse
import statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional, Tuple

TW_TZ = timezone(timedelta(hours=8))


# ════════════════════════════════════════════════════════════════════
#  常數: 個人大戶名單 + 規則閾值
# ════════════════════════════════════════════════════════════════════

# 排除外資 (foreign_ib) + 官股 (public) + 整家公司加總 (company_total) + 地緣特色分點 (area_hotspot)
# 只分析「個人大戶操作習慣」— 法人 / 公司 / 地緣熱點 都排除
EXCLUDED_STYLES = {'foreign_ib', 'public', 'company_total', 'area_hotspot'}


def get_individual_masters() -> Dict[str, List[str]]:
    """從 branches.py 取個人大戶 (排除法人/官股)"""
    try:
        from branches import MASTER_STYLES
        return {m: s for m, s in MASTER_STYLES.items()
                if not any(es in s for es in EXCLUDED_STYLES)}
    except ImportError:
        return {}


# 標籤閾值 — v3.31.10 一次性重校 (基於 32 天真實資料 + 業界印象反推)
# 校準前: 19 master 全部「📈長線持有/高頻交易/持續進場」一面倒, 沒區別
# 校準依據:
#   蔣承翰 21% 漲停 (業界主漲停獵手) → 應觸發
#   航海王/陳族元/民哥 11-14% 漲停 (不該觸發)
#   32 天樣本下 long_term_days=5 太短, streak_long=8 太低
THRESH = {
    'limit_up_hit_high': 0.18,        # 60% → 18% (蔣 21% / Tradow 20% / 優式 21% 觸發, 民哥 14% 不觸發)
    'style_dominant': 0.40,           # 50% → 40% (32 天合計 trade_style 自然分散, 放寬)
    'concentration_high': 35.0,       # 50% → 35% (32 天累積集中度自然降, 35% 算明顯集中)
    'concentration_low': 18.0,        # 20% → 18% (微調)
    'consistency_high': 0.65,         # 80% → 65% (放寬讓真主導風格 master 觸發風格純粹)
    'consistency_low': 0.40,          # 50% → 40%
    'active_ratio_high': 0.85,        # 不變 (高頻=幾乎天天動)
    'active_ratio_low': 0.4,          # 不變
    'streak_long': 15,                # 8 → 15 (32 天下大多有 8+ 連續, 15+ 才算明顯節奏)
    # v3.30.9: 鎖漲停 + 長線持有
    'locked_at_lu_tolerance': 0.99,   # 不變
    'locked_at_lu_ratio_amt': 0.15,   # 30% → 15% (蔣承翰 19% 鎖漲停/total, 15% 閾值讓他觸發)
    'long_term_days_threshold': 15,   # 5 → 15 (5 天太短, 32 天/2 ≈ 15)
    'long_term_amt_ratio': 0.65,      # 50% → 65% (更嚴, 配合天數放寬)
    # v3.30.11: 族群專家
    'top_industry_pct_high': 60.0,    # 不變
    # v3.30.13: 處置股獵手
    'disposal_amt_ratio_high': 0.30,  # 不變
}


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


# ════════════════════════════════════════════════════════════════════
#  v3.30.9 helpers — 鎖漲停 + 長線持有
# ════════════════════════════════════════════════════════════════════

def _build_stock_close_map(data_dir: str) -> Optional[Dict[str, Dict[str, float]]]:
    """v3.31.11: 從 stock_history.json 建 {code: {date: close}} map.
    給 _derive_limit_up_price 查前一日 close → tick-size 算精確漲停價."""
    p = Path(data_dir) / 'stock_history.json'
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            d = json.load(f)
        out = {}
        for code, info in d.get('stocks', {}).items():
            if isinstance(info, dict):
                daily = info.get('daily', {})
                if isinstance(daily, dict):
                    out[code] = {date: rec.get('close')
                                 for date, rec in daily.items()
                                 if isinstance(rec, dict) and rec.get('close')}
        return out if out else None
    except Exception:
        return None


def _derive_limit_up_price(stock: Dict[str, Any],
                            stock_close_map: Optional[Dict[str, Dict[str, float]]] = None,
                            trade_date: Optional[str] = None) -> Optional[float]:
    """從 stock dict 推算當日漲停價 (元/股).
    v3.31.11: 加 stock_close_map + trade_date, 用前一日 close 推算 (解 stock dict 缺欄位問題).
    優先順序: 直接欄位 limit_up_price → stock 內 prev_close →
              stock_close_map 找 prev_close → None."""
    lu = stock.get('limit_up_price')
    if lu and lu > 0:
        return float(lu)
    prev = stock.get('prev_close')
    if prev and prev > 0:
        try:
            from price_utils import calc_limit_up_price
            return float(calc_limit_up_price(float(prev)))
        except Exception:
            return float(prev) * 1.10
    # v3.31.11: 從 stock_close_map 找前一日 close
    if stock_close_map and trade_date:
        code = stock.get('code') or stock.get('stock_code')  # v3.31.12 fix: trade dict 用 stock_code
        if code and code in stock_close_map:
            days = sorted(d for d in stock_close_map[code] if d < trade_date)
            if days:
                pc = stock_close_map[code][days[-1]]
                if pc and pc > 0:
                    try:
                        from price_utils import calc_limit_up_price
                        return float(calc_limit_up_price(float(pc)))
                    except Exception:
                        return float(pc) * 1.10
    return None


def _is_locked_at_lu(stock: Dict[str, Any], tolerance: float = 0.99,
                      stock_close_map: Optional[Dict[str, Dict[str, float]]] = None,
                      trade_date: Optional[str] = None) -> bool:
    """判定該筆 trade 是否在漲停價附近成交 (買均 ≥ 漲停價 × tolerance).
    v3.31.11: 加 stock_close_map + trade_date 傳遞給 _derive_limit_up_price."""
    buy_lot = stock.get('buy_lot', 0) or 0
    buy_amt = stock.get('buy_amt', 0) or 0
    if buy_lot <= 0 or buy_amt <= 0:
        return False
    buy_avg = buy_amt / buy_lot
    lu_price = _derive_limit_up_price(stock, stock_close_map, trade_date)
    if not lu_price or lu_price <= 0:
        return False
    return buy_avg >= lu_price * tolerance


def _compute_industry_metrics(trades: List[Dict[str, Any]],
                                stock_industry_map: Optional[Dict[str, str]]
                                ) -> Optional[Dict[str, Any]]:
    """v3.30.11: 族群集中度. 用 industry_classifier 的 stock_industry 反查表.
    回傳: {top_industry, top_industry_pct, industry_count, top3_industries}
    或 None (無資料 / 無分類表)."""
    if not trades or not stock_industry_map:
        return None
    industry_amt = defaultdict(int)
    total_amt = 0
    for t in trades:
        code = t.get('stock_code')
        amt = t.get('buy_amt', 0) or 0
        industry = stock_industry_map.get(code, '未分類')
        industry_amt[industry] += amt
        total_amt += amt
    if total_amt == 0:
        return None
    sorted_ind = sorted(industry_amt.items(), key=lambda x: -x[1])
    top_industry, top_amt = sorted_ind[0]
    return {
        'top_industry': top_industry,
        'top_industry_pct': round(top_amt / total_amt * 100, 1),
        'industry_count': len(industry_amt),
        'top3_industries': [
            {'name': name, 'pct': round(amt / total_amt * 100, 1)}
            for name, amt in sorted_ind[:3]
        ],
    }


def _compute_disposal_metrics(trades: List[Dict[str, Any]],
                                disposal_codes: Optional[set]) -> Optional[Dict[str, Any]]:
    """v3.30.13: 處置股買進占比 (風險偏好維度).
    disposal_codes: 當前窗口內被處置/即將處置的個股 set (from chengwaye).
    回傳: {disposal_stocks_count, disposal_amt_ratio} 或 None (無資料/無 set)."""
    if not trades or not disposal_codes:
        return None
    disposal_amt = 0
    disposal_codes_seen = set()
    total_amt = 0
    for t in trades:
        amt = t.get('buy_amt', 0) or 0
        total_amt += amt
        code = t.get('stock_code')
        if code and code in disposal_codes:
            disposal_amt += amt
            disposal_codes_seen.add(code)
    if total_amt == 0:
        return None
    return {
        'disposal_stocks_count': len(disposal_codes_seen),
        'disposal_amt_ratio': round(disposal_amt / total_amt, 3),
    }


def _compute_long_term_metrics(trades: List[Dict[str, Any]],
                                 days_threshold: int) -> Tuple[int, float]:
    """單檔在窗口內被加碼 ≥ N 天 → 長線持倉。
    回傳: (長線股數, 長線金額占比)."""
    if not trades:
        return 0, 0.0
    # 對每檔 stock 算被加碼的不重複日數
    stock_days = defaultdict(set)
    stock_amt = defaultdict(int)
    for t in trades:
        c = t.get('stock_code')
        if c:
            stock_days[c].add(t['date'])
            stock_amt[c] += t['buy_amt']
    long_term_stocks = {c for c, days in stock_days.items() if len(days) >= days_threshold}
    long_term_amt = sum(stock_amt[c] for c in long_term_stocks)
    total_amt = sum(stock_amt.values())
    ratio = (long_term_amt / total_amt) if total_amt else 0.0
    return len(long_term_stocks), round(ratio, 3)


# ════════════════════════════════════════════════════════════════════
#  歷史載入 (解密)
# ════════════════════════════════════════════════════════════════════

def load_history(data_dir: str, window_days: Optional[int], password: str) -> List[Dict[str, Any]]:
    """
    讀最近 window_days 天 daily JSON, 解密.
    v3.31.9: 同時掃 data/*.json (hot) + data/archive/*.json (warm) + *.json.gz (cold)
             解決 v3.31.6 archive 整合後 hot 區只剩 5 天的副作用.

    Args:
        data_dir: data/ 路徑
        window_days: None 表示用所有可用 (使用者選的「最大可搜尋窗口」)
        password: CHIP_RADAR_PASSWORD
    Returns:
        [{'date': 'YYYYMMDD', 'data': {<解密後資料>}}, ...] 依日期升序
    """
    data_path = Path(data_dir)
    archive_path = data_path / 'archive'
    # hot + warm + cold 三層全掃
    files = []
    files.extend(data_path.glob('[0-9]' * 8 + '.json'))
    if archive_path.exists():
        files.extend(archive_path.glob('[0-9]' * 8 + '.json'))
        files.extend(archive_path.glob('[0-9]' * 8 + '.json.gz'))
    # 依檔名(YYYYMMDD)排序; .json.gz 也含同樣 8 字
    files = sorted(files, key=lambda p: p.stem.replace('.json', ''))
    if window_days is not None:
        files = files[-window_days:]

    history = []
    skipped = 0
    invalid_tag_count = 0
    for f in files:
        try:
            # v3.31.9: 支援 .json.gz cold 區
            if f.suffix == '.gz':
                import gzip
                with gzip.open(f, 'rt', encoding='utf-8') as fh:
                    enc = json.load(fh)
            else:
                with open(f, 'r', encoding='utf-8') as fh:
                    enc = json.load(fh)
            if enc.get('encrypted'):
                from crawler import decrypt_data
                plaintext = decrypt_data(enc['data'], password)
                data = json.loads(plaintext)
            else:
                data = enc.get('data', enc)
            # v3.31.9: .json.gz → stem = YYYYMMDD.json, 要再 strip 一次
            date_stem = f.stem.replace('.json', '') if f.suffix == '.gz' else f.stem
            history.append({'date': date_stem, 'data': data})
        except Exception as e:
            # v3.30.10: 印 exception type (避免「⚠️ 跳過 ...: 」空白訊息)
            type_name = type(e).__name__
            detail = f': {e}' if str(e) else ''
            print(f"  ⚠️ 跳過 {f.name}: {type_name}{detail}", file=sys.stderr)
            if type_name == 'InvalidTag':
                invalid_tag_count += 1
            skipped += 1
    if skipped:
        print(f"  總計跳過 {skipped} 個檔案 (解密失敗或結構錯)", file=sys.stderr)
        if invalid_tag_count >= max(3, len(files) // 2):
            print(f"  🔑 提示: {invalid_tag_count} 個 InvalidTag = 密碼錯誤。"
                  f"確認 CHIP_RADAR_PASSWORD 是 production 真密碼"
                  f" (不是 <...> 占位符)", file=sys.stderr)
    return history


# ════════════════════════════════════════════════════════════════════
#  抽取 master 交易紀錄
# ════════════════════════════════════════════════════════════════════

def _list_master_branches(history: List[Dict[str, Any]],
                           master_name: str) -> Dict[str, str]:
    """v3.30.12: 掃 history 找該 master 出現的所有分點 (含 co_masters 共用).
    回傳 {branch_code: branch_name}."""
    branches: Dict[str, str] = {}
    for day in history:
        for br in day['data'].get('branches', []):
            br_master = br.get('master')
            co = br.get('co_masters') or []
            if br_master == master_name or master_name in co:
                code = br.get('code')
                if code:
                    branches[code] = br.get('name', '')
    return branches


def extract_master_trades(history: List[Dict[str, Any]],
                          master_name: str,
                          branch_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """從歷史抽出該 master 所有買進紀錄 (含 co_masters 共用分點的情境).
    v3.30.12: branch_code 非 None 時只抽該分點 (per-branch 細分用)."""
    trades = []
    for day in history:
        for br in day['data'].get('branches', []):
            if branch_code is not None and br.get('code') != branch_code:
                continue
            br_master = br.get('master')
            co = br.get('co_masters') or []
            if br_master != master_name and master_name not in co:
                continue
            for stock in (br.get('buys') or []):
                trades.append({
                    'date': day['date'],
                    'branch_code': br.get('code'),
                    'stock_code': str(stock.get('code') or ''),
                    'stock_name': stock.get('name') or '',
                    'buy_lot': stock.get('buy_lot', 0) or 0,
                    'sell_lot': stock.get('sell_lot', 0) or 0,
                    'buy_amt': stock.get('buy_amt', 0) or 0,  # 仟元
                    'sell_amt': stock.get('sell_amt', 0) or 0,
                    'is_limit_up': bool(stock.get('is_limit_up', False)),
                    'trade_style': stock.get('trade_style', 'unknown'),  # daytrade/partial/overnight
                })
    return trades


# ════════════════════════════════════════════════════════════════════
#  維度 1: 操作類型 metrics (最高優先)
# ════════════════════════════════════════════════════════════════════

def compute_operation_metrics(trades: List[Dict[str, Any]],
                                stock_industry_map: Optional[Dict[str, str]] = None,
                                disposal_codes: Optional[set] = None,
                                stock_close_map: Optional[Dict[str, Dict[str, float]]] = None
                                ) -> Optional[Dict[str, Any]]:
    """風格分布 + 漲停命中 + 集中度 + 一致性 + (v3.30.11) 族群集中度
       + (v3.30.13) 處置股風險偏好 + (v3.31.11) 鎖漲停用 stock_close_map.
    optional 參數 None 時跳過對應計算 (向後相容)."""
    if not trades:
        return None
    total = len(trades)

    # trade_style 分布 (來自 crawler merge_rows 計算的 daytrade_ratio 判定)
    style_count = Counter(t.get('trade_style', 'unknown') for t in trades)
    daytrade = style_count.get('daytrade', 0) / total       # 當沖
    partial = style_count.get('partial', 0) / total          # 部分當沖 (近似隔日沖)
    overnight = style_count.get('overnight', 0) / total      # 留倉 (波段)

    # 漲停命中
    limit_up_hit = sum(1 for t in trades if t['is_limit_up']) / total

    # 集中度: 前 5 大個股佔該 master 總買進金額 %
    stock_amt = defaultdict(int)
    for t in trades:
        if t['stock_code']:
            stock_amt[t['stock_code']] += t['buy_amt']
    total_amt = sum(stock_amt.values())
    top5_sum = sum(sorted(stock_amt.values(), reverse=True)[:5])
    concentration = (top5_sum / total_amt * 100) if total_amt else 0.0

    # 一致性 (主導風格佔比)
    consistency = max(daytrade, partial, overnight) if total else 0.0

    # v3.30.9 / v3.31.11: 🔒 鎖漲停 metric (每 trade 傳 stock_close_map + 該 trade 的 date)
    locked_trades = [t for t in trades
                     if _is_locked_at_lu(t, THRESH['locked_at_lu_tolerance'],
                                          stock_close_map=stock_close_map,
                                          trade_date=t.get('date'))]
    locked_amt = sum(t['buy_amt'] for t in locked_trades)
    locked_lot = sum(t['buy_lot'] for t in locked_trades)
    total_lot = sum(t['buy_lot'] for t in trades)
    locked_ratio_amt = (locked_amt / total_amt) if total_amt else 0.0
    locked_ratio_lot = (locked_lot / total_lot) if total_lot else 0.0

    # v3.30.9: 📈 長線持有 metric (單檔被加碼 ≥ N 天)
    long_term_stocks_count, long_term_amt_ratio = _compute_long_term_metrics(
        trades, THRESH['long_term_days_threshold']
    )

    # v3.30.11: 🎯 族群專家 metric (用 industry_classifier)
    industry_metrics = _compute_industry_metrics(trades, stock_industry_map)

    # v3.30.13: ⚠️ 處置股獵手 metric (用 chengwaye disposal-forecast)
    disposal_metrics = _compute_disposal_metrics(trades, disposal_codes)

    result = {
        'trades_count': total,
        'unique_stocks': len(stock_amt),
        'daytrade_ratio': round(daytrade, 3),
        'partial_ratio': round(partial, 3),       # 近似隔日沖
        'overnight_ratio': round(overnight, 3),    # 波段/留倉
        'limit_up_hit_ratio': round(limit_up_hit, 3),
        'concentration_top5_pct': round(concentration, 1),
        'consistency': round(consistency, 3),
        'total_buy_amt_wan': round(total_amt / 10),   # 仟元轉萬元
        # v3.30.9: 鎖漲停精度
        'limit_up_locked_trades_count': len(locked_trades),
        'limit_up_locked_ratio_amt': round(locked_ratio_amt, 3),
        'limit_up_locked_ratio_lot': round(locked_ratio_lot, 3),
        # v3.30.9: 長線 vs 中短期波段拆分
        'long_term_stocks_count': long_term_stocks_count,
        'long_term_amt_ratio': long_term_amt_ratio,
    }
    if industry_metrics:
        result.update(industry_metrics)   # top_industry / top_industry_pct / industry_count / top3_industries
    if disposal_metrics:
        result.update(disposal_metrics)   # disposal_stocks_count / disposal_amt_ratio
    return result


# ════════════════════════════════════════════════════════════════════
#  維度 2: 進出場時機規律 metrics
# ════════════════════════════════════════════════════════════════════

def compute_timing_metrics(trades: List[Dict[str, Any]],
                            total_days: int) -> Optional[Dict[str, Any]]:
    """活躍天數比 + 週分布 + 連續性 (streaks)."""
    if not trades:
        return None

    trade_dates = sorted(set(t['date'] for t in trades))
    active_days = len(trade_dates)
    active_ratio = (active_days / total_days) if total_days else 0.0
    avg_trades_per_active = (len(trades) / active_days) if active_days else 0.0

    # 週分布 (Mon=0..Sun=6, 應只看週一-五)
    weekday_count = Counter()
    parsed = []
    for d in trade_dates:
        try:
            dt = datetime.strptime(d, '%Y%m%d')
            weekday_count[dt.weekday()] += 1
            parsed.append(dt)
        except ValueError:
            continue
    weekday_names = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
    weekday_dist = {weekday_names[i]: weekday_count.get(i, 0) for i in range(5)}

    # streaks (持續進場): 兩筆交易日間隔 ≤ 3 天視為連續 (跨週末)
    parsed.sort()
    streaks = []
    cur = 1
    for i in range(1, len(parsed)):
        diff = (parsed[i] - parsed[i - 1]).days
        if diff <= 3:
            cur += 1
        else:
            streaks.append(cur)
            cur = 1
    streaks.append(cur)

    return {
        'active_days': active_days,
        'total_window_days': total_days,
        'active_days_ratio': round(active_ratio, 3),
        'avg_trades_per_active_day': round(avg_trades_per_active, 1),
        'weekday_distribution': weekday_dist,
        'max_streak_days': max(streaks) if streaks else 0,
        'avg_streak_days': round(statistics.mean(streaks), 1) if streaks else 0.0,
        'streak_count': len(streaks),
    }


# ════════════════════════════════════════════════════════════════════
#  策略標籤 (規則式, 透明可調)
# ════════════════════════════════════════════════════════════════════

def generate_labels(op: Dict[str, Any], timing: Dict[str, Any],
                     declared_styles: Optional[List[str]] = None,
                     cross_day: Optional[Dict[str, Any]] = None) -> List[str]:
    """基於 metric 閾值規則生成標籤.
    v3.31.13: declared_styles 參數
    v3.31.23 C2: cross_day 參數 — T+1 真實 flip_ratio 自動判定風格
      actual_flip_ratio > 0.45 → 「隔日沖(verified)」(取代 declared override)
      actual_flip_ratio < 0.20 → 確認波段/長線 (不加隔日沖標籤)"""
    labels = []
    declared = set(declared_styles or [])
    flip_ratio = cross_day.get('actual_flip_ratio', 0) if cross_day else 0

    # 風格主導 (互斥, 取最強)
    if op['limit_up_hit_ratio'] > THRESH['limit_up_hit_high']:
        labels.append('漲停獵手')

    # v3.30.9: 🔒 鎖漲停 — 真實在漲停價成交 (vs 漲停獵手只看當日是否漲停股)
    # 跟「漲停獵手」獨立, 可共存 (蔣承翰兩者都觸發, 迷你哥可能只「漲停獵手」)
    if op.get('limit_up_locked_ratio_amt', 0) > THRESH['locked_at_lu_ratio_amt']:
        labels.append('🔒 鎖漲停')

    style_assigned = False
    if op['daytrade_ratio'] > THRESH['style_dominant']:
        labels.append('當沖客')
        style_assigned = True
    elif op['partial_ratio'] > THRESH['style_dominant']:
        labels.append('短打型')          # 近似隔日沖
        style_assigned = True
    elif op['overnight_ratio'] > THRESH['style_dominant']:
        # v3.30.9: 拆波段 vs 長線
        if op.get('long_term_amt_ratio', 0) > THRESH['long_term_amt_ratio']:
            labels.append('📈 長線持有')
        # v3.31.23 C3: 「波段囤貨(中短期)」改預設不標 — 19/29 master 都有=沒區別力
        # 波段是 default 行為, 只標「特殊」風格 (漲停/當沖/長線/族群)
        # 但保留 style_assigned 讓 declared override 不誤觸發
        style_assigned = True

    # v3.31.13: declared style override — TWSE 分點資料結構性限制修補
    # 迷你哥在 A 分點買 B 管道賣 → sell_lot=0 → daytrade_ratio=0 → 被判 overnight
    # 業界知識: declared day_trader → 強制加「當沖客(declared)」
    if not style_assigned or ('day_trader' in declared and '當沖客' not in labels):
        if 'day_trader' in declared and '當沖客' not in labels:
            labels.append('當沖客(declared)')
    if 'next_day_flipper' in declared and '短打型' not in labels and '當沖客' not in labels and '當沖客(declared)' not in labels:
        labels.append('短打型(declared)')

    # v3.31.23 C2: T+1 verified 風格 (用真實 sells 驗證, 優先度最高)
    if flip_ratio >= 0.45 and '隔日沖(verified)' not in labels:
        labels.append('隔日沖(verified)')    # 航海王 55.8% / 陳族元 48.5% 觸發
    elif flip_ratio >= 0.35:
        labels.append('混合進出')            # 蔣承翰 42.9% / 迷你哥 41.3%

    # 集中度
    if op['concentration_top5_pct'] > THRESH['concentration_high']:
        labels.append('集中投資')
    elif op['concentration_top5_pct'] < THRESH['concentration_low']:
        labels.append('分散布局')

    # 一致性
    if op['consistency'] > THRESH['consistency_high']:
        labels.append('風格純粹')
    elif op['consistency'] < THRESH['consistency_low']:
        labels.append('多變策略')

    # 進出場
    if timing['active_days_ratio'] > THRESH['active_ratio_high']:
        labels.append('高頻交易')
    elif timing['active_days_ratio'] < THRESH['active_ratio_low']:
        labels.append('精選出手')

    if timing['max_streak_days'] > THRESH['streak_long']:
        labels.append('持續進場')

    # v3.30.11: 🎯 族群專家 (獨立, 跟其他標籤都可共存; 族群名在 narrative)
    if op.get('top_industry_pct', 0) > THRESH['top_industry_pct_high']:
        labels.append('🎯 族群專家')

    # v3.30.13: ⚠️ 處置股獵手 (獨立, 風險偏好維度, 可與所有標籤共存)
    if op.get('disposal_amt_ratio', 0) > THRESH['disposal_amt_ratio_high']:
        labels.append('⚠️ 處置股獵手')

    return labels


# ════════════════════════════════════════════════════════════════════
#  模板 narrative (v3.30.0 同風格, 規則式 50-100 字)
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  v3.31.16: 標籤分層體系 (Level 1 / 2 / 3)
# ════════════════════════════════════════════════════════════════════

# Level 1: 操作大類 (3 分類, 按標籤歸屬)
LABEL_L1_MAP = {
    # 攻擊型: 主動追求超額報酬
    '漲停獵手': '攻擊型', '🔒 鎖漲停': '攻擊型',
    '當沖客': '攻擊型', '當沖客(declared)': '攻擊型',
    '短打型': '攻擊型', '短打型(declared)': '攻擊型',
    '⚠️ 處置股獵手': '攻擊型',
    # 防守型: 穩定持倉 + 風格穩定 (v3.31.23: 波段囤貨移除, 波段是 default 不標)
    '📈 長線持有': '防守型',
    '集中投資': '防守型', '風格純粹': '防守型',
    # 攻擊型 (續): 主動進出場
    '高頻交易': '攻擊型', '精選出手': '攻擊型',
    # 觀察型: 風格/族群/節奏特徵
    '持續進場': '觀察型', '分散布局': '觀察型',
    '🎯 族群專家': '觀察型', '多變策略': '觀察型',
}

# Level 2: 策略子類 (根據標籤組合判定)
def classify_strategy_l2(labels: List[str]) -> str:
    """根據 Level 1 標籤組合 → Level 2 策略子類."""
    s = set(labels)
    # 攻擊型子分類
    if ('漲停獵手' in s or '🔒 鎖漲停' in s) and ('當沖客' in s or '當沖客(declared)' in s):
        return '漲停當沖策略'       # 迷你哥式: 追漲停 + 當沖進出
    if ('漲停獵手' in s or '🔒 鎖漲停' in s) and ('短打型' in s or '短打型(declared)' in s):
        return '漲停鎖定策略'       # 蔣承翰/Tradow式: 鎖漲停 + 隔日沖
    if '漲停獵手' in s and '🔒 鎖漲停' in s:
        return '漲停鎖定策略'       # v3.31.17: 漲停獵手+鎖漲停 = 鎖定策略 (優式資本式: +7%鎖漲停)
    if '漲停獵手' in s or '🔒 鎖漲停' in s:
        return '漲停追擊策略'       # 只有一個 → 追擊 (非鎖定)
    if '⚠️ 處置股獵手' in s:
        return '高風險偏好策略'     # 重度押注處置/注意股
    # 防守型子分類
    if '📈 長線持有' in s and '集中投資' in s:
        return '長線集中持股'
    if '📈 長線持有' in s:
        return '長線分散持股'
    if '集中投資' in s:
        return '波段集中操作'
    # v3.31.23: 波段不再標 label, 但策略子類仍需判
    # 沒有任何特殊風格標籤 = default 波段輪動
    # 觀察型
    if '🎯 族群專家' in s:
        return '族群深耕策略'       # 專注單一族群
    if '多變策略' in s:
        return '彈性多變操作'       # 無固定主軸
    return '一般操作'


def build_label_hierarchy(labels: List[str], op: Dict[str, Any]) -> Dict[str, Any]:
    """v3.31.16: 組 Level 1/2/3 標籤分層結構."""
    # Level 1: 按大類分組
    l1_groups = {'攻擊型': [], '防守型': [], '觀察型': []}
    for label in labels:
        cat = LABEL_L1_MAP.get(label, '觀察型')
        l1_groups[cat].append(label)
    # 移除空 group
    l1_groups = {k: v for k, v in l1_groups.items() if v}

    # Level 2: 策略子類
    l2_strategy = classify_strategy_l2(labels)

    # Level 3: 個人操作 DNA (關鍵 metrics 直接帶)
    l3_dna = {
        'locked_pct': op.get('limit_up_locked_ratio_amt', 0),
        'limit_up_pct': op.get('limit_up_hit_ratio', 0),
        'concentration_pct': op.get('concentration_top5_pct', 0),
        'top_industry': op.get('top_industry'),
        'top_industry_pct': op.get('top_industry_pct', 0),
        'disposal_pct': op.get('disposal_amt_ratio', 0),
        'consistency': op.get('consistency', 0),
    }

    return {
        'level1_groups': l1_groups,
        'level2_strategy': l2_strategy,
        'level3_dna': l3_dna,
    }


def generate_narrative(master_name: str,
                       op: Dict[str, Any],
                       timing: Dict[str, Any],
                       labels: List[str]) -> str:
    """50-100 字模板 narrative."""
    style_parts = []
    if op['partial_ratio'] >= 0.1:
        style_parts.append(f"隔日沖近似 {op['partial_ratio'] * 100:.0f}%")
    if op['daytrade_ratio'] >= 0.1:
        style_parts.append(f"當沖 {op['daytrade_ratio'] * 100:.0f}%")
    if op['overnight_ratio'] >= 0.1:
        style_parts.append(f"留倉 {op['overnight_ratio'] * 100:.0f}%")
    style_str = " / ".join(style_parts) if style_parts else "風格不明"

    label_str = "/".join(labels[:4]) if labels else "未明"

    # v3.30.9: 鎖漲停精度補充說明
    lu_hit = op['limit_up_hit_ratio'] * 100
    lu_lock = op.get('limit_up_locked_ratio_amt', 0) * 100
    lu_part = (f"漲停命中 {lu_hit:.0f}% (其中 🔒鎖漲停 {lu_lock:.0f}%)"
               if lu_hit > 0 else "漲停命中 0%")

    # v3.30.9: 長線部位補充
    lt_ratio = op.get('long_term_amt_ratio', 0) * 100
    lt_n = op.get('long_term_stocks_count', 0)
    lt_part = (f", 長線部位 {lt_ratio:.0f}% ({lt_n} 檔)" if lt_n > 0 else "")

    # v3.30.11: 族群主攻補充 (族群名在這顯示, 標籤本身固定為「🎯 族群專家」)
    # v3.31.11: 顯示閾值 30% → 50% (32 天樣本下半導體業 40-57% 太普遍, 太低會誤導)
    top_ind = op.get('top_industry')
    top_ind_pct = op.get('top_industry_pct', 0)
    ind_part = (f", 主攻 {top_ind} ({top_ind_pct:.0f}%)"
                if top_ind and top_ind_pct > 50 else "")

    # v3.30.13: 處置股部位補充 (高風險偏好揭露)
    disp_ratio = op.get('disposal_amt_ratio', 0) * 100
    disp_n = op.get('disposal_stocks_count', 0)
    disp_part = (f", ⚠️ 處置股部位 {disp_ratio:.0f}% ({disp_n} 檔)"
                 if disp_n > 0 else "")

    return (
        f"{master_name} 近 {timing['active_days']}/{timing['total_window_days']} 交易日出手 "
        f"{op['trades_count']} 次 ({op['unique_stocks']} 檔), "
        f"風格分布: {style_str}, {lu_part}, "
        f"前 5 大集中 {op['concentration_top5_pct']:.0f}%{lt_part}{ind_part}{disp_part}。"
        f" 主軸: {label_str}。"
    )


# ════════════════════════════════════════════════════════════════════
#  組裝單一 master profile
# ════════════════════════════════════════════════════════════════════

def build_master_profile(master_name: str,
                          history: List[Dict[str, Any]],
                          master_styles: Dict[str, List[str]],
                          stock_industry_map: Optional[Dict[str, str]] = None,
                          branch_filter: Optional[str] = None,
                          disposal_codes: Optional[set] = None,
                          stock_close_map: Optional[Dict[str, Dict[str, float]]] = None
                          ) -> Dict[str, Any]:
    """組一個 master 的完整 profile.
    stock_industry_map (v3.30.11): code → 產業名稱反查表, 算 🎯族群專家用。
    branch_filter (v3.30.12): 非 None 時只算該分點 (per-branch 細分用,
                              且不再遞迴算 per_branch_profiles 截斷遞迴)。
    disposal_codes (v3.30.13): 處置股 code set (from chengwaye), 算 ⚠️處置股獵手用。"""
    trades = extract_master_trades(history, master_name, branch_code=branch_filter)
    declared = master_styles.get(master_name, [])

    if not trades:
        result = {
            'master': master_name,
            'declared_styles': declared,
            'no_data': True,
            'narrative': f"{master_name} 在窗口內無交易紀錄。",
        }
        if branch_filter:
            result['branch_filter'] = branch_filter
        return result

    op = compute_operation_metrics(trades, stock_industry_map, disposal_codes,
                                    stock_close_map=stock_close_map)
    timing = compute_timing_metrics(trades, len(history))
    # v3.31.23: 算 cross_day 給 generate_labels 用 (T+1 verified)
    _cd = None
    try:
        from cross_day_tracker import compute_cross_day_metrics
        _cd = compute_cross_day_metrics(history, master_name, master_styles)
    except Exception:
        pass
    labels = generate_labels(op, timing, declared_styles=declared, cross_day=_cd)
    narrative = generate_narrative(master_name, op, timing, labels)
    label_hierarchy = build_label_hierarchy(labels, op)

    result = {
        'master': master_name,
        'declared_styles': declared,
        'operation_metrics': op,
        'timing_metrics': timing,
        'strategy_labels': labels,
        'label_hierarchy': label_hierarchy,
        'narrative': narrative,
    }
    if branch_filter:
        result['branch_filter'] = branch_filter

    # v3.30.12: per-branch 細分 (僅 master 整體層級, 且該 master 有 >1 分點時)
    # 解盲點 #5 — 巨人傑等雙風格 master 在不同分點各自可能是純風格
    if branch_filter is None:
        branches = _list_master_branches(history, master_name)
        if len(branches) > 1:
            per_branch = {}
            for code, name in branches.items():
                bp = build_master_profile(
                    master_name, history, master_styles,
                    stock_industry_map=stock_industry_map,
                    branch_filter=code,
                    disposal_codes=disposal_codes,
                    stock_close_map=stock_close_map,
                )
                bp['branch_name'] = name
                per_branch[code] = bp
            result['per_branch_profiles'] = per_branch
            result['per_branch_count'] = len(per_branch)

    return result


# ════════════════════════════════════════════════════════════════════
#  主跑函式
# ════════════════════════════════════════════════════════════════════

def build_all_profiles(history: List[Dict[str, Any]],
                        master_filter: Optional[str] = None,
                        data_dir: str = 'data') -> Dict[str, Any]:
    """對所有個人大戶建 profile.
    v3.30.11: 自動載入 industry_map (用於🎯族群專家). 失敗則跳過 (向後相容)."""
    indiv = get_individual_masters()
    targets = {master_filter: indiv.get(master_filter, [])} if master_filter else indiv

    # 載入產業對照表 (v3.30.11)
    stock_industry_map = None
    try:
        from industry_classifier import get_industry_map
        from pathlib import Path
        ind_data = get_industry_map(Path(data_dir))
        stock_industry_map = ind_data.get('stock_industry') if ind_data else None
        if stock_industry_map:
            print(f"  [Industry] 載入 {len(stock_industry_map)} 檔產業分類")
    except Exception as e:
        print(f"  ⚠️ industry_classifier 載入失敗 (跳過族群分析): {type(e).__name__}: {e}",
              file=sys.stderr)

    # 載入處置股清單 (v3.30.13)
    disposal_codes = None
    try:
        from disposal_fetcher import get_disposal_map
        disposal_data = get_disposal_map(data_dir)
        disposal_codes = disposal_data.get('all_risky') if disposal_data else None
        if disposal_codes:
            print(f"  [Disposal] 載入 {len(disposal_codes)} 檔處置/即將處置股 "
                  f"(來源 chengwaye disposal-forecast)")
    except Exception as e:
        print(f"  ⚠️ disposal_fetcher 載入失敗 (跳過處置股分析): {type(e).__name__}: {e}",
              file=sys.stderr)

    # 載入個股 close 歷史 (v3.31.11) — 給 _is_locked_at_lu 推前一日 close
    stock_close_map = _build_stock_close_map(data_dir)
    if stock_close_map:
        print(f"  [Stock Close] 載入 {len(stock_close_map)} 檔個股 close 歷史 (給 🔒鎖漲停用)")

    # v3.31.11 修盲點: 動態用當下 branches.py 的 WATCHED_BRANCHES 覆寫歷史 raw_output 的 master 欄位
    # (解 6/03 前 daily.json 仍對應「迷你哥」9200/9600 等舊 declared 的問題)
    try:
        from branches import WATCHED_BRANCHES
        br_master_map = {b['code']: (b.get('master'), b.get('co_masters') or [])
                         for b in WATCHED_BRANCHES if b.get('code')}
        overridden = 0
        for day in history:
            for br in day['data'].get('branches', []):
                code = br.get('code')
                if code in br_master_map:
                    new_master, new_co = br_master_map[code]
                    if br.get('master') != new_master or (br.get('co_masters') or []) != new_co:
                        br['master'] = new_master
                        br['co_masters'] = new_co
                        overridden += 1
        if overridden:
            print(f"  [Master Override] 用當下 branches.py 覆寫 {overridden} 筆歷史 branch master "
                  f"(解 v3.31.7 拆 9200/9600 後歷史對應問題)")
    except Exception as e:
        print(f"  ⚠️ master override 失敗: {type(e).__name__}: {e}", file=sys.stderr)

    masters_out = {}
    for m in targets:
        masters_out[m] = build_master_profile(m, history, indiv,
                                               stock_industry_map=stock_industry_map,
                                               disposal_codes=disposal_codes,
                                               stock_close_map=stock_close_map)

    # v3.31.19: Phase 2 聯動面 — master × master 同向率 + 派系
    alliance_data = None
    try:
        from master_alliance import compute_alliance_matrix, format_alliance_summary
        alliance_data = compute_alliance_matrix(history, indiv)
        print(format_alliance_summary(alliance_data))
    except Exception as e:
        print(f"  ⚠️ 聯動面計算失敗: {type(e).__name__}: {e}", file=sys.stderr)

    # v3.31.22: T+1 跨日追蹤 — 用真實 sells 驗證隔日沖/留倉
    cross_day_data = None
    try:
        from cross_day_tracker import compute_all_cross_day, format_cross_day_table
        cross_day_data = compute_all_cross_day(history, indiv)
        if cross_day_data:
            print(format_cross_day_table(cross_day_data))
    except Exception as e:
        print(f"  ⚠️ T+1 追蹤失敗: {type(e).__name__}: {e}", file=sys.stderr)

    # v3.32.0: 實戰信號 (異常+共識+連續加碼)
    trading_signals = None
    try:
        from daily_signals import compute_daily_signals, format_daily_signals
        faction_list = alliance_data.get('factions', []) if alliance_data else []
        trading_signals = compute_daily_signals(history, indiv, factions=faction_list)
        if trading_signals:
            print(format_daily_signals(trading_signals))
            # 存 daily_trading_signals.json
            sig_path = Path(data_dir) / 'daily_trading_signals.json'
            sig_path.write_text(json.dumps(trading_signals, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
            print(f"  → {sig_path.name}")
    except Exception as e:
        print(f"  ⚠️ 實戰信號失敗: {type(e).__name__}: {e}", file=sys.stderr)

    perf_data = None

    dates = [d['date'] for d in history]
    result = {
        'generated_at': now_tw().isoformat(),
        'window_days': len(history),
        'trade_date_range': [dates[0], dates[-1]] if dates else [],
        'master_count': len(masters_out),
        'industry_classification_available': stock_industry_map is not None,
        'disposal_classification_available': disposal_codes is not None,
        'masters': masters_out,
    }
    if alliance_data:
        result['alliance'] = {
            'top_alliances': alliance_data['top_alliances'],
            'factions': alliance_data['factions'],
            'threshold': alliance_data['threshold'],
        }
    if cross_day_data:
        result['cross_day'] = cross_day_data
        for m, cd in cross_day_data.items():
            if m in masters_out:
                masters_out[m]['cross_day'] = cd
    if trading_signals:
        result['daily_signals'] = {
            'date': trading_signals.get('date'),
            'summary': trading_signals.get('summary'),
            'anomalies': trading_signals.get('anomalies', [])[:10],
            'consensus': trading_signals.get('consensus', [])[:10],
            'accumulations': trading_signals.get('accumulations', [])[:10],
        }
    return result


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='籌碼大戶深度操作分析 + 策略標籤')
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--window', type=int, default=60,
                        help='最近 N 天滾動窗口 (預設 60 天, 0=全部)')
    parser.add_argument('--master', default=None, help='只算單一 master (debug)')
    parser.add_argument('--output', default='data/master_profiles.json')
    parser.add_argument('--no-encrypt-input', action='store_true',
                        help='跳過解密 (測試用 unencrypted fixture)')
    args = parser.parse_args()

    password = '' if args.no_encrypt_input else os.environ.get('CHIP_RADAR_PASSWORD', '')
    if not args.no_encrypt_input and not password:
        print("❌ 需要 CHIP_RADAR_PASSWORD 環境變數 (解密歷史 daily JSON)")
        print("   或加 --no-encrypt-input 使用 unencrypted fixture")
        sys.exit(1)
    # v3.30.10: 偵測常見 placeholder 錯誤 (使用者複製貼上忘了替換)
    if password and ('<' in password or '>' in password or password.upper() == 'YOUR_PASSWORD'):
        print(f"❌ CHIP_RADAR_PASSWORD 看起來是占位符: {password!r}")
        print("   請設定真實的 production 密碼 (GitHub Secret CHIP_RADAR_PASSWORD 的值)")
        print('   PowerShell: $env:CHIP_RADAR_PASSWORD = "你的真實密碼字串"')
        print("   注意: 不要保留 < > 角括號")
        sys.exit(1)

    print(f"[Master Profile] 載入歷史 {args.data_dir}/ (window={args.window or '全部'})...")
    # v3.31.22: window=0 → None (全部); 預設 60 天滾動
    window = args.window if args.window and args.window > 0 else None
    history = load_history(args.data_dir, window, password)
    if not history:
        print("❌ 無可用歷史")
        sys.exit(1)
    print(f"  載入 {len(history)} 天: {history[0]['date']} ~ {history[-1]['date']}")

    print(f"[Master Profile] 計算 {'單一 master' if args.master else '全部個人大戶'}...")
    result = build_all_profiles(history, master_filter=args.master, data_dir=args.data_dir)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[Master Profile] → {out_path}")
    print(f"  {result['master_count']} masters, 窗口 {result['window_days']} 天")

    # 印 summary 表
    print()
    print(f"{'Master':25s} {'交易次':>5s} {'活躍天':>5s} {'漲停%':>6s} {'集中%':>6s} "
          f"{'策略子類':>14s}  Labels")
    print("─" * 130)
    for m, p in result['masters'].items():
        if p.get('no_data'):
            print(f"{m:25s} {'(無資料)':>30s}")
            continue
        op = p['operation_metrics']
        tm = p['timing_metrics']
        lh = p.get('label_hierarchy', {})
        l2 = lh.get('level2_strategy', '') if lh else ''
        labels = '/'.join(p['strategy_labels'][:5])
        # v3.30.11: 主攻族群欄 (族群名前 6 字 + %)
        # v3.31.11: 顯示閾值 → 50% (低於不顯示, 避免「半導體業 40%」誤導)
        top_ind = op.get('top_industry') or ''
        top_ind_pct = op.get('top_industry_pct', 0)
        ind_col = (f"{top_ind[:6]}{top_ind_pct:>3.0f}%"
                   if top_ind and top_ind_pct > 50 else '-')
        print(f"{m:25s} {op['trades_count']:>5d} {tm['active_days']:>5d} "
              f"{op['limit_up_hit_ratio'] * 100:>5.0f}% {op['concentration_top5_pct']:>5.0f}% "
              f"{l2:>14s}  {labels}")

        # v3.30.12: per-branch 細分 — 顯示條件: 該 master 有 >1 分點且某分點 labels 跟整體不同
        pb = p.get('per_branch_profiles')
        if pb:
            master_label_set = set(p['strategy_labels'])
            for code, bp in pb.items():
                if bp.get('no_data'):
                    continue
                bp_labels = bp['strategy_labels']
                # 只印「跟 master 整體 labels 有差」的分點 (差才有資訊量)
                if set(bp_labels) != master_label_set:
                    bp_op = bp['operation_metrics']
                    bp_labels_str = '/'.join(bp_labels[:5])
                    print(f"  └ {code} {bp['branch_name'][:10]:10s} {bp_op['trades_count']:>4d}筆  "
                          f"{bp_op['limit_up_hit_ratio']*100:>3.0f}%漲停  {bp_labels_str}")


if __name__ == '__main__':
    main()
