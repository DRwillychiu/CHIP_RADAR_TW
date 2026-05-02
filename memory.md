# 🧠 Chip Radar TW · Memory

> 這個檔案是 Chip Radar 專案的**完整結構化記憶系統**，給未來 Claude 對話讀取使用。
> 每次升版必更新「## 📅 當前工作焦點」段落。

**最後更新**: 2026/05/02 · v3.19 部署完成
**累計戰力**: 94/100 (期貨情報滿分 + 行情面 + 個股行情整合)

---

## 📅 當前工作焦點

### 進行中
- ✅ **v3.19 個股行情整合** (2026/05/02 完成)
  - 個股股價 chip 全面整合 (3 個 helper + 4 個整合點)
  - 利用 stock_history.json (8,885 檔每日 close)
  - 不需動爬蟲, 純前端優化
  - Playwright 11 項測試全綠

- ✅ **v3.18 期貨行情面 + 夜盤三大法人** (2026/05/01 完成)
  - TX 6 個月份開高低收 + 跨月價差
  - 夜盤三大法人 (TXF/MXF/TMF)
  - 新增 17 個欄位 100% 對齊 TAIFEX
  - 累計 83 個欄位通過審計

### 短期路線圖 (1-2 週)
- ✅ **v3.19 個股行情整合** (2026/05/02 完成)
- ⏳ **v3.20 Discord/Line 推播** - 5 種訊號條件式通知 (8-10h)
- ⏳ **v3.21 族群深度頁** (3-5h)

### 中期路線圖 (1 個月)
- ⏳ v3.21 族群深度頁 (半導體/航運/AI 板塊)
- ⏳ v3.22 主力 vs 散戶雙視角儀表板
- ⏳ v3.23 自動化反饋驗證 (隔日沖預測準確率)

### 長期路線圖
- ⏳ Max Pain (需找付費資料源)
- ⏳ 立委持股追蹤
- ⏳ 多股比較圖

---

## 🎯 專案核心資訊

```
專案名稱: Chip Radar TW · 分點籌碼觀察站
定位: 台股籌碼分析專家 (不是宏觀晨報、不是美股工具)
GitHub: https://github.com/DRwillychiu/CHIP_RADAR_TW
網站: https://drwillychiu.github.io/CHIP_RADAR_TW/
解鎖密碼: testpass123 (測試) / GitHub Secret CHIP_RADAR_PASSWORD
加密: AES-256-GCM + PBKDF2-SHA256
工作目錄: /home/claude/chip-radar-v3/
訂閱: Claude Max 20x
```

---

## 🏗️ 模組架構

### 後端 (10 個 Python 模組)
| 檔案 | 職責 | 大小 |
|------|------|------|
| `crawler.py` | 主流程 (整合所有模組) | ~96KB |
| `branches.py` | 49 分點籌碼 + 25 master | - |
| `institutional.py` | 三大法人 (TWSE + TPEx) | - |
| `margin.py` | 融資融券 (TWSE + HiStock 雙源) | - |
| `futures.py` | TAIFEX 期貨/選擇權 (v3.18 ~970 行) | ~30KB |
| `history.py` | 30 天累積 (含期貨歷史) | - |
| `industry_classifier.py` | 1965 檔產業分類 | - |
| `market_classifier.py` | 上市/上櫃/ETF 分類 | - |
| `histock_verifier.py` | HiStock 交叉驗證 | - |
| `reports.py` | 每日報告 | - |

### 前端 (index.html ~360KB)
- HTML/CSS/JS 單檔
- Chart.js 4.4.1
- AES-256-GCM 加密解鎖
- 13 個 tab + 多個 Modal
- **主頁面**:籌碼溫度計 (5 信號 + 0-100 分)

### GitHub Actions
- `daily-full.yml`: 1 個排程 (20:00 週一-五) - 全部資料
- `margin-refresh.yml`: 7 個排程 (22:30/23:30/00:30/02:00/08:00/09:00/12:00) - 融資融券補抓

---

## 📊 完整版本歷程

### v3.19 個股行情整合 (2026/05/02) ⭐
- 個股股價 chip 全面整合
- 3 個 helper:getStockQuote / renderQuoteChip / renderInlineQuote
- 4 個整合點:個股追蹤 / 共買榜 / 高手共識 / Top 20
- 利用 stock_history.json (8,885 檔, 不需動爬蟲)
- ≥7% 自動跳過避免重複
- Playwright 11 項全綠

### v3.18 期貨行情面 (2026/05/01) ⭐
- 期貨各月份開高低收 + 跨月價差 + 夜盤
- 夜盤三大法人 (TXF/MXF/TMF)
- 17 個新欄位對齊 TAIFEX (累計 83)

### v3.17.5 數據準確性審計 (2026/04/29) ⭐⭐
- 修正 PCR bug (1.579 → 1.7112 對齊官方)
- 修正十大交易人 bug (改用全部月份)
- 「✓ TAIFEX 對齊」綠色徽章上線
- 66 個欄位 100% 對齊 TAIFEX

### v3.17.4 (2026/04/29)
- 籌碼溫度計顯示修復 (5 信號完整)
- 視覺優化:加粗 22px / 白色雙箭頭指針

### v3.17.3 (2026/04/29)
- 視覺化溫度計 (線性漸層 + 0-100 分)

### v3.17.2 (2026/04/29) 套餐 D
- 籌碼溫度計 (5 信號儀表板)
- 個股追蹤預設熱門 + 期貨 banner 三欄

### v3.17.1-patch1 (2026/04/29)
- 結算日 toISOString UTC bug 修正
- 十大交易人資料來源透明化

### v3.17.1 (2026/04/29)
- TMF 微型臺指補上
- Modal 點擊看 30 天走勢
- 期貨歷史累積 18 指標

### v3.17.0 (2026/04/28)
- 期貨情報新模組 futures.py
- TXF/MXF + TXO Call/Put 三法人

### v3.16.1 (2026/04/24)
- 個股追蹤三線比較圖

### v3.16.0 (2026/04/23)
- 配色系統統一 (買=紅 / 賣=綠 / 賺=紅 / 虧=綠)

### v3.15.x (2026/04/21-22)
- 產業分類資料層 (1965 檔)
- 強弱族群篩選

### v3.14.x (2026/04/22-28)
- workflow 拆分 (Daily Full + Margin Refresh)
- 7 重排程跨 14 小時 (解 GitHub Schedule 不可靠)

---

## 🎯 TAIFEX 涵蓋率盤點

### ✅ 已抓 (~25%, 83 欄位 100% 對齊)

#### 三大法人區分各期貨契約 (futContractsDateDown)
- TXF/MXF/TMF × 3 法人 × 4 欄位 = 36 欄

#### 選擇權三大法人 (callsAndPutsDateDown)
- TXO Call/Put × 3 法人 × 3 欄位 = 18 欄

#### 大額交易人未沖銷部位 (largeTraderFutDown)
- 前 5/10 大買賣 + 全市場 OI

#### P/C Ratio (pcRatio HTML)
- PCR-OI / PCR-成交量 / Put OI / Call OI

#### **v3.18 新增**:期貨各月份行情 (dlFutDataDown)
- TX 6 月份 × 9 欄 (OHLC + 漲跌/成交/結算/未沖銷)
- 跨月價差

#### **v3.18 新增**:夜盤三大法人 (futContractsDateAhDown)
- TXF/MXF/TMF × 3 法人 × 3 欄 (僅交易量沒 OI)

### ❌ TAIFEX 有但未抓 (~21 項)

#### ⭐⭐ 重要遺漏
- 三大法人總表 (totalTableDate) - HTML 動態頁,需 JS 模擬
- 臺指 VIX (vixMinNew) - JS 動態載入,HTML 表格空
- 各履約價 OI (Max Pain 來源) - 公開 API 無此資料

#### ⭐ 中等遺漏
- 選擇權各履約價 OI
- 選擇權 Delta 值
- 選擇權大額交易人
- 區分各選擇權契約三法人

#### 🟢 低優先 (用不到)
- 期貨流動性資訊 (3 種)
- 鉅額交易議價申報
- 期貨商交易量排行
- 每日外幣參考匯率
- 前 30 日成交資料

---

## 👤 用戶偏好 (DRwillychiu)

### 工作風格
- ✅ 嚴格按 SKILL 紀律 (不接受跳過驗證)
- ✅ 追求「最正確資訊不管工作量」
- ✅ 不喜歡一次改太多
- ✅ 喜歡按推薦組合開工 (套餐 A/B/C)
- ✅ 會自己測試並截圖回報
- ✅ 直球追問每個數字怎麼來
- ✅ 重視「實戰可用」不只「覺得自己很厲害」

### 溝通偏好
- ❌ 不要用 ask_user_input_v0 問問題
- ❌ 不要過度 emoji
- ❌ 不要過度建議休息 (除非真的紅燈)
- ✅ 喜歡看「鎖定目標 → 不偏離 → 完成才慶祝」

### 投入時數
- 平日:8h 可投入,但實際 4-5h 較健康
- 週末:10h 可投入,但實際 7-8h 較健康
- 紅燈警報:單日 9.5 小時 → 強制收工

### 重要規則 (用戶親自訂的)
1. **每次升版必更新 README** (4/29 訂)
2. **目標絕對不要偏離** (5/1 訂)
3. **收工 SOP**:
   - README + memory.md「當前工作焦點」加今日總結段
   - 最後一次 git commit + push
   - 確認 git status 完全乾淨
   - TodoWrite 全部 completed

---

## 🛠️ 開發 SKILL (已永久化)

| SKILL | 用途 |
|-------|------|
| `version-bump-protocol` | 升版號 + HOTFIX_GUIDE + README 必更新 + 自動檢查 |
| `api-debugging-triage` | 5 個 TAIFEX 踩雷系統性 debug |
| `three-files-sync` | futures + history + crawler + index 四檔同步 |
| `playwright-verification` | 13 tab + Modal + 截圖 + 零 JS 錯誤 |
| `api-crawler-checklist` | 動工前先測資料源 |

---

## ⚠️ 開發歷程教訓

### 通用教訓
1. **規劃要留白**:用戶 60h 可投入但實際 22h 健康
2. **任何計算過的數值都該加資料來源說明**
3. **不能假設 production 欄位名,要查 crawler.py 真實寫入**
4. **數據準確性必對齊官方來源**

### TAIFEX 5 個踩雷 (v3.17.0 累積)
1. OpenAPI 503 → 改用瀏覽器端點
2. 選擇權「買方」非「多方」(中文用詞陷阱)
3. 大額交易人用 TX 非 TXF (英文代碼差異)
4. 商品代碼有空格 (`'TX  '` 要 `.strip()`)
5. 月份過濾要排除 666666 (當月合約標記)

### v3.17.5 教訓
1. **PCR 計算邏輯不能用三法人 OI** (要用全市場)
2. **大額交易人用全部月份 999999** (TAIFEX 官網標準)

### v3.18 教訓
1. **夜盤 CSV 只有 9 欄** (沒 OI 只有交易量,因為夜盤不結算)
2. **三大法人總表 + VIX 是 JS 動態載入**,公開端點抓不到
3. **dlFutDataDown 端點完美**,給 commodity_id=TX 抓所有月份

### v3.16.1
- race condition 用 requestAnimationFrame 解決

### v3.15.1
- Playwright 本機資料舊不代表 bug

### v3.14.8
- GitHub schedule 不可靠 → 7 重排程防禦

### v3.14.7
- workflow stage + git pull --rebase 順序很重要

---

## 🔥 用戶健康紀律 (Claude 必遵守)

### 紅綠燈系統
| 累計時數 | 燈號 | Claude 行為 |
|---------|------|-----------|
| 0-4h | 🟢 | 全速衝刺 |
| 4-6h | 🟡 黃燈 | 提醒節制,不擋 |
| 6-8h | 🟠 橘燈 | 強烈建議收工,部分擋 |
| 8h+ | 🔴 紅燈 | 強制收工,拒絕加碼 |
| 9.5h+ | ⛔ 強制 | 完全擋,只接受 SOP 收工 |

### 拒絕加碼三鐵律
1. ❌ 「順便修一下 X」 → 寫進下版待辦
2. ❌ 「我突然想到 Y 也很重要」 → 寫進下版待辦
3. ❌ 「再 30 分鐘就好」 → 不接受

---

## 🚪 收工 SOP (用戶 5/1 訂)

```
▶ Step 1: 更新「當前工作焦點」
  - README.md 加版本歷程條目
  - memory.md 「📅 當前工作焦點」加今日總結
  - Last Updated 改今日

▶ Step 2: git commit + push
  Commit: feat(vX.Y): <主功能> + <次功能>
  
▶ Step 3: git status 乾淨
  ✅ working tree clean
  ✅ ahead/behind = 0

▶ Step 4: TodoWrite 全部 completed

▶ Step 5: SKILL 紀律自檢
  - 版號一致 (crawler.py × 2 + README × 2 = 4 處)
  - JS 語法 OK
  - Python 全 import OK
  - Playwright 13 tab + 零錯誤
```

---

## 📂 檔案位置

```
工作區 (Claude 環境):
  /home/claude/chip-radar-v3/         本機開發目錄
  /mnt/user-data/outputs/v<ver>/      交付物 (給用戶部署)
  /mnt/transcripts/                   歷史對話歸檔
  /tmp/                               暫存 (測試 JSON、Playwright JS)

GitHub Repo (用戶部署):
  README.md                           專案文件
  index.html                          前端
  crawler.py                          主爬蟲
  futures.py / branches.py / ...      模組
  skills/version-bump-protocol/       SKILL 紀律
  data/latest.json                    最新資料
  data/stock_history.json             30 天累積
  .github/workflows/                  自動排程
```

---

## 🎯 戰力進化軌跡

```
v3.6  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40/100 (基礎籌碼)
v3.10 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 55/100 (融資融券)
v3.14 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 65/100 (workflow 穩定)
v3.15 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 70/100 (產業分類)
v3.16 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 75/100 (視覺統一)
v3.17 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 85/100 (期貨情報 + 溫度計)
v3.18 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 90/100 (期貨行情面)
v3.19 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 94/100 (個股行情整合)

⬜ 還缺:
  - 主動推播 (v3.20)
  - 族群深度 (v3.21)
  - 主散對照 (v3.22)
  - 自動驗證 (v3.23)
```

---

**Chip Radar 是用戶實戰可用的台股籌碼工具,不是 demo 玩具。** 🎯📊
