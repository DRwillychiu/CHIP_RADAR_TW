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
  進出場: 高頻交易 / 精選出手 / 連續部署

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

# 排除外資 (foreign_ib) + 官股 (public), 那些不適合操作習慣分類
EXCLUDED_STYLES = {'foreign_ib', 'public'}


def get_individual_masters() -> Dict[str, List[str]]:
    """從 branches.py 取個人大戶 (排除法人/官股)"""
    try:
        from branches import MASTER_STYLES
        return {m: s for m, s in MASTER_STYLES.items()
                if not any(es in s for es in EXCLUDED_STYLES)}
    except ImportError:
        return {}


# 標籤閾值 (基於 metric 觸發, 透明可調)
THRESH = {
    'limit_up_hit_high': 0.6,         # > 60% 買的當天漲停 → 漲停獵手
    'style_dominant': 0.5,            # 某風格 > 50% → 該風格標籤
    'concentration_high': 50.0,       # 前5大 > 50% → 集中投資
    'concentration_low': 20.0,        # 前5大 < 20% → 分散布局
    'consistency_high': 0.8,          # 主導風格 > 80% → 風格純粹
    'consistency_low': 0.5,           # 主導風格 < 50% → 多變策略
    'active_ratio_high': 0.85,        # 活躍天 > 85% → 高頻交易
    'active_ratio_low': 0.4,          # 活躍天 < 40% → 精選出手
    'streak_long': 8,                 # 連續部署 > 8 個交易日
}


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


# ════════════════════════════════════════════════════════════════════
#  歷史載入 (解密)
# ════════════════════════════════════════════════════════════════════

def load_history(data_dir: str, window_days: Optional[int], password: str) -> List[Dict[str, Any]]:
    """
    讀最近 window_days 天 daily JSON, 解密.

    Args:
        data_dir: data/ 路徑
        window_days: None 表示用所有可用 (使用者選的「最大可搜尋窗口」)
        password: CHIP_RADAR_PASSWORD
    Returns:
        [{'date': 'YYYYMMDD', 'data': {<解密後資料>}}, ...] 依日期升序
    """
    files = sorted(Path(data_dir).glob('[0-9]' * 8 + '.json'))
    if window_days is not None:
        files = files[-window_days:]

    history = []
    skipped = 0
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                enc = json.load(fh)
            if enc.get('encrypted'):
                from crawler import decrypt_data
                plaintext = decrypt_data(enc['data'], password)
                data = json.loads(plaintext)
            else:
                data = enc.get('data', enc)
            history.append({'date': f.stem, 'data': data})
        except Exception as e:
            print(f"  ⚠️ 跳過 {f.name}: {e}", file=sys.stderr)
            skipped += 1
    if skipped:
        print(f"  總計跳過 {skipped} 個檔案 (解密失敗或結構錯)", file=sys.stderr)
    return history


# ════════════════════════════════════════════════════════════════════
#  抽取 master 交易紀錄
# ════════════════════════════════════════════════════════════════════

def extract_master_trades(history: List[Dict[str, Any]],
                          master_name: str) -> List[Dict[str, Any]]:
    """從歷史抽出該 master 所有買進紀錄 (含 co_masters 共用分點的情境)."""
    trades = []
    for day in history:
        for br in day['data'].get('branches', []):
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

def compute_operation_metrics(trades: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """風格分布 + 漲停命中 + 集中度 + 一致性."""
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

    return {
        'trades_count': total,
        'unique_stocks': len(stock_amt),
        'daytrade_ratio': round(daytrade, 3),
        'partial_ratio': round(partial, 3),       # 近似隔日沖
        'overnight_ratio': round(overnight, 3),    # 波段
        'limit_up_hit_ratio': round(limit_up_hit, 3),
        'concentration_top5_pct': round(concentration, 1),
        'consistency': round(consistency, 3),
        'total_buy_amt_wan': round(total_amt / 10),   # 仟元轉萬元
    }


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

    # streaks (連續部署): 兩筆交易日間隔 ≤ 3 天視為連續 (跨週末)
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

def generate_labels(op: Dict[str, Any], timing: Dict[str, Any]) -> List[str]:
    """基於 metric 閾值規則生成標籤."""
    labels = []

    # 風格主導 (互斥, 取最強)
    if op['limit_up_hit_ratio'] > THRESH['limit_up_hit_high']:
        labels.append('漲停獵手')
    if op['daytrade_ratio'] > THRESH['style_dominant']:
        labels.append('當沖客')
    elif op['partial_ratio'] > THRESH['style_dominant']:
        labels.append('短打型')          # 近似隔日沖
    elif op['overnight_ratio'] > THRESH['style_dominant']:
        labels.append('波段囤貨')

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
        labels.append('連續部署')

    return labels


# ════════════════════════════════════════════════════════════════════
#  模板 narrative (v3.30.0 同風格, 規則式 50-100 字)
# ════════════════════════════════════════════════════════════════════

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
        style_parts.append(f"波段 {op['overnight_ratio'] * 100:.0f}%")
    style_str = " / ".join(style_parts) if style_parts else "風格不明"

    label_str = "/".join(labels[:3]) if labels else "未明"

    return (
        f"{master_name} 近 {timing['active_days']}/{timing['total_window_days']} 交易日出手 "
        f"{op['trades_count']} 次 ({op['unique_stocks']} 檔), "
        f"風格分布: {style_str}, 漲停命中 {op['limit_up_hit_ratio'] * 100:.0f}%, "
        f"前 5 大個股集中 {op['concentration_top5_pct']:.0f}%。"
        f" 主軸: {label_str}。"
    )


# ════════════════════════════════════════════════════════════════════
#  組裝單一 master profile
# ════════════════════════════════════════════════════════════════════

def build_master_profile(master_name: str,
                          history: List[Dict[str, Any]],
                          master_styles: Dict[str, List[str]]) -> Dict[str, Any]:
    """組一個 master 的完整 profile."""
    trades = extract_master_trades(history, master_name)
    declared = master_styles.get(master_name, [])

    if not trades:
        return {
            'master': master_name,
            'declared_styles': declared,
            'no_data': True,
            'narrative': f"{master_name} 在窗口內無交易紀錄。",
        }

    op = compute_operation_metrics(trades)
    timing = compute_timing_metrics(trades, len(history))
    labels = generate_labels(op, timing)
    narrative = generate_narrative(master_name, op, timing, labels)

    return {
        'master': master_name,
        'declared_styles': declared,
        'operation_metrics': op,
        'timing_metrics': timing,
        'strategy_labels': labels,
        'narrative': narrative,
    }


# ════════════════════════════════════════════════════════════════════
#  主跑函式
# ════════════════════════════════════════════════════════════════════

def build_all_profiles(history: List[Dict[str, Any]],
                        master_filter: Optional[str] = None) -> Dict[str, Any]:
    """對所有個人大戶建 profile."""
    indiv = get_individual_masters()
    targets = {master_filter: indiv.get(master_filter, [])} if master_filter else indiv

    masters_out = {}
    for m in targets:
        masters_out[m] = build_master_profile(m, history, indiv)

    dates = [d['date'] for d in history]
    return {
        'generated_at': now_tw().isoformat(),
        'window_days': len(history),
        'trade_date_range': [dates[0], dates[-1]] if dates else [],
        'master_count': len(masters_out),
        'masters': masters_out,
    }


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='籌碼大戶深度操作分析 + 策略標籤')
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--window', type=int, default=None,
                        help='最近 N 天 (預設用所有可用)')
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

    print(f"[Master Profile] 載入歷史 {args.data_dir}/ (window={args.window or '全部'})...")
    history = load_history(args.data_dir, args.window, password)
    if not history:
        print("❌ 無可用歷史")
        sys.exit(1)
    print(f"  載入 {len(history)} 天: {history[0]['date']} ~ {history[-1]['date']}")

    print(f"[Master Profile] 計算 {'單一 master' if args.master else '全部個人大戶'}...")
    result = build_all_profiles(history, master_filter=args.master)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[Master Profile] → {out_path}")
    print(f"  {result['master_count']} masters, 窗口 {result['window_days']} 天")

    # 印 summary 表
    print()
    print(f"{'Master':25s} {'交易次':>5s} {'活躍天':>5s} {'漲停%':>6s} {'集中%':>6s}  Labels")
    print("─" * 100)
    for m, p in result['masters'].items():
        if p.get('no_data'):
            print(f"{m:25s} {'(無資料)':>30s}")
            continue
        op = p['operation_metrics']
        tm = p['timing_metrics']
        labels = '/'.join(p['strategy_labels'][:4])
        print(f"{m:25s} {op['trades_count']:>5d} {tm['active_days']:>5d} "
              f"{op['limit_up_hit_ratio'] * 100:>5.0f}% {op['concentration_top5_pct']:>5.0f}%  {labels}")


if __name__ == '__main__':
    main()
