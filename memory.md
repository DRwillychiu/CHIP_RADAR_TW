# 🧠 Chip Radar TW · Memory

> 這個檔案是 Chip Radar 專案的**完整結構化記憶系統**，給未來 Claude 對話讀取使用。
> 每次升版必更新「## 📅 當前工作焦點」段落。

**最後更新**: 2026/05/14 深夜 · v3.29.0 部署完成 (**Signal Engine MVP** — actionable signals + backtest-derived weights)
**累計戰力**: 99.995/100 (設計哲學翻轉: raw data 展示 → actionable 答案)

---

## 🔪 v3.29+ Backlog 大整理 (2026-05-14 破壞式 review)

**KILLED**(從 backlog 移除,理由如下):

| 項目 | 砍掉理由 |
|---|---|
| ❌ L2 雙源交叉比對 (TWSE + MIS) | v3.27.3 stale detect + 強制全量 MIS fallback 已 100% 救援 5/11-5/13 連 3 天,L2 純錦上添花。實測零次需要。 |
| ❌ T-d 過去 7 天信號觸發時間軸 | Backtest 上線後 hit rate 分析更深,7 天 visual 多餘。 |
| ❌ M-c 30 天主散背離趨勢 chart | v3.25 已有「30 天溫度趨勢 chart」涵蓋,重複建設;且 user 4 天 review 都沒打開過 chart。 |
| ❌ Excel γ 漲停股 2 欄 (漲停買進均價 + 距漲停價差%) | sniper 入選個股本就接近漲停,兩欄資訊量 ≈ 0,且老闆要的是「蔣承翰買 11 檔漲停」事實,不是價差細節。 |

**PARKED**(暫時擱置,等觸發條件):

| 項目 | 觸發條件 |
|---|---|
| ⏸️ M-d 主散背離 → alerts.py 推播 | 等 alerts.py 復活 (Discord/Slack/Line/email 任一) |
| ⏸️ lot_source / quote_stale / limit_up_source UI 視覺化 | 等 user 反饋是否需要透明度 |
| ⏸️ 新上市股前 5 天 uncapped 邊界 | 等真踩到誤判 case |

**ACTIVE backlog (v3.29+)**:

| 優先序 | 項目 | 預估 |
|---|---|---|
| 🔴 高 | **latest.json 瘦身** (10.49 MB → ~4 MB gzip) | 1-2h |
| 🔴 高 | **Backtest 補洞**:寫 `backtester.py` 拉 TWSE 歷史 1 年資料,模擬 7 信號 + sniper,算 hit rate (取代 T-c 等 30 天累積) | 4-6h |
| 🟡 中 | **Signal Engine**:後端 build「明日 actionable signals」+ 信心區間,砍 7 信號自己解讀。**需 Backtest 結果做 prerequisite** | 8-12h |
| 🟢 降級 | ~~T-c 校準~~:Backtest 上線後 obsolete | (廢棄) |

**設計哲學變更**:
- **過去 4 天 90% 力氣花在 data infrastructure 防禦** (audit / fallback / verify),沒 proportional 提升 user value
- **轉向「資料 → 決策」**:不再讓 user 自己看 7 信號拼湊,改成 actionable signal + 信心區間
- **砍 incremental visualization** (T-d/M-c/Excel γ),投資 backtest + signal engine

---

## 📅 當前工作焦點

### 進行中 - 一週優化規劃 (5/4 - 5/10)
- ✅ **Day 1 (5/5): v3.21 全資料源完整審計** ← 完成
- ✅ **Day 2 (5/8): v3.22 老闆版 Excel 日報** ← 完成 (插隊取代「時效性儀表板」)
- ✅ **Day 3 (5/8): v3.23 Excel template-aligned + keepalive** ← 完成
- ✅ **Day 4 (5/9): v3.24 Excel 嚴格模仿手動版「分點觀察」** ← 完成
- ✅ **Day 5 (5/9): v3.25 溫度計 v2 + 主散對照 + 30 天趨勢** ← 完成 (提前 1 日)
- ✅ **Day 6 (5/10): v3.26 Excel 風格分流 (隔日沖/當沖 → 漲停股)** ← 完成
- ✅ **Day 6 (5/10): v3.26.1 hotfix 排程自動化修復** ← 完成
- ✅ **Day 6 (5/10): v3.27 籌碼溫度計 7 信號 (T-c 完成)** ← 完成
- ✅ **Day 6 (5/10): v3.27.1 v3.28 校準前置工程** ← 完成
- ✅ **Day 6 (5/10): v3.27.2 高價股盲點修補 (user 主動發現)** ← 完成
- ✅ **Day 7 (5/11): v3.27.3 TWSE OpenAPI stale 偵測 (user 主動要求完整修)** ← 完成

### Day 7 v3.27.3 成果 (2026/05/11 21:50)
- 🐛 **問題** (用戶要求交叉驗證 5/11 Excel 可信度時發現):
  - 5/11 21:30 TWSE OpenAPI STOCK_DAY_ALL 還在 publish 5/8 資料
  - 同時 MI_INDEX 也卡 5/8 資料
  - chip_radar 沒檢查回傳 Date 欄位,直接全盤接收
  - 結果: stock_history.json 5/11 entry 跟 5/8 完全一樣 (2330=2290 / TAIEX=41603.94)
  - Excel 個股 close/change_pct/is_limit_up 全部錯
  - 影響:v3.26 風格分流的「漲停股」分類錯誤,v3.27.2 高價股反推用錯誤 close
- 🔍 **根因**:TWSE OpenAPI 端點延遲 publish。chip_radar 缺日期校驗
- 🔧 **修法 (3 層防護)**:
  1. **fetch_twse_daily_quotes** + **fetch_tpex_daily_quotes** + **_fetch_taiex_index**
     - 加 `expected_trade_date` 參數
     - 比對回傳 Date 欄位 (ROC 民國格式)
     - 不符合 → 回傳空 dict / None,觸發 fallback
  2. **fetch_all_public_data** 偵測 stale 後,**強制全量 MIS fallback**:
     - 不只補缺檔,而是把所有 priority_codes 都用 MIS 重抓
     - 因為 MIS API (`mis.twse.com.tw/stock/api/getStockInfo.jsp`) 是即時報價,不受 OpenAPI 延遲影響
  3. **crawler.py audit summary**:
     - 每個 stock 多 `quote_date` + `quote_stale` 欄位
     - main 流程列印「fresh=X / stale=Y / missing=Z, source 分布: twse=a, mis_tse=b, tpex=c」
     - 仍有 stale → 印 🚨 警告
- 🛠️ **helper 新增**:`_yyyymmdd_to_roc()` 西元↔民國轉換(institutional.py + history.py 各一份)
- 📋 **本地測試 11/11 PASS** (test_v3273_stale_detect.py):
  - 西元↔民國轉換 6 case
  - TWSE/TPEx stale → 空 dict ✅
  - TWSE/TPEx fresh → 正常解析 + quote_date 欄位 ✅
  - MI_INDEX stale → None ✅
  - MI_INDEX fresh → 正常 + quote_date ✅
  - backward compat: 不傳 expected_trade_date → 跟以前行為一樣 ✅
- 🛡️ **回歸**: v3.27/v3.27.1/v3.27.2 三個既有測試套件全 PASS
- ⏳ **後續觀察**:
  - 5/12 (二) 21:17 排程 fire 時 → log 應印「quote_date=1150512 fresh」
  - 若 OpenAPI 還卡舊 → 自動 fallback MIS,log 印 🚨 + source 分布 mis_tse 居多
- 🟢 戰力 99.95 → 99.97/100

### Day 6/7 完整成果回顧
| 版本 | 修什麼 | Commit |
|---|---|---|
| v3.26 | Excel 風格分流 | 1d56c79 |
| v3.26.1 | 排程 cron 移時段 + 兜底 + notice | 0d18ab3 |
| v3.27 | 籌碼溫度計 7 信號 | 7caa8cb |
| v3.27.1 | 校準資料管線 | c80bc79 |
| v3.27.2 | 高價股 lot/amt 反推 | f4dbf12 |
| v3.27.3 | TWSE OpenAPI stale 偵測 | (本次) |

### Day 6 v3.27.2 成果 (2026/05/10 21:40)
- 🐛 **問題** (用戶手動 review Excel 截圖發現):
  - 國票-安和 (張濬安/航海王 swing master) 779Z 分點顯示
  - 創意(3443) 買進 0 張 / 買進金額 54,376 萬 / 買均 0.00 ← 嚴重誤導
  - 緯穎/台積電 同樣的「0 張 + 幾億金額」
- 🔍 **根因**:不是 bug,是 TWSE 公開資料結構限制
  - TWSE 分點頁面對每分點每日只 publish 兩張 Top 15 排行:
    - 金額榜 (c=B): Top 15 by 買賣超金額
    - 張數榜 (c=E): Top 15 by 買賣超張數
  - 創意(5210元)/緯穎(5200元) 等天價股,5 億金額也才 ~100 張,張數擠不進 Top 15
  - crawler.py L533 註解早已說明這個限制
- 🔧 **修法**:在 quote 注入點 (crawler.py L1940 區域) 加反推
  - buy_lot==0 + buy_amt>0 + close>0 → `buy_lot = round(buy_amt / close)`, `buy_avg = close`
  - sell side 同
  - 反向 case: lot>0 + amt==0 + close>0 → `buy_amt = lot * close`
  - 加 `lot_source: "estimated_from_close"` 旗標保留誠實
  - 重算 net_amt/net_lot 保持一致
- 📋 **本地驗證 6/6 PASS** (test_v3272_lot_estimate.py):
  - 創意 close=5210 amt_K=543760 → lot=104 ✅ (截圖反推 104)
  - 緯穎 close=5200 amt_K=89550 → lot=17 ✅
  - 台積電 close=2290 amt_K=124460 → lot=54 ✅
  - 南亞科/世界 已有真實 lot → 不誤動 ✅
  - 群創 close=32.17 lot=3559 (amt 漏) → 反推 amt=114,493 仟元 = 11,449 萬 ✅
- 🌐 **影響範圍** (一次到位): Excel + 全部 13 個 tab 都會受惠
  - swing master (張濬安/林滄海/陳族元/強森) 招牌的高價股部位現在資料完整
  - 隔日沖 master 的漲停股 (本來就在 Top 15 不太會缺) 影響小
- ⏳ 5/11 跑完後驗證:打開 Excel 看 779Z 創意/緯穎/台積電 那 3 行張數是否變 104/17/54
- 🟢 戰力 99.92 → 99.95/100

### v3.27.x 已知未完成 (v3.28+)
- ⏳ **T-c 校準**:資料累積到 30 天後跑 signal_audit.py,人工 review 後調 TEMP_THRESHOLDS
- ⏳ **T-d** / **M-c** / **M-d** (見前面紀錄)
- ⏳ **Excel γ**:漲停股加「漲停買進均價」「距漲停價差%」2 欄
- ⏳ **lot_source 旗標前端視覺化**:Excel/網站可考慮對 estimated 資料加 ~ 符號或 tooltip

### Day 6 v3.27.1 成果 (校準前置, 2026/05/10)
- 🎯 **動機**:v3.27 的 7 信號閾值是初版,需要實戰資料校準。但目前 `temp_history.json` 沒存 raw value 也沒存次日報酬 → 校準無法進行。先建好資料管線
- 🆕 **temp_history.json 結構升級** (backward compat):
  - 每個 signal 多 `value` field (foreign_net=15000 之類,持久化原始數值)
  - 每個 entry 多 `taiex_index` + `taiex_change_pct` (從 stock_history.json 的 market 區段讀)
  - 每個 entry 多 `next_day_change_pct` placeholder,**隔天 crawl 自動回填**
  - max_days 30 → 60 (校準窗口)
  - 加 `_calibration_meta` block 含閾值快照、min_days_for_calibration=30、ideal=60
- 🆕 **signal_audit.py 新工具**:
  - 用法: `python signal_audit.py`
  - 印 4 段報告: 累積狀況進度條 / 信號×level 分布 / 預測力評估 (hit rate) / 校準建議
  - 累積 < 30 天: 印「還差 X 天」,跳過 hit rate 分析
  - 累積 ≥ 30 天: 對每個 (signal, level) 算次日報酬 hit rate (預期方向 vs 實際),hit rate < 45% 標 ❌ 並建議檢視
  - 只「印報告」,不改任何閾值 — 校準仍須人工 review
- 🆕 **test_signal_audit.py 回歸測試**:
  - 生成 35 天 fixture (含強相關信號 + 弱相關控制組)
  - 驗證腳本正確抓出 hit rate 強弱 (PASS)
- 🐛 *未發現新 bug*
- ⏳ **資料累積期**: 從 5/11 (週一) 開始,每天 v3.27.1 crawl 會自動累積一個 entry + 回填前日次日報酬
  - 5/11 (Mon): 第一個 v3.27.1 entry, 5/8 entry 被回填 next_day_change_pct
  - 約 5 週後 (~6/15) 累積到 30 天 → 第一次校準
  - 約 11 週後 (~7/25) 累積到 60 天 → 信心校準
- 🟢 戰力 99.9 → 99.92/100

### Day 6 v3.27 成果 (2026/05/10)
- 🎯 **T-c**: 籌碼溫度計從 5 信號擴成 **7 信號**(memory.md v3.27+ TODO 第 1 項完成)
- 🆕 **信號 6 法人共識** (institutional_consensus):
  - 外資 + 投信 同向 + 雙方各自量達標 → 共識(極端);只同向 → bull/bear;一買一賣 → neutral
  - 閾值: 外資 ±30K張 / 投信 ±3K張 (v3.27 初版,待回測)
  - 哲學: 加總會被外資吃掉,雙條件確保真共識而非外資單邊
- 🆕 **信號 7 結算日壓力** (settlement_pressure):
  - 距結算日(每月第三個週三)距離 × 外資期貨等效大台 OI
  - 結算當日±1 + 外資深空 → extreme-bull (反彈訊號);深多 → extreme-bear (回檔)
  - 結算週(±3) 弱反指標 / 非結算週退化為 neutral 不污染溫度計
  - 閾值: ±20K (結算日±1) / ±10K (結算週) (v3.27 初版,待回測)
- 🔧 **TEMP_THRESHOLDS** module-level dict 統一管理 7 信號閾值,標記 `⚠️ pending backtest calibration` 註記
- 🔧 `_days_to_settlement(date)` helper: 上/本/下月候選,過去結算日只保留 ≤ 3 天餘波,取絕對值最小
- 🔧 `compute_chip_temperature(raw_output, trade_date)` 改簽名 (新加 trade_date 參數)
- 🔧 前端 `renderChipTemperature()` 同步加 sig6/sig7 + 同樣的結算日演算法
- 📋 **21/21 本地測試 PASS** (7 結算日距離 + 6 法人共識 + 8 結算日壓力 邊界 case)
- 🐛 **修一個 bug**: 結算日演算法原本 (本月+上月/下月) 二候選會在 6/1 case 誤判 -12 (取 5/20 過去結算)→ 改三候選 + 過去結算只保留 -3 天內 → 正確 +16
- ⏳ **v3.28+ 待辦** (memory 標記):
  - 收集 30-60 個交易日 (score, 次日漲跌) 對應,統計各區段 hit rate
  - 若極端區段預測力差 → 收緊閾值
  - 若中性區段佔比過高(例如 > 60%)→ 拉開
  - 預期 v3.28 用統計資料校準 7 個 TEMP_THRESHOLDS 各值
- 🟢 戰力 99.85 → 99.9/100

### v3.27 已知未完成 (滾下一輪 / v3.28+)
- ⏳ **T-c 校準**:用 30-60 個交易日資料回測 TEMP_THRESHOLDS 各值
- ⏳ **T-d**: 過去 7 天信號觸發時間軸
- ⏳ **M-c**: 30 天主散背離趨勢 chart
- ⏳ **M-d**: 主散背離 → alerts.py 推播
- ⏳ **Excel γ**: 漲停股加「漲停買進均價」「距漲停價差%」2 欄

### Day 6 Hotfix 成果 (v3.26.1, 2026/05/10)
- 🎯 **問題**:Daily Full Crawl 自動排程實際延遲 1-2 小時(5/7 延遲 2h 03m, 5/8 延遲 1h 29m),用戶每天都得手動觸發
- 🔍 **根因**:cron `0 12 * * 1-5` 撞 GitHub 整點塞車(GitHub 官方明示 "high load times include the start of every hour")
- 🔧 **修復 a**:cron 改成 `17 13 * * 1-5` (TW 21:17),奇怪分鐘避開整點塞車
- 🔧 **修復 b**:加 `37 14 * * 1-5` (TW 22:37) 兜底排程,主排程被吃掉時補,no-op 自動 dedup 零成本
- 🔧 **修復 c**:沒變動的執行改用 `::notice::` GitHub 級別,Actions 頁能一眼分出「真跑了沒新資料」vs「根本沒跑」
- ⏳ 待觀察:5/11 (週一) 21:17 是否準時 fire(預期延遲 < 5min)
- 🟢 戰力 99.8 → 99.85/100

### Day 6 重大成果 (v3.26, 2026/05/10)
- 🎯 **問題**:v3.24 Excel 對所有 master 用同一套「Top 10 by 買超」邏輯,隔日沖/當沖 master 在涨停狙击 tab 抓到的漲停股資料完全沒進到 Excel
- 🔧 `excel_report.py` 加 `_is_sniper_master()` + `SNIPER_STYLES = {next_day_flipper, day_trader}` (4 位 sniper:蔣承翰/迷你哥/Tradow/巨人傑)
- 🔧 `_top_stocks_for_branch()` 加 `sniper_mode` 參數,過濾 `is_limit_up=True`
- 🆕 從 `branches.py` 讀 `MASTER_STYLES` 作為單一真實來源
- 🛡️ sniper master 沒搶任何漲停 → 整 10 列空白 (不 fallback,維持風格純度)
- 🛡️ 視覺格式 100% 跟手動版一致 (字型/欄寬/合併儲存格不變)
- 📋 本地測試 PASS:民哥(swing) 3 檔全留 / 蔣承翰(sniper) 濾掉台積電留 2 漲停 / 迷你哥(sniper) 0 漲停全空白
- 🟢 戰力 99.7 → 99.8/100

### Day 5 重大成果 (v3.25, 2026/05/09)
- 🔧 **T-a 透明化權重**:每信號 score/20 + 加權公式列
- 🆕 **M-a 主散對照面板**:外資/投信/融資/散戶小台 4 欄
- 🆕 **M-b 主散背離指數** ∈ [-8, +8]
- 🆕 **T-b 30 天溫度趨勢**:Chart.js line chart + 區段配色
- 🔧 `crawler.py` 加 `compute_chip_temperature()` + `update_temp_history()`
- 🆕 後端產生 `data/temp_history.json` (30 天累積)
- 🟢 戰力 99.5 → 99.7/100

### v3.26 已知未完成 (滾下一輪 / v3.27+)
- ⏳ T-c: 加 2 個新信號 (法人共識 / 結算日壓力)
- ⏳ T-d: 過去 7 天信號觸發時間軸
- ⏳ M-c: 30 天背離趨勢 chart
- ⏳ M-d: 主散背離 → alerts.py 推播
- ⏳ Excel γ 升級候選:漲停股加「漲停買進均價」「距漲停價差%」2 欄 (v3.26 暫不做,優先觀察 β 用幾天)

### Day 4 重大成果 (v3.24, 2026/05/09)
- 🔧 `excel_report.py` 從 v3.23 完整重寫
- 🆕 內建 `MASTER_MAPPING`:13 高手 / 42 分點 (從手動 5/8 版抽出)
- 🆕 字型 `新細明體` 12pt, 全 cell center 對齊 (對齊手動版)
- 🆕 每分點固定 10 列 (空白填補)
- 🆕 `latest.xlsx` multi-sheet, 30 交易日, sheet 名 `YYYYMMDD`
- 📊 與手動版結構驗證:462 列、12 欄、97 merges 完全對齊
- 🟢 戰力 99.3 → 99.5/100

### Day 2+3 重大成果 (v3.22 + v3.23, 2026/05/08-09)
- 🆕 `excel_report.py` 從零開始 (~24KB)
- 🆕 主流程整合 → 每次 daily-full 自動產出 `data/reports/chip_radar_<日期>.xlsx`
- 🆕 `index.html` 加綠色「下載老闆版日報」按鈕
- 🆕 `.github/workflows/keepalive.yml` 防 60 天 disable
- 🐛 fix: workflow 補 openpyxl 依賴
- 🔧 v3.23 重構為 vertical layout, 12 欄結構, P/L 公式
- 📊 戰力 99 → 99.3/100

### Day 1 重大成果 (v3.21)
- 215+ 個欄位 100% 對齊官方 (TAIFEX + TWSE + MOPS)
- 修 1 個 bug (institutional.py dealer floor 誤差)
- 新增 3 個 audit script
- 主頁「🛡️ 資料準確度承諾」徽章 + Modal
- Playwright 14/15 全綠
  - alerts.py 推播警報系統 (5 種訊號)
  - insiders.py MOPS 內部人 + 重大訊息
  - today3 主頁「v3.20 即時警報」儀表板
  - 戰力 94 → 98/100 (質的飛躍 - 從工具升級成主動助手)
  - 用戶需在 GitHub Secret 加 DISCORD_WEBHOOK_URL 啟用實際推播

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
- ✅ **v3.20 主動推播 + MOPS 內部人** (2026/05/03 完成)
- ⏳ **v3.20.1 微調** - 用戶設置 DISCORD_WEBHOOK_URL 啟用推播
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

### 後端 (16 個 Python 模組)
| 檔案 | 職責 | 大小 |
|------|------|------|
| `crawler.py` | 主流程 (整合所有模組) | ~102KB |
| `branches.py` | 56 分點籌碼 + 29 master | ~28KB |
| `institutional.py` | 三大法人 (TWSE + TPEx) | - |
| `margin.py` | 融資融券 (TWSE + HiStock 雙源) | - |
| `futures.py` | TAIFEX 期貨/選擇權 (v3.18 ~970 行) | ~30KB |
| `history.py` | 30 天累積 (含期貨歷史) | - |
| `industry_classifier.py` | 1965 檔產業分類 | - |
| `market_classifier.py` | 上市/上櫃/ETF 分類 | - |
| `histock_verifier.py` | HiStock 交叉驗證 | - |
| `reports.py` | 週/月報告 | - |
| `alerts.py` | v3.20 推播警報 (5 訊號) | ~14KB |
| `insiders.py` | v3.20 MOPS 內部人 | ~17KB |
| `audit_institutional.py` | v3.21 三大法人審計 (60,276 點 100%) | ~10KB |
| `audit_margin.py` | v3.21 融資融券審計 (15,192 點 100%) | ~7KB |
| `audit_branches.py` | v3.21 分點 3 層審計 | ~9KB |
| **`excel_report.py`** | **v3.22+v3.23 老闆版 Excel 日報** | **~24KB** |

### 前端 (index.html ~360KB)
- HTML/CSS/JS 單檔
- Chart.js 4.4.1
- AES-256-GCM 加密解鎖
- 13 個 tab + 多個 Modal
- **主頁面**:籌碼溫度計 (5 信號 + 0-100 分)

### GitHub Actions
- `daily-full.yml`: 1 個排程 (20:00 週一-五) - 全部資料 + Excel 生成
- `margin-refresh.yml`: 7 個排程 (22:30/23:30/00:30/02:00/08:00/09:00/12:00) - 融資融券補抓
- `keepalive.yml`: 週日 04:00 (v3.23) - 防 60 天 disable

---

## 📊 完整版本歷程

### v3.25 溫度計 v2 + 主散對照 (2026/05/09) ⭐⭐ Day 5
- T-a 透明化權重: 每信號 score/20 + 加權公式列
- M-a 主散對照: 外資/投信/融資/散戶小台 4 欄並列
- M-b 主散背離指數 [-8, +8]
- T-b 30 天溫度趨勢 chart (Chart.js)
- crawler.py 加 compute_chip_temperature() + update_temp_history()
- 後端產生 data/temp_history.json

### v3.24 Excel 嚴格模仿手動版 (2026/05/09) ⭐ Day 4
- `excel_report.py` 完整重寫 (~21KB)
- 字型 `新細明體` + 全 cell center 對齊 (對齊手動版)
- 內建 `MASTER_MAPPING` 13 高手 / 42 分點 (來自手動 5/8 版)
- 每分點固定 10 列 (top 10 by 買進金額,空白填補)
- `latest.xlsx` multi-sheet, 30 交易日
- 移除 v3.23 的藍底/邊框/粉紅虧損 bg
- 結構對齊驗證:462 列 + 97 merges = 100% match 手動版

### v3.23 Excel template-aligned + keepalive (2026/05/08-09) ⭐ Day 3
- `excel_report.py` 重構為 vertical layout, 12 欄結構
- 對齊手動版「分點觀察」格式
- P/L 公式條件式格式 (`=F*(K-J)`, 紅字虧損)
- 新增 `.github/workflows/keepalive.yml` 防 60 天 disable
- fix: daily-full workflow 補 openpyxl 依賴

### v3.22 老闆版 Excel 日報 (2026/05/08) ⭐ Day 2 (插隊)
- 新增 `excel_report.py` 從零開始
- 主流程整合 → 每次 daily-full 自動產出 `data/reports/chip_radar_<日期>.xlsx`
- 同步生成 `data/reports/latest.xlsx`
- `index.html` 加綠色「下載老闆版日報」按鈕

### v3.21 全資料源審計 (2026/05/05) ⭐⭐ Day 1
- 215+ 個欄位 100% 對齊官方 (TAIFEX + TWSE + MOPS)
- 修 institutional.py dealer floor bug (99.83% → 100%)
- 3 個 audit script (institutional/margin/branches)
- 主頁「🛡️ 資料準確度承諾」徽章 + Modal
- Playwright 14/15 全綠

### v3.20 主動推播 + MOPS 內部人 (2026/05/03) ⭐⭐
- alerts.py 推播警報系統 (5 種訊號 + Test/Production 雙模式)
- insiders.py MOPS 內部人 + 重大訊息
- today3 主頁「v3.20 即時警報」儀表板
- 戰力 94 → 98/100 (質的飛躍)

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
v3.20 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 98/100 (主動推播 + MOPS 內部人)
v3.21 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99/100 (全資料源審計 + 準確度徽章) ⭐ Day 1
v3.22 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99.1/100 (老闆版 Excel 日報自動生成) ⭐ Day 2
v3.23 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99.3/100 (Excel template-aligned + keepalive) ⭐ Day 3
v3.24 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99.5/100 (Excel 嚴格 mimic 手動版「分點觀察」) ⭐ Day 4
v3.25 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99.7/100 (溫度計透明化 + 主散背離指數 + 30 天趨勢) ⭐⭐ Day 5
v3.26 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 99.8/100 (Excel 風格分流 — 隔日沖/當沖 master → 漲停股 Top 10) ⭐ Day 6

⬜ 還缺 0.2 分 (滾下一輪 v3.27+):
  - T-c 加 2 個新信號 / T-d 信號觸發時間軸
  - M-c 30 天背離趨勢 / M-d 背離推播
  - Excel γ:漲停股加均價/價差欄 (待 β 試用幾天再決定)
```

---

**Chip Radar 是用戶實戰可用的台股籌碼工具,不是 demo 玩具。** 🎯📊
