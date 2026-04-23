---
name: chip-radar-api-crawler-checklist
description: |
  Chip Radar 專屬 — 修改任何 API 爬蟲檔案 (institutional.py / margin.py / crawler.py) 前後必跑的嚴格檢查清單。
  Use when 修改 fetch_* 函數、宣稱「升級限流處理」、新增 TWSE/TPEx/MIS API 呼叫、或增加 retry/delay/fallback 時。
  NOT for 純 UI 改動或不涉及 API 爬蟲的檔案。
  Designed to prevent v3.14.2 → v3.14.3 那種「漏改一個檔案導致用戶看到過時資料」的災難。
---

# Chip Radar API 爬蟲修改 Checklist

## Overview

這個 skill 來自**真實災難案例 (2026/04/22)**：
- v3.14.2 宣稱「全部 API 限流升級」
- 實際上只改了 `institutional.py`
- 漏掉 `margin.py`（融資融券）也有相同問題
- 結果：融資融券頁幾天沒更新,用戶截圖質問才發現
- 必須再發 v3.14.3 hotfix 補修

**核心教訓**：宣稱系統性修復之前,必須先系統性檢查。

## When to Use

**觸發條件**（任一成立即啟動）：
- 修改 `institutional.py` 的 `fetch_*` 函數
- 修改 `margin.py` 的 `fetch_*` 函數
- 修改 `crawler.py` 的爬取主流程
- 新增任何 TWSE/TPEx/MIS API 呼叫
- 宣稱「升級限流處理」或「修復 API 錯誤」
- 增加 retry / delay / fallback 機制

**負面排除**：
- 純 UI 改動 → 不需要
- 只動 `branches.py` 設定 → 不需要
- 只動 `reports.py` 報告產生 → 不需要

## Core Process

### Step 1：列出所有相關 fetch 函數

**修改前**,先執行：

```bash
grep -rn "def fetch\|requests\.get\|requests\.post" \
  --include="*.py" .
```

**必須能列出至少這些**：
- `institutional.py`: fetch_twse_t86, fetch_tpex_3insti, fetch_twse_daily_quotes, fetch_tpex_daily_quotes, fetch_mis_fallback_quotes
- `margin.py`: fetch_twse_margin, fetch_tpex_margin, fetch_all_margin
- `crawler.py`: fetch_branch_amt, fetch_branch_lot

**Exit criterion**：清單存在於對話中。沒列出 = 不能進入 Step 2。

### Step 2：四項全檢查（每個 fetch 函數都跑）

| # | 檢查項 | Grep | 預期 |
|---|-------|------|------|
| A | `import time` 在檔案頂部 | `grep "^import time" <file>.py` | ≥ 1 行 |
| B | retry 之間有 `time.sleep` | `grep -A 3 "次失敗" <file>.py` | 每個 except 後 |
| C | 多個 fetch 之間有 delay | `grep "time.sleep" <file>.py` | fetch_all 內 |
| D | 失敗有 fallback（選配） | 看是否有 MIS / 歷史檔備援 | 關鍵 API 才需要 |

### Step 3：寫並執行系統驗證腳本

```python
#!/usr/bin/env python3
"""每次修改 API 爬蟲後必跑"""
import re
from pathlib import Path

def check(filepath, name):
    content = Path(filepath).read_text()
    fetches = re.findall(r'def (fetch_\w+)', content)
    print(f"\n🟢 {name}: {len(fetches)} 個 fetch 函數")
    
    has_time = bool(re.search(r'^import time', content, re.MULTILINE))
    has_retry = 'time.sleep(10 + attempt' in content
    has_gap = content.count('time.sleep(5)') >= 1
    
    print(f"   {'✅' if has_time else '❌'} import time")
    print(f"   {'✅' if has_retry else '❌'} retry delay (10s+)")
    print(f"   {'✅' if has_gap else '❌'} 查詢間 delay (5s)")
    return all([has_time, has_retry, has_gap])

ok = all([
    check('institutional.py', 'institutional.py'),
    check('margin.py', 'margin.py'),
])
print(f"\n{'✅ 全部通過' if ok else '❌ 禁止 commit'}")
```

**Exit criterion**：腳本顯示 `✅ 全部通過`。

### Step 4：端到端 import 測試

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
import institutional, margin, crawler
print('✓ 所有模組 import 成功')
print('✓ MIS fallback:', callable(institutional.fetch_mis_fallback_quotes))
"
```

**Exit criterion**：所有 `print` 成功執行。

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「我只改一個檔案,其他不會受影響」 | v3.14.2 就是這樣出錯的。grep 一下不會死。|
| 「時間緊迫,等部署後再檢查」 | 部署後再發現 = 寫 hotfix 道歉,更慢 |
| 「我剛剛跑過測試了」 | 跑的是上次成功的快照?還是真的剛改過的版本?|
| 「margin.py 看起來沒壞」 | 「看起來」不是證據。執行 grep 驗證。|
| 「用戶還沒抱怨就是沒問題」 | 用戶總是幾天後才抱怨,到時已累積多次錯誤 |
| 「檢查 4 個點太繁瑣」 | 比寫 hotfix 道歉快 10 倍 |
| 「這次只是小改動」 | v3.14.2 也以為是小改動,結果漏整個檔案 |

## Red Flags

- ❌ 沒執行 Step 1 的 grep 就開始改 code
- ❌ 宣稱「全部升級」但沒跑 Step 3 驗證腳本
- ❌ 說「應該沒問題」、「看起來對」
- ❌ commit 前沒執行 Step 4 的 import 測試
- ❌ commit message 寫「修復所有 API 限流」但 git diff 只動一個檔案

## Verification

交付 / commit 前必須通過：

- [ ] Step 1：grep 清單存在於對話中
- [ ] Step 2：四項檢查每個檔案都過
- [ ] Step 3：驗證腳本顯示 `✅ 全部通過`
- [ ] Step 4：import 測試無錯誤
- [ ] 如果宣稱系統性修復,grep 結果中**所有**相關函數都已改

## Meta-Rule

**如果這個 skill 讓你覺得繁瑣 → 更應該用它**。跳過檢查才會發生 v3.14.2 漏 margin.py 的事故。
