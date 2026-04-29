# 📊 Chip Radar TW · 分點籌碼觀察站

> 自動化追蹤台股券商分點 + 期貨選擇權籌碼 + 法人動向的專業級個人看板  
> **當前版本**：v3.17.1-patch1 ｜ **網站**：https://drwillychiu.github.io/CHIP_RADAR_TW/

---

## 🎯 專案定位

```
Chip Radar 是「台股籌碼分析專家」
─────────────────────────────────────
不是宏觀晨報、不是美股工具、不是 Podcast 整合
專注做好一件事:把台股每日籌碼數據,變成你能秒判讀的儀表板
```

---

## ✨ 核心功能 (13 個 Tab)

### 📊 即時籌碼分析
| Tab | 功能 | 資料來源 |
|-----|------|---------|
| 01 | 🌅 今日三視角 | 49 分點當沖/隔日沖/波段 |
| 02 | 🔥 共買榜 | 多分點同步買進的標的 |
| 03 | 📊 分點動態 | 49 個券商分點即時動向 |
| 04 | 🏆 累積排行 | N 天累積買超排行 |
| 05 | 👤 高手合併視圖 | 25 位 master 模式比對 |
| 06 | 🏛️ 三大法人 | 外資/投信/自營商買賣超 |

### 🎯 期貨選擇權 (v3.17 新增)
| Tab | 功能 | 資料來源 |
|-----|------|---------|
| 07 | 🎯 期貨情報 | TAIFEX 完整籌碼 |

包含：
- 💎 外資等效大台 (TXF + MXF/4 + TMF/20)
- 👥 散戶小台反指標
- 📊 P/C Ratio (選擇權情緒)
- 🎲 外資選擇權傾向
- 🏛️ 三大法人 TXF/MXF/**TMF** 完整明細
- 🎯 十大交易人集中度

### 📈 進階分析
| Tab | 功能 | 資料來源 |
|-----|------|---------|
| 08 | 💰 融資融券 | TWSE + HiStock 雙源驗證 |
| 09 | 🔥 漲停狙擊 | 漲停板分點分析 |
| 10 | 📉 個股追蹤 | 個股 + 產業 + 大盤 三線圖 |
| 11 | 🎓 高手 master | 25 位精選分點配對 |
| 12 | 📋 操作日報 | 每日總結報告 |
| 13 | ⭐ 自選股 | 個人關注清單 |

---

## 🏗️ 技術架構

### 後端 (10 個 Python 模組)
```
crawler.py            主爬蟲 (~95KB) 整合所有資料
├ branches.py         49 分點抓取邏輯
├ institutional.py    三大法人爬蟲
├ margin.py           融資融券 (TWSE + HiStock)
├ reports.py          每日報告產生
├ market_classifier.py  市場分類 (上市/上櫃/ETF)
├ histock_verifier.py 融資融券交叉驗證
├ industry_classifier.py  產業分類 (1965 檔)
├ history.py          歷史累積 (含期貨)
└ futures.py          TAIFEX 期貨/選擇權 (~480 行)
```

### 前端
```
index.html (~340KB)
├ HTML/CSS/JS 單檔
├ Chart.js 4.4.1
├ AES-256-GCM + PBKDF2-SHA256 加密解鎖
└ 13 個 tab + 多個 Modal
```

### 自動化排程 (GitHub Actions)
```
1. Daily Full Crawl (20:00)        每天主爬蟲, 抓全部
2. Margin Refresh (7 重防禦)       融資融券補抓
   • 22:30 / 23:30 (週一-五)
   • 00:30 / 02:00 (週二-六)
   • 08:00 / 09:00 / 12:00 (週二-六)
```

---

## 📈 版本歷程

### v3.17.x 期貨情報系列
- **v3.17.1-patch1** (2026/04/29) 🆕
  - 結算日時區 bug 修正
  - 十大交易人資料來源透明說明
- **v3.17.1** (2026/04/29)
  - 期貨歷史累積 (history.py 擴充)
  - 4 個 hero card 點擊跳出 30 天走勢 Modal
  - TMF 微型台指完整明細表
  - 期貨 tab 時間 banner + 結算日倒數
- **v3.17.0** (2026/04/28)
  - 全新「期貨情報 tab」
  - 整合 TXF/MXF/TMF 三大法人 + TXO 選擇權 + 十大交易人
  - 今日三視角加「外資期現貨對照」面板

### v3.16.x 視覺與走勢
- **v3.16.1** (2026/04/24)
  - 個股追蹤三線比較圖 (個股 vs 產業 vs 大盤)
  - 5/10/20/30 天切換
- **v3.16.0** (2026/04/23)
  - 配色系統統一 (買=紅 / 賣=綠 / 賺=紅 / 虧=綠)
  - 17 處配色違和修正

### v3.15.x 產業分類
- **v3.15.1** (2026/04/22)
  - 產業 chip 顯示在個股卡
  - 強弱族群篩選
  - Modal 加入產業濾鏡
- **v3.15.0** (2026/04/21)
  - 產業分類資料層 (TWSE 1082 + TPEx 883 = 1965 檔)

### v3.14.x 工作流穩定化
- **v3.14.8** (2026/04/28)
  - Margin Refresh 7 重排程防禦
  - 解決 GitHub Schedule 不可靠問題
- **v3.14.7** (2026/04/24)
  - workflow 拆分 (Daily Full + Margin Refresh)
  - git pull --rebase 順序修復
- **v3.14.5** (2026/04/22)
  - 情緒信號 Modal (聰明錢進/出/散戶追漲/軋空潛力)
- **v3.14.4** (2026/04/22)
  - 融資融券日期驗證 (T-0 / T-1 自動標示)

---

## 🚀 快速部署 (新手 15 分鐘)

### Step 1：Fork 或 Clone Repository
```bash
# 方法 A: Fork (推薦,可獲得後續更新)
前往 https://github.com/DRwillychiu/CHIP_RADAR_TW
點右上角「Fork」

# 方法 B: 全新 Clone
git clone https://github.com/DRwillychiu/CHIP_RADAR_TW.git
```

### Step 2：設定 Repository Secret
GitHub Repo → Settings → Secrets and variables → Actions
新增 secret：
```
Name:  CHIP_RADAR_PASSWORD
Value: 自設密碼 (例如 testpass123)
```

### Step 3：開啟 GitHub Pages
GitHub Repo → Settings → Pages
- Source: Deploy from a branch
- Branch: `main` / `(root)`
- Save

等 1-2 分鐘,網址會變成: `https://YOUR_USERNAME.github.io/CHIP_RADAR_TW/`

### Step 4：授權 Actions 寫入
GitHub Repo → Settings → Actions → General
- Workflow permissions → ✅ **Read and write permissions**
- ✅ Allow GitHub Actions to create and approve pull requests

### Step 5：手動執行第一次爬蟲
GitHub Repo → Actions → `1. Daily Full Crawl (20:00)` → **Run workflow**
等 5-8 分鐘,看到綠色 ✅ 即可。

### Step 6：開啟網站
打開 `https://YOUR_USERNAME.github.io/CHIP_RADAR_TW/`
輸入 Step 2 的密碼解鎖。

---

## 📅 自動執行時程

| Workflow | 時段 | 抓什麼 |
|----------|------|-------|
| Daily Full Crawl | 每日 20:00 (週一-五) | 全部資料 (含期貨) |
| Margin Refresh | 22:30 / 23:30 / 00:30 / 02:00 / 08:00 / 09:00 / 12:00 | 融資融券補抓 (7 重防禦) |

**TAIFEX 公告時程**：
- 15:00 - 三大法人期貨/選擇權公告
- 15:30 - 大額交易人 (前 5/10 大) 公告
- 17:00 - 結算價、結算公告
- Chip Radar 在 20:00 抓穩定版

---

## 🎨 自訂分點 / Master / 自選股

### 在網站直接改 (容易,只影響自己瀏覽器)
打開網站 → 分點動態 / 個股追蹤 → 點⭐ 加入收藏

### 修改原始碼 (改變實際爬取)
```python
# crawler.py 的 BRANCHES 陣列
BRANCHES = [
    {"id": "1234", "name": "你的分點"},
    # ...
]
```

---

## 🛠️ 常見問題

### Q: 為什麼網站打開是空的？
A: 確認 GitHub Pages 已 Deploy + 至少跑過一次爬蟲 (Step 5)。

### Q: 資料什麼時候更新？
A: 
- **分點/法人**: 每天 20:00 (週一-五)
- **融資融券**: 22:30 後 (TWSE 公告完成)
- **期貨/選擇權**: 跟主爬蟲同步 (20:00)
- **隔日早上 8:00 前完整更新**

### Q: 可以查歷史資料嗎？
A: 可以！上方「查看日期」下拉選單可看過去 30 天 (新版),或直接從 GitHub `data/` 資料夾下載 JSON。

### Q: 期貨資料怎麼算的？可信度？
A: 100% TAIFEX 官方資料,我們只做除法。
詳見「07 期貨情報 tab」的資料來源說明條。

### Q: 我想自架,但不想被 Google 找到？
A: GitHub Pages 預設不會被搜尋,但若要更私密:
1. 把 repo 設為 Private (但 GitHub Pages 需要 GitHub Pro)
2. 或改用密碼解鎖 (本專案已內建)

---

## 📁 檔案結構

```
CHIP_RADAR_TW/
├── README.md                  本檔案
├── index.html                 前端 (340KB, 含加密邏輯)
├── crawler.py                 主爬蟲 (~95KB)
├── branches.py                49 分點定義
├── institutional.py           三大法人
├── margin.py                  融資融券
├── reports.py                 每日報告
├── market_classifier.py       市場分類
├── histock_verifier.py        HiStock 驗證
├── industry_classifier.py     產業分類
├── history.py                 歷史累積
├── futures.py                 TAIFEX 期貨/選擇權 (v3.17 新)
├── .github/workflows/
│   ├── daily-full.yml         每日主爬蟲
│   └── margin-refresh.yml     7 重融資融券補抓
└── data/                      自動產生的資料
    ├── latest.json            最新一日 (加密)
    ├── 20260428.json          歷史日期檔
    ├── 20260427.json
    └── stock_history.json     30 天累積 (含期貨歷史)
```

---

## 🔄 後續開發路線圖

### 短期 (本月內)
- ⏳ v3.18 Discord/Line 推播通知
- ⏳ 台股市場溫度計 (5 個訊號儀表板)

### 中期 (5/4-5/20)
- ⏳ v3.19 台股族群深度頁
- ⏳ v3.20 主力 vs 散戶雙視角分析

### 長期
- ⏳ Max Pain (需研究第三方資料源)
- ⏳ 立委持股追蹤
- ⏳ 多股比較圖

---

## 📊 數據規模

| 維度 | 規模 |
|------|------|
| 監控分點 | 49 個 |
| Master 高手 | 25 位 |
| 抓取個股 | 上市 1082 + 上櫃 883 = **1965 檔** |
| 期貨商品 | TXF (大台) + MXF (小台) + TMF (微台) |
| 選擇權 | TXO Call + Put 三大法人 |
| 累積歷史 | 30 天循環 (含期貨) |
| Tab 數量 | 13 個 |

---

## ⚠️ 免責聲明

本工具僅供學習研究之用,所有資料皆來自公開來源 (TWSE/TPEx/TAIFEX/HiStock):
- 不構成任何投資建議
- 不對資料準確性負完全責任
- 投資有風險,盈虧自負

---

## 📜 授權

MIT License - 自由使用、修改、分享。

---

## 🙏 致謝

- **TWSE** 證券交易所 - 分點 + 法人資料
- **TPEx** 櫃買中心 - 上櫃資料
- **TAIFEX** 期貨交易所 - 期貨選擇權資料
- **HiStock 嗨投資** - 融資融券交叉驗證

---

**Chip Radar TW · 90% 戰力 · 持續演進中** 📊🎯

*Last Updated: 2026/04/29 · v3.17.1-patch1*
