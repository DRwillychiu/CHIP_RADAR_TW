---
name: chip-radar-api-debugging-triage
description: |
  Chip Radar 專屬 — 當用戶報告「資料沒更新」、「融資融券頁卡住」、「顯示舊資料」等症狀時的診斷流程。
  Use when 用戶回報資料疑似過時、Actions log 顯示 503/429 錯誤、或畫面顯示歷史快照。
  NOT for 用戶介面 bug 或資料邏輯錯誤(那是其他 skill)。
  基於 debugging-and-error-recovery 5 步驟 triage 改編,專門處理 TWSE / TPEx / MIS API 限流問題。
---

# Chip Radar API 限流 Debugging Triage

## Overview

TWSE OpenAPI **每 5 秒 3 request** 的限流規則很容易被觸發。常見症狀：
- 融資融券頁沒更新
- 個股收盤價是昨天的
- Actions log 顯示 `503 Server Error`

本 skill 提供 **5 步驟系統診斷**(改編自 Addy Osmani 的 debugging-and-error-recovery)。

## When to Use

**用戶語句觸發**：
- 「資料怎麼沒更新?」
- 「這數字看起來是前幾天的」
- 「融資融券頁沒動」
- 截圖質問 UI 上的數字

**技術徵兆觸發**：
- Actions log 出現 `503` 或 `429`
- 爬蟲 log 顯示 `✓ 0 檔`
- `data/latest.json` 的 date 字段跟今日不符

## Core Process

### Step 1: Reproduce (重現)

**不要猜, 先看實際 log**:

- A. 看最新一次 Actions 的 log
- B. 找出哪個 API 失敗
- C. 記下 retry 次數和錯誤碼

**Exit criterion**: 能用一句話說出「哪個 API、哪個函數、錯幾次」。

### Step 2: Localize (定位)

系統性 grep 找問題位置:

- 找所有 fetch 函數: `grep -n "def fetch" *.py`
- 檢查該函數的 retry 邏輯: `grep -A 10 "def fetch_twse_margin" margin.py`

**Exit criterion**: 能指出具體檔案的具體行號。

### Step 3: Reduce (縮小)

**對比相似的函數**, 檢查是否有一個能運作、另一個壞掉。

例如: `institutional.py` 的 `fetch_twse_daily_quotes` 運作, 但 `margin.py` 的 `fetch_twse_margin` 失敗。對比兩者的結構差異(一個有 time.sleep, 另一個沒有)。

**Exit criterion**: 找出兩個函數的結構差異。

### Step 4: Fix (修復)

**必須符合 v3.14.3 限流標準**:
- retry 間 delay: `time.sleep(10 + attempt * 5)` (10s → 15s → 20s)
- 多個 fetch 間 delay: `time.sleep(5)`
- 關鍵 API: 要有 fallback (MIS API / 歷史檔)

修完後跑 import 測試:
- `python3 -c "import margin; print('OK')"`

**Exit criterion**: import 成功、grep 確認 time.sleep 存在。

### Step 5: Guard (防回歸)

**寫驗證腳本並跑**, 未來同類問題會被捕捉:

- 檢查每個 fetch 函數都有 `import time`
- 檢查每個 except 區塊後都有 `time.sleep`
- 寫成 `tools/verify_api_delays.py` 方便重複跑

**Exit criterion**: 腳本存在, 未來 commit 前可跑。

## Examples

### 範例: v3.14.2 → v3.14.3 診斷過程

**用戶截圖**: 融資融券頁 4/22 顯示的資料看起來是 4/18 的。

**套用本 skill**:

1. **Reproduce**: 找 Actions log → `TWSE Margin 第 1/3 次失敗: 503... 第 2... 第 3... ✓ 0 檔`
2. **Localize**: `margin.py` 第 77 行 retry 區塊
3. **Reduce**: 對比 `institutional.py`(已升級) vs `margin.py`(沒升級) → 差在 time.sleep
4. **Fix**: 加 `import time` + retry `time.sleep(10 + attempt * 5)` + 查詢間 `time.sleep(5)`
5. **Guard**: 寫 `chip-radar-api-crawler-checklist` skill 防未來再犯

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「可能是網路問題」 | 網路問題會一直 503? 不, 是限流。|
| 「再等一下就好」 | API 限流不會自己消失, 要改 code |
| 「用戶可能眼花」 | 看 log, 不要猜 |
| 「先改 UI 顯示警告」 | 根本原因沒修, 警告只是遮醜 |

## Red Flags

- 跳過 Reproduce, 直接開始改 code
- 只改 UI 不修 API 邏輯
- 沒對比相似函數就下診斷
- 修完沒跑 verify script

## Verification

- Step 1 能描述錯誤(哪個 API、哪個函數、錯幾次)
- Step 2 指出具體檔案行號
- Step 3 找到與運作中函數的結構差異
- Step 4 修完 import 測試通過
- Step 5 寫了 verify script
