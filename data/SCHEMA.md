# Chip Radar TW · data/ 目錄資料 schema 文件

> **目的**:文件化每個 JSON 檔的 `effective_date` 語意 + 跨檔時間軸 mismatch 風險,防雙重計算/誤判
> **版本**:v3.38.0 (P0-3)
> **最後修訂**:2026-06-19

---

## 1. 時間軸定義 (避免 mismatch)

| 概念 | 定義 | 範例 |
|---|---|---|
| **trade_date** | 該檔資料對應的「TWSE 交易日」 (TW 時區 YYYYMMDD) | 20260618 |
| **crawled_at** | 抓取時間戳 (TW ISO with tz) | 2026-06-19T12:18:09+08:00 |
| **effective_date** | 該資料**生效**的交易日 (可能 lag, 例如處置 T+3) | 20260622 (處置生效日) |
| **applicable_period** | 該資料**適用期間** (週頻、月頻用) | "2026-W25" |
| **lag_days** | crawled_at 跟 effective_date 的時差 | 處置 T+3 = 3 天 |

---

## 2. 各檔 schema + 時間軸

### `latest.json` (加密 + gzip)
- **內容**:當日完整分點 + 三大法人 + 期貨 + 融資維持率 + TDCC 注入
- **trade_date**:當日盤後最新 (例 20260618)
- **crawled_at**:本日 21:17-23:47 之間 (兜底排程多次重跑取最後成功)
- **更新頻率**:每交易日 1-3 次
- **加密**:AES-256-GCM + PBKDF2-SHA256 + gzip (magic bytes auto-detect)

### `YYYYMMDD.json` (加密 + gzip, hot 7 天)
- **內容**:同 latest.json 但鎖定為該日歷史版
- **位置**:`data/YYYYMMDD.json` (≤ 7 天) → `data/archive/` (warm, 7-60 天) → `*.json.gz` (cold, >60 天)

### `stock_history.json` (明文)
- **內容**:30 天滾動個股收盤 + 期貨 + 大盤
- **不需密碼**:純行情統計, 供前端 chart 直接讀
- **更新頻率**:每交易日

### `master_profiles.json` (明文)
- **內容**:29 大戶 × 15 標籤 + 派系 + T+1 跨日 + 實戰信號 + 處置持倉 + 族群輪動
- **trade_date_range**:`[start, end]` (例 `[20260421, 20260618]`)
- **window_days**:60 天滾動視窗 (B3 時間衰減 half_life=20)
- **更新頻率**:每交易日由 crawler 自動產出

### `disposal_map.json` (明文)
- **內容**:當日處置股清單 (active + imminent_1 + imminent_2)
- **lag**:**T+3** — 處置生效日 ≥ TWSE 公告日 + 3 個交易日
- **更新頻率**:每日抓 chengwaye (TTL 1 天)
- **⚠️ 時間軸風險**:`disposal_map.applicable_date` 是「生效日」,**不是抓取日**

### `disposal_history/YYYYMMDD.json` (明文 snapshot)
- **內容**:該日的 `sets` (active/imminent_1/imminent_2) 純資料層
- **YYYYMMDD**:抓取日 (= crawled date), 不是生效日
- **6/4 起開始累積**

### `tdcc_holdings.json` (明文, 主檔)
- **內容**:篩選 2376 檔的完整持股結構 (big400_pct / mega1000_pct / retail_pct + 上週 delta)
- **effective_date**:**TDCC 資料期** (週六公布, 通常是「未來週五」如 20260618 — TDCC 用「適用週」標期)
- **effective_week_iso**:對應 ISO 週 (2026-W25)
- **更新頻率**:每週六 11:00 + 14:00 TW (兜底)

### `tdcc_history/YYYYMMDD.json` (明文 snapshot, P0-6 精簡版)
- **內容**:slim_v1 格式 (只存 big400/mega1000/retail/mid + effective_date)
- **YYYYMMDD**:effective_date (TDCC 資料期)
- **schema_version**:`slim_v1` (區分舊全量 snapshot)

### `audit_history.json` (明文)
- **內容**:每日 audit verdict 趨勢 (180 筆)
- **YYYYMMDD**:audit run date (= 抓取日)

### `daily_signals.json` / `daily_trading_signals.json` (明文)
- **內容**:當日異常 + 派系共識 + 連續加碼
- **trade_date**:當日

### `temp_history.json` (明文)
- **內容**:60 天溫度計信號歷史
- **每日 entry**:`{date, score, signals[], taiex_index, next_day_change_pct}`

---

## 3. ⚠️ 已知時間軸 mismatch 風險

### Risk-1: TDCC 週頻 + disposal T+3 + 60 天視窗 → 雙重計算

**場景**:某股 6/15 (一) 進處置 (effective_date=6/18 T+3), TDCC 6/14 (週五) 公布 (effective_date=6/14)
→ master_profile 視窗內同股「處置中買進」+「TDCC 大戶比例上升」可能由同一筆交易產生
→ 大戶力度信號被計兩次

**對策 (v3.38.0 P0-3)**:
1. 本文件文件化 effective_date 語意
2. 計算端 dedup guard:同 master × 同股 × 同 calendar week 只算最近一次買進

### Risk-2: 結算日 TZ race (P0-1 已解)

`_days_to_settlement` 在 UTC runner 跨日時可能 off-by-one
→ 已於 v3.38.0 P0-1 修補, third_wed 提升為公開函式 + 明示 TW 約定

### Risk-3: 兜底排程多次 crawled_at, master_profile 重複生成

主排程 21:17 + 兜底 22:37 + 23:47 都會跑 build_all_profiles
→ master_profiles.json 一日內被覆寫 3 次
→ 前端讀檔時可能讀到「中間態」(寫一半)

**對策**:write atomic (寫 .tmp → rename) — 已內建在 Python 的 `text.write_text`

### Risk-4: archive 三層 vs master_profile 視窗 mismatch

`master_profile.load_history` 同時掃 `data/` (hot) + `data/archive/` (warm) + `*.json.gz` (cold)
→ 60 天視窗剛好跨 warm/cold 邊界時, 若 archive_manager 還沒輪轉, 同一天可能有兩份檔案
→ extract_master_trades 會去重 (set), 但仍會兩次解密

**對策**:archive_manager 輪轉前後 master_profile 不會 panic, 但有效能浪費

---

## 4. dedup guard 實作位置

| Module | 函式 | 邏輯 |
|---|---|---|
| `master_profile.extract_master_trades` | for loop | (date, branch_code, stock_code) 三元組去重 (set) |
| `disposal_holdings._extract_net_flows` | for loop | (branch, code) per day 去重 (seen set) ← v3.36.0 已內建 |
| `master_alliance.compute_alliance_matrix` | jaccard | per day stock set (天然去重) |

---

## 5. 變更紀錄

| 版本 | 變動 |
|---|---|
| v3.38.0 (P0-3) | 本文件首版, 文件化 6 個主要 effective_date 語意 + 4 個已知 mismatch 風險 |
| v3.38.0 (P0-6) | tdcc_history snapshot 改精簡 slim_v1 (~200KB vs 605KB) |

---

## 6. 何時更新本檔

- 新增新檔案 (新 module 寫入 data/)
- effective_date 語意改變
- 跨檔交叉計算的新 join 邏輯
- 任何 archive / TTL / 視窗變動
