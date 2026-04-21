# 📊 分點籌碼觀察站 · Chip Radar

自動化追蹤台股券商分點每日買賣超的個人看板。

**核心特色：**
- ✅ 每天下午 5 點 GitHub Actions 自動爬取資料，**零維護**
- ✅ 每個分點抓取前 30 檔買賣超（比手動記錄多 3 倍資訊量）
- ✅ 共買榜、分點動態、個股追蹤、高手偏好，四大分析功能
- ✅ 可切換「全部分點 / 僅關注分點」兩種檢視模式
- ✅ 完全免費、完全自動、手機電腦都能看

---

## 🚀 快速部署（新手完整教學）

照著做，15 分鐘完成部署。

### Step 1：註冊 GitHub 帳號（3 分鐘）

1. 前往 <https://github.com/signup>
2. 輸入 email、設定密碼、帳號名稱（後續網址會用到，請取簡短的，例如 `tomchen`）
3. 驗證 email（收信點確認連結）

### Step 2：建立新的 Repository（2 分鐘）

1. 登入後，點右上角 `+` → `New repository`
2. 填寫：
   - **Repository name**: `chip-radar`（或您喜歡的名字）
   - **Public**：✅ 勾選（Private 無法用 GitHub Pages 免費版）
   - 其他保持預設
3. 點最下方 `Create repository`

### Step 3：上傳檔案（5 分鐘）

1. 下載本資料夾所有檔案到您的電腦（保持資料夾結構）：
   ```
   chip-radar/
   ├── .github/
   │   └── workflows/
   │       └── daily-crawl.yml
   ├── data/
   │   ├── index.json
   │   ├── latest.json
   │   └── 20260421.json（範例資料）
   ├── crawler.py
   ├── index.html
   ├── requirements.txt
   └── README.md
   ```

2. 在 repo 頁面點 `uploading an existing file`（藍字連結）

3. 把整個 `chip-radar` 資料夾「**內容**」拖拉進去（不要把外層資料夾一起拉，要拉裡面的檔案）
   - 特別注意：`.github` 資料夾**一定要上傳**
   - 如果看不到 `.github`（macOS 會隱藏），在 Finder 按 `Cmd+Shift+.` 顯示隱藏檔

4. 最下方 Commit message 填 `Initial setup`，點 `Commit changes`

### Step 4：開啟 GitHub Pages（2 分鐘）

1. 在 repo 頁面點 `Settings`（右上角齒輪旁）
2. 左側選單找到 `Pages`
3. 在 `Source` 選 `Deploy from a branch`
4. 在 `Branch` 選 `main` + `/(root)`，按 `Save`
5. 等 1~2 分鐘，畫面上方會出現：
   ```
   ✓ Your site is live at https://你的帳號.github.io/chip-radar/
   ```
6. **點那個網址就是您的專屬網站！** 📱🖥️

### Step 5：授權 Actions 寫入（1 分鐘）

這一步很重要，否則爬蟲無法自動更新資料到 repo。

1. 一樣在 `Settings`
2. 左側選單 → `Actions` → `General`
3. 拉到最下面 `Workflow permissions`
4. 選 `Read and write permissions`
5. 點 `Save`

### Step 6：手動執行一次測試（2 分鐘）

1. 點 repo 頁面上方的 `Actions` 分頁
2. 左側選 `Daily Chip Data Crawl`
3. 右側點 `Run workflow` → 再點綠色的 `Run workflow` 按鈕
4. 等 3~5 分鐘，看到綠色 ✓ 就成功了
5. 回到首頁會看到 data 資料夾有新的 json 檔案
6. 重新整理您的網站，就看到最新資料了 🎉

---

## 📅 自動執行排程

設定完成後，之後系統會在**每個交易日台灣時間下午 5 點自動執行**（cron: `0 9 * * 1-5`，UTC 09:00）。

您不需要做任何事，**每天打開網站都是最新資料**。

---

## 🎨 自訂關注分點

### 方法 A：在網站上直接改（容易，只影響自己瀏覽器）

打開網站 → 第 5 個分頁「關注設定」→ 點選/取消分點。設定會存在您瀏覽器。

### 方法 B：修改 `crawler.py`（改變實際爬取的分點）

如果您只想爬某些分點、或要新增分點，修改 `crawler.py` 檔案最上方的 `WATCHED_BRANCHES` 列表：

```python
WATCHED_BRANCHES = [
    {"code": "9B25", "name": "元富-台中",     "master": "民哥"},
    {"code": "9666", "name": "富邦-南屯",     "master": "富邦南屯"},
    # ...在這裡增減
]
```

**分點代號怎麼查？** 打開富邦頁面 <https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm>，下拉選單選擇分點後，網址列會顯示 `?a=xxxx&b=xxxx`，這個 xxxx 就是代號。

修改後存檔，上傳（或用 GitHub 網頁版編輯），下次自動爬蟲就會用新清單。

---

## 🛠️ 常見問題

### Q：為什麼我的網站打開是空的？

**A：** 首次部署後，需要手動觸發一次爬蟲（Step 6）。之後每個交易日會自動執行。

### Q：資料什麼時候會更新？

**A：** 每個交易日（週一到週五）下午 5 點台灣時間。如果那天沒交易（國定假日），該日會沒更新，屬正常現象。

### Q：我可以查歷史資料嗎？

**A：** 可以。網站右上角有日期選擇器，列出所有已爬取的日期。資料會一直累積在 `data/` 資料夾。

### Q：可以分享網站給朋友嗎？

**A：** 可以，直接給他們網址 `https://你的帳號.github.io/chip-radar/`。但關注設定是各自的瀏覽器儲存，不會共用。

### Q：如果爬蟲失敗怎麼辦？

**A：** 到 `Actions` 分頁看紅色 ✗ 的執行紀錄，點進去看錯誤訊息。常見原因：
- 富邦網站臨時故障 → 等下次自動執行
- 被富邦暫時封鎖 IP → 等 24 小時會恢復
- 分點代號過時 → 修改 `crawler.py` 移除無效代號

### Q：GitHub Actions 免費額度夠用嗎？

**A：** GitHub 提供個人戶每月 2000 分鐘免費額度。這個爬蟲每次跑 3-5 分鐘，一個月 20 個交易日 × 5 分鐘 = 100 分鐘，**遠低於免費額度**。

### Q：我想讓網站更私密，不要被 Google 搜尋到？

**A：** 
- 方法 1：repo 設為 Private，但 GitHub Pages 免費版會變成無法用
- 方法 2：保持 Public，但在 `index.html` 加 `<meta name="robots" content="noindex">`（已內建）
- 方法 3：在網站加簡單的密碼（需請工程師協助）

---

## 📁 檔案結構說明

```
chip-radar/
├── .github/
│   └── workflows/
│       └── daily-crawl.yml      # GitHub Actions 排程檔
├── data/                         # 資料夾（爬蟲產出）
│   ├── index.json               # 日期索引
│   ├── latest.json              # 最新資料（網站主要讀取這個）
│   └── YYYYMMDD.json            # 每日歷史檔
├── crawler.py                    # Python 爬蟲（自動執行）
├── index.html                    # 網站主頁
├── requirements.txt              # Python 套件清單
└── README.md                     # 本說明文件
```

---

## 🔄 未來擴充建議

如果您未來想擴展功能：

- **📧 Email 通知**：在爬蟲結束後自動寄 email 提醒今日重點股
- **📈 加入股價**：結合 TWSE API 顯示當日漲跌幅
- **🔔 共買警示**：某股票被 ≥ 5 個分點共買時發 LINE 通知
- **📊 趨勢圖**：畫出某分點近 30 日累計進出熱區

這些都是相對容易新增的功能，有興趣可以再請工程師幫忙。

---

## ⚠️ 免責聲明

本工具提供的資料來自富邦證券公開網頁，僅供個人研究參考，不構成任何投資建議。依此資料交易造成之損失需自行承擔。

---

**Made with ❤️ for Taiwan stock market chip analysis**
