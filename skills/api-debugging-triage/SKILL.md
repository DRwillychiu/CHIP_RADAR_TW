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

### Step 1:Reproduce (重現)

**不要猜,先看實際 log**:

```bash
