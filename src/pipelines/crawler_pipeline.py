"""
crawler_pipeline.py — 計算層 (v3.35.0 B1 從 crawler.py 拆出)

1. 籌碼溫度計 (v3.25/v3.27): 7 信號 0-100 分 + temp_history 累積
2. FIFO 部位追蹤: load/save (加密) + rollback + apply_day
3. 期間彙總: compute_period_summaries / compute_limit_up_summary
   / compute_next_day_flip_verification / compute_master_summaries

依賴: crawler_output (加密) + branches (MASTER_STYLES / LIMIT_UP_THRESHOLD)
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from crawler_output import encrypt_data, decrypt_data, PBKDF2_ITERATIONS
from branches import MASTER_STYLES, LIMIT_UP_THRESHOLD

TW_TZ = timezone(timedelta(hours=8))

def now_tw():
    return datetime.now(TW_TZ)

BASELINE_DATE = "20260421"  # 累積損益基準日（不納入此日之前資料）

# ════════════════════════════════════════════════════════════════
#  v3.25: 籌碼溫度計後端計算 + 30 天歷史累積
# ════════════════════════════════════════════════════════════════
#  與前端 renderChipTemperature() 邏輯對齊 (5 信號等權重 0-20 分,
#  加總 / 最大值 × 100 = 0-100 分)。每次 daily-full 後寫入
#  data/temp_history.json (前端 chart 用)。

# ════════════════════════════════════════════════════════════════════
#  v3.27 籌碼溫度計閾值表 — ⚠️ 初版上線,待回測校準
# ────────────────────────────────────────────────────────────────────
#  這些閾值是 v3.27 (2026-05-10) 上線時的初始值,基於 logical reasoning
#  + 5/4-5/10 觀察 (非統計回測)。實戰跑一段時間後應該:
#    1. 收集每日 (score, 次日漲跌) 對應
#    2. 統計各區段 hit rate
#    3. 若極端區段預測力差 → 收緊閾值; 若中性區段佔比過高 → 拉開
#    4. 預期 v3.28+ 用 30-60 個交易日資料校準
#  欄位形式 = (extreme_bull, bull, neutral_low, bear) → score 20/15/10/5/0
# ════════════════════════════════════════════════════════════════════
TEMP_THRESHOLDS = {
    # 信號 1: 外資現貨買賣超 (張)
    'foreign_cash':       (50000,  10000, -10000, -50000),
    # 信號 2: 外資期貨等效大台淨 OI (口)
    'foreign_futures_eq': (30000,  10000, -10000, -30000),
    # 信號 3: P/C OI Ratio (反指標,高 PCR = 散戶極空 = 反向看多)
    'pc_ratio_oi':        (1.3,    1.0,   0.8,    0.6),
    # 信號 4: 分點漲停股數 (無 bear/extreme-bear 區隔,因下限是 0)
    'limit_up_count':     (8,      4,     1,      0),     # >=8/4/1/0
    # 信號 5: 融資熱度 Top5 變化 (億, 反指標, 散戶追漲 = 看空)
    'margin_top5_yi':     (30,     10,    -10,    -30),   # +30/+10/-10/-30 → 0/5/10/15/20
    # 信號 6 (v3.27 新): 法人共識 — 用「外資量達標 AND 投信量達標 AND 同向」雙條件
    'consensus_foreign':  30000,   # 張 (外資門檻)
    'consensus_trust':    3000,    # 張 (投信門檻)
    # 信號 7 (v3.27 新): 結算日壓力 — 距結算日 d 天 × 外資期貨 OI
    'settlement_near_oi': 20000,   # 結算日±1 內的 OI 門檻
    'settlement_week_oi': 10000,   # 結算日±3 內的 OI 門檻 (排除 ±1)
}


def _temp_signal_score(value, thresholds):
    """thresholds = (extreme_bull, bull, neutral_low, bear)
    回傳 (score, level)。score = 20/15/10/5/0, level = 'extreme-bull'/etc."""
    if value is None:
        return None
    eb, b, nl, br = thresholds
    if value >= eb:    return (20, 'extreme-bull')
    if value >= b:     return (15, 'bull')
    if value >= nl:    return (10, 'neutral')
    if value >= br:    return (5, 'bear')
    return (0, 'extreme-bear')


from datetime import date as _date


def third_wed(yy: int, mm: int) -> _date:
    """每月第三個週三 (台股期權結算日, 一律以 Asia/Taipei 計算).

    P0-1 (v3.38.0): 提升為 module-level 函式 + 型別簽名,
    避免 UTC runner 跨日時的隱性錯日風險 (signal 7 結算日壓力訊號依賴)."""
    first = _date(yy, mm, 1)
    # weekday: Mon=0 ... Wed=2 ... Sun=6
    offset_to_first_wed = (2 - first.weekday()) % 7
    first_wed_day = 1 + offset_to_first_wed
    return _date(yy, mm, first_wed_day + 14)


def _days_to_settlement(trade_date_str: str):
    """v3.27: 計算距離下一個結算日(每月第三個週三)的天數。
    d=0 = 當日就是結算日; d>0 = 還有 d 天; d<0 = 結算日已過 d 天。

    ⚠️ TZ 約定 (P0-1): trade_date_str **必須是台北時間 YYYYMMDD**.
    呼叫端必須用 now_tw().strftime('%Y%m%d') 生成, 不可直接用 UTC date.
    GitHub Actions runner 預設 UTC, 若直接 datetime.now() 會錯日.

    規則:
      1. 候選: 上月/本月/下月 三個結算日
      2. 過去的結算日只有「≤ 3 天前」才視為相關(結算後 1-3 天還有餘波)
      3. 在相關候選中取絕對值最小 (最近的結算日)
    """
    try:
        y = int(trade_date_str[:4])
        m = int(trade_date_str[4:6])
        d = int(trade_date_str[6:8])
        td = _date(y, m, d)

        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        candidates = [third_wed(py, pm), third_wed(y, m), third_wed(ny, nm)]
        diffs = [(c - td).days for c in candidates]
        # 過去的結算日只保留 >= -3 天的(餘波範圍)
        relevant = [x for x in diffs if x >= -3]
        if not relevant:
            return diffs[1]  # fallback to current month
        return min(relevant, key=abs)
    except Exception:
        return None


def compute_chip_temperature(raw_output, trade_date=None):
    """
    從 raw_output 計算籌碼溫度計分數 (0-100) + 信號明細.
    v3.27: 7 信號 (新增「法人共識」+「結算日壓力」)。
    與前端 renderChipTemperature() 對齊。

    Args:
      raw_output: crawler 主流程組好的 dict
      trade_date: YYYYMMDD 字串(必要 — 信號 7 需要)。若 None,信號 7 略過。

    Returns: dict { score: int, signals: [...], total, max_total, signal_count } 或 None
    """
    signals = []

    # 信號 1: 外資現貨
    try:
        r = raw_output.get('institutional_rankings', {}).get('foreign') or {}
        buy = r.get('buy') or []
        sell = r.get('sell') or []
        if buy or sell:
            net = (sum(x.get('foreign_net_lot', 0) or 0 for x in buy)
                   + sum(x.get('foreign_net_lot', 0) or 0 for x in sell))
            sc = _temp_signal_score(net, TEMP_THRESHOLDS['foreign_cash'])
            if sc:
                signals.append({'name': '外資現貨', 'score': sc[0], 'level': sc[1], 'value': net})
    except Exception:
        pass

    # 信號 2: 外資期貨等效大台
    try:
        eq = raw_output.get('futures_data', {}).get('summary', {}).get('foreign_equivalent_net_oi')
        sc = _temp_signal_score(eq, TEMP_THRESHOLDS['foreign_futures_eq'])
        if sc:
            signals.append({'name': '外資期貨', 'score': sc[0], 'level': sc[1], 'value': eq})
    except Exception:
        pass

    # 信號 3: P/C Ratio (反指標 — PCR 高 = 散戶極空 = 反向看多)
    try:
        pc = raw_output.get('futures_data', {}).get('summary', {}).get('pc_ratio_oi')
        sc = _temp_signal_score(pc, TEMP_THRESHOLDS['pc_ratio_oi'])
        if sc:
            signals.append({'name': 'P/C Ratio', 'score': sc[0], 'level': sc[1], 'value': pc})
    except Exception:
        pass

    # 信號 4: 分點漲停數
    try:
        lus = raw_output.get('limit_up_summary') or {}
        n = len(lus.get('limit_up_stocks') or [])
        thr = TEMP_THRESHOLDS['limit_up_count']  # (8, 4, 1, 0)
        if n >= thr[0]:   sc = (20, 'extreme-bull')
        elif n >= thr[1]: sc = (15, 'bull')
        elif n >= thr[2]: sc = (10, 'neutral')
        else:             sc = (5, 'bear')
        signals.append({'name': '分點漲停', 'score': sc[0], 'level': sc[1], 'value': n})
    except Exception:
        pass

    # 信號 5: 融資熱度 (反指標)
    try:
        mr = raw_output.get('margin_rankings') or {}
        buy_top = (mr.get('top_margin_buy') or [])[:5]
        if buy_top:
            total_increase = sum(x.get('margin_change', 0) or 0 for x in buy_top)
            billion = total_increase / 1e8
            thr = TEMP_THRESHOLDS['margin_top5_yi']  # (30, 10, -10, -30)
            # 反指標: 散戶大幅追漲 = 看空
            if billion >= thr[0]:   sc = (0, 'extreme-bear')
            elif billion >= thr[1]: sc = (5, 'bear')
            elif billion >= thr[2]: sc = (10, 'neutral')
            elif billion >= thr[3]: sc = (15, 'bull')
            else:                   sc = (20, 'extreme-bull')
            signals.append({'name': '融資熱度', 'score': sc[0], 'level': sc[1], 'value': round(billion, 2)})
    except Exception:
        pass

    # 信號 6 (v3.27 新): 法人共識 — 外資 + 投信 同向 且 雙方量達標
    try:
        ir = raw_output.get('institutional_rankings', {}) or {}
        fr = ir.get('foreign') or {}
        tr = ir.get('trust') or {}
        f_buy, f_sell = fr.get('buy') or [], fr.get('sell') or []
        t_buy, t_sell = tr.get('buy') or [], tr.get('sell') or []
        if (f_buy or f_sell) and (t_buy or t_sell):
            f_net = (sum(x.get('foreign_net_lot', 0) or 0 for x in f_buy)
                     + sum(x.get('foreign_net_lot', 0) or 0 for x in f_sell))
            t_net = (sum(x.get('trust_net_lot', 0) or 0 for x in t_buy)
                     + sum(x.get('trust_net_lot', 0) or 0 for x in t_sell))
            f_thr = TEMP_THRESHOLDS['consensus_foreign']
            t_thr = TEMP_THRESHOLDS['consensus_trust']
            # 雙條件: 同向 + 雙方各自量達標
            if f_net >= f_thr and t_net >= t_thr:
                sc = (20, 'extreme-bull')
            elif f_net > 0 and t_net > 0:
                sc = (15, 'bull')
            elif f_net <= -f_thr and t_net <= -t_thr:
                sc = (0, 'extreme-bear')
            elif f_net < 0 and t_net < 0:
                sc = (5, 'bear')
            else:
                # 一正一負 = 分歧, 中性
                sc = (10, 'neutral')
            signals.append({
                'name': '法人共識', 'score': sc[0], 'level': sc[1],
                'value': {'foreign_net': f_net, 'trust_net': t_net},
            })
    except Exception:
        pass

    # 信號 7 (v3.27 新): 結算日壓力 — 距結算日 d 天 × 外資期貨等效 OI
    if trade_date:
        try:
            d = _days_to_settlement(trade_date)
            eq = raw_output.get('futures_data', {}).get('summary', {}).get('foreign_equivalent_net_oi')
            if d is not None and eq is not None:
                near_thr = TEMP_THRESHOLDS['settlement_near_oi']
                week_thr = TEMP_THRESHOLDS['settlement_week_oi']
                if abs(d) <= 1:
                    # 結算當日±1: 反指標放大 (外資大空 → 預期反彈)
                    if eq <= -near_thr:    sc = (20, 'extreme-bull')
                    elif eq >= near_thr:   sc = (0, 'extreme-bear')
                    else:                  sc = (10, 'neutral')
                elif abs(d) <= 3:
                    # 結算週 (但非當日±1): 弱反指標
                    if eq <= -week_thr:    sc = (15, 'bull')
                    elif eq >= week_thr:   sc = (5, 'bear')
                    else:                  sc = (10, 'neutral')
                else:
                    # 非結算週: 信號退化為中性, 不污染溫度計
                    sc = (10, 'neutral')
                signals.append({
                    'name': '結算日壓力', 'score': sc[0], 'level': sc[1],
                    'value': {'days_to_settle': d, 'foreign_eq_oi': eq},
                })
        except Exception:
            pass

    if not signals:
        return None

    total = sum(s['score'] for s in signals)
    max_total = len(signals) * 20
    norm = round(total / max_total * 100) if max_total > 0 else 0

    return {
        'score': norm,
        'signals': signals,
        'total': total,
        'max_total': max_total,
        'signal_count': len(signals),
    }


def update_temp_history(data_dir, trade_date, temp_result, max_days=60):
    """更新 data/temp_history.json (前端 chart 讀取 + v3.27.1 校準資料源).

    v3.27.1 變更:
      - max_days 30 → 60 (校準需要更長窗口)
      - 每個 signal 多 'value' field (raw 數值, 供未來 v3.28 重算分數)
      - 每個 entry 多 'taiex_index'/'taiex_change_pct' (從 stock_history 的 market 區段)
      - 每個 entry 多 'next_day_change_pct' (今天 entry 寫 None, 隔天 entry 寫入時順便回填昨日的)
      - 加 _calibration_meta block (記錄當前閾值快照, v3.28 校準時參照)
    """
    hist_file = data_dir / "temp_history.json"
    history = []
    if hist_file.exists():
        try:
            with open(hist_file, 'r', encoding='utf-8') as f:
                history = json.load(f).get('history', [])
        except Exception:
            history = []

    # 從 stock_history.json 讀今日大盤 TAIEX
    taiex_today = None
    try:
        sh_file = data_dir / "stock_history.json"
        if sh_file.exists():
            with open(sh_file, 'r', encoding='utf-8') as f:
                sh = json.load(f)
            taiex_today = sh.get('market', {}).get(trade_date)
    except Exception:
        pass

    # 移除同日重複
    history = [h for h in history if h.get('date') != trade_date]

    # 追加今日 entry (v3.27.1: persist raw value + taiex + next_day_return placeholder)
    entry = {
        'date': trade_date,
        'score': temp_result['score'],
        'signals': [
            {
                'name': s['name'],
                'score': s['score'],
                'level': s['level'],
                'value': s.get('value'),  # v3.27.1: 持久化 raw value, 供 v3.28 校準
            }
            for s in temp_result['signals']
        ],
        'taiex_index': taiex_today.get('index') if taiex_today else None,
        'taiex_change_pct': taiex_today.get('change_pct') if taiex_today else None,
        'next_day_change_pct': None,  # 隔天 run 才會回填
    }
    history.append(entry)

    # 排序
    history.sort(key=lambda h: h.get('date', ''))

    # v3.27.1: 回填「最近一筆前一日 entry」的 next_day_change_pct
    # 例: 5/11 跑完寫入 5/11 entry 同時把 5/8 entry 的 next_day_change_pct 填成 5/11 的 taiex_change_pct
    if taiex_today and len(history) >= 2:
        # 找到剛追加的今日 entry 位置
        for i in range(len(history) - 1, -1, -1):
            if history[i]['date'] == trade_date:
                # 回填 i-1 (前一個交易日)
                if i >= 1 and history[i-1].get('next_day_change_pct') is None:
                    history[i-1]['next_day_change_pct'] = taiex_today.get('change_pct')
                break

    # 截斷
    history = history[-max_days:]

    payload = {
        'updated_at': now_tw().isoformat(),
        'count': len(history),
        'history': history,
        # v3.27.1 校準 metadata
        '_calibration_meta': {
            'min_days_for_calibration': 30,
            'ideal_days_for_calibration': 60,
            'thresholds_snapshot': dict(TEMP_THRESHOLDS),
            'last_calibrated_at': None,  # v3.28+ 校準工具寫入
            'note': (
                "raw 'value' per signal + taiex_change_pct + next_day_change_pct "
                "are the 3 fields v3.28 calibration needs. signal_audit.py 可 inspect."
            ),
        },
    }
    with open(hist_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return entry



# ========== FIFO 部位追蹤 ==========

def load_positions(data_dir: Path, password: str):
    """載入 positions.json 的加密內容；若不存在則回傳空結構"""
    positions_file = data_dir / "positions.json"
    if not positions_file.exists():
        return {"branches": {}, "baseline_date": BASELINE_DATE, "last_update_date": None}
    try:
        with open(positions_file, "r", encoding="utf-8") as f:
            enc = json.load(f)
        if enc.get("encrypted"):
            plain = decrypt_data(enc["data"], password)
            return json.loads(plain)
        else:
            return enc
    except Exception as e:
        print(f"⚠️  載入 positions.json 失敗 ({e})，從頭開始")
        return {"branches": {}, "baseline_date": BASELINE_DATE, "last_update_date": None}


def save_positions(positions: dict, data_dir: Path, password: str):
    """加密儲存 positions.json"""
    plaintext = json.dumps(positions, ensure_ascii=False)
    encrypted_token = encrypt_data(plaintext, password)
    output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "updated_at": now_tw().isoformat(),
        "baseline_date": positions.get("baseline_date", BASELINE_DATE),
        "data": encrypted_token,
    }
    with open(data_dir / "positions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def _rollback_day(positions: dict, trade_date: str) -> int:
    """
    回滾指定日期的 FIFO 變化（用於重跑同一天的覆蓋邏輯）
    
    操作：
      1. 從每個 stock.open_lots 移除該日新建立的 lot 項目
      2. 從每個 stock.realized_history 移除該日記錄
      3. 重算 total_realized_wan
    
    注意：FIFO 中已被 sell 消耗的 lot 無法精確還原（只能近似）
    所以這個機制只適合「同日內快速重跑」，不適合追溯
    
    Returns: 受影響的 (branch, stock) 組合數
    """
    affected = 0
    for br_code, br in positions.get("branches", {}).items():
        for stock_code, stock in br.get("stocks", {}).items():
            changed = False
            
            # 1) 移除該日新建立的 open_lots
            new_open_lots = [lot for lot in stock.get("open_lots", []) 
                             if lot.get("date") != trade_date]
            if len(new_open_lots) != len(stock.get("open_lots", [])):
                stock["open_lots"] = new_open_lots
                changed = True
            
            # 2) 移除該日的 realized_history
            new_history = [rec for rec in stock.get("realized_history", []) 
                           if rec.get("date") != trade_date]
            if len(new_history) != len(stock.get("realized_history", [])):
                # 重算 total
                rolled_pnl = sum(rec["pnl_wan"] for rec in stock.get("realized_history", [])
                                  if rec.get("date") == trade_date)
                stock["realized_history"] = new_history
                stock["total_realized_wan"] = round(
                    stock.get("total_realized_wan", 0.0) - rolled_pnl, 2)
                changed = True
            
            if changed:
                affected += 1
    
    # 把 last_update_date 設為前一個有資料的日期（從歷史推算）
    all_dates = set()
    for br in positions.get("branches", {}).values():
        for st in br.get("stocks", {}).values():
            for rec in st.get("realized_history", []):
                all_dates.add(rec.get("date"))
    
    prior_dates = sorted([d for d in all_dates if d and d < trade_date], reverse=True)
    positions["last_update_date"] = prior_dates[0] if prior_dates else None
    
    return affected


def apply_day_to_positions(positions: dict, trade_date: str, branches_data: list):
    """
    用當日交易資料更新累積部位（FIFO 演算法）
    
    positions["branches"][branch_code]["stocks"][stock_code] = {
        "stock_name": "聯發科",
        "open_lots": [  # FIFO 佇列
            {"date": "20260421", "lots": 402, "avg_price": 2039.38}
        ],
        "realized_history": [
            {"date": "20260421", "pnl_wan": 6.3, "lots_closed": 9}
        ],
        "total_realized_wan": 6.3
    }
    """
    baseline = positions.get("baseline_date", BASELINE_DATE)
    if trade_date < baseline:
        print(f"  (跳過累積損益更新，{trade_date} 早於基準日 {baseline})")
        return
    
    # ════════════════════════════════════════════════════════════════
    # 重複跑同一天的處理（例如 18:30 第一次 + 20:00 第二次）
    # ════════════════════════════════════════════════════════════════
    # 策略：
    #   - 若 trade_date < last_update_date，跳過（避免回頭爬舊日期）
    #   - 若 trade_date == last_update_date，回滾當日的 FIFO 變化後重做
    #     這樣第二次跑就能用更完整的資料覆蓋第一次
    
    last_date = positions.get("last_update_date")
    
    if last_date and trade_date < last_date:
        print(f"  (跳過：{trade_date} 早於 last_update_date={last_date})")
        return
    
    if last_date and trade_date == last_date:
        print(f"  (重新跑同一天 {trade_date}：先回滾當日 FIFO 變化...)")
        rolled_back_count = _rollback_day(positions, trade_date)
        print(f"  → 回滾完成，影響 {rolled_back_count} 個 branch×stock 組合")
    
    branches_store = positions.setdefault("branches", {})
    
    for br in branches_data:
        branch_code = br["code"]
        if not br.get("buys"):
            continue
        
        br_store = branches_store.setdefault(branch_code, {
            "branch_name": br["name"],
            "master": br["master"],
            "stocks": {},
        })
        # 更新分點名（可能有改）
        br_store["branch_name"] = br["name"]
        br_store["master"] = br["master"]
        stocks_store = br_store["stocks"]
        
        # 把 buys + sells 合併成「股票級」的進出記錄
        # buys 裡面的 buy_lot/buy_amt 是當天買了多少
        # buys 和 sells 可能會列出同一檔股票（從不同排序看）
        # 以 buys 為主，因為資料最完整
        seen_codes = set()
        
        for s in br["buys"]:
            stock_code = s["code"]
            if stock_code in seen_codes:
                continue
            seen_codes.add(stock_code)
            
            # 只對「資料完整」（金額+張數都有）的股票做 FIFO
            if not s.get("data_complete", False):
                continue
            
            # 取得當日該分點對該股票的完整進出
            buy_lot = s.get("buy_lot", 0)
            sell_lot = s.get("sell_lot", 0)
            buy_avg = s.get("buy_avg", 0.0)
            sell_avg = s.get("sell_avg", 0.0)
            
            if buy_lot == 0 and sell_lot == 0:
                continue
            
            # 取出或新建該股票部位
            stock_store = stocks_store.setdefault(stock_code, {
                "stock_name": s["name"],
                "open_lots": [],  # FIFO: [{date, lots, avg_price}, ...]
                "realized_history": [],
                "total_realized_wan": 0.0,
            })
            stock_store["stock_name"] = s["name"]
            
            # Step 1: 先建倉（把買進的量加入 FIFO 佇列末尾）
            if buy_lot > 0:
                stock_store["open_lots"].append({
                    "date": trade_date,
                    "lots": buy_lot,
                    "avg_price": buy_avg,
                })
            
            # Step 2: 平倉（從 FIFO 佇列頭部開始扣）
            day_pnl_wan = 0.0
            lots_closed_today = 0
            
            if sell_lot > 0:
                remaining = sell_lot
                queue = stock_store["open_lots"]
                
                while remaining > 0 and queue:
                    head = queue[0]
                    if head["lots"] <= remaining:
                        # 整筆出清
                        closed = head["lots"]
                        pnl = (sell_avg - head["avg_price"]) * closed * 1000 / 10000  # 萬元
                        day_pnl_wan += pnl
                        lots_closed_today += closed
                        remaining -= closed
                        queue.pop(0)
                    else:
                        # 部分出清
                        closed = remaining
                        pnl = (sell_avg - head["avg_price"]) * closed * 1000 / 10000
                        day_pnl_wan += pnl
                        lots_closed_today += closed
                        head["lots"] -= closed
                        remaining = 0
                
                # 如果賣超過持有（可能是基準日前就有倉位），剩餘的 remaining 當作「無基底賣出」
                # 用當日買均作為推估成本，避免異常損益
                if remaining > 0:
                    # 使用當日買均作為假設成本（保守處理）
                    assumed_cost = buy_avg if buy_avg > 0 else sell_avg
                    pnl = (sell_avg - assumed_cost) * remaining * 1000 / 10000
                    day_pnl_wan += pnl
                    lots_closed_today += remaining
            
            # 記錄當日已實現
            if abs(day_pnl_wan) > 0.001 or lots_closed_today > 0:
                day_pnl_wan = round(day_pnl_wan, 2)
                stock_store["realized_history"].append({
                    "date": trade_date,
                    "pnl_wan": day_pnl_wan,
                    "lots_closed": lots_closed_today,
                })
                stock_store["total_realized_wan"] = round(
                    stock_store.get("total_realized_wan", 0.0) + day_pnl_wan, 2
                )
    
    positions["last_update_date"] = trade_date


def compute_period_summaries(positions: dict, trade_date: str, today_branches_data: list = None):
    """
    給每個分點計算：日/週/月/累積 損益，以及交易風格
    回傳 dict: {branch_code: {daily, weekly, monthly, total, open_positions_count, style, ...}}
    
    today_branches_data: 當日爬取的 results 列表，用於計算當日風格指標
    """
    from datetime import datetime as _dt
    
    def parse_date(d):
        return _dt.strptime(d, "%Y%m%d")
    
    today = parse_date(trade_date)
    week_start = today - timedelta(days=today.weekday())  # 本週一
    month_start = today.replace(day=1)
    
    # 當日爬蟲結果 index
    today_branches_map = {}
    if today_branches_data:
        for br in today_branches_data:
            today_branches_map[br["code"]] = br
    
    summaries = {}
    
    # 先處理有 positions 紀錄的分點（歷史損益）
    all_branch_codes = set(positions.get("branches", {}).keys()) | set(today_branches_map.keys())
    
    for branch_code in all_branch_codes:
        br = positions.get("branches", {}).get(branch_code, {"stocks": {}})
        daily = 0.0
        weekly = 0.0
        monthly = 0.0
        total = 0.0
        open_pos_count = 0
        open_total_lots = 0
        
        for stock_code, stock in br.get("stocks", {}).items():
            total += stock.get("total_realized_wan", 0.0)
            for rec in stock.get("realized_history", []):
                try:
                    rec_date = parse_date(rec["date"])
                    pnl = rec.get("pnl_wan", 0.0)
                    if rec_date == today:
                        daily += pnl
                    if rec_date >= week_start:
                        weekly += pnl
                    if rec_date >= month_start:
                        monthly += pnl
                except Exception:
                    continue
            total_lots_for_stock = sum(p["lots"] for p in stock.get("open_lots", []))
            if total_lots_for_stock > 0:
                open_pos_count += 1
                open_total_lots += total_lots_for_stock
        
        # === 當日風格指標 ===
        today_br = today_branches_map.get(branch_code)
        avg_daytrade_ratio = 0.0
        today_total_buy_lot = 0
        today_total_sell_lot = 0
        today_total_buy_amt = 0
        today_total_sell_amt = 0
        today_overnight_lots = 0   # 今日淨新建倉
        today_overnight_cost_wan = 0.0
        today_daytrade_stocks = 0
        today_overnight_stocks = 0
        today_partial_stocks = 0
        stocks_count = 0
        ratio_sum = 0.0
        
        if today_br and today_br.get("buys"):
            for s in today_br["buys"]:
                if not (s.get("buy_lot") or s.get("sell_lot") or s.get("buy_amt") or s.get("sell_amt")):
                    continue
                stocks_count += 1
                today_total_buy_lot += s.get("buy_lot", 0)
                today_total_sell_lot += s.get("sell_lot", 0)
                today_total_buy_amt += s.get("buy_amt", 0)
                today_total_sell_amt += s.get("sell_amt", 0)
                today_overnight_lots += s.get("overnight_lots", 0)
                today_overnight_cost_wan += s.get("overnight_cost_wan", 0.0)
                ratio_sum += s.get("daytrade_ratio", 0.0)
                style = s.get("trade_style", "")
                if style == "daytrade":
                    today_daytrade_stocks += 1
                elif style == "overnight":
                    today_overnight_stocks += 1
                elif style == "partial":
                    today_partial_stocks += 1
        
        if stocks_count > 0:
            avg_daytrade_ratio = round(ratio_sum / stocks_count, 3)
        
        # 當日風格判定（基於當日所有股票平均）
        today_style = "unknown"
        if stocks_count >= 3:
            if avg_daytrade_ratio >= 0.55:
                today_style = "daytrader"
            elif avg_daytrade_ratio >= 0.3:
                today_style = "mixed"
            else:
                today_style = "swing"
        
        summaries[branch_code] = {
            "daily_pnl": round(daily, 2),
            "weekly_pnl": round(weekly, 2),
            "monthly_pnl": round(monthly, 2),
            "total_pnl": round(total, 2),
            "open_positions_count": open_pos_count,
            "open_total_lots": open_total_lots,
            # 風格資訊
            "today_style": today_style,
            "avg_daytrade_ratio": avg_daytrade_ratio,
            "today_buy_lot": today_total_buy_lot,
            "today_sell_lot": today_total_sell_lot,
            "today_buy_amt": today_total_buy_amt,
            "today_sell_amt": today_total_sell_amt,
            "today_net_amt": today_total_buy_amt - today_total_sell_amt,
            "today_overnight_lots": today_overnight_lots,
            "today_overnight_cost_wan": round(today_overnight_cost_wan, 2),
            "today_daytrade_stocks": today_daytrade_stocks,
            "today_overnight_stocks": today_overnight_stocks,
            "today_partial_stocks": today_partial_stocks,
            "today_stocks_count": stocks_count,
        }
    
    return summaries


def compute_limit_up_summary(today_branches_data: list, unique_branches: list):
    """
    v3.12 漲停狙擊匯總
    
    回傳:
    {
      "limit_up_stocks": [  # 今日所有漲停股
        {
          "code": "4536", "name": "達能", "change_pct": 10.0,
          "close": 123.5, "volume_lot": 3500,
          "buyers": [  # 我的分點中誰買了這檔漲停
            {"branch_code": "9227", "branch_name": "凱基-城中", 
             "master": "蔣承翰", "styles": ["next_day_flipper"],
             "buy_amt": 500, "buy_lot": 100, "net_amt": 450, "net_lot": 90,
             "overnight_lots": 90}
          ],
          "total_buy_amt": ..., "total_buy_lot": ...,
          "buyer_count": 1
        }
      ],
      "sniper_ranking": [  # 各分點的漲停狙擊成績
        {
          "branch_code": "9227", "branch_name": "凱基-城中",
          "master": "蔣承翰", "styles": ["next_day_flipper"],
          "limit_up_stocks_bought": 5,           # 買了幾檔漲停股
          "total_limit_up_buy_amt": 2850,        # 買漲停股總金額
          "total_limit_up_buy_lot": 500,         # 買漲停股總張數
          "limit_up_codes": ["4536", "5314", ...]
        }
      ],
      "master_sniper_ranking": [  # 各 master 的漲停狙擊成績（多分點合併）
        {"master": "蔣承翰", "styles": ["next_day_flipper"],
         "branches_count": 2, "limit_up_stocks_bought": 8,
         "total_limit_up_buy_amt": 4500, ...}
      ],
      "consensus_limit_up": [  # 2 位以上 master 同時買的漲停股（超強信號）
        {
          "code": "...", "name": "...", "masters_list": [...],
          "master_count": 3, "total_buy_amt": ...
        }
      ],
      "style_stats": {  # 各風格的漲停狙擊統計
        "next_day_flipper": {"masters": [...], "limit_up_count": 8, "total_buy_amt": 4500},
        ...
      },
      "total_limit_up_today": 35,   # 全市場漲停股總數
      "limit_up_bought_count": 8,    # 我的分點買到幾檔漲停
    }
    """
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # 收集所有被分點買的漲停股
    limit_up_map = {}  # {stock_code: {...}}
    sniper_map = {}    # {branch_code: {...}}
    
    # v3.13：漲停股被分點賣出 (出貨/隔日沖 Day2 結清)
    limit_up_sell_map = {}   # {stock_code: {sellers:[...]}}
    seller_map = {}          # {branch_code: {...}}
    
    for br_data in today_branches_data:
        branch_code = br_data["code"]
        branch_obj = code_to_branch.get(branch_code, {})
        master = br_data.get("master", "")
        styles = MASTER_STYLES.get(master, ["unknown"])
        
        # ───── BUY 側（原邏輯）─────
        for s in (br_data.get("buys") or []):
            if not s.get("is_limit_up"):
                continue
            
            stock_code = s.get("code")
            if not stock_code:
                continue
            
            # 加入漲停股清單
            if stock_code not in limit_up_map:
                limit_up_map[stock_code] = {
                    "code": stock_code,
                    "name": s.get("name", ""),
                    "change_pct": s.get("change_pct"),
                    "close": s.get("close_price"),
                    "volume_lot": s.get("volume_lot"),
                    "market_type": s.get("market_type"),
                    "industry": s.get("industry"),
                    "buyers": [],
                    "total_buy_amt": 0,
                    "total_buy_lot": 0,
                    "total_net_amt": 0,
                    "total_net_lot": 0,
                    "total_overnight_lots": 0,
                    "masters_set": set(),
                }
            
            lu = limit_up_map[stock_code]
            lu["buyers"].append({
                "branch_code": branch_code,
                "branch_name": br_data.get("name", ""),
                "master": master,
                "styles": styles,
                "region": br_data.get("region", "domestic"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),
                "net_lot": s.get("net_lot", 0),
                "overnight_lots": s.get("overnight_lots", 0),
            })
            lu["total_buy_amt"] += s.get("buy_amt", 0) or 0
            lu["total_buy_lot"] += s.get("buy_lot", 0) or 0
            lu["total_net_amt"] += s.get("net_amt", 0) or 0
            lu["total_net_lot"] += s.get("net_lot", 0) or 0
            lu["total_overnight_lots"] += s.get("overnight_lots", 0) or 0
            lu["masters_set"].add(master)
            
            # 分點狙擊榜
            if branch_code not in sniper_map:
                sniper_map[branch_code] = {
                    "branch_code": branch_code,
                    "branch_name": br_data.get("name", ""),
                    "master": master,
                    "styles": styles,
                    "region": br_data.get("region", "domestic"),
                    "limit_up_stocks_bought": 0,
                    "total_limit_up_buy_amt": 0,
                    "total_limit_up_buy_lot": 0,
                    "total_limit_up_net_amt": 0,
                    "total_limit_up_overnight_lots": 0,
                    "limit_up_details": [],   # 每筆漲停買進
                }
            sn = sniper_map[branch_code]
            sn["limit_up_stocks_bought"] += 1
            sn["total_limit_up_buy_amt"] += s.get("buy_amt", 0) or 0
            sn["total_limit_up_buy_lot"] += s.get("buy_lot", 0) or 0
            sn["total_limit_up_net_amt"] += s.get("net_amt", 0) or 0
            sn["total_limit_up_overnight_lots"] += s.get("overnight_lots", 0) or 0
            sn["limit_up_details"].append({
                "code": stock_code,
                "name": s.get("name", ""),
                "change_pct": s.get("change_pct"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "net_amt": s.get("net_amt", 0),
                "overnight_lots": s.get("overnight_lots", 0),
            })
        
        # ───── SELL 側 (v3.13 新增) ─────
        # 分點「賣超」漲停股 → 疑似隔日沖 Day2 出貨 / 獲利了結
        for s in (br_data.get("sells") or []):
            if not s.get("is_limit_up"):
                continue
            stock_code = s.get("code")
            if not stock_code:
                continue
            
            # 加入漲停賣出清單
            if stock_code not in limit_up_sell_map:
                limit_up_sell_map[stock_code] = {
                    "code": stock_code,
                    "name": s.get("name", ""),
                    "change_pct": s.get("change_pct"),
                    "close": s.get("close_price"),
                    "volume_lot": s.get("volume_lot"),
                    "market_type": s.get("market_type"),
                    "sellers": [],
                    "total_sell_amt": 0,
                    "total_sell_lot": 0,
                    "total_net_sell_amt": 0,   # 淨賣（負數）
                    "total_net_sell_lot": 0,
                    "masters_set": set(),
                }
            
            ls = limit_up_sell_map[stock_code]
            ls["sellers"].append({
                "branch_code": branch_code,
                "branch_name": br_data.get("name", ""),
                "master": master,
                "styles": styles,
                "region": br_data.get("region", "domestic"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),  # 會是負數（淨賣）
                "net_lot": s.get("net_lot", 0),
            })
            ls["total_sell_amt"] += s.get("sell_amt", 0) or 0
            ls["total_sell_lot"] += s.get("sell_lot", 0) or 0
            ls["total_net_sell_amt"] += s.get("net_amt", 0) or 0
            ls["total_net_sell_lot"] += s.get("net_lot", 0) or 0
            ls["masters_set"].add(master)
            
            # 分點「漲停出貨榜」
            if branch_code not in seller_map:
                seller_map[branch_code] = {
                    "branch_code": branch_code,
                    "branch_name": br_data.get("name", ""),
                    "master": master,
                    "styles": styles,
                    "region": br_data.get("region", "domestic"),
                    "limit_up_stocks_sold": 0,
                    "total_limit_up_sell_amt": 0,
                    "total_limit_up_sell_lot": 0,
                    "total_limit_up_net_sell_amt": 0,
                    "limit_up_sell_details": [],
                }
            sel = seller_map[branch_code]
            sel["limit_up_stocks_sold"] += 1
            sel["total_limit_up_sell_amt"] += s.get("sell_amt", 0) or 0
            sel["total_limit_up_sell_lot"] += s.get("sell_lot", 0) or 0
            sel["total_limit_up_net_sell_amt"] += s.get("net_amt", 0) or 0
            sel["limit_up_sell_details"].append({
                "code": stock_code,
                "name": s.get("name", ""),
                "change_pct": s.get("change_pct"),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),
            })
    
    # 後處理：漲停股清單 + 排序
    limit_up_stocks = []
    consensus_limit_up = []
    for code, lu in limit_up_map.items():
        lu["masters_list"] = sorted(lu["masters_set"])
        lu["master_count"] = len(lu["masters_set"])
        lu["buyer_count"] = len(lu["buyers"])
        del lu["masters_set"]
        limit_up_stocks.append(lu)
        
        # 2 位以上 master 共買 → 加入 consensus
        if lu["master_count"] >= 2:
            consensus_limit_up.append(lu)
    
    limit_up_stocks.sort(key=lambda x: (-x["master_count"], -x["total_buy_amt"]))
    consensus_limit_up.sort(key=lambda x: (-x["master_count"], -x["total_buy_amt"]))
    
    # 分點狙擊排名
    sniper_ranking = sorted(sniper_map.values(), 
                             key=lambda x: (-x["limit_up_stocks_bought"], -x["total_limit_up_buy_amt"]))
    
    # Master 層級聚合（多分點合併）
    master_sniper_map = {}
    for sn in sniper_ranking:
        m = sn["master"]
        if m not in master_sniper_map:
            master_sniper_map[m] = {
                "master": m,
                "styles": sn["styles"],
                "branches": [],
                "limit_up_codes_set": set(),
                "total_limit_up_buy_amt": 0,
                "total_limit_up_buy_lot": 0,
                "total_limit_up_net_amt": 0,
                "total_limit_up_overnight_lots": 0,
            }
        ms = master_sniper_map[m]
        ms["branches"].append({
            "code": sn["branch_code"],
            "name": sn["branch_name"],
            "limit_up_stocks_bought": sn["limit_up_stocks_bought"],
            "total_buy_amt": sn["total_limit_up_buy_amt"],
        })
        ms["total_limit_up_buy_amt"] += sn["total_limit_up_buy_amt"]
        ms["total_limit_up_buy_lot"] += sn["total_limit_up_buy_lot"]
        ms["total_limit_up_net_amt"] += sn["total_limit_up_net_amt"]
        ms["total_limit_up_overnight_lots"] += sn["total_limit_up_overnight_lots"]
        for d in sn["limit_up_details"]:
            ms["limit_up_codes_set"].add(d["code"])
    
    master_sniper_ranking = []
    for m, data in master_sniper_map.items():
        data["branches_count"] = len(data["branches"])
        data["limit_up_stocks_bought"] = len(data["limit_up_codes_set"])
        data["limit_up_codes"] = sorted(data["limit_up_codes_set"])
        del data["limit_up_codes_set"]
        master_sniper_ranking.append(data)
    master_sniper_ranking.sort(key=lambda x: (-x["limit_up_stocks_bought"], -x["total_limit_up_buy_amt"]))
    
    # 依風格統計
    style_stats = {}
    for sn in sniper_ranking:
        for style in sn["styles"]:
            if style not in style_stats:
                style_stats[style] = {
                    "style": style,
                    "masters": set(),
                    "limit_up_count": 0,
                    "total_buy_amt": 0,
                    "total_buy_lot": 0,
                }
            ss = style_stats[style]
            ss["masters"].add(sn["master"])
            ss["limit_up_count"] += sn["limit_up_stocks_bought"]
            ss["total_buy_amt"] += sn["total_limit_up_buy_amt"]
            ss["total_buy_lot"] += sn["total_limit_up_buy_lot"]
    for style, ss in style_stats.items():
        ss["masters"] = sorted(ss["masters"])
        ss["master_count"] = len(ss["masters"])
    
    # v3.13：漲停賣出 (隔日沖 Day2 出貨 / 獲利了結) 後處理
    limit_up_sold_stocks = []
    for code, ls in limit_up_sell_map.items():
        ls["masters_list"] = sorted(ls["masters_set"])
        ls["master_count"] = len(ls["masters_set"])
        ls["seller_count"] = len(ls["sellers"])
        del ls["masters_set"]
        limit_up_sold_stocks.append(ls)
    limit_up_sold_stocks.sort(key=lambda x: (-x["master_count"], -x["total_sell_amt"]))
    
    # 分點漲停出貨排名
    seller_ranking = sorted(seller_map.values(),
                             key=lambda x: (-x["limit_up_stocks_sold"], -x["total_limit_up_sell_amt"]))
    
    return {
        "limit_up_stocks": limit_up_stocks,
        "sniper_ranking": sniper_ranking,
        "master_sniper_ranking": master_sniper_ranking,
        "consensus_limit_up": consensus_limit_up,
        "style_stats": style_stats,
        "limit_up_bought_count": len(limit_up_stocks),
        # v3.13 新增
        "limit_up_sold_stocks": limit_up_sold_stocks,   # 今日被我分點賣超的漲停股
        "seller_ranking": seller_ranking,               # 分點漲停出貨排名
        "limit_up_sold_count": len(limit_up_sold_stocks),
    }


def compute_next_day_flip_verification(today_branches_data: list, 
                                        yesterday_branches_data: list,
                                        unique_branches: list):
    """
    v3.13 隔日沖驗證 — 比對「昨日漲停買進」vs「今日賣超」
    
    實戰場景:
      Day 1: 蔣承翰的 9227 分點買進漲停聯發科 300 張
      Day 2: 9227 分點賣超聯發科 280 張 → 確認隔日沖出貨
    
    回傳:
    {
      "verified_flips": [  # 確認隔日沖的案例
        {
          "branch_code": "9227", "branch_name": "凱基-城中",
          "master": "蔣承翰", "styles": [...],
          "stock_code": "2454", "stock_name": "聯發科",
          "yesterday_buy_lot": 300,  "yesterday_buy_amt": 5000,
          "yesterday_change_pct": 10.0,
          "today_sell_lot": 280, "today_sell_amt": 4800,
          "today_change_pct": -2.5,
          "flip_ratio": 93.3,  # 出貨比例 = 今賣張 / 昨買張
          "status": "full_flip" | "partial_flip" | "over_flip",
        }
      ],
      "pending_positions": [  # 昨日買進但今日未賣（還在留倉）
        { ..., "flip_ratio": 0, "status": "still_holding" }
      ],
      "flipper_scorecard": [  # 依 master 聚合出貨表現
        {
          "master": "蔣承翰", "styles": [...],
          "verified_flip_count": 8,
          "pending_count": 2,
          "total_yesterday_buy_lot": 1200,
          "total_today_sell_lot": 1080,
          "overall_flip_ratio": 90.0,
        }
      ],
      "is_first_day": bool,  # 是否為系統首日（沒昨日資料）
    }
    """
    if not yesterday_branches_data:
        return {
            "verified_flips": [],
            "pending_positions": [],
            "flipper_scorecard": [],
            "is_first_day": True,
        }
    
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # Step 1: 建 index — 昨日漲停買進明細
    # key = (branch_code, stock_code), value = {...}
    yesterday_limit_up_buys = {}
    for br_data in yesterday_branches_data:
        branch_code = br_data.get("code")
        if not branch_code or not br_data.get("buys"):
            continue
        for s in br_data["buys"]:
            # v3.12 之前沒有 is_limit_up 欄位，相容處理
            is_lu = s.get("is_limit_up")
            if is_lu is None:
                # 用 change_pct 判定
                cp = s.get("change_pct")
                is_lu = (cp is not None and cp >= LIMIT_UP_THRESHOLD)
            if not is_lu:
                continue
            stock_code = s.get("code")
            if not stock_code:
                continue
            key = (branch_code, stock_code)
            yesterday_limit_up_buys[key] = {
                "branch_code": branch_code,
                "stock_code": stock_code,
                "stock_name": s.get("name", ""),
                "buy_lot": s.get("buy_lot", 0) or 0,
                "buy_amt": s.get("buy_amt", 0) or 0,
                "overnight_lots": s.get("overnight_lots", 0) or 0,
                "change_pct": s.get("change_pct"),
            }
    
    # Step 2: 建 index — 今日「該分點 vs 該股」的所有交易（買+賣）
    today_trades = {}
    for br_data in today_branches_data:
        branch_code = br_data.get("code")
        if not branch_code:
            continue
        # buys 和 sells 都要看
        for s in (br_data.get("buys") or []) + (br_data.get("sells") or []):
            stock_code = s.get("code")
            if not stock_code:
                continue
            key = (branch_code, stock_code)
            # 累加（因為 buys 和 sells 理論上不會有同一檔，但保險處理）
            if key in today_trades:
                continue
            today_trades[key] = {
                "branch_code": branch_code,
                "stock_code": stock_code,
                "buy_lot": s.get("buy_lot", 0) or 0,
                "sell_lot": s.get("sell_lot", 0) or 0,
                "buy_amt": s.get("buy_amt", 0) or 0,
                "sell_amt": s.get("sell_amt", 0) or 0,
                "change_pct": s.get("change_pct"),
            }
    
    # Step 3: 配對 — 昨日漲停買進 × 今日賣出動作
    verified_flips = []
    pending_positions = []
    
    for key, yest in yesterday_limit_up_buys.items():
        branch_code = yest["branch_code"]
        branch_obj = code_to_branch.get(branch_code, {})
        master = branch_obj.get("master", "")
        styles = MASTER_STYLES.get(master, ["unknown"])
        
        today = today_trades.get(key, {})
        today_sell_lot = today.get("sell_lot", 0)
        today_sell_amt = today.get("sell_amt", 0)
        
        # 計算出貨比例
        if yest["buy_lot"] > 0:
            flip_ratio = round(today_sell_lot / yest["buy_lot"] * 100, 1)
        else:
            flip_ratio = 0.0
        
        # 判定狀態
        if flip_ratio >= 90:
            status = "full_flip"        # 幾乎全部出清
        elif flip_ratio >= 30:
            status = "partial_flip"     # 部分出貨
        elif flip_ratio > 0:
            status = "minor_flip"       # 少量出貨
        else:
            status = "still_holding"    # 尚未賣出
        
        record = {
            "branch_code": branch_code,
            "branch_name": branch_obj.get("name", ""),
            "master": master,
            "styles": styles,
            "region": branch_obj.get("region", "domestic"),
            "stock_code": yest["stock_code"],
            "stock_name": yest["stock_name"],
            "yesterday_buy_lot": yest["buy_lot"],
            "yesterday_buy_amt": yest["buy_amt"],
            "yesterday_overnight_lots": yest["overnight_lots"],
            "yesterday_change_pct": yest["change_pct"],
            "today_sell_lot": today_sell_lot,
            "today_sell_amt": today_sell_amt,
            "today_change_pct": today.get("change_pct"),
            "flip_ratio": flip_ratio,
            "status": status,
        }
        
        if status == "still_holding":
            pending_positions.append(record)
        else:
            verified_flips.append(record)
    
    # 按出貨比例降序
    verified_flips.sort(key=lambda x: -x["flip_ratio"])
    pending_positions.sort(key=lambda x: -x["yesterday_buy_amt"])
    
    # Step 4: Master 聚合評分
    master_map = {}
    for rec in verified_flips + pending_positions:
        m = rec["master"]
        if m not in master_map:
            master_map[m] = {
                "master": m,
                "styles": rec["styles"],
                "verified_flip_count": 0,
                "pending_count": 0,
                "total_yesterday_buy_lot": 0,
                "total_yesterday_buy_amt": 0,
                "total_today_sell_lot": 0,
                "total_today_sell_amt": 0,
            }
        mm = master_map[m]
        if rec["status"] != "still_holding":
            mm["verified_flip_count"] += 1
        else:
            mm["pending_count"] += 1
        mm["total_yesterday_buy_lot"] += rec["yesterday_buy_lot"]
        mm["total_yesterday_buy_amt"] += rec["yesterday_buy_amt"]
        mm["total_today_sell_lot"] += rec["today_sell_lot"]
        mm["total_today_sell_amt"] += rec["today_sell_amt"]
    
    flipper_scorecard = []
    for m, mm in master_map.items():
        if mm["total_yesterday_buy_lot"] > 0:
            mm["overall_flip_ratio"] = round(
                mm["total_today_sell_lot"] / mm["total_yesterday_buy_lot"] * 100, 1)
        else:
            mm["overall_flip_ratio"] = 0.0
        flipper_scorecard.append(mm)
    flipper_scorecard.sort(key=lambda x: -x["overall_flip_ratio"])
    
    return {
        "verified_flips": verified_flips,
        "pending_positions": pending_positions,
        "flipper_scorecard": flipper_scorecard,
        "is_first_day": False,
    }


def compute_master_summaries(branch_summaries: dict, unique_branches: list, today_branches_data: list = None):
    """
    按高手（master）聚合多分點的統計
    v3.10：支援 co_masters（一分點歸入多位 master）
    回傳: {master_name: {branches: [...], total_*, consensus_stocks: [...]}}
    """
    # 分點代號 → [主 master] + [co_masters]（陣列形式）
    def all_masters_of(b):
        lst = [b.get("master", "未知")]
        lst.extend(b.get("co_masters", []) or [])
        return [m for m in lst if m]
    
    code_to_all_masters = {b["code"]: all_masters_of(b) for b in unique_branches}
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # 今日爬蟲資料 index
    today_map = {}
    if today_branches_data:
        for br in today_branches_data:
            today_map[br["code"]] = br
    
    master_data = {}
    
    for branch_code, summary in branch_summaries.items():
        # v3.10：一個分點可能歸入多位 master
        for master in code_to_all_masters.get(branch_code, ["未知"]):
            if master not in master_data:
                master_data[master] = {
                    "master": master,
                    "branches": [],
                    "total_daily_pnl": 0.0,
                    "total_weekly_pnl": 0.0,
                    "total_monthly_pnl": 0.0,
                    "total_cumulative_pnl": 0.0,
                    "total_buy_amt": 0,
                    "total_sell_amt": 0,
                    "total_buy_lot": 0,
                    "total_sell_lot": 0,
                    "total_overnight_lots": 0,
                    "total_overnight_cost_wan": 0.0,
                    "total_open_positions": 0,
                    "total_open_lots": 0,
                    "avg_daytrade_ratio_sum": 0.0,
                    "branches_count_with_data": 0,
                    "daytrade_stocks": 0,
                    "overnight_stocks": 0,
                    "partial_stocks": 0,
                    "tags_personal": set(),
                    "tags_market": set(),
                    "stock_stats": {},
                    "sell_stats": {},  # v3.13 賣超個股彙整
                }
            
            mdata = master_data[master]
            branch_obj = code_to_branch.get(branch_code, {})
            
            # v3.10：如果此分點對此 master 是「共用」，加個標記
            is_shared = (branch_obj.get("master") != master)
            primary_master = branch_obj.get("master", "")
            
            mdata["branches"].append({
                "code": branch_code,
                "name": branch_obj.get("name", ""),
                "summary": summary,
                "tags_personal": branch_obj.get("tags_personal", []),
                "tags_market": branch_obj.get("tags_market", []),
                "is_shared": is_shared,       # v3.10：是否共用
                "primary_master": primary_master,  # v3.10：主要歸屬（若共用）
            })
            for t in branch_obj.get("tags_personal", []):
                mdata["tags_personal"].add(t)
            for t in branch_obj.get("tags_market", []):
                mdata["tags_market"].add(t)
            mdata["total_daily_pnl"] += summary["daily_pnl"]
            mdata["total_weekly_pnl"] += summary["weekly_pnl"]
            mdata["total_monthly_pnl"] += summary["monthly_pnl"]
            mdata["total_cumulative_pnl"] += summary["total_pnl"]
            mdata["total_buy_amt"] += summary.get("today_buy_amt", 0)
            mdata["total_sell_amt"] += summary.get("today_sell_amt", 0)
            mdata["total_buy_lot"] += summary.get("today_buy_lot", 0)
            mdata["total_sell_lot"] += summary.get("today_sell_lot", 0)
            mdata["total_overnight_lots"] += summary.get("today_overnight_lots", 0)
            mdata["total_overnight_cost_wan"] += summary.get("today_overnight_cost_wan", 0.0)
            mdata["total_open_positions"] += summary.get("open_positions_count", 0)
            mdata["total_open_lots"] += summary.get("open_total_lots", 0)
            mdata["daytrade_stocks"] += summary.get("today_daytrade_stocks", 0)
            mdata["overnight_stocks"] += summary.get("today_overnight_stocks", 0)
            mdata["partial_stocks"] += summary.get("today_partial_stocks", 0)
            
            if summary.get("today_stocks_count", 0) > 0:
                mdata["avg_daytrade_ratio_sum"] += summary.get("avg_daytrade_ratio", 0.0)
                mdata["branches_count_with_data"] += 1
            
            # 彙整該分點買進的個股
            today_br = today_map.get(branch_code)
            if today_br and today_br.get("buys"):
                for s in today_br["buys"]:
                    code = s["code"]
                    if code not in mdata["stock_stats"]:
                        mdata["stock_stats"][code] = {
                            "code": code, "name": s["name"],
                            "branches": [],
                            "total_buy_amt": 0, "total_sell_amt": 0, "total_net_amt": 0,
                            "total_buy_lot": 0, "total_sell_lot": 0, "total_net_lot": 0,
                            "total_overnight_lots": 0,
                        }
                    ss = mdata["stock_stats"][code]
                    ss["branches"].append({
                        "code": branch_code,
                        "name": code_to_branch.get(branch_code, {}).get("name", ""),
                        "buy_amt": s.get("buy_amt", 0),
                        "sell_amt": s.get("sell_amt", 0),
                        "net_amt": s.get("net_amt", 0),
                        "buy_lot": s.get("buy_lot", 0),
                        "sell_lot": s.get("sell_lot", 0),
                        "net_lot": s.get("net_lot", 0),
                        "overnight_lots": s.get("overnight_lots", 0),
                    })
                    ss["total_buy_amt"] += s.get("buy_amt", 0)
                    ss["total_sell_amt"] += s.get("sell_amt", 0)
                    ss["total_net_amt"] += s.get("net_amt", 0)
                    ss["total_buy_lot"] += s.get("buy_lot", 0)
                    ss["total_sell_lot"] += s.get("sell_lot", 0)
                    ss["total_net_lot"] += s.get("net_lot", 0)
                    ss["total_overnight_lots"] += s.get("overnight_lots", 0)
            
            # v3.13 新增：彙整該分點「賣超」的個股（淨賣方向）
            if today_br and today_br.get("sells"):
                for s in today_br["sells"]:
                    code = s["code"]
                    if code not in mdata["sell_stats"]:
                        mdata["sell_stats"][code] = {
                            "code": code, "name": s["name"],
                            "branches": [],
                            "total_buy_amt": 0, "total_sell_amt": 0, "total_net_amt": 0,
                            "total_buy_lot": 0, "total_sell_lot": 0, "total_net_lot": 0,
                        }
                    ss = mdata["sell_stats"][code]
                    ss["branches"].append({
                        "code": branch_code,
                        "name": code_to_branch.get(branch_code, {}).get("name", ""),
                        "buy_amt": s.get("buy_amt", 0),
                        "sell_amt": s.get("sell_amt", 0),
                        "net_amt": s.get("net_amt", 0),
                        "buy_lot": s.get("buy_lot", 0),
                        "sell_lot": s.get("sell_lot", 0),
                        "net_lot": s.get("net_lot", 0),
                    })
                    ss["total_buy_amt"] += s.get("buy_amt", 0) or 0
                    ss["total_sell_amt"] += s.get("sell_amt", 0) or 0
                    ss["total_net_amt"] += s.get("net_amt", 0) or 0
                    ss["total_buy_lot"] += s.get("buy_lot", 0) or 0
                    ss["total_sell_lot"] += s.get("sell_lot", 0) or 0
                    ss["total_net_lot"] += s.get("net_lot", 0) or 0
    
    # 最後計算平均當沖比、風格判定
    for master, mdata in master_data.items():
        n = mdata["branches_count_with_data"]
        if n > 0:
            mdata["avg_daytrade_ratio"] = round(mdata["avg_daytrade_ratio_sum"] / n, 3)
        else:
            mdata["avg_daytrade_ratio"] = 0.0
        del mdata["avg_daytrade_ratio_sum"]
        
        # 風格判定
        total_style_stocks = mdata["daytrade_stocks"] + mdata["overnight_stocks"] + mdata["partial_stocks"]
        if total_style_stocks >= 3:
            dt_pct = mdata["daytrade_stocks"] / total_style_stocks
            ov_pct = mdata["overnight_stocks"] / total_style_stocks
            if dt_pct >= 0.5:
                mdata["today_style"] = "daytrader"
            elif ov_pct >= 0.5:
                mdata["today_style"] = "swing"
            else:
                mdata["today_style"] = "mixed"
        else:
            mdata["today_style"] = "unknown"
        
        mdata["total_net_amt"] = mdata["total_buy_amt"] - mdata["total_sell_amt"]
        mdata["total_cumulative_pnl"] = round(mdata["total_cumulative_pnl"], 2)
        mdata["total_daily_pnl"] = round(mdata["total_daily_pnl"], 2)
        mdata["total_weekly_pnl"] = round(mdata["total_weekly_pnl"], 2)
        mdata["total_monthly_pnl"] = round(mdata["total_monthly_pnl"], 2)
        mdata["total_overnight_cost_wan"] = round(mdata["total_overnight_cost_wan"], 2)
        
        # set 轉 list 才能 JSON 序列化
        mdata["tags_personal"] = sorted(mdata["tags_personal"])
        mdata["tags_market"] = sorted(mdata["tags_market"])
        
        # 共識個股（2 個以上分點買同一檔）
        mdata["consensus_stocks"] = [
            s for s in mdata["stock_stats"].values() if len(s["branches"]) >= 2
        ]
        mdata["consensus_stocks"].sort(key=lambda x: -x["total_net_amt"])
        
        # 轉換 stock_stats 為 list 以便序列化
        mdata["top_stocks"] = sorted(
            mdata["stock_stats"].values(),
            key=lambda x: -x["total_net_amt"]
        )[:30]
        del mdata["stock_stats"]  # 省空間
        
        # v3.13 新增：共識賣超個股 + top_sells
        mdata["consensus_sells"] = [
            s for s in mdata["sell_stats"].values() if len(s["branches"]) >= 2
        ]
        mdata["consensus_sells"].sort(key=lambda x: x["total_net_amt"])  # 淨賣越大（負值）越前面
        
        mdata["top_sells"] = sorted(
            mdata["sell_stats"].values(),
            key=lambda x: x["total_net_amt"]  # 淨買由小到大（最賣超的在前）
        )[:30]
        del mdata["sell_stats"]
    
    return master_data


# ========== 主流程 ==========
