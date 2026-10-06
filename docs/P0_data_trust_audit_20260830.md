# P0 資料信任度掃尾稽核 — 2026-08-30

> 起因:v3.76.0(2026-08-29)揭穿 `stock_history.market` 有 78% 的紀錄日期慢一天。
> 根因是 `_fetch_taiex_index` 的 stale guard 讀 `.get('Date')`,但 TWSE MI_INDEX
> 是中文欄位「日期」→ `response_date` 永遠空字串 → guard 自 v3.27.3 起從未執行。
>
> 本次不修那一個 bug(已修),而是回答三個問題:
> **① 哪些既有結論建立在污染資料上?**
> **② 還有沒有同一類的錯誤?**
> **③ 下次同類錯誤會自己叫嗎?**

---

## ① 下游影響清單 — 哪些結論被污染?

`market` 的消費者共 4 條路徑,逐一用 TWSE 官方 FMTQIK 對照驗證:

| 消費者 | 用途 | 資料來源 | 判定 | 證據 |
|---|---|---|---|---|
| `backtest_results.json`(247 配對) | **硬編碼 `SIGNAL_WEIGHTS` 的依據**(P/C Ratio、結算日壓力) | 2025-05-09 ~ 2026-05-16 自有 backfill | ✅ **乾淨** | 抽 6 個月 × 官方 FMTQIK 對照:**116 正確 / 0 不符** |
| `signal_history_official.json`(119 筆) | **Phase B 動態權重的實際輸入** | TWSE T86 + TAIFEX + **FMTQIK** + own archive | ✅ **乾淨** | 與現行 market 重疊 18 筆,**18 正確 / 0 不符** |
| `backtest_phase_b_results.json` | 現行 4 信號動態權重(外資現貨/分點漲停/融資熱度/法人共識) | 由上一列產生(`_meta.data_source` 已記錄) | ✅ **乾淨** | regime=mild_bull,trust_weights=True |
| `temp_history.next_day_change_pct` | **Q5 命中判定** | 由污染的 `market` 推導 | ❌ **曾污染 47/60** | v3.76.0 已用官方重算,現 59/59 正確 |
| `index.html` 個股走勢圖的大盤基準線 | 視覺對照 | 讀 `stock_history.market` | ⚠️ **曾偏移一天** | 隨 v3.76.0 資料修正自動修好,雲端版已驗證 0 錯位 |

**結論:權重體系(SIGNAL_WEIGHTS + Phase B)完全沒有被污染,不需要重跑。**
唯一被污染的是 Q5 的命中判定,而那正是 v3.76.0 揭穿「Δ +0.0pp」的地方。

### ⚠️ 順帶發現的陷阱(已補守門)

`backtester_phase_b.py` 的 CLI **預設是 `data/temp_history.json`**,
但現行 production 檔案實際是從 `signal_history_official.json` 產生的。
直接跑預設會**靜默換掉權重的資料基礎**,而權重是 `infer_market_direction` 的核心。

→ `save_results()` 現在會比對前一版的 `_meta.data_source`,不同就大聲警告。

---

## ② 同類錯誤掃描 — 還有沒有別的欄位名讀錯?

新增 `scripts/audit_api_fields.py`:對 **13 個上游端點做實際 probe**,
比對「程式碼實際會讀的欄位名」是否存在於回傳結構。

```
結果: 13 OK / 0 WARN / 0 CRITICAL
```

### 特別確認的三處

- **`institutional.py:324` / `:412` 也寫 `.get('Date')`** — 但 STOCK_DAY_ALL 與
  TPEx daily 的日期欄**確實是英文 `Date`**。那兩處寫法正確,不是同一個 bug。
  這也解釋了為何個股收盤價完全沒事(2330/2317 各 42 筆零錯位)。
- **融資融券兩支的欄位語言是相反的** — TWSE MI_MARGN 是**中文**(融資今日餘額…),
  TPEx margin_balance 是**英文**(MarginPurchaseBalance…)。`margin.py` 兩邊都寫對。
  第一版稽核 registry 反而把兩者寫反並誤報 CRITICAL,已修正並在測試裡釘死。
- **rwd 系列有兩種形狀** — 頂層 `fields`/`data`,或資料包在 `tables[]` 內。
  MI_MARGN `selectType=MS` 屬後者,稽核已同時支援。

---

## ③ 結構性防護 — 下次會自己叫嗎?

這類 bug 的致命特徵是**完全靜默**:不拋例外、workflow 不變紅、資料看起來正常,
錯的只有「保護沒生效」。用戶目標是「一個月不去動他,讓他自動更新」,
所以真正該補的不是修一次資料,而是讓同類錯誤下次會自己叫。

分兩層,依變動頻率決定執行頻率:

| 層 | 檢查 | 頻率 | 打網路 | 觸發後果 |
|---|---|---|---|---|
| **本機自我一致性** | `heartbeat_check.check_data_integrity()`<br>· 每筆 market 必須有 `quote_date`<br>· `quote_date` 換算後必須等於 key 日期<br>· 大盤最新日不得落後個股最新日 | 每日 2 次<br>(00:30 / 09:00 TW) | ❌ 否 | 前兩項 → **FAIL**(靜默汙染)<br>第三項 → WARN |
| **上游欄位漂移** | `scripts/audit_api_fields.py`<br>13 端點 × 程式碼實際讀的欄位 | 每週 1 次<br>(週日 22:00 TW) | ✅ 是 | CRITICAL → workflow 變紅 |

設計理由:欄位名不會天天變,把網路檢查放週檢即可;
而日期錯位是每天都可能發生的,必須放在每日心跳,且不能依賴網路(否則 API 抖動會誤報)。

### 驗證方式

`tests/test_v3770_data_integrity_guard.py`(25 PASS)**直接餵入 v3.76.0 之前的真實壞狀態**:

- A2:`quote_date` 慢一天 → 必須 FAIL(這是 43/55 筆的狀態)
- A3:`quote_date` 全空 → 必須 FAIL(這是 guard 從未執行時的狀態)
- A6:production 現況 → 必須 PASS

也就是說,**這道守門若在一年前就存在,當天就會擋下來。**

---

## 全套回歸(267 case)

```
v3770 資料完整性守門    25 PASS    v3723 top-buyer highlight   53 pass
v3760 TAIEX stale guard 10 PASS    v3729 sniper enricher       17 pass
v3750 quad live stats   25 PASS    v3380 結算時區              36 PASS
v3740 公司行動          43 PASS    v3371 TDCC                  25 PASS
v3370 融資維持率        33 PASS
```

---

## 尚未處理(不屬 P0,列此備查)

- **溫度計去留** — 乾淨資料下 Δ +0.0pp;7 信號中 3 個對方向判定影響為 **0 天**,
  另 2 個各只有 1-2 天。實際做決策的只有 P/C Ratio(21/59)與分點漲停(22/59)。
  方向分布偏多 50 / 中性 7 / 偏空 2,行為上近乎無腦全多。**需用戶裁示**。
- **外資期貨閾值** — 現行 `[30000, 10000, -10000, -30000]`,實際 60 天值域
  `-90,946 ~ -60,275`,全部落在同一區 → score 恆 0。
  另注意它同時是 `KILLED_SIGNALS` 成員(weight 本來就 0),兩件事需分開處理。
- **分點漲停閾值** — 現行 `[8, 4, 1, 0]`,實際值域 `3 ~ 166`。
  但它現在是撐住 0.10 方向門檻的兩根柱子之一,**改它屬策略層改動而非資料校準**。
