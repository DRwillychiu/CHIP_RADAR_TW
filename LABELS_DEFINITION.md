# Chip Radar TW · master_profile 策略標籤完整定義文件

> **目的**:給每個策略標籤一個**透明、可驗證、可調整**的定義。任何標籤的觸發都能逐步回溯到 raw data。
> **版本**:v3.33.0（**15 標籤 + 2 T+1 verified + Level 1/2/3 分層 + 派系 + 實戰信號 + 時間衰減**）
> **配套 code**:`master_profile.py` 的 `THRESH` dict + `generate_labels()` + `build_label_hierarchy()` + `classify_strategy_l2()`
> **最後修訂**:2026-06-11

---

## 版本變動總覽（v3.30.13 → v3.32.4）

| 版本 | 變動 |
|---|---|
| v3.31.10 | 全面閾值重校（32 天真實資料 + 業界印象反推），7 個閾值大幅調整 |
| v3.31.13 | `declared_styles` override（迷你哥跨分點賣→daytrade_ratio=0 修補） |
| v3.31.16 | Level 1/2/3 標籤分層體系 + 10 種 Level 2 策略子類 |
| v3.31.17 | 高頻/精選→攻擊型歸類修正 |
| v3.31.18 | 個人大戶 19→29 人（Excel 交叉比對新增 10 master） |
| v3.31.19 | Phase 2 聯動面（Jaccard 同向率 + 派系 union-find） |
| v3.31.22 | T+1 跨日追蹤 + 60 天滾動窗口 |
| v3.31.23 | 波段囤貨不再標（default 行為）+ T+1 verified 標籤 + 派系 MIN_CO_DAYS=5 |
| v3.32.0 | 實戰信號系統（異常偵測 + 派系共識 + 連續加碼） |
| v3.33.0 | **時間衰減**（B3）：所有 ratio metrics 乘指數衰減權重 half_life=20，標籤反映近期行為 |

---

## 0. 為何要這份文件

業務邏輯標籤如果是「黑盒」,使用者無法:
1. 信任（為什麼蔣承翰是「漲停獵手」?）
2. 調整（我覺得 18% 太鬆,想改 25%）
3. 擴展（我想加「結算週加碼」標籤）
4. 驗證（這個標籤對嗎?）

本文件對每個標籤給:**意圖 → 計算公式 → 觸發條件 → 閾值依據 → 互斥規則 → 典型代表**。所有閾值集中在 `THRESH` dict,改一處全 master 重算。

---

## 1. 完整資料流（從 TWSE 到標籤）

```
┌────────────────────────────────────────────────────────────────────┐
│ Layer 1: TWSE 分點頁面                                              │
│   c=B 金額榜 (買金額/賣金額/淨額, 單位仟元)                          │
│   c=E 張數榜 (買張/賣張/淨張, 單位張)                                │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ crawler.fetch_branch_combined + merge_rows
┌────────────────────────────────────────────────────────────────────┐
│ Layer 2: stock dict (每筆 master×branch×day×stock)                  │
│   {code, name, buy_lot, sell_lot, buy_amt, sell_amt,                │
│    is_limit_up, trade_style ∈ {daytrade,partial,overnight},          │
│    daytrade_ratio = min(buy_lot,sell_lot)/max(...)}                  │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ 60 天歷史 daily JSON (解密)
                  ↓ master_profile.extract_master_trades
┌────────────────────────────────────────────────────────────────────┐
│ Layer 3: 該 master 的 trades[] 全部買進紀錄 (60 天滾動窗口)          │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ compute_operation_metrics + compute_timing_metrics
┌────────────────────────────────────────────────────────────────────┐
│ Layer 4: metrics                                                     │
│   操作類型: daytrade_ratio, partial_ratio, overnight_ratio,          │
│             limit_up_hit_ratio, limit_up_locked_ratio_amt,           │
│             concentration_top5_pct, consistency,                      │
│             long_term_amt_ratio                                      │
│   進出場規律: active_days_ratio, max_streak_days                     │
│   族群: top_industry_pct                                             │
│   風險偏好: disposal_amt_ratio                                       │
│   T+1 驗證: actual_flip_ratio (cross_day_tracker)                   │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ generate_labels (規則式閾值) + declared_styles override
┌────────────────────────────────────────────────────────────────────┐
│ Layer 5: 標籤集合 (每 master 0-8 個標籤)                             │
│   build_label_hierarchy → Level 1 / 2 / 3 分層                     │
│   master_alliance → Jaccard 派系 + union-find                       │
│   daily_signals → 異常偵測 + 派系共識 + 連續加碼                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 分析對象

**29 個個人大戶**（排除 8 外資 + 2 官股 + 2 整家公司 + 10 地緣熱點）

排除邏輯（`EXCLUDED_STYLES`）:
- `foreign_ib`: 外資（高盛/摩根/瑞銀/大和/野村/美林/HSBC/港商瑞穗）— 法人單向流動,不適合「操作習慣」分析
- `public`: 官股（兆豐/合庫）— 政策性買賣
- `company_total`: 整家公司加總（凱基證券/富邦證券）— 非個人交易者
- `area_hotspot`: 地緣特色分點（凱基台北/永豐天母等）— 追蹤但不分析

**原始 19 master**:蔣承翰/林滄海/航海王/陳族元/陳律師/迷你哥松山哥/布哥/Tradow/巨人傑/Krenz/大牌/強森/優式/東億/民哥/志誠/林適中/竹科主力/謝明彧

**v3.31.18 新增 10 master**（使用者 Excel 交叉比對）:宋福祥/呂金發/陳光裕/謝孟恭/丁凌全/何莎/江士勳/劉子豪/陳泊澔/嘉義幫

---

## 3. Metrics 計算公式（逐項）

### 3.1 操作類型 metrics

#### 3.1.1 `daytrade_ratio` / `partial_ratio` / `overnight_ratio`

**來源**:每筆 stock 在 crawler `merge_rows` 已標記 `trade_style`:

```python
# crawler.py merge_rows 內
daytrade_ratio_stock = min(buy_lot, sell_lot) / max(buy_lot, sell_lot)

if daytrade_ratio_stock >= 0.7:
    trade_style = 'daytrade'      # 當沖 (買賣同日且數量接近)
elif daytrade_ratio_stock >= 0.3:
    trade_style = 'partial'       # 部分當沖 + 留倉 (近似隔日沖)
else:
    trade_style = 'overnight'     # 主要留倉 (波段建倉)
```

**master 級彙總**:
```
daytrade_ratio  = (該 master trades 中 trade_style='daytrade' 的數量) / 總 trades 數
partial_ratio   = ... 'partial' / 總數
overnight_ratio = ... 'overnight' / 總數
```

三者加總 = 1.0。

#### 3.1.2 `limit_up_hit_ratio`

```
limit_up_hit_ratio = (trades 中 is_limit_up=True 的數量) / 總 trades 數
```

`is_limit_up` 來源:`price_utils.calc_limit_up_price`（v3.28 tick-size 精確版），用 prev_close + tick 反推當日漲停價，實際 close ≥ 漲停價 → True。

#### 3.1.3 `limit_up_locked_ratio_amt`（v3.30.9 新增）

```
per trade: buy_avg = buy_amt(仟元) / buy_lot(張) = 元/股
若 buy_avg ≥ 漲停價 × 0.99 → 視為鎖漲停

limit_up_locked_ratio_amt = Σ(鎖漲停 trades 金額) / 總買進金額
```

漲停價查找優先序:stock.limit_up_price → price_utils.calc_limit_up_price(prev_close) → fallback prev_close × 1.10

#### 3.1.4 `concentration_top5_pct`

```
stock_amt[code] = Σ buy_amt (該 master 該股所有日累積, 單位仟元)
total_amt       = Σ stock_amt.values()
top5_amt        = Σ sorted(stock_amt.values(), desc)[:5]
concentration_top5_pct = top5_amt / total_amt × 100
```

#### 3.1.5 `consistency`

```
consistency = max(daytrade_ratio, partial_ratio, overnight_ratio)
```

1.0 = 全部同一風格，0.33 = 三風格均分。

#### 3.1.6 `long_term_amt_ratio`（v3.30.9 新增）

```
對每個 stock_code，計算在窗口內被加碼的天數 (buy_lot > 0 的不同日期數)
若某 stock 被加碼 ≥ 15 天 → 視為長線部位
long_term_amt_ratio = Σ(長線部位金額) / 總買進金額
```

### 3.2 進出場規律 metrics

#### 3.2.1 `active_days_ratio`

```
active_days = len(set(trade.date for trade in trades))
total_window_days = len(history)    # 載入的 daily JSON 數 (含週末)
active_days_ratio = active_days / total_window_days
```

#### 3.2.2 `max_streak_days`

```
trade_dates = sorted(set(parsed datetime from trade.date))
for consecutive pair: diff_days ≤ 3 → 視為連續 (跨週末容忍)
max_streak_days = 最長連續片段
```

### 3.3 族群 metrics（v3.30.11）

```
用 industry_classifier 1965 檔產業分類 → 每族群買進金額 → 取最大族群
top_industry_pct = 最大族群買進金額 / 總買進金額 × 100
```

### 3.4 風險偏好 metrics（v3.30.13）

```
用 disposal_fetcher 抓 chengwaye 「差1次/差2次/處置中」union set
disposal_amt_ratio = Σ(處置股買進金額) / 總買進金額
```

### 3.5 T+1 跨日追蹤 metrics（v3.31.22）

```
cross_day_tracker.py:
對每個 (master, branch):
  day T 的買入股票集合 vs day T+1 的賣出股票集合
  intersection = 真正隔日沖出場
  actual_flip_ratio = |intersection days| / |total T→T+1 pairs|
  跨分點賣出也計入 flip
  週末容忍 ≤ 4 天
```

### 3.6 時間衰減（v3.33.0, B3）

**問題**:60 天滾動窗口下，40 天前的操作跟昨天的操作對標籤影響力一樣 → 標籤反映「歷史平均」而非「他最近在幹嘛」。master 換策略要 30 天才看得出來。

**解法**:每筆 trade 乘指數衰減權重：

```
weight = 0.5 ** (age_days / half_life)
  age_days = (窗口最新日 - trade 日期).days   ← 錨點全 master 共用, 避免偏差
  half_life = THRESH['decay_half_life'] = 20

  今天     → 1.0
  20 天前  → 0.5
  40 天前  → 0.25
  60 天前  → 0.125
```

**加權範圍**:

| Metric | 加權? | 理由 |
|---|---|---|
| daytrade/partial/overnight ratio | ✅ 加權筆數 | 近期風格主導標籤 |
| limit_up_hit_ratio | ✅ 加權筆數 | 同上 |
| limit_up_locked_ratio_amt/lot | ✅ 加權金額/張數 | 同上 |
| concentration_top5_pct | ✅ 加權金額 | 集中度反映近期持股 |
| top_industry_pct | ✅ 加權金額 | 族群輪動更快被看到 |
| disposal_amt_ratio | ✅ 加權金額 | 風險偏好反映近期 |
| long_term_amt_ratio | ✅ 金額加權 | — |
| long_term_stocks_count（天數判定）| ❌ raw | 「加碼 ≥15 天」是事實判定 |
| trades_count / unique_stocks / total_buy_amt_wan | ❌ raw | 真實數字，加權會說謊 |
| timing metrics（active_days/streaks）| ❌ raw | 節奏 pattern 不適用衰減 |

**透明度**:`operation_metrics` 多兩個欄位 `decay_applied: true` + `decay_half_life: 20`。

**停用方式**:`THRESH['decay_half_life'] = 0`（或 None）→ 全部權重 1.0，回到 v3.32 行為。`compute_operation_metrics` 不傳 `decay_ref_date` 也等同停用（向後相容，舊測試不變）。

---

## 4. 標籤完整定義（15 + 2 = 17 個）

### 4.1 風格類

#### 漲停獵手

| 項 | 內容 |
|---|---|
| **意圖** | 高比例買進當天的漲停股（主動追漲） |
| **觸發** | `limit_up_hit_ratio > 0.18` |
| **閾值依據** | v3.31.10 重校:蔣承翰 21%、Tradow 20%、優式 21% 觸發;民哥 14%、航海王 11% 不觸發。業界公認蔣承翰是主漲停獵手 |
| **互斥** | **獨立**（可與所有標籤共存） |
| **典型** | 蔣承翰、Tradow、優式資本 |

#### 🔒 鎖漲停

| 項 | 內容 |
|---|---|
| **意圖** | 在漲停價附近成交建倉（真實 sniper 行為） |
| **觸發** | `limit_up_locked_ratio_amt > 0.15`（buy_avg ≥ 漲停價 × 0.99） |
| **閾值依據** | v3.31.10:蔣承翰 19% → 觸發；15% 閾值區分「鎖漲停」vs「盤中追漲停」 |
| **互斥** | **獨立**（可與漲停獵手共存:蔣承翰兩者都有,迷你哥可能只有漲停獵手） |

#### 當沖客 / 短打型 / 📈 長線持有（3 互斥）

| 標籤 | 觸發 | 說明 |
|---|---|---|
| **當沖客** | `daytrade_ratio > 0.40` | 主軸當沖 |
| **短打型** | `partial_ratio > 0.40`（且未觸發當沖客） | 近似隔日沖 |
| **📈 長線持有** | `overnight_ratio > 0.40` 且 `long_term_amt_ratio > 0.65` | 真長線（單檔加碼 ≥15 天 + 金額佔比 65%+） |

**波段囤貨**:v3.31.23 移除。19/29 master 都觸發 = 無區別力。波段是 default 行為,只標「特殊」風格。

`elif` 結構保證**最多一個風格類**。三者 ratio 都未過 0.40 → 都不觸發。

#### 當沖客(declared) / 短打型(declared)（v3.31.13）

| 項 | 內容 |
|---|---|
| **意圖** | 修補 TWSE 分點資料結構性限制 — 迷你哥在 A 分點買、B 管道賣 → sell_lot=0 → daytrade_ratio=0 → 被誤判 overnight |
| **觸發** | `branches.py` 的 `MASTER_STYLES` 有 `day_trader`/`next_day_flipper` 但自動標籤未觸發對應風格 |
| **優先度** | 低於自動標籤,只在自動未觸發時啟用 |

### 4.2 T+1 verified 標籤（v3.31.23）

| 標籤 | 觸發 | 說明 |
|---|---|---|
| **隔日沖(verified)** | `actual_flip_ratio ≥ 0.45` | T+1 賣出驗證的真隔日沖。航海王 55.8%、陳族元 48.5% 觸發 |
| **混合進出** | `actual_flip_ratio ∈ [0.35, 0.45)` | 蔣承翰 42.9%、迷你哥 41.3% — 有隔日沖但比例未過半 |

**資料來源**:`cross_day_tracker.py` 比對 T 日買 vs T+1 日賣（含跨分點,週末容忍 ≤4 天）。

### 4.3 集中度類（2 個,互斥）

| 標籤 | 觸發 | 閾值依據 |
|---|---|---|
| **集中投資** | `concentration_top5_pct > 35` | v3.31.10:35% 在 60 天累積下已算明顯集中 |
| **分散布局** | `concentration_top5_pct < 18` | 前 5 大不到 18% = 鋪在 25+ 檔以上 |

### 4.4 一致性類（2 個,互斥）

| 標籤 | 觸發 | 閾值依據 |
|---|---|---|
| **風格純粹** | `consistency > 0.65` | v3.31.10:65% 主導風格 = 可預測操作模式 |
| **多變策略** | `consistency < 0.40` | 主導風格不到四成 = 無明顯主軸 |

### 4.5 進出場活躍度（2 個,互斥）

| 標籤 | 觸發 | 閾值依據 |
|---|---|---|
| **高頻交易** | `active_days_ratio > 0.85` | 幾乎每個交易日都動 |
| **精選出手** | `active_days_ratio < 0.40` | 平均每週只出手 2-3 次 |

### 4.6 節奏類（1 個,獨立）

| 標籤 | 觸發 | 閾值依據 |
|---|---|---|
| **持續進場** | `max_streak_days > 15` | v3.31.10:8→15。60 天下大多有 8+ 連續,15+ 才算明顯節奏性建倉 |

### 4.7 族群類（1 個,獨立,v3.30.11）

| 標籤 | 觸發 | 說明 |
|---|---|---|
| **🎯 族群專家** | `top_industry_pct > 60` | 單一族群佔買進 60%+。族群名在 narrative（不是標籤本身） |
| **典型** | 航海王（航運 80%+） |

### 4.8 風險偏好類（1 個,獨立,v3.30.13）

| 標籤 | 觸發 | 說明 |
|---|---|---|
| **⚠️ 處置股獵手** | `disposal_amt_ratio > 0.30` | 買進金額 30%+ 在處置/注意股 |
| **資料源** | chengwaye.com/disposal-forecast.html（TWSE 無公開 JSON API） |
| **風險揭露** | chengwaye 改 HTML/關站 → break,fallback 跳過此 metric |

---

## 5. Level 1/2/3 標籤分層體系（v3.31.16）

### Level 1: 操作大類（3 分類）

| 大類 | 包含標籤 | 意圖 |
|---|---|---|
| **攻擊型** | 漲停獵手、🔒 鎖漲停、當沖客/declared、短打型/declared、⚠️ 處置股獵手、高頻交易、精選出手 | 主動追求超額報酬 |
| **防守型** | 📈 長線持有、集中投資、風格純粹 | 穩定持倉 + 風格穩定 |
| **觀察型** | 持續進場、分散布局、🎯 族群專家、多變策略 | 風格/族群/節奏特徵 |

### Level 2: 策略子類（10 種，`classify_strategy_l2`）

| 策略子類 | 觸發標籤組合 | 代表人物 |
|---|---|---|
| **漲停鎖定策略** | (漲停獵手 or 🔒鎖漲停) + (短打型 or declared) | 蔣承翰、Tradow |
| **漲停當沖策略** | (漲停獵手 or 🔒鎖漲停) + (當沖客 or declared) | 迷你哥 |
| **漲停追擊策略** | 漲停獵手 or 🔒鎖漲停（無當沖/短打） | 優式資本 |
| **高風險偏好策略** | ⚠️ 處置股獵手 | — |
| **長線集中持股** | 📈 長線持有 + 集中投資 | 林滄海 |
| **長線分散持股** | 📈 長線持有（無集中） | 東億、優式 |
| **波段集中操作** | 集中投資（無長線） | 航海王 |
| **族群深耕策略** | 🎯 族群專家 | 航海王（航運） |
| **彈性多變操作** | 多變策略 | 巨人傑 |
| **一般操作** | 以上均不符合（default） | — |

### Level 3: 個人操作 DNA（`build_label_hierarchy`）

直接帶出關鍵 metrics 數值,供前端精細展示:

```json
{
  "locked_pct": 0.19,
  "limit_up_pct": 0.21,
  "concentration_pct": 42.5,
  "top_industry": "半導體",
  "top_industry_pct": 35.2,
  "disposal_pct": 0.05,
  "consistency": 0.72
}
```

---

## 6. 聯動面 — 派系系統（v3.31.19）

### Jaccard 同向率

```
兩個 master A, B 在窗口內:
  A_stocks[date] = set(A 當日買入的 stock codes)
  B_stocks[date] = set(B 當日買入的 stock codes)
  co_days = {date: A_stocks[date] ∩ B_stocks[date]} 中有交集的天數
  jaccard[date] = |A ∩ B| / |A ∪ B|
  avg_jaccard = mean(jaccard for dates with co_days)
```

**閾值**:
- `avg_jaccard ≥ 0.30` → 判定為同派系
- `MIN_CO_DAYS = 5` → 至少 5 天共同出現才計算（v3.31.23 防新 master 1 天 data = 100% Jaccard 污染）

### 派系發現（union-find）

滿足門檻的 pairs 用 union-find 合併 → 自動發現派系

**已知派系**:
- 派系 1:巨人傑 / 強森 / 民哥
- 派系 2:航海王 / 林滄海 / 陳族元

**實戰意義**:同派系 ≥2 人同天同股 = 「派系共識信號」（見 §7）

---

## 7. 實戰信號系統（v3.32.0）

`daily_signals.py` 產出 3 類信號:

### Q1 異常偵測（per master）
- **量能爆發**:某 master 當日買進金額 > 歷史 mean + 2σ
- **新股涌入**:某 master 當日 ≥3 檔從未買過的新股

### Q2 派系共識（cross master）
- 同派系 ≥2 位 master 同天買同檔股票
- Top 15 cap 避免噪音

### Q3 連續加碼（per master × stock）
- 同 master 同股連續 ≥3 天買進
- Top 15 cap

---

## 8. 閾值總覽（`THRESH` dict，v3.31.10 校準）

```python
THRESH = {
    # 操作風格
    'limit_up_hit_high': 0.18,        # 漲停獵手 (v3.30.8: 0.60 → v3.31.10: 0.18)
    'locked_at_lu_tolerance': 0.99,   # 鎖漲停容忍 (1% tick 誤差)
    'locked_at_lu_ratio_amt': 0.15,   # 🔒鎖漲停 (v3.30.9: 0.40 → v3.31.10: 0.15)
    'style_dominant': 0.40,           # 風格三互斥 (v3.30.8: 0.50 → 0.40)
    'long_term_days_threshold': 15,   # 長線天數 (v3.30.9: 5 → v3.31.10: 15)
    'long_term_amt_ratio': 0.65,      # 長線金額比 (v3.30.9: 0.50 → 0.65)
    # 集中度
    'concentration_high': 35.0,       # 集中投資 (v3.30.8: 50 → 35)
    'concentration_low': 18.0,        # 分散布局 (v3.30.8: 20 → 18)
    # 一致性
    'consistency_high': 0.65,         # 風格純粹 (v3.30.8: 0.80 → 0.65)
    'consistency_low': 0.40,          # 多變策略 (v3.30.8: 0.50 → 0.40)
    # 進出場
    'active_ratio_high': 0.85,        # 高頻交易 (不變)
    'active_ratio_low': 0.40,         # 精選出手 (不變)
    'streak_long': 15,                # 持續進場 (v3.30.8: 8 → 15)
    # 族群
    'top_industry_pct_high': 60.0,    # 🎯族群專家 (不變)
    # 風險偏好
    'disposal_amt_ratio_high': 0.30,  # ⚠️處置股獵手 (不變)
    # v3.33.0: 時間衰減 (B3)
    'decay_half_life': 20,            # 指數衰減半衰期 (日曆天), 0/None 停用
}
```

**v3.31.10 校準依據**:
- 32 天真實資料 + 業界印象反推
- 校準前:19 master 全部「📈長線持有/高頻交易/持續進場」一面倒
- 校準後:蔣承翰=漲停獵手+鎖漲停、迷你哥=當沖客、Krenz=波段、航海王=族群專家

---

## 9. 標籤共存矩陣

```
                  漲停獵手 🔒鎖漲 當沖客 短打型 長線  集中  分散  純粹  多變  高頻  精選  持續  族群  處置  隔日沖V 混合
漲停獵手          —       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
🔒鎖漲停          ✓       —     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
當沖客            ✓       ✓     —     ✗     ✗    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
短打型            ✓       ✓     ✗     —     ✗    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
📈長線持有         ✓       ✓     ✗     ✗     —    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
集中投資          ✓       ✓     ✓     ✓     ✓    —    ✗    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
分散布局          ✓       ✓     ✓     ✓     ✓    ✗    —    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓      ✓
風格純粹          ✓       ✓     ✓     ✓     ✓    ✓    ✓    —    ✗    ✓    ✓    ✓    ✓    ✓    ✓      ✓
多變策略          ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✗    —    ✓    ✓    ✓    ✓    ✓    ✓      ✓
高頻交易          ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    —    ✗    ✓    ✓    ✓    ✓      ✓
精選出手          ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✗    —    ✓    ✓    ✓    ✓      ✓
持續進場          ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    —    ✓    ✓    ✓      ✓
🎯族群專家        ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    —    ✓    ✓      ✓
⚠️處置股獵手      ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    —    ✓      ✓
隔日沖(verified)  ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    —      ✗
混合進出          ✓       ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✗      —
```

**互斥規則**:同 metric 不同邊互斥（集中↔分散、純粹↔多變、高頻↔精選、隔日沖V↔混合,當沖↔短打↔長線三互斥）。

**最大組合**:1 風格 + 1 T+1 + 漲停獵手 + 🔒鎖漲停 + 1 集中度 + 1 一致性 + 1 活躍度 + 持續進場 + 🎯族群 + ⚠️處置 = **最多 10 個**（實務常見 3-5 個）。

---

## 10. `declared_styles` override 機制（v3.31.13）

### 問題

TWSE 分點資料有結構性盲點:
- 迷你哥在 A 分點買、B 管道賣 → A 分點的 sell_lot=0 → daytrade_ratio=0 → 被判 overnight
- 巨人傑有 next_day_flipper + day_trader 雙 style,但某些日只看到一面

### 解法

`branches.py` 的 `MASTER_STYLES` 存業界知識（declared style）。`generate_labels` 接收 `declared_styles` 參數:

```python
# 自動標籤未觸發 day_trader → 加 declared 版本
if 'day_trader' in declared and '當沖客' not in labels:
    labels.append('當沖客(declared)')
if 'next_day_flipper' in declared and '短打型' not in labels:
    labels.append('短打型(declared)')
```

**原則**:declared 是「業界知識覆蓋」,不取代自動標籤,只在自動未觸發時補充。

---

## 11. Per-branch 細分（v3.30.12）

同 master 有 >1 分點時,每個分點獨立計算 metrics + labels → `per_branch_profiles` 子結構。

**價值案例**:
- 巨人傑 9B2n = 純隔日沖,9B2z = 純當沖（master 整體落「多變策略」看不出這差異）
- 林滄海 9216 凱基-信義 = 漲停獵手（長線 master 但某分點專搶漲停）
- 航海王 779Z = sniper 風格

---

## 12. 邊界 case 處理

| 情境 | 處理 |
|---|---|
| trades 為空 | `no_data: True`,narrative 寫「窗口內無交易」 |
| trades < 5 | metrics 都能算但失準,前端顯示「⏳ 資料不足 N 天,標籤待確認」（v3.31.23 F2） |
| 窗口 < 14 天 | 標註「近 X/Y 交易日」 |
| trade_style 全 unknown | 三 ratio 都 0 → 多變策略誤觸發;舊版 crawler 歷史 |
| 新增 master 初期 | 10 個新 master 只有 ~4 天 data → 標籤高度不穩定,待自然累積 |

---

## 13. 可調性 — 怎麼改閾值

所有閾值在 `master_profile.py` 的 `THRESH` dict。

**調整 SOP**:
1. 改 `THRESH` 對應 key
2. `python master_profile.py` 重算
3. 觀察 summary 是否符合業界直覺
4. 不符 → 微調 → 再跑

---

## 14. 擴展指南 — 怎麼加新標籤

1. 定義 metric（`compute_*_metrics` 內加）
2. 閾值進 `THRESH`
3. `generate_labels` 加判斷
4. `LABEL_L1_MAP` 加歸類
5. `classify_strategy_l2` 加對應
6. 本文件加一節
7. 加測試
8. 跑 + 驗證

---

## 15. Quick Reference

```
標籤                       觸發                                          metric
─────────────────────────────────────────────────────────────────────────────────
漲停獵手                   limit_up_hit_ratio > 0.18                     op
🔒 鎖漲停                  locked_ratio_amt > 0.15 (avg ≥ 漲停×0.99)    op
當沖客                     daytrade_ratio > 0.40                         op
短打型                     partial_ratio > 0.40 (非當沖客)              op
📈 長線持有                overnight > 0.40 + long_term_amt > 0.65      op
當沖客(declared)           MASTER_STYLES day_trader + 自動未觸發         declared
短打型(declared)           MASTER_STYLES next_day_flipper + 自動未觸發   declared
隔日沖(verified)           actual_flip_ratio ≥ 0.45                     cross_day
混合進出                   actual_flip_ratio ∈ [0.35, 0.45)             cross_day
集中投資                   concentration_top5_pct > 35                   op
分散布局                   concentration_top5_pct < 18                   op
風格純粹                   consistency > 0.65                            op
多變策略                   consistency < 0.40                            op
高頻交易                   active_days_ratio > 0.85                      timing
精選出手                   active_days_ratio < 0.40                      timing
持續進場                   max_streak_days > 15                          timing
🎯 族群專家                top_industry_pct > 60                         op
⚠️ 處置股獵手              disposal_amt_ratio > 0.30                     op
```

---

*本文件與 `master_profile.py` 的 `THRESH` + `generate_labels()` + `build_label_hierarchy()` + `classify_strategy_l2()` 嚴格同步。任何改動兩處都要對齊。*
