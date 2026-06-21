"""
signal_engine.py — v3.29 Signal Engine MVP

把 7 個 raw signal 從「user 自己解讀」變「actionable 答案 + 信心區間」。
權重來自 1 年 backtest (data/backtest_results.json) 實證 hit rate,不是拍腦袋。

Phase 1 (本檔, MVP):
  - 市場方向 (TAIEX 明日多空 + 信心 %)
  - 個股 Top 3 (sniper consensus 漲停股 排名)
  - 透明告知: 哪些信號因 backtest 證實沒預測力被廢除

Phase 2 (押 v3.29.1+):
  - 異常 pattern 警示 (結算週 + 外資深空反彈 / PCR 反轉 setup)
  - Phase B 信號 1/4/5/6 補上後動態調權重

輸出: data/daily_signal.json (~5-20 KB, 純 actionable)

設計哲學:
  - 不再讓 user 看 7 信號自己加權
  - 給 user 明天該關注什麼 + 為什麼 + 多有信心
  - 所有信心數字都有 backtest sample 出處,可追溯
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


# ════════════════════════════════════════════════════════════════════
#  Signal weights, derived from 1-year backtest (247 配對, 5/2025-5/2026)
#  See backtest_results.json for raw numbers.
#  Weight = hit_rate - 0.50 (random baseline), signed by expected direction.
#  ⚠️ 校準時直接改這份 table, 重跑 signal_engine 即可重生 daily_signal.
# ════════════════════════════════════════════════════════════════════
SIGNAL_WEIGHTS = {
    # 信號 3: P/C OI Ratio (反指標)
    # 1-year backtest: 極多 hit 58.7% (n=109), 偏多 hit 58.8% (n=102), 中性 hit 38.2% (n=34)
    'pc_ratio_oi': {
        'extreme-bull': +0.087,   # 散戶極空 → 反指標偏多
        'bull':         +0.088,   # 散戶偏空 → 反指標偏多 (與 extreme-bull 幾乎同強)
        'neutral':      -0.118,   # 多頭 baseline 下「期待窄幅」會 mis-fit, hit 38% 反推
        'bear':         -0.500,   # n=2 太少,但方向預期向下,給保守權重
        'extreme-bear':  0.000,   # 0 樣本
    },

    # 信號 7: 結算日壓力 — 兩段邏輯 (結算當日±1 vs 結算週 D±3 vs 非結算週)
    # 1-year backtest: 偏多 (D±3) hit 63.6% (n=22) — 唯一 strong alpha
    #                  極多 (D±1) hit 53.3% (n=30) — 弱
    #                  中性 (非結算週) hit 33.3% (n=186) — 大盤偏多時 mis-fit
    # 用法: 看 level + abs(days_to_settle) 動態決定 weight
    'settlement_pressure_near_extreme': +0.033,   # 結算當日±1 + 深空 → 弱反彈訊號
    'settlement_pressure_week_bull':    +0.136,   # 結算週 D±3 + 深空 → 強反彈訊號 (sweet spot)
    'settlement_pressure_week_bear':    -0.136,   # 對稱: 結算週 + 深多 → 強回檔訊號
    'settlement_pressure_near_bear':    -0.033,   # 結算當日±1 + 深多
    'settlement_pressure_neutral':       0.000,   # 非結算週,不參與

    # 信號 1/4/5/6: Phase B v3.42.0 — 從 data/backtest_phase_b_results.json 動態載入
    # (見下方 load_phase_b_weights 函式; 不採信時 fallback 0)
}


# ════════════════════════════════════════════════════════════════════
#  v3.42.0 C2: Phase B 動態載入 (signal 1/4/5/6 weights from backtest)
# ════════════════════════════════════════════════════════════════════
# Cache: 載入一次, 主流程結束清空 (避免長 process 抓不到新檔)
_phase_b_cache = None

def load_phase_b_weights(data_dir: str = 'data') -> Dict[str, Dict[str, float]]:
    """從 backtest_phase_b_results.json 載入 Phase B 4 信號權重.

    Returns:
      {signal_name: {level: weight}} or {} if file 不存在 / 不可採信
    """
    global _phase_b_cache
    if _phase_b_cache is not None:
        return _phase_b_cache
    from pathlib import Path
    import json as _json
    p = Path(data_dir) / 'backtest_phase_b_results.json'
    if not p.exists():
        _phase_b_cache = {}
        return _phase_b_cache
    try:
        d = _json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        _phase_b_cache = {}
        return _phase_b_cache
    # 對抗式驗證: market_regime 強單邊時不採信 weights
    # 注意: 不依賴 trust_weights 欄位 (舊檔可能缺), 直接看 regime
    regime_caveat = d.get('market_regime_caveat', {}) or {}
    regime = regime_caveat.get('regime')
    trust = regime_caveat.get('trust_weights')
    # 明確 False / 強單邊 regime → 不採信
    if trust is False or regime in ('strong_bull', 'strong_bear'):
        _phase_b_cache = {}
        return _phase_b_cache
    # 萃取 weights
    out = {}
    for sig_name, sig_data in (d.get('results') or {}).items():
        levels_w = {}
        for level, lvl_data in (sig_data.get('levels') or {}).items():
            if lvl_data.get('verdict') == 'enable':
                w = lvl_data.get('weight', 0.0)
                if w != 0:
                    levels_w[level] = w
        if levels_w:
            out[sig_name] = levels_w
    _phase_b_cache = out
    return _phase_b_cache

# ════════════════════════════════════════════════════════════════════
#  Killed signals (backtest 證實 < 隨機 50%)
# ════════════════════════════════════════════════════════════════════
KILLED_SIGNALS = {
    '外資期貨等效大台淨 OI': {
        'reason': '1 年 backtest 96% 樣本歸到偏空/極空, 全年外資長期淨空, 反指標假設失效',
        'evidence': 'hit 40.8% (偏空 n=98) / 41.4% (極空 n=140), 比隨機 50% 還差',
        'killed_in': 'v3.29 Signal Engine',
        'recall_condition': '若市場結構翻轉 (外資轉淨多 ≥30 天連續), 重啟 backtest 評估',
    },
}


# ════════════════════════════════════════════════════════════════════
#  Market direction inference
# ════════════════════════════════════════════════════════════════════
def _signal_weight(name: str, sig_data: Dict) -> float:
    """從 SIGNAL_WEIGHTS 查單一信號當下的權重 (考慮 level + 結構特性)"""
    if not sig_data:
        return 0.0
    level = sig_data.get('level')
    value = sig_data.get('value')

    if name == 'P/C Ratio':
        return SIGNAL_WEIGHTS['pc_ratio_oi'].get(level, 0.0)

    if name == '結算日壓力':
        # 細分: 看 days_to_settle 區分 near vs week vs other
        if isinstance(value, dict):
            d = value.get('days_to_settle')
            if d is None:
                return 0.0
            ad = abs(d)
            if ad <= 1:
                if level == 'extreme-bull': return SIGNAL_WEIGHTS['settlement_pressure_near_extreme']
                if level == 'extreme-bear': return SIGNAL_WEIGHTS['settlement_pressure_near_bear']
            elif ad <= 3:
                if level == 'bull': return SIGNAL_WEIGHTS['settlement_pressure_week_bull']
                if level == 'bear': return SIGNAL_WEIGHTS['settlement_pressure_week_bear']
            return SIGNAL_WEIGHTS['settlement_pressure_neutral']

    # v3.42.0 C2: Phase B 動態 (信號 1/4/5/6)
    # 若 backtest 期間 strong_bull/bear → trust_weights=False → 自然返 0
    pb = load_phase_b_weights()
    if name in pb:
        return pb[name].get(level, 0.0)

    return 0.0  # 其他信號 (含信號 2 等被 KILLED) 維持 0 權重


def infer_market_direction(temp_signals: List[Dict]) -> Dict[str, Any]:
    """從溫度計 signals 推 TAIEX 明日方向 + 信心.

    Returns:
        {
            'direction': '偏多' | '中性' | '偏空',
            'confidence_pct': 50-100,
            'net_weight': float,
            'contributing': [{name, level, weight, hit_rate_1y, evidence}, ...],
            'ignored': [list of signal names 未參與決策],
        }
    """
    contributing = []
    ignored = []
    net = 0.0

    for sig in (temp_signals or []):
        name = sig.get('name')
        w = _signal_weight(name, sig)
        if abs(w) > 0.001:
            net += w
            contributing.append({
                'name': name,
                'level': sig.get('level'),
                'weight': round(w, 4),
                'sign': 'bull' if w > 0 else 'bear',
            })
        else:
            ignored.append(name)

    # confidence% = 50% + net * 100, clamp [10, 95]
    conf_pct = max(10, min(95, 50 + net * 100))

    if net > 0.05:
        direction = '偏多'
    elif net < -0.05:
        direction = '偏空'
    else:
        direction = '中性'

    return {
        'direction': direction,
        'confidence_pct': round(conf_pct, 1),
        'net_weight': round(net, 4),
        'contributing': contributing,
        'ignored': ignored,
    }


# ════════════════════════════════════════════════════════════════════
#  Top focus stocks: sniper consensus + net buyer
# ════════════════════════════════════════════════════════════════════
def top_focus_stocks(raw_output: Dict, top_n: int = 3) -> List[Dict]:
    """從 raw_output 抓出明日該關注的個股 Top N.

    優先序:
      1. 多個 sniper master 共識買的漲停股 (consensus_limit_up)
      2. 單一強勢 sniper master 重倉買的漲停股
      3. 淨買金額排名

    每檔附:
      - 原因 (which masters + 淨買金額 + 漲幅)
      - 信心 (master_count + 淨買量轉換)
    """
    lus = raw_output.get('limit_up_summary') or {}
    consensus = lus.get('consensus_limit_up') or []
    limit_up_stocks = lus.get('limit_up_stocks') or []

    # consensus 已按 master_count desc 排序 (compute_limit_up_summary 內)
    out = []
    seen_codes = set()

    # Tier 1: consensus (>=2 master 同時買)
    for stock in consensus[:top_n * 2]:
        code = stock.get('code')
        if not code or code in seen_codes:
            continue
        buyers = stock.get('buyers', [])
        master_names = sorted({b.get('master_name') for b in buyers if b.get('master_name')})
        master_count = len(master_names)
        total_net = stock.get('total_buy_amt', 0)
        change_pct = stock.get('change_pct')

        # 信心: 起始 60%, 每多 1 個 master +8%, cap 95%
        confidence = min(95, 60 + (master_count - 1) * 8)

        out.append({
            'rank': len(out) + 1,
            'code': code,
            'name': stock.get('name', ''),
            'change_pct': change_pct,
            'tier': 'consensus',
            'master_count': master_count,
            'masters': master_names,
            'total_buy_amt_K': total_net,
            'total_buy_amt_yi': round(total_net / 1e5, 2),  # 仟元 → 億
            'confidence_pct': confidence,
            'reason': (f"{master_count} 位 sniper 共識買 ({'、'.join(master_names[:3])}"
                       f"{'…' if master_count > 3 else ''}), "
                       f"漲幅 {change_pct}%, 共淨買 {round(total_net / 1e5, 2)} 億"),
            'action': '明早開盤關注強勢續攻,若沒開高可分批進場',
        })
        seen_codes.add(code)
        if len(out) >= top_n:
            break

    # Tier 2: 補單一強勢 sniper master 重倉的漲停股 (若 consensus 不夠 top_n)
    if len(out) < top_n:
        sniper_ranking = lus.get('master_sniper_ranking') or []
        for master_block in sniper_ranking[:5]:
            master = master_block.get('master_name', '')
            details = master_block.get('limit_up_details') or []
            details_sorted = sorted(details, key=lambda x: -(x.get('buy_amt', 0) or 0))
            for d in details_sorted:
                code = d.get('code')
                if not code or code in seen_codes:
                    continue
                buy_amt = d.get('buy_amt', 0)
                change_pct = d.get('change_pct')
                out.append({
                    'rank': len(out) + 1,
                    'code': code,
                    'name': d.get('name', ''),
                    'change_pct': change_pct,
                    'tier': 'single_master',
                    'master_count': 1,
                    'masters': [master],
                    'total_buy_amt_K': buy_amt,
                    'total_buy_amt_yi': round(buy_amt / 1e5, 2),
                    'confidence_pct': 55,
                    'reason': f"{master} 單獨重倉買, 漲幅 {change_pct}%, 淨買 {round(buy_amt / 1e5, 2)} 億",
                    'action': '明早關注,但需確認其他資金跟進',
                })
                seen_codes.add(code)
                if len(out) >= top_n:
                    break
            if len(out) >= top_n:
                break

    return out


# ════════════════════════════════════════════════════════════════════
#  Main entry: generate daily signal
# ════════════════════════════════════════════════════════════════════
def generate_daily_signal(raw_output: Dict, temp_result: Dict, trade_date: str) -> Dict:
    """生成當日 actionable signal.

    Args:
        raw_output: crawler 主流程組好的 dict (含 institutional_rankings, futures_data,
                    limit_up_summary)
        temp_result: compute_chip_temperature 輸出 (含 signals[7])
        trade_date: YYYYMMDD

    Returns:
        daily_signal dict (寫到 data/daily_signal.json)
    """
    temp_signals = (temp_result or {}).get('signals') or []

    # 1. 市場方向推論
    market = infer_market_direction(temp_signals)

    # 2. 個股 Top 3
    stocks = top_focus_stocks(raw_output, top_n=3)

    # 3. headline (簡短描述)
    if market['confidence_pct'] >= 70:
        conf_word = '高'
    elif market['confidence_pct'] >= 60:
        conf_word = '中'
    else:
        conf_word = '低'
    headline = f"{market['direction']} 信心{market['confidence_pct']}% ({conf_word}信心) · {len(stocks)} 檔個股關注"

    return {
        'date': trade_date,
        'generated_at': datetime.now().isoformat(),
        'generator': 'signal_engine v3.29 MVP (Phase A backtest based)',
        'headline': headline,
        'market_direction': market,
        'top_focus_stocks': stocks,
        'killed_signals': KILLED_SIGNALS,
        'meta': {
            'backtest_basis': 'data/backtest_results.json (1-year, 247 pairs, 5/2025-5/2026)',
            'phase_a_signals': ['P/C Ratio', '結算日壓力'],
            'phase_b_pending': ['外資現貨', '分點漲停', '融資熱度', '法人共識'],
            'note': (
                'Phase A 只啟用 backtest 證實有 alpha 的 信號 3 (PCR) + 信號 7 (結算日 D±3)。'
                '信號 2 (外資期貨) 已廢除,理由詳 killed_signals。'
                '信號 1/4/5/6 待 Phase B backtest 後納入。'
            ),
        },
    }


def save_daily_signal(data_dir: Path, daily_signal: Dict) -> Path:
    """寫入 data/daily_signal.json (前端讀取點)."""
    out_path = data_dir / 'daily_signal.json'
    out_path.write_text(
        json.dumps(daily_signal, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return out_path


# ════════════════════════════════════════════════════════════════════
#  CLI: 從 latest.json 不能直接讀 (加密),所以這支 CLI 只支援 fake input
#  正式用法是被 crawler.py 在主流程裡 import 呼叫
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("signal_engine.py — module to be imported by crawler.py")
    print("正式用法: 在 crawler.py 主流程末尾 import 並呼叫 generate_daily_signal()")
    print()
    print("信號權重 (從 1-year backtest 推):")
    for k, v in SIGNAL_WEIGHTS.items():
        print(f"  {k}: {v}")
    print()
    print(f"已廢除信號: {list(KILLED_SIGNALS.keys())}")
