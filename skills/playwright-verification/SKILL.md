---
name: chip-radar-playwright-verification
description: |
  Chip Radar 專屬 — 任何涉及 index.html 前端改動都必須跑 Playwright E2E 測試才能交付。
  Use when 修改 index.html、新增前端 tab、改動 chip 顯示邏輯、或前端 JS 邏輯變更。
  NOT for 純 Python 後端改動(那用 pytest)或純 CSS 調整。
  Prevents「JS 看似對但實際上一運作就 crash」或「某個 tab 打不開」的問題。
---

# Chip Radar Playwright 驗證 Protocol

## Overview

Chip Radar 前端有 12 個 tab、加密解鎖、複雜 JS 邏輯。任何改動都可能：
- 破壞某個 tab 的 render 邏輯
- JS 執行時 throw 錯誤但 Node --check 檢查不到
- 條件渲染(如 `s.quote_stale ? ... : ...`)邏輯破損

Node `--check` 只能檢查語法,**Playwright 才能檢查真實行為**。

## When to Use

**觸發條件**:
- 修改任何 `render*` 函數
- 新增或修改 tab 結構
- 變更資料流(buildStockIndex 等)
- 修改條件渲染邏輯
- 新增 chip / badge / tooltip

**負面排除**:
- 只改 CSS 樣式 → 肉眼確認即可
- 純後端 Python 改動 → 用 pytest
- 只改 README.md → 不用

## Core Process

### Step 1:啟動 local server

```bash
cd /home/claude/chip-radar-v3 && python3 -m http.server 8765 > /tmp/srv.log 2>&1 &
SPID=$!
sleep 3
```

### Step 2:寫 Playwright 測試腳本

**必要測試項目**(每次都要跑):

```javascript
const { chromium } = require('/home/claude/.npm-global/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 }});
  const errs = [];
  page.on('pageerror', e => errs.push('Page: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('Console: ' + m.text()); });
  
  // [必要 1] 解鎖
  await page.goto('http://localhost:8765/index.html', { waitUntil: 'networkidle' });
  await page.fill('#passwordInput', 'testpass123');
  await page.click('#unlockBtn');
  await page.waitForTimeout(4000);
  const unlocked = await page.evaluate(() => 
    document.getElementById('appContent').classList.contains('unlocked'));
  console.log('解鎖:', unlocked ? '✓' : '❌');
  
  // [必要 2] 切過所有 12 個 tab
  for (const t of ['today3','overview','branches','ranking','masterview',
                   'institutional','margin','limitup','stock','master',
                   'reports','watchlist']) {
    await page.click(`[data-tab="${t}"]`);
    await page.waitForTimeout(200);
  }
  console.log('12 個 tab 切換: ✓');
  
  // [必要 3] 零 JS 錯誤
  console.log(errs.length === 0 ? '✅ 零 JS 錯誤' : `❌ ${errs.length} 錯誤: ${errs}`);
  
  // [額外] 你改動部分的特定驗證
  // ...
  
  await browser.close();
})();
```

### Step 3:額外功能特定驗證

根據你的改動加額外測試:

**改了 chip 樣式** → 驗證 chip 數量 / className
**改了定義面板** → 驗證 toggleDefinitionPanel 可開關
**改了個股查詢** → 驗證輸入 2317 會顯示鴻海卡片

### Step 4:截圖驗證

```javascript
await page.screenshot({ path: '/tmp/vXXX_verify.png', fullPage: false });
```

**重要改動必截圖**,方便 user 第一眼看到結果。

### Step 5:關閉 server

```bash
kill $SPID 2>/dev/null
```

## Common Rationalizations

| 藉口 | 反駁 |
|------|------|
| 「Node --check 通過了」 | Node 只檢語法,不檢行為 |
| 「我改得很小,不會壞其他功能」 | 你怎麼知道?跑一下 5 分鐘 |
| 「上次沒跑 Playwright 也沒事」 | 你只是還沒發現 bug |
| 「用戶會自己回報 bug」 | 用戶回報 = 你要寫 hotfix 道歉 |

## Red Flags

- ❌ 改 index.html 後只跑 Node `--check` 就說完成
- ❌ 寫了 Playwright 但不執行
- ❌ 有 JS 錯誤但說「可能是資料問題」
- ❌ 忽略特定 tab 切換測試
- ❌ 沒截圖驗證就交付

## Verification

- [ ] Step 1:local server 啟動成功
- [ ] Step 2:[必要 1][必要 2][必要 3] 全通過
- [ ] Step 3:針對改動的特定驗證通過
- [ ] Step 4:截圖存在 `/tmp/` 並肉眼檢查
- [ ] Step 5:server 關閉(避免殘留)

---

## 交付模板

Playwright 通過後,在回覆中附上測試結果表:

```markdown
## 🧪 Playwright 測試結果

| 測試項 | 結果 |
|--------|------|
| 解鎖 | ✅ |
| 12 個 tab 切換 | ✅ |
| 零 JS 錯誤 | ✅ |
| [你的特定測試] | ✅ |
```

這讓用戶一眼看到「真的驗證過了」,而不是你說「應該沒問題」。
