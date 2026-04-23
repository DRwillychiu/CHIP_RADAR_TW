---
name: chip-radar-three-files-sync
description: |
  Chip Radar 專屬 — 新增或修改任何「前端顯示功能」時,必須同步 branches.py / crawler.py / index.html 三個檔案的 checklist。
  Use when 新增分點、新增 master style、修改 chip 顯示邏輯、或調整共買榜/漲停狙擊頁面資料流。
  NOT for 純樣式調整 (CSS only) 或 bug 修復。
  Prevents 「branches.py 改了但 crawler 沒注入、或 index.html 沒渲染」的斷鏈問題。
---

# Chip Radar 三檔同步 Protocol

## Overview

Chip Radar 的資料流是 **branches.py → crawler.py → JSON → index.html**。

新增任何前端顯示的資料欄位(例如 master_style、co_masters、is_limit_up)時,必須**三個檔案都改**：
1. `branches.py`：定義資料結構 / 設定值
2. `crawler.py`：計算 + 注入到 JSON
3. `index.html`：渲染顯示

只改一處會導致「有資料但不顯示」或「顯示空值」。

## When to Use

**觸發條件**：
- 新增分點到 WATCHED_BRANCHES
- 新增 MASTER_STYLES 分類
- 新增任何 compute_* 函數到 crawler.py
- 在 chip / badge / table 新增欄位
- 調整共買榜資料結構

## Core Process

### Step 1：確認資料流方向

用圖示理解這個改動在哪一環：

```
前端新增顯示 → 從哪來?
    ↓
    crawler.py compute_* 函數
    ↓
    從哪抓?
    ↓
    branches.py 設定 / 三大法人 API / 分點 API
```

### Step 2：三檔同步 checklist

**每新增一個前端欄位都跑這個檢查**：

| 階段 | 檔案 | 檢查點 |
|------|------|--------|
| 1 | `branches.py` | 有沒有新增設定?(如 master style dict)|
| 2 | `crawler.py` | 有沒有 compute 這個欄位並寫到 JSON?|
| 3 | `crawler.py` | JSON 輸出結構是否有這個欄位?|
| 4 | `index.html` | buildStockIndex 有帶這個欄位嗎?|
| 5 | `index.html` | render 函數有使用並顯示嗎?|

### Step 3：資料流測試

```bash
# 模擬執行 crawler,看 JSON 結構
cd /home/claude/chip-radar-v3
python3 -c "
import sys; sys.path.insert(0, '.')
import json
from pathlib import Path
# 讀現有 JSON 看是否有新欄位
data = json.loads(Path('data/latest.json').read_text())
sample = data.get('branches', [{}])[0].get('buys', [{}])[0]
print('一筆 buy 資料的所有欄位:')
for k in sorted(sample.keys()): print(f'  {k}')
"
```

**Exit criterion**：新增的欄位出現在輸出中。

### Step 4：前端渲染驗證

```bash
# Playwright 打開網頁,用 page.evaluate 檢查
page.evaluate("""
const samples = Array.from(document.querySelectorAll('.stock-name'))
  .slice(0, 3).map(el => el.innerHTML);
console.log(samples);
""")
```

**Exit criterion**：新增欄位真的顯示在畫面。

## Examples

### 範例：v3.12 新增 master_style

- `branches.py`：`MASTER_STYLES = { "蔣承翰": ["next_day_flipper"], ... }`
- `crawler.py`：`compute_limit_up_summary()` 讀 MASTER_STYLES 產生 style_stats
- `index.html`：漲停狙擊頁的 style_stats 儀表板使用

**如果漏任一環**：
- 漏 branches → 錯誤：`MASTER_STYLES` not defined
- 漏 crawler → 前端 style_stats 永遠是空的
- 漏 index.html → 資料在 JSON 但畫面看不到

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「我只改前端,其他不用動」 | 前端顯示的資料是從哪來的?|
| 「branches.py 加一個分點應該不用改 crawler」 | 分點設定有沒有新欄位?沒有就 OK。有的話 crawler 要讀它 |
| 「crawler 有算但 JSON 沒寫出來也沒關係」 | 前端讀 JSON,JSON 沒寫 = 永遠顯示空 |

## Red Flags

- ❌ 只改 branches.py 就說做完
- ❌ 只改 index.html 就說做完
- ❌ 沒看 JSON 輸出結構就 commit
- ❌ 沒跑 Playwright 檢查畫面就交付

## Verification

- [ ] 三檔案都改(或明確說明為什麼只改兩個)
- [ ] Step 3 資料流測試：新欄位在 JSON 中
- [ ] Step 4 前端驗證：新欄位顯示在畫面
- [ ] commit message 列出三個檔案的變動

---

## 歷史教訓

**v3.10 共用分點**：
- ❌ 只改了 branches.py 加 `co_masters`
- ✅ 後來發現 crawler.py 要用 co_masters 產生合併視角
- ✅ index.html 要同時顯示 master + co_masters

如果當時有這個 skill,不會 v3.10.1 hotfix。
