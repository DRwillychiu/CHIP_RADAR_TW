---
name: chip-radar-version-bump-protocol
description: |
  Chip Radar 專屬 — 每次版本升級（3.14 → 3.14.1 或 → 3.15）必須同步完成的所有步驟清單。
  Use when 修改 crawler.py 版號、新增大型功能、準備 HOTFIX 交付、或用戶明確說「升到 vX.Y.Z」。
  NOT for 臨時測試修改或未提交的實驗性改動。
  防止版號改了但 HOTFIX_GUIDE 沒寫、或語法錯誤沒驗證就交付。
---

# Chip Radar 版號升級 Protocol

## Overview

Chip Radar 每個版本號升級都需要同步一系列動作。過去曾發生：
- 版號升 3.14.2 但忘記 commit 其中一個檔案
- HOTFIX_GUIDE 寫錯上版差異
- 交付時 JS 語法還有 bug

這個 skill 確保每次升版**檢查清單完整**。

## When to Use

**觸發條件**：
- 修改 `crawler.py` 的 `"version": "X.Y.Z"` 字串
- 在對話中說「升到 vX.Y.Z」
- 準備 `/mnt/user-data/outputs/v<ver>/` 交付
- 寫 HOTFIX_GUIDE 或 DEPLOY_GUIDE

## Core Process

### Step 1：版號一致性檢查

```bash
# crawler.py 有兩處版號,必須一致
grep -n '"version"' crawler.py
# 預期：兩行都顯示相同版號
```

### Step 2：檔案清單完整性

寫 HOTFIX_GUIDE 時,**必須逐一列出**每個檔案的狀態：

| 檔案 | 變更 | 必須更新? |
|------|------|-----------|
| `crawler.py` | 版號 + X 功能 | 是 |
| `institutional.py` | 不變 or 改動說明 | 是/否 |
| `margin.py` | ... | ... |
| `index.html` | ... | ... |
| `branches.py` | ... | ... |
| `reports.py` | ... | ... |
| `market_classifier.py` | ... | ... |

**Exit criterion**：表格包含**全部 7 個核心檔案**,每個都有明確狀態。

### Step 3：語法驗證三件套

```bash
# 1. JS 括號平衡
python3 -c "
with open('index.html') as f: html = f.read()
for l, r in [('{', '}'), ('(', ')'), ('[', ']')]:
    a, b = html.count(l), html.count(r)
    print(f'{l}{r}: {a}/{b}', '✓' if a == b else '❌')
"

# 2. Node JS 語法檢查
python3 -c "
import re
with open('index.html') as f: html = f.read()
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
with open('/tmp/main.js', 'w') as f: f.write(max(scripts, key=len))
" && node --check /tmp/main.js

# 3. Python 全部模組 import
python3 -c "
import sys; sys.path.insert(0, '.')
import branches, crawler, institutional, margin, reports, market_classifier
print('✓ 6 個模組 import OK')
"
```

**Exit criterion**：三項全部通過,無 error。

### Step 4：Playwright E2E 測試

```bash
cd /home/claude/chip-radar-v3 && python3 -m http.server 8765 > /tmp/srv.log 2>&1 &
sleep 3
# 用 Playwright 跑測試(略)
# 至少要：解鎖 → 切 12 個 tab → 零 JS 錯誤
```

**Exit criterion**：零 JS 錯誤。

### Step 5：HOTFIX_GUIDE 結構驗證

HOTFIX_GUIDE 必須包含：

- [ ] 🐛 本次解決的問題(用戶角度)
- [ ] ✨ 修復內容(技術角度)
- [ ] 📦 檔案交付清單(表格)
- [ ] 📝 部署步驟(Step by step)
- [ ] 🧪 測試結果表
- [ ] 🔮 建議下一步

### Step 6：複製到 outputs

```bash
mkdir -p /mnt/user-data/outputs/v<VERSION>
cp /home/claude/chip-radar-v3/*.py /home/claude/chip-radar-v3/index.html \
   /mnt/user-data/outputs/v<VERSION>/
ls /mnt/user-data/outputs/v<VERSION>/  # 確認 7 個 + HOTFIX_GUIDE
```

**Exit criterion**：`ls` 結果有 8 個檔案(7 個核心 + HOTFIX_GUIDE.md)。

### Step 7：present_files

必須一次把所有 8 個檔案送出。

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「版號改一下就好」 | 那 HOTFIX_GUIDE 呢?Playwright 呢?|
| 「這次沒動 index.html 不用驗證」 | 那 present_files 為什麼要附它?|
| 「反正用戶自己會跑」 | 用戶跑出錯會質問你,不如先跑 |
| 「測試太花時間」 | 寫 hotfix 的時間更長 |

## Red Flags

- ❌ `crawler.py` 兩處版號不一致
- ❌ HOTFIX_GUIDE 沒有「檔案清單」表格
- ❌ 沒跑 Node `--check /tmp/main.js`
- ❌ 沒跑 Playwright 就 present_files
- ❌ `/mnt/user-data/outputs/v<VERSION>/` 檔案數 ≠ 8

## Verification

- [ ] Step 1：版號一致
- [ ] Step 2：檔案清單表格完整
- [ ] Step 3：JS/Node/Python 三驗證通過
- [ ] Step 4：Playwright 零 JS 錯誤
- [ ] Step 5：HOTFIX_GUIDE 6 段齊全
- [ ] Step 6：outputs 有 8 檔
- [ ] Step 7：present_files 交付全部
