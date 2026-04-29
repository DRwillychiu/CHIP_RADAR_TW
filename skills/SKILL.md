---
name: chip-radar-version-bump-protocol
description: |
  Chip Radar 專屬 — 每次版本升級必須同步完成的所有步驟清單,含強制 README 更新 (v3.17.5 起)。
  Use when 修改 crawler.py 版號、新增大型功能、準備 HOTFIX 交付、或用戶明確說「升到 vX.Y.Z」。
  NOT for 臨時測試修改或未提交的實驗性改動。
  防止版號改了但 HOTFIX_GUIDE 沒寫、或 README 落後 (v3.17.5 教訓:落後 13 個版本)。
---

# Chip Radar 版號升級 Protocol (v3.17.5 強化版)

## Overview

Chip Radar 每個版本號升級都需要同步一系列動作。

歷史教訓:
- 版號升 3.14.2 但忘記 commit 其中一個檔案
- HOTFIX_GUIDE 寫錯上版差異
- 交付時 JS 語法還有 bug
- **🚨 v3.17.5 最大教訓:從 v3.14.4 → v3.17.4 連續 13 個版本沒更新 README**
  - GitHub README 仍寫 v3.14.3
  - 別人看 GitHub 不知道專案實際能力
  - 用戶 (DRwillychiu) 親自指出此紀律問題

這個 skill 確保每次升版**檢查清單完整,包含 README**。

## When to Use

**觸發條件**:
- 修改 `crawler.py` 的 `"version": "X.Y.Z"` 字串
- 在對話中說「升到 vX.Y.Z」
- 準備 `/mnt/user-data/outputs/v<ver>/` 交付
- 寫 HOTFIX_GUIDE 或 DEPLOY_GUIDE

## Core Process

### Step 1: 版號一致性檢查

```bash
# crawler.py 有兩處版號,必須一致
grep -n '"version"' crawler.py
# 預期:兩行都顯示相同版號
```

### Step 2: 檔案清單完整性

寫 HOTFIX_GUIDE 時,**必須逐一列出**每個檔案的狀態:

| 檔案 | 變更 | 必須更新? |
|------|------|-----------|
| `crawler.py` | 版號 + X 功能 | 是 |
| `institutional.py` | 不變 or 改動說明 | 是/否 |
| `margin.py` | ... | ... |
| `index.html` | ... | ... |
| `branches.py` | ... | ... |
| `reports.py` | ... | ... |
| `market_classifier.py` | ... | ... |
| `futures.py` | ... | ... |
| `history.py` | ... | ... |
| `industry_classifier.py` | ... | ... |
| `histock_verifier.py` | ... | ... |

**Exit criterion**: 表格包含**全部 11 個核心檔案** (含 v3.17 新增 futures.py),每個都有明確狀態。

### Step 3: 語法驗證三件套

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
import branches, crawler, institutional, margin, reports, market_classifier, histock_verifier, industry_classifier, history, futures
print('✓ 10 個模組 import OK')
"
```

**Exit criterion**: 三項全部通過,無 error。

### Step 4: Playwright E2E 測試

```bash
cd /home/claude/chip-radar-v3 && python3 -m http.server 8765 > /tmp/srv.log 2>&1 &
sleep 3
# 用 Playwright 跑測試
# 至少要:解鎖 → 切 13 個 tab → 零 JS 錯誤
```

**Exit criterion**: 零 JS 錯誤。

### Step 5: HOTFIX_GUIDE 結構驗證

HOTFIX_GUIDE 必須包含:

- [ ] 🐛 本次解決的問題(用戶角度)
- [ ] ✨ 修復內容(技術角度)
- [ ] 📦 檔案交付清單(表格)
- [ ] 📝 部署步驟(Step by step)
- [ ] 🧪 測試結果表
- [ ] 🔮 建議下一步

### Step 6: ⭐ README.md 必更新 (v3.17.5 起強制)

**這是 v3.17.5 起的新規則 — 不可省略**。

```bash
# 6-1. 更新版本標記
# README.md 開頭的「當前版本:vX.Y.Z」必須改為新版號
grep -n "當前版本" README.md
# 預期:看到新版號

# 6-2. 加版本歷程條目
# 在「## 📈 版本歷程」段落加新條目,格式:
# - **vX.Y.Z** (YYYY/MM/DD) 🆕
#   - 主要功能 1
#   - 主要功能 2
#   - bug 修正

# 6-3. 更新最後標記
# README.md 結尾的「Last Updated」必須改為新日期 + 新版號
grep -n "Last Updated" README.md
```

**驗證**:
```bash
# README 提及的最新版號必須等於 crawler.py 版號
README_VER=$(grep -oP "當前版本.*?v\K[0-9.]+(-patch[0-9]+)?" README.md | head -1)
CRAWLER_VER=$(grep -oP '"version": "\K[^"]+' crawler.py | head -1)
[ "$README_VER" = "$CRAWLER_VER" ] && echo "✅ 版本一致" || echo "❌ 不一致 README=$README_VER vs crawler=$CRAWLER_VER"
```

**Exit criterion**: README 版本標記 = crawler.py 版號。

### Step 7: 複製到 outputs

```bash
mkdir -p /mnt/user-data/outputs/v<VERSION>
cp /home/claude/chip-radar-v3/*.py /home/claude/chip-radar-v3/index.html \
   /home/claude/chip-radar-v3/README.md \
   /mnt/user-data/outputs/v<VERSION>/
ls /mnt/user-data/outputs/v<VERSION>/
# 確認至少有: 11 個核心檔案 + HOTFIX_GUIDE.md + README.md = 13 個
```

**Exit criterion**: `ls` 結果包含 README.md。

### Step 8: present_files

必須一次把所有檔案送出,**包含 README.md**。

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「版號改一下就好」 | 那 HOTFIX_GUIDE 呢?Playwright 呢?**README 呢?** |
| 「這次沒動 index.html 不用驗證」 | 那 present_files 為什麼要附它? |
| 「反正用戶自己會跑」 | 用戶跑出錯會質問你,不如先跑 |
| 「測試太花時間」 | 寫 hotfix 的時間更長 |
| 「README 改個版本歷程而已」 | **是的,所以更不能漏。10 秒鐘的事** |
| 「上次也沒更新 README 沒事」 | **v3.17.5 用戶就直接抓包,不能再有下次** |

## Red Flags

- ❌ `crawler.py` 兩處版號不一致
- ❌ HOTFIX_GUIDE 沒有「檔案清單」表格
- ❌ 沒跑 Node `--check /tmp/main.js`
- ❌ 沒跑 Playwright 就 present_files
- ❌ **README 版號跟 crawler.py 版號不一致** ⭐ v3.17.5 新增
- ❌ **README 沒有新版本的歷程條目** ⭐ v3.17.5 新增
- ❌ `/mnt/user-data/outputs/v<VERSION>/` 沒有 README.md ⭐ v3.17.5 新增

## Verification Checklist

- [ ] Step 1: 版號一致 (crawler.py 兩處)
- [ ] Step 2: 檔案清單表格完整
- [ ] Step 3: JS/Node/Python 三驗證通過
- [ ] Step 4: Playwright 零 JS 錯誤
- [ ] Step 5: HOTFIX_GUIDE 6 段齊全
- [ ] Step 6: ⭐ **README 已更新** (版本標記 + 版本歷程 + Last Updated)
- [ ] Step 7: outputs 包含 README.md
- [ ] Step 8: present_files 交付全部含 README

---

## 🎯 v3.17.5 教訓 (永久記錄)

**事件**: 2026/04/29 用戶 DRwillychiu 指出:
> 「我認為在此時此刻之後,每一次的優化都要去更新 README.MD」

**原因**: 從 v3.14.4 到 v3.17.4,連續 13 個版本沒更新 README。GitHub 上呈現的還是 v3.14.3。

**用戶的話**:
> 「我這上面所有 66 個期貨/選擇權數字,都是從 TAIFEX 官方端點直接抓的」

→ 用戶把 Chip Radar 當實戰工具用,需要 GitHub README 對外呈現完整能力。

**修正**:
- 從 v3.17.5 起,Step 6 (README 更新) 列為**強制必做**
- 不更新 README → 不能 commit
- 寫進這個 SKILL,永久化紀律
