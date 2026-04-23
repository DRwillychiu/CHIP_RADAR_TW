# 🏛️ Chip Radar TW — Agent Skills 專屬庫

基於 [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) 的哲學，為 Chip Radar 專案量身打造的 5 個關鍵 workflow skills。

**設計目標**：強迫 AI (Claude) 遵守 Chip Radar 的工程紀律,防止「用戶截圖質問才發現」的災難。

---

## 📋 Skills 清單

| # | Skill | 用途 | 觸發時機 |
|---|-------|------|---------|
| 1 | [api-crawler-checklist](./api-crawler-checklist/SKILL.md) | API 爬蟲修改前後檢查 | 改 fetch_* 函數 |
| 2 | [version-bump-protocol](./version-bump-protocol/SKILL.md) | 版號升級規範 | 改版號 / 交付 |
| 3 | [three-files-sync](./three-files-sync/SKILL.md) | 三檔同步（前端功能）| branches/crawler/index.html 改動 |
| 4 | [api-debugging-triage](./api-debugging-triage/SKILL.md) | API 限流 5 步驟診斷 | 用戶報告資料沒更新 |
| 5 | [playwright-verification](./playwright-verification/SKILL.md) | 前端 E2E 驗證 | 改 index.html |

---

## 🎯 核心原則（從 Addy Osmani 內化）

### 1. Encode process, not knowledge
每個 skill 都是**工作流程**，不是參考文件。有步驟、驗證點、退出條件。

### 2. Anti-rationalization
每個 skill 都有「Common Rationalizations」反藉口表。例如：
- ❌ 「時間緊迫,先交付再說」→ ✅ 「hotfix 時間更長」
- ❌ 「看起來沒問題」→ ✅ 「看起來不是證據」

### 3. Verification non-negotiable
每個 skill 必有**退出條件 checklist**。`Seems right` 永遠不夠。

---

## 🚀 使用方式

### 方法 A：用戶明確指定

```
你跟 Claude 說：
「按 chip-radar-api-crawler-checklist 改 margin.py」
```

Claude 會自動套用該 skill 的 4 步驟流程。

### 方法 B：Claude 自動偵測（推薦）

把 SKILLS 載入 Claude 的對話 context：
```
在對話開頭貼：
「Chip Radar 專案使用 skills/ 中的工作流程：
 - api-crawler-checklist
 - version-bump-protocol
 - three-files-sync
 - api-debugging-triage
 - playwright-verification
請根據我的 request 自動判斷該用哪個 skill」
```

---

## 📖 Skills 設計哲學

這些 skills 全部來自 **Chip Radar 的真實災難案例**：

| Skill | 來自哪個事故 |
|-------|-------------|
| api-crawler-checklist | v3.14.2 漏改 margin.py 限流（用戶截圖質問）|
| version-bump-protocol | 多次版號改了但 HOTFIX_GUIDE 寫不全 |
| three-files-sync | v3.10 共用分點欠 index.html 顯示 |
| api-debugging-triage | 多次 503/429 限流問題診斷 |
| playwright-verification | 改 JS 後「看似對」但實際 crash |

**結論**：這些不是理論,是**實戰血淚**換來的。

---

## 📊 版本歷程

- **v1.0**（2026/04/23）：初版 5 個 skills,基於 Addy Osmani 的 6 段 SDLC 架構

---

## 🔗 延伸閱讀

- 原版 [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
- Chip Radar 主 README: [../README.md](../README.md)

---

**Made with ❤️ 用以避免「用戶截圖質問」的尷尬**
