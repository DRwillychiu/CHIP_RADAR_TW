# Chip Radar TW · master_profile 策略標籤完整定義文件

> **目的**:給每個策略標籤一個**透明、可驗證、可調整**的定義。任何標籤的觸發都能逐步回溯到 raw data。
> **版本**:v3.30.13 Phase 1(**15 標籤 + per-branch 細分機制**)
> **配套 code**:`master_profile.py` 的 `THRESH` dict + `generate_labels()` 函式
> **最後修訂**:2026-05-30

> **v3.30.13 變動摘要**:
> - 新增 ⚠️ **處置股獵手**(獨立,風險偏好維度):用 `disposal_fetcher.py` 從 chengwaye 抓「差1次/差2次/處置中」85 檔 union set,觸發 `disposal_amt_ratio > 0.30`(該 master 買進金額 30% 以上在處置股)。narrative 顯示「⚠️ 處置股部位 X% (N 檔)」。**資料源限制誠實揭露**:TWSE 處置股無公開 JSON API(試 9 端點全 404),繞 chengwaye(robots.txt 允許 + 全免費 + 使用者自用),但 chengwaye 改 HTML/關站我們會 break,fallback = 跳過此 metric。

> **v3.30.12 變動摘要**:
> - 新增 **per-branch 細分**(不是新標籤,是新機制):master 有 >1 分點時,每個分點獨立計算 metrics + labels,放在 `per_branch_profiles` 子結構。解業界印象「巨人傑雙風格 master 在 9B2n 純隔日沖、9B2z 純當沖」現有 master 整體層級看不出的盲點 #5。`extract_master_trades` 加 `branch_code` filter,`build_master_profile` 加 `branch_filter` 參數(branch_filter 模式不再遞迴,避免無限)。main summary 表只印「分點 labels 跟 master 整體不同」的細分(差才有資訊量)。

> **v3.30.11 變動摘要**:
> - 新增 🎯 **族群專家**(獨立,可與所有標籤共存):用 `industry_classifier` 1965 檔產業分類,單一族群買進金額占比 > 60% 觸發。族群名顯示在 narrative「主攻 X 族群」。解業界印象「航海王=航運專家」現有標籤無法表達的盲點 #3。

> **v3.30.9 變動摘要**:
> - 新增 🔒 **鎖漲停**(獨立,可與漲停獵手共存):用 `buy_avg ≥ 漲停價 × 99%` 判定真實鎖漲停成交
> - 新增 📈 **長線持有**:用「單檔被加碼 ≥ 5 天」近似真實長線部位
> - 原「波段囤貨」改名為「**波段囤貨(中短期)**」:overnight > 0.5 **且** long_term_amt < 0.5
> - 解 v3.30.8 §9 兩個已知限制:鎖漲停 vs 漲停獵手混淆、longterm 無對應標籤

---

## 0. 為何要這份文件

業務邏輯標籤如果是「黑盒」,使用者無法:
1. 信任(為什麼蔣承翰是「漲停獵手」?)
2. 調整(我覺得 60% 太鬆,想改 70%)
3. 擴展(我想加「結算週加碼」標籤)
4. 驗證(這個標籤對嗎?)

本文件對每個標籤給:**意圖 → 計算公式 → 觸發條件 → 閾值依據 → 互斥規則 → 典型代表**。所有閾值集中在 `THRESH` dict,改一處全 master 重算。

---

## 1. 完整資料流(從 TWSE 到標籤)

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
                  ↓ 28 天歷史 daily JSON (解密) → master_profile.extract_master_trades
┌────────────────────────────────────────────────────────────────────┐
│ Layer 3: 該 master 的 trades[] 全部買進紀錄                          │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ compute_operation_metrics + compute_timing_metrics
┌────────────────────────────────────────────────────────────────────┐
│ Layer 4: 8 個 metrics                                                │
│   操作類型(6): daytrade_ratio, partial_ratio, overnight_ratio,       │
│                limit_up_hit_ratio, concentration_top5_pct, consistency │
│   進出場規律(2): active_days_ratio, max_streak_days                  │
└─────────────────┬──────────────────────────────────────────────────┘
                  ↓ generate_labels (規則式閾值)
┌────────────────────────────────────────────────────────────────────┐
│ Layer 5: 標籤集合(每 master 0-7 個標籤)                              │
│   風格(4 互斥): 漲停獵手/當沖客/短打型/波段囤貨                       │
│   集中度(2 互斥): 集中投資 / 分散布局                                  │
│   一致性(2 互斥): 風格純粹 / 多變策略                                  │
│   活躍度(2 互斥): 高頻交易 / 精選出手                                  │
│   節奏(獨立): 連續部署                                                │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Metrics 計算公式(逐項)

### 2.1 操作類型 metrics(6 個)

#### 2.1.1 `daytrade_ratio` / `partial_ratio` / `overnight_ratio`

**來源**:每筆 stock 在 crawler `merge_rows` L606-622 已標記 `trade_style`:

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

三者加總 = 1.0(若無 unknown)。

**注意**:`partial` 不等於嚴格的「次日結清隔日沖」。嚴格隔日沖驗證需要 T+1 賣出紀錄(Phase 2 績效面)。Phase 1 用 `partial` 作為「近似隔日沖」的 proxy(主因:當天買賣有 30-70% 同步 + 部分留倉,實務上多對應隔日沖部位)。

#### 2.1.2 `limit_up_hit_ratio`

```
limit_up_hit_ratio = (trades 中 is_limit_up=True 的數量) / 總 trades 數
```

**`is_limit_up` 來源**:`price_utils.calc_limit_up_price`(v3.28,tick-size 精確版),用 prev_close + tick 反推當日漲停價,實際 close ≥ 漲停價 → True。

#### 2.1.3 `concentration_top5_pct`

```
stock_amt[code] = Σ buy_amt(該 master 該股的所有日累積, 單位仟元)
total_amt       = Σ stock_amt.values()
top5_amt        = Σ sorted(stock_amt.values(), desc)[:5]
concentration_top5_pct = top5_amt / total_amt × 100
```

代表「前 5 大個股佔該 master 總買進金額的 %」。

**參考基準**:台股約 2000 檔,完全隨機分散應約 0.25%/檔,前 5 大 1.25%。實務中即使「分散派」前 5 大也常在 15-25%。50%+ 是極端集中。

#### 2.1.4 `consistency`

```
consistency = max(daytrade_ratio, partial_ratio, overnight_ratio)
```

代表「主導風格佔比」。1.0 = 全部同一風格,0.33 = 三風格均分。

---

### 2.2 進出場規律 metrics(2 個)

#### 2.2.1 `active_days_ratio`

```
active_days = len(set(trade.date for trade in trades))   # 該 master 有出手的不重複日數
total_window_days = len(history)                         # 載入的 daily JSON 數
active_days_ratio = active_days / total_window_days
```

**注意**:`total_window_days` 包含週末(daily JSON 在週末沒新增,但載入時可能有舊檔)。若窗口 28 天含 8 個週末,實際交易日約 20 天。`active_days_ratio > 0.85` 在 28 天窗口下約 = 24 天出手(≈ 全部交易日)。

#### 2.2.2 `max_streak_days`

```
trade_dates = sorted(set(parsed datetime from trade.date))
streaks = []
current = 1
for i in range(1, len(trade_dates)):
    diff_days = (trade_dates[i] - trade_dates[i-1]).days
    if diff_days <= 3:    # 跨週末 (週五→週一 = 3 天) 視為連續
        current += 1
    else:
        streaks.append(current)
        current = 1
streaks.append(current)
max_streak_days = max(streaks)
```

代表「最長連續部署天數」。連續 8+ 天 = 約 1.5 週節奏性建倉。

---

## 3. 11 個標籤的完整定義

> **格式**:每個標籤給:意圖 / 公式 / 觸發 / 閾值依據 / 互斥規則 / 典型代表 / 邊界 case

### 3.1 風格類(4 個,3 個互斥 + 1 個獨立)

#### ⭐ 漲停獵手

| 項 | 內容 |
|---|---|
| **意圖** | 高比例買進當天的漲停股(主動追漲) |
| **公式** | `limit_up_hit_ratio = 漲停 trades 數 / 總 trades 數` |
| **觸發** | `limit_up_hit_ratio > 0.60`(`THRESH['limit_up_hit_high']`) |
| **閾值依據** | 台股每日約 5-20 檔漲停,**被動撞到漲停的機率 < 5%**。60% = 明顯刻意追漲停。70% 以上幾乎肯定 sniper 風格 |
| **互斥規則** | **獨立**(可與風格類及 🔒鎖漲停共存) |
| **典型代表** | 蔣承翰、巨人傑、迷你哥(sniper 路線) |
| **邊界 case** | 若 trades < 5 → 比例失準(本文件 §5 處理) |
| **⚠️ 限制** | 只判定「買的當天有漲停」,**不證明在漲停價成交**。盤中買進後拉漲停的情境也算。**v3.30.9 新增 🔒鎖漲停 補強這層** |

#### 🔒 鎖漲停 (v3.30.9 新增)

| 項 | 內容 |
|---|---|
| **意圖** | 在漲停價附近成交建倉(真實 sniper 行為,vs 漲停獵手只看當天漲停) |
| **公式** | per trade: `buy_avg = buy_amt(仟元) / buy_lot(張) = 元/股`。當 `buy_avg ≥ 漲停價 × 0.99` 視為鎖漲停。<br>master 級:`limit_up_locked_ratio_amt = Σ(鎖漲停 trades 金額) / 總買進金額` |
| **觸發** | `limit_up_locked_ratio_amt > 0.40`(`THRESH['locked_at_lu_ratio_amt']`) |
| **判定容忍** | 99%(`THRESH['locked_at_lu_tolerance']`)— 留 1% 容忍給高價股 tick 寬度 |
| **閾值依據** | 業界對「鎖漲停」沒有 tick × 分點公開資料,**均價 vs 漲停價對比**是唯一公認近似(chengwaye 也是這樣展示給人眼比較)。40% 表示「該 master 的買進金額中 40% 以上落在漲停價附近」 |
| **互斥規則** | **獨立**(可與漲停獵手 + 風格類共存) |
| **共存組合範例** | **蔣承翰** = 漲停獵手 + 🔒鎖漲停 + 短打型(真 sniper 鎖漲停建倉);<br>**迷你哥** = 漲停獵手 + 當沖客 + **無**🔒鎖漲停(盤中買進漲停股當沖,沒鎖) |
| **漲停價來源** | `stock.limit_up_price`(若有)→ `price_utils.calc_limit_up_price(prev_close)`(v3.28 tick 精確)→ fallback `prev_close × 1.10`(粗略) |
| **⚠️ 限制** | 仍是「均價推論」非「tick 級成交價」。同檔多次買進均價會被混合;高價股 tick 寬可能誤判 |

#### 🔥 當沖客 / 📊 短打型 / 🌙 波段囤貨(3 互斥)

| 標籤 | 公式 | 觸發 | 閾值依據 |
|---|---|---|---|
| **當沖客** | daytrade_ratio | `> 0.50` | 過半 trades 是當沖(min/max lot ≥ 0.7) → 主軸 |
| **短打型** | partial_ratio | `> 0.50`(且未觸發當沖客) | partial 含部分當沖+留倉,實務多對應隔日沖部位 |
| **波段囤貨(中短期)** | overnight_ratio | `> 0.50` **且** long_term_amt_ratio < 0.50 | 留倉為主 **但** 無長線連續加碼 → 中短期波段(< 5 天加碼) |
| **📈 長線持有** (v3.30.9) | overnight_ratio + long_term_amt_ratio | overnight > 0.50 **且** long_term_amt_ratio > 0.50 | 留倉為主 + 真實連續加碼,跟「波段囤貨」拆開 |

**互斥邏輯**(`generate_labels`, v3.30.9 更新):
```python
if daytrade_ratio > 0.5:
    labels.append('當沖客')
elif partial_ratio > 0.5:
    labels.append('短打型')
elif overnight_ratio > 0.5:
    # v3.30.9: 拆波段 vs 長線 (兩者互斥)
    if long_term_amt_ratio > 0.5:
        labels.append('📈 長線持有')
    else:
        labels.append('波段囤貨(中短期)')
```

`elif` 結構 → **最多一個風格類**。三者 ratio 都未過 50% → 都不觸發(會被「多變策略」抓)。
**v3.30.9 新增**:overnight 分支內再分波段 vs 長線(兩者互斥)。

**典型代表**:
- 當沖客:迷你哥/松山哥、Krenz
- 短打型:Tradow、蔣承翰(嚴格隔日沖被歸這類)
- 波段囤貨(中短期):民哥、陳族元、強森(swing 但無長線連續加碼)
- 📈長線持有(v3.30.9):**林滄海**(declared longterm)、**優式資本**、**東億資本**(declared longterm)— 終於有對應標籤了 |

---

### 3.2 集中度類(2 個,互斥)

| 標籤 | 公式 | 觸發 | 閾值依據 |
|---|---|---|---|
| **集中投資** | concentration_top5_pct | `> 50` | 前 5 大佔總買進 50%+ = 高度押注少數個股 |
| **分散布局** | concentration_top5_pct | `< 20` | 前 5 大不到 20% = 鋪在 25+ 檔以上,撒網策略 |

**中間區間**(20-50%)兩個都不觸發 = 中等集中,不貼標。

**閾值依據**:
- 50% 為什麼:25 檔均分時前 5 大為 20%。50% 代表前 5 大份額是均分的 2.5 倍 → 明顯集中
- 20% 為什麼:剛好對應「均分 25 檔」的水位,低於此 = 鋪比 25 檔更廣

**典型代表**:
- 集中投資:蔣承翰(只追漲停股,標的數量少)、航海王(押航運)
- 分散布局:大牌分析師(swing 撒網)

---

### 3.3 一致性類(2 個,互斥)

| 標籤 | 公式 | 觸發 | 閾值依據 |
|---|---|---|---|
| **風格純粹** | consistency = max(三 ratio) | `> 0.80` | 主導風格佔 80%+ = 一招走天下 |
| **多變策略** | consistency | `< 0.50` | 主導風格不到 50% = 三風格混用 |

**中間**(50-80%)= 主軸明確但有混搭。

**閾值依據**:
- 80% 為什麼:8 成風格一致 = 「他就是這種人」可預測
- 50% 為什麼:主導風格不到一半 = 沒有明顯主軸

**典型代表**:
- 風格純粹:蔣承翰(partial 近 100%)、民哥(overnight 近 100%)
- 多變策略:巨人傑(declared style 雙 next_day_flipper + day_trader,實際操作也常混)

---

### 3.4 進出場活躍度(2 個,互斥)

| 標籤 | 公式 | 觸發 | 閾值依據 |
|---|---|---|---|
| **高頻交易** | active_days_ratio | `> 0.85` | 28 天窗口下 = 24+ 天有出手 ≈ 每個交易日都動 |
| **精選出手** | active_days_ratio | `< 0.40` | 28 天 < 11 天出手 = 大多時間觀望,精挑時機 |

**閾值依據**:
- 0.85 為什麼:28 天窗口含 8 個週末,交易日 20 天。85% = 17 天+,實務上幾乎每交易日都動
- 0.40 為什麼:28 天 < 11 天 = 平均每週只出手 2-3 次,屬精選

**注意 window 偏差**:`total_window_days` 含週末日歷天數,所以 0.85 不等於「85% 交易日」。實務上活躍 master 通常 0.65-0.75。**0.85 是嚴格高頻門檻**。

**典型代表**:
- 高頻交易:當沖/隔日沖類(每天都搶漲停)
- 精選出手:大額波段 master,等大機會才動

---

### 3.5 族群類(1 個,獨立,v3.30.11 新增)

#### 🎯 族群專家

| 項 | 內容 |
|---|---|
| **意圖** | 該 master 的買進金額高度集中在單一產業族群(航運/PCB/半導體 等) |
| **公式** | 對該 master 所有 trades:用 `industry_classifier.py` 反查 `code → 產業`,加總每族群買進金額,取最大族群占比 |
| 額外 metrics | `top_industry`(族群名)、`top_industry_pct`(最大族群%)、`industry_count`(觸及族群數)、`top3_industries`(前 3 族群分布,在 narrative 顯示) |
| **觸發** | `top_industry_pct > 60`(`THRESH['top_industry_pct_high']`) |
| **閾值依據** | 60% 表示「該 master 過半買進都在單一族群」= 明顯專家定位。台股 33 個產業類別均分應約 3%/族群,60% 是均分 20 倍。航海王、半導體專家、PCB 玩家 都應觸發 |
| **互斥規則** | **獨立**,可與所有標籤共存 |
| **族群名來源** | TWSE 官方產業分類(`industry_classifier.py` v3.15.0,33 類 + DR);族群名顯示在 narrative「主攻 X 族群 (Y%)」,標籤本身固定 `🎯 族群專家` |
| **典型代表** | **張濬安(航海王)**:航運業 > 80%;**Tradow**:可能集中半導體/電子業;其他 swing master 多在 1-2 主攻族群 |
| **邊界 case** | (1) industry_classifier 未涵蓋的 code(新上市股、特殊類別)歸「未分類」,可能誤觸發。(2) 若 master 集中 5 檔同族群但只有少量交易 → top_industry_pct 高但樣本少,信心降 |
| **資料源** | `industry_classifier.get_industry_map(data_dir)['stock_industry']` 反查表,7 天快取(產業分類年度調整,變動頻率低) |
| **⚠️ 限制** | 「未分類」 code 若占比高會觸發但無意義,真實使用要確認 `industry_classification_available: true` |

### 3.6 節奏類(1 個,獨立)

#### 🔄 連續部署

| 項 | 內容 |
|---|---|
| **公式** | `max_streak_days`(見 §2.2.2) |
| **觸發** | `max_streak_days > 8` |
| **閾值依據** | 連續 8+ 個交易日出手 = 約 1.5 週節奏性建倉。一般操作通常 streak 在 3-5。**8 是「明顯有節奏」的門檻** |
| **互斥規則** | **獨立**,可與任何標籤共存 |
| **典型代表** | 波段建倉型(看好一波,連續加碼);連續搶漲停類也常觸發 |

---

## 4. 標籤共存矩陣

```
                  漲停獵手  當沖客 短打型 波段  集中  分散  純粹  多變  高頻  精選 連續
漲停獵手          —        ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    ✓
當沖客            ✓        —     ✗     ✗     ✓    ✓    ✓    ✓    ✓    ✓    ✓
短打型            ✓        ✗     —     ✗     ✓    ✓    ✓    ✓    ✓    ✓    ✓
波段囤貨          ✓        ✗     ✗     —     ✓    ✓    ✓    ✓    ✓    ✓    ✓
集中投資          ✓        ✓     ✓     ✓     —    ✗    ✓    ✓    ✓    ✓    ✓
分散布局          ✓        ✓     ✓     ✓     ✗    —    ✓    ✓    ✓    ✓    ✓
風格純粹          ✓        ✓     ✓     ✓     ✓    ✓    —    ✗    ✓    ✓    ✓
多變策略          ✓        ✓     ✓     ✓     ✓    ✓    ✗    —    ✓    ✓    ✓
高頻交易          ✓        ✓     ✓     ✓     ✓    ✓    ✓    ✓    —    ✗    ✓
精選出手          ✓        ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✗    —    ✓
連續部署          ✓        ✓     ✓     ✓     ✓    ✓    ✓    ✓    ✓    ✓    —
```

**規律**:同一 metric 的不同邊互斥(集中↔分散、純粹↔多變、高頻↔精選),不同 metric 的標籤都可共存。

**最大可能組合**:1 風格 + 1 集中度 + 1 一致性 + 1 活躍度 + 連續部署 + 漲停獵手 = **最多 6 個標籤**(實務上常見 3-4 個)。

---

## 5. 邊界 case 處理

| 情境 | 處理 |
|---|---|
| **trades 為空** | profile 設 `no_data: True`,narrative 寫「窗口內無交易」,不算標籤 |
| **trades < 5** | metrics 都能算但失準(ratio 變極端)。**建議**:`compute_operation_metrics` 加 `if total < 5: return {...flag: 'insufficient_sample'}`(Phase 2 補強) |
| **窗口 < 14 天** | timing metrics(streaks、weekday)失準。`build_master_profile` 不限制,但 narrative 應加註(目前已標 `近 X/Y 交易日`) |
| **trade_style 全 'unknown'** | 三 ratio 都 0,consistency=0 → 多變策略誤觸發。**原因**:舊版 crawler(< v3.26) trade_style 未注入。**對策**:Phase 2 加 `if all_unknown: skip` |
| **單股壟斷**(unique_stocks=1) | concentration_top5_pct = 100,集中投資觸發。合理(就是只買一檔) |
| **全部漲停** | limit_up_hit_ratio = 1.0,漲停獵手觸發 |
| **均分三風格**(各 33%) | consistency = 0.33 < 0.5 → 多變策略;三 ratio 都 ≤ 0.5 → 風格類都不觸發。合理 |

---

## 6. 可調性 — 怎麼改閾值

所有閾值集中在 `master_profile.py` 的 `THRESH` global dict:

```python
THRESH = {
    'limit_up_hit_high': 0.6,         # 漲停獵手
    'style_dominant': 0.5,            # 風格類三互斥
    'concentration_high': 50.0,       # 集中投資
    'concentration_low': 20.0,        # 分散布局
    'consistency_high': 0.8,          # 風格純粹
    'consistency_low': 0.5,           # 多變策略
    'active_ratio_high': 0.85,        # 高頻交易
    'active_ratio_low': 0.4,          # 精選出手
    'streak_long': 8,                 # 連續部署
}
```

**調整 SOP**:
1. 改 `THRESH` 對應 key
2. 重跑 `python master_profile.py`(會覆寫 `data/master_profiles.json`)
3. 觀察 summary 表是否符合你直覺
4. 若不符 → 微調 → 再跑

**未來建議**:把 THRESH 移到 `config/labels_thresholds.yaml`(v3.31+ backlog 提過的「規則外配化」)。改 yaml 不需動 code。

---

## 7. 驗證 SOP — 怎麼確認標籤對不對

跑出 `master_profiles.json` 後,對每個 master 做 4 步驗證:

### Step 1:對你的直覺
你心中知道蔣承翰是「漲停獵手 + 短打型」,看看自動產出的 labels 是不是。

### Step 2:對 `declared_styles`
`branches.py` 的 `MASTER_STYLES` 是你手動標的(declared)。自動產出的 labels 應該大致一致:
- declared `next_day_flipper` → 應觸發「短打型」(可能 + 漲停獵手)
- declared `day_trader` → 應觸發「當沖客」
- declared `swing` → 應觸發「波段囤貨」

不一致 = 真實操作 ≠ 你印象。要嘛 declared 過時要更新,要嘛閾值太鬆/嚴。

### Step 3:看 metric 數字本身
忽略 label,看 `operation_metrics` 和 `timing_metrics`:
- `limit_up_hit_ratio: 0.78` → 觀感:**這數字本身合理嗎**?
- `concentration_top5_pct: 92` → 看 master 是不是真的押少數股
- `consistency: 0.55` → 主導風格五成多,合理嗎

### Step 4:抽樣 raw trades
若 metric 看起來怪,從 latest.json 抽該 master 最近幾天的 trades 人眼看:
```bash
python -c "from master_profile import load_history, extract_master_trades; \
  h = load_history('data', 7, '<密碼>'); \
  for t in extract_master_trades(h, '蔣承翰'): print(t)"
```

---

## 8. 擴展指南 — 怎麼加新標籤

加一個「結算週加碼」標籤(範例):

### Step 1:定義 metric

在 `compute_timing_metrics` 加:
```python
# 結算週 = 每月第三個週三所在的週
settlement_week_trades_pct = (結算週 trades 數) / 總 trades 數
```

### Step 2:閾值進 `THRESH`
```python
THRESH['settlement_week_high'] = 0.35   # 結算週 trades > 35% 觸發
```

### Step 3:`generate_labels` 加判斷
```python
if timing.get('settlement_week_trades_pct', 0) > THRESH['settlement_week_high']:
    labels.append('結算週加碼')
```

### Step 4:本文件加一節描述新標籤

### Step 5:加測試(test_v3308 加 case)

### Step 6:跑 + 驗證

---

## 9. 已知限制 + Phase 2 預告

| 限制 | 影響 | Phase 2 對策 |
|---|---|---|
| 嚴格隔日沖未驗證 | partial 是 proxy,可能含「部分當沖+留倉」 | 用 stock_history.json 看 T+1 賣出紀錄 |
| 無績效 | 不知道這 master「準不準」 | 次日報酬 + 隔日沖勝率 + 漲停 3 日後表現 |
| 無聯動 | 不知道誰跟誰同陣營 | master 對 master 同向率矩陣 + 派系發現 |
| 窗口短(~28 天) | 季節性看不到 | v3.31+ 擴 60 天 / 整年 archive |
| 閾值寫死在 code | 改要動 code | 移 `config/labels_thresholds.yaml` |
| trade_style proxy 失準 | 沒考慮 T+N 後是否賣出 | 整合 FIFO 部位 → 真實持倉天數 |

---

## 10. Quick Reference

```
                    觸發條件                                                 metric
漲停獵手            limit_up_hit_ratio > 0.6                                 op.limit_up_hit_ratio
🔒 鎖漲停 (v3.30.9) limit_up_locked_ratio_amt > 0.40                         op.limit_up_locked_ratio_amt
                    (buy_avg ≥ 漲停價 × 0.99 視為鎖漲停)
當沖客              daytrade_ratio > 0.5                                     op.daytrade_ratio
短打型              partial_ratio > 0.5 (且不是當沖客)                       op.partial_ratio
波段囤貨(中短期)    overnight_ratio > 0.5 且 long_term_amt_ratio ≤ 0.5      op.overnight_ratio + op.long_term_amt_ratio
📈 長線持有 (v3.30.9) overnight_ratio > 0.5 且 long_term_amt_ratio > 0.5    同上
                    (單檔在窗口內加碼 ≥ 5 天 = 長線部位)
集中投資            concentration_top5_pct > 50                              op.concentration_top5_pct
分散布局            concentration_top5_pct < 20                              op.concentration_top5_pct
風格純粹            consistency = max(三 ratio) > 0.8                       op.consistency
多變策略            consistency < 0.5                                        op.consistency
高頻交易            active_days / window_days > 0.85                         timing.active_days_ratio
精選出手            active_days_ratio < 0.4                                  timing.active_days_ratio
連續部署            max_streak_days > 8 (跨週末 ≤3 天視為連續)               timing.max_streak_days
🎯 族群專家 (v3.30.11) top_industry_pct > 60                                    op.top_industry_pct
                    (需 industry_classifier 1965 檔產業分類, narrative 顯示族群名)
⚠️ 處置股獵手 (v3.30.13) disposal_amt_ratio > 0.30                              op.disposal_amt_ratio
                    (需 disposal_fetcher 抓 chengwaye, 風險偏好維度,
                     narrative 顯示「⚠️ 處置股部位 X% (N 檔)」)
```

---

*本文件與 `master_profile.py` 的 `THRESH` + `generate_labels()` 嚴格同步。任何改動兩處都要對齊。*
