"""
========================================================================
Module: backtester_phase_b.py  (v3.42.0 — C2 Sprint 5)

Phase B backtest — 4 個未回測信號的 hit_rate 計算

關鍵設計決策 (對抗式驗證):
  ❌ 不使用 FinMind 外部 API (API 風險 + 配額限制)
  ✅ 直接讀 data/temp_history.json (30+ 天累積) 跑 backtest
  ✅ 對抗式建議: 二分法 (≥55% enable / <45% disable / 中間維持)
  ✅ 樣本不足 (n<10) 明示「樣本不足」不評估 (避免 n=4 標 99% CI 假信心)

涵蓋信號 (signal_engine 目前 weight=0 那批):
  - 信號 1: 外資現貨
  - 信號 4: 分點漲停
  - 信號 5: 融資熱度
  - 信號 6: 法人共識

輸出: data/backtest_phase_b_results.json
  {
    'backtest_run_at': ISO,
    'window_days': N,
    'data_source': 'data/temp_history.json',
    'min_sample_size': 10,
    'enable_threshold_pct': 55.0,
    'disable_threshold_pct': 45.0,
    'results': {
      '外資現貨': {
        'levels': {
          'extreme-bull': {n: 5, mean_next_chg: 0.42, hit_rate: 60.0,
                            verdict: 'insufficient' (n<10) | 'enable' | 'disable' | 'maintain'},
          'bull': {...},
          ...
        },
        'overall_hit_rate_directional': 52.3,
        'overall_n': 25,
      },
      ...
    }
  }
========================================================================
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

TW_TZ = timezone(timedelta(hours=8))

# Phase B 涵蓋 4 信號 (名稱要跟 temp_history.json 的 signals[].name 一致)
PHASE_B_SIGNALS = ['外資現貨', '分點漲停', '融資熱度', '法人共識']

# 對抗式建議: 二分法門檻
ENABLE_THRESHOLD_PCT = 55.0      # ≥55% → enable
DISABLE_THRESHOLD_PCT = 45.0     # <45% → disable
MIN_SAMPLE_SIZE = 10             # n<10 → insufficient (不評估)

# Level → 預期方向 (用於 directional hit 判定)
# extreme-bull / bull = 預期偏多 → 次日 change_pct > 0 算 hit
# extreme-bear / bear = 預期偏空 → 次日 change_pct < 0 算 hit
# neutral = 不算入 directional hit (太模糊)
LEVEL_EXPECTED_DIR = {
    'extreme-bull': 'up',
    'bull':         'up',
    'neutral':      'flat',
    'bear':         'down',
    'extreme-bear': 'down',
}


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _is_hit(expected_dir: str, next_chg: float) -> Optional[bool]:
    """判定該筆配對是否 hit.
    expected_dir: 'up' | 'down' | 'flat'
    Returns True (hit) / False (miss) / None (不算)
    """
    if next_chg is None:
        return None
    if expected_dir == 'up':
        return next_chg > 0
    if expected_dir == 'down':
        return next_chg < 0
    return None  # flat 不算入 directional hit


def compute_phase_b_results(temp_history_path: str = 'data/temp_history.json'
                              ) -> Optional[Dict[str, Any]]:
    """從 temp_history.json 跑 Phase B backtest."""
    path = Path(temp_history_path)
    if not path.exists():
        print(f"[Phase B] ❌ {path} 不存在")
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[Phase B] ❌ {path} 讀取失敗: {e}")
        return None

    history = data.get('history', []) or []
    if not history:
        print("[Phase B] ❌ history 為空")
        return None

    # 收集每信號 × 每 level 的配對
    # signal_name → level → list of (date, signal_score, next_day_change_pct)
    pairs: Dict[str, Dict[str, List[Tuple]]] = defaultdict(lambda: defaultdict(list))

    n_total_days = 0
    n_with_next = 0
    for h in history:
        date_str = h.get('date', '?')
        next_chg = h.get('next_day_change_pct')
        n_total_days += 1
        if next_chg is None:
            continue
        n_with_next += 1
        for sig in h.get('signals', []) or []:
            name = sig.get('name')
            level = sig.get('level')
            if not name or not level or name not in PHASE_B_SIGNALS:
                continue
            pairs[name][level].append((date_str, sig.get('score'), next_chg))

    print(f"[Phase B] 樣本: {n_with_next}/{n_total_days} 天有 next_day_change_pct")

    # 算 hit_rate per signal × level
    results: Dict[str, Any] = {}
    for sig_name in PHASE_B_SIGNALS:
        sig_results = {}
        all_hits = 0
        all_misses = 0
        for level, level_pairs in pairs.get(sig_name, {}).items():
            expected_dir = LEVEL_EXPECTED_DIR.get(level)
            hits = 0
            misses = 0
            chgs = []
            for date_str, score, next_chg in level_pairs:
                chgs.append(next_chg)
                h = _is_hit(expected_dir, next_chg)
                if h is True:
                    hits += 1
                    all_hits += 1
                elif h is False:
                    misses += 1
                    all_misses += 1
            n = hits + misses
            mean_chg = sum(chgs) / len(chgs) if chgs else 0.0
            if n < MIN_SAMPLE_SIZE:
                verdict = 'insufficient'
                weight = 0.0
            elif expected_dir == 'flat':
                # neutral level 不參與 directional 評估
                verdict = 'neutral_level'
                weight = 0.0
            else:
                hit_rate = hits / n * 100 if n > 0 else 0.0
                if hit_rate >= ENABLE_THRESHOLD_PCT:
                    verdict = 'enable'
                    # weight 依預期方向: up → 正, down → 負
                    base = (hit_rate - 50.0) / 100.0   # 0.05 ~ 0.5
                    weight = round(base if expected_dir == 'up' else -base, 3)
                elif hit_rate < DISABLE_THRESHOLD_PCT:
                    verdict = 'disable'
                    weight = 0.0
                else:
                    verdict = 'maintain'
                    weight = 0.0
            hit_rate_pct = (hits / n * 100) if n > 0 else None
            sig_results[level] = {
                'n': n,
                'mean_next_chg_pct': round(mean_chg, 3),
                'hits': hits,
                'misses': misses,
                'hit_rate_pct': round(hit_rate_pct, 1) if hit_rate_pct is not None else None,
                'expected_dir': expected_dir,
                'verdict': verdict,
                'weight': weight,
            }
        # 整體 directional hit rate
        all_n = all_hits + all_misses
        overall_hit_rate = (all_hits / all_n * 100) if all_n > 0 else None
        results[sig_name] = {
            'levels': sig_results,
            'overall_hit_rate_directional': round(overall_hit_rate, 1) if overall_hit_rate is not None else None,
            'overall_n_directional': all_n,
        }

    # ⚠️ market_regime 偵測 — 防 spurious hit rate (對抗式驗證)
    # 如果 backtest 期間所有 next_day_change_pct 偏向同方向, 任一 directional 信號
    # 都會看起來「準」, 實際上是市場單邊行情而非信號有效.
    # v3.45.0 (運4): 排除 stale 重複日 (兜底排程跑時 TWSE 沒更新, index 跟前日同)
    # 這類資料雖然有 next_day_change_pct 但價值為 0, 不該算入 regime 判定
    all_next_chgs = [h.get('next_day_change_pct') for h in history
                      if h.get('next_day_change_pct') is not None]
    if all_next_chgs:
        # 0% (重複日, 兜底排程無新資料) 不算入 regime 判定
        directional = [c for c in all_next_chgs if c != 0]
        n_up = sum(1 for c in directional if c > 0)
        n_down = sum(1 for c in directional if c < 0)
        mean_chg = sum(directional) / len(directional) if directional else 0.0
        bias_pct = n_up / len(directional) * 100 if directional else 50.0
        if bias_pct >= 70:
            market_regime = 'strong_bull'
        elif bias_pct >= 55:
            market_regime = 'mild_bull'
        elif bias_pct <= 30:
            market_regime = 'strong_bear'
        elif bias_pct <= 45:
            market_regime = 'mild_bear'
        else:
            market_regime = 'mixed'
    else:
        market_regime = 'unknown'
        n_up = n_down = 0
        mean_chg = 0.0
        bias_pct = 0.0

    return {
        'backtest_run_at': now_tw().isoformat(),
        'window_days': n_total_days,
        'samples_with_next_day_chg': n_with_next,
        'data_source': str(path),
        'min_sample_size': MIN_SAMPLE_SIZE,
        'enable_threshold_pct': ENABLE_THRESHOLD_PCT,
        'disable_threshold_pct': DISABLE_THRESHOLD_PCT,
        'level_expected_dir': LEVEL_EXPECTED_DIR,
        'phase_b_signals': PHASE_B_SIGNALS,
        'market_regime_caveat': {
            'regime': market_regime,
            'next_day_up_pct': round(bias_pct, 1),
            'mean_next_day_chg_pct': round(mean_chg, 3),
            'n_up': n_up, 'n_down': n_down,
            'warning': (
                '🚨 next_day_change_pct 100% 正值 — 高度懷疑 data quality bug '
                '(真實大盤不可能 30 天全漲), 不是真實 alpha. '
                'crawler temp_history backfill 邏輯需查 (TODO).'
                if bias_pct >= 99.0 and len(all_next_chgs) >= 10
                else '⚠️ 偵測強單邊行情 — directional 信號 hit_rate 可能是 spurious '
                f'(該方向 ≥70% 機率 hit). 結果僅供觀察, 不可作為長期 alpha 證據.'
                if market_regime in ('strong_bull', 'strong_bear')
                else None
            ),
            # 對 signal_engine 的明示指令: 是否該採信 weight
            'trust_weights': market_regime not in ('strong_bull', 'strong_bear') or bias_pct < 70,
        },
        'caveat': (
            f'樣本 n<{MIN_SAMPLE_SIZE} 不評估 (verdict=insufficient); '
            f'≥{ENABLE_THRESHOLD_PCT}% enable / <{DISABLE_THRESHOLD_PCT}% disable / 中間 maintain. '
            '從內建 temp_history 跑, 樣本數 = 累積天數, 隨時間自然增加. '
            '⚠️ 樣本期間若市場偏單邊 (見 market_regime_caveat), '
            'hit_rate 可能 spurious, 需累積 180+ 天涵蓋 bull+bear 才能信賴.'
        ),
        # C8 (v3.43.0): 明示已知 methodology bias (機構級 disclosure)
        'methodology_caveats': {
            'survivorship_bias': (
                '本 backtest 為市場大盤層級 (TAIEX), survivorship bias 影響小. '
                '若未來擴充至個股 alpha backtest, 須加 universe filter 排除 '
                '(a) 回測期間後上市 (b) 回測期間下市 (c) 變更交易方法 (d) 處置/警示股.'
            ),
            'look_ahead_bias': (
                '已避免 — 每筆 (T 日 signal, T+1 日 chg) 配對嚴格時序, '
                'temp_history 寫入時 T+1 chg 才回填.'
            ),
            'data_snooping': (
                '⚠️ 二分法閾值 55/45/10 是設計選擇, 未經 walk-forward 驗證. '
                '應用過程不可微調這些閾值來「優化」hit_rate, 否則陷入過擬合.'
            ),
            'small_sample': (
                f'30 天樣本對 directional hit_rate 標準差約 ±10% '
                f'(95% CI 寬度), 任何「hit_rate 變動 <10%」都不應視為信號變化. '
                f'累積 100+ 天後 CI 才收斂至 ±5%.'
            ),
            'regime_dependence': (
                '本 backtest 不分 bull/bear regime, hit_rate 是 lifetime average. '
                '建議用戶觀察 market_regime_caveat 一同判讀.'
            ),
        },
        'results': results,
    }


def universe_filter(stocks_universe: List[str],
                     reference_date: str,
                     listing_data: Optional[Dict[str, Dict[str, str]]] = None,
                     data_dir: str = 'data'
                     ) -> List[str]:
    """C8 (v3.43.0) hook — 未來個股 backtest 用的 universe filter.
    v3.45.0 (後3): listing_data=None 時自動從 data/listing_history.json 載入
    (listing_fetcher.py 抓的 TWSE+TPEx 1980 檔上市櫃公司基本資料).

    目前 backtester_phase_b 是市場層級 backtest, 暫不需要.
    若未來擴充至個股 alpha (e.g. 漲停大戶 master 跟單回測), 必須先呼叫此函式
    排除 survivorship bias.

    Args:
      stocks_universe: 候選個股 list
      reference_date: backtest 起算日 YYYYMMDD
      listing_data: {code: {first_listed: YYYYMMDD, delisted: YYYYMMDD or None}}
                     None → 自動載入 data/listing_history.json

    Returns: 通過 filter 的 universe
    """
    if not listing_data:
        # v3.45.0: 自動從 listing_fetcher cache 載
        try:
            from listing_fetcher import load_listings
            listing_data = load_listings(data_dir)
        except Exception:
            listing_data = None
    if not listing_data:
        # 仍無 → 返原 universe + 警告
        print("[universe_filter] ⚠️ 無 listing_data (跑 listing_fetcher.py 抓), "
              "跳過 survivorship 過濾 (有 bias 風險)")
        return list(stocks_universe)
    filtered = []
    for code in stocks_universe:
        info = listing_data.get(code) or {}
        first_listed = info.get('first_listed', '00000000')
        delisted = info.get('delisted')
        # 排除 1: reference 之前還沒上市
        if first_listed > reference_date:
            continue
        # 排除 2: reference 時已下市
        if delisted and delisted <= reference_date:
            continue
        filtered.append(code)
    excluded = len(stocks_universe) - len(filtered)
    if excluded:
        print(f"[universe_filter] 排除 {excluded} 檔 (未上市/已下市)")
    return filtered


def save_results(results: Dict[str, Any],
                  out_path: str = 'data/backtest_phase_b_results.json') -> Path:
    """寫 backtest_phase_b_results.json.

    ⚠️ v3.77.0 資料源分歧守門:
      本模組 CLI 預設是 data/temp_history.json, 但現行 production 檔
      實際是從 data/signal_history_official.json 產生的 (官方 FMTQIK backfill).
      直接跑預設會**靜默換掉權重的資料基礎** — 權重是 infer_market_direction
      的核心, 換源等於換掉整個方向判定的依據, 卻不會有任何提示.
      → 覆寫前比對前一版 data_source, 不同就大聲警告.
    """
    p = Path(out_path)
    prev_src = None
    if p.exists():
        try:
            prev_src = ((json.loads(p.read_text(encoding='utf-8')).get('_meta') or {})
                        .get('data_source'))
        except Exception:
            pass
    new_src = (results.get('_meta') or {}).get('data_source')
    if prev_src and new_src and Path(prev_src).name != Path(new_src).name:
        print(f"  ⚠️ Phase B 資料源改變: 前版「{prev_src}」→ 本次「{new_src}」")
        print("     權重是方向判定的基礎, 換源會改變所有 direction 結論.")
        print(f"     若非刻意, 請改用 --temp-history {prev_src} 重跑.")

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    tmp.replace(p)
    return p


def format_console_summary(results: Dict[str, Any]) -> str:
    """console summary."""
    if not results:
        return "  [Phase B] no results"
    lines = [
        f"[Phase B Backtest] 樣本 {results.get('samples_with_next_day_chg', 0)} 天 "
        f"/ 窗口 {results.get('window_days', 0)} 天",
        f"  二分法: ≥{ENABLE_THRESHOLD_PCT}% enable / <{DISABLE_THRESHOLD_PCT}% disable / "
        f"n<{MIN_SAMPLE_SIZE} insufficient",
    ]
    for sig_name, sig_data in results.get('results', {}).items():
        overall = sig_data.get('overall_hit_rate_directional')
        all_n = sig_data.get('overall_n_directional', 0)
        lines.append(f"  • {sig_name}: 整體 directional hit "
                     f"{overall}% (n={all_n}) " if overall else f"  • {sig_name}: 樣本不足")
        for level, lvl_data in sig_data.get('levels', {}).items():
            verdict = lvl_data.get('verdict', '?')
            n = lvl_data.get('n', 0)
            hr = lvl_data.get('hit_rate_pct')
            icon = {
                'enable': '✅', 'disable': '❌', 'maintain': '→',
                'insufficient': '⏳', 'neutral_level': '·',
            }.get(verdict, '?')
            hr_str = f"hit {hr}%" if hr is not None else "no data"
            lines.append(f"    {icon} {level:<14s} n={n:>3d}  {hr_str:>10s}  → {verdict}")
    return '\n'.join(lines)


def main():
    import argparse
    # v3.72.0: Windows console cp950 → UTF-8 (⭐/≥ 等符號防 UnicodeEncodeError)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description='Phase B backtest')
    parser.add_argument('--temp-history', default='data/temp_history.json')
    parser.add_argument('--output', default='data/backtest_phase_b_results.json')
    args = parser.parse_args()

    results = compute_phase_b_results(args.temp_history)
    if not results:
        print("[Phase B] ❌ 無法產出結果")
        return 1
    out = save_results(results, args.output)
    print(format_console_summary(results))
    print(f"\n[Phase B] → {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
