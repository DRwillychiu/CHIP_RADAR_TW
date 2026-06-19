# Chip Radar TW · 機構級升級 Roadmap

> **目的**:從機構角度評估 chip radar 該怎麼升級、不該追什麼。
> **產出方法**:4 平行 audit (backend / content / frontend / scheduling) × 對抗式驗證 × 綜合 roadmap
> **核心紀律**:**可稽核 + 可辯護 + 可重現** ≠ Bloomberg 仿品
> **總工時**:P0 25h + P1 32h + 排程 12h = **~70h**(取代原 audit 600h 空中樓閣)
> **報告日期**:2026-06-19

---

## A. 機構角度評分卡

| 面向 | 散戶級(現況) | 機構級(目標) | Gap | 補洞潛力 |
|---|---|---|---|---|
| **資料治理** | 5/10 — 日期分檔備份有,缺 calc metadata + 演算法版本 | 8/10 — metadata 注入 + algo 凍結即可 | 中 | 高(10h 內) |
| **可解釋性** | 4/10 — 標籤是結論,無 reasoning chain、無 sample size | 8/10 — 三檔 sufficiency + 異常 narrative | 中 | 高(12h 內) |
| **排程覆蓋** | 6/10 — 夜盤兜底完善,但盤前/盤中/結算空白 | 9/10 — 加 4 個新 workflow 即達標 | 中 | 高(14h 內) |
| **稽核合規** | 3/10 — 無 owner trail、無 event log、ToS 風險未檢 | 7/10 — masters_roster + structured log + ToS 文件 | 大 | 中(15h 內) |
| **風險偵測** | 2/10 — 純呈現大戶進出,無操縱/對敲/出貨偵測 | 7/10 — manipulation_flags 模組 | 大 | 中(8h) |
| **DR/RBAC/Multi-monitor** | 2/10 | **2/10(不做)** | — | 拒絕(見 F) |

**現況加權**:散戶優秀 / 機構勉強及格邊緣。
**升級後**:對個人決策 + 小型機構通報級可用。

---

## B. P0 機構必要(6 項,不上線就被嫌)

### B1. Masters 名單 owner trail
- **需求**:「鄭弘明為何在 master 列表?納入/剔除標準?」
- **差距**:29 master hardcode,無 owner、無 criteria snapshot
- **修法**:新增 `data/masters_roster.json` `{branch_id, name, added_date, added_by, criteria, removed_date?, removal_reason?}`
- **工時**:4h | **解鎖**:任何外部詢問可秒答;剔除門檻可量化

### B2. 演算法參數凍結 + CHANGELOG
- **需求**:「6/12 算的結論用哪版邏輯?」必須答得出
- **差距**:half_life / Jaccard 門檻散佈各模組,無版本鎖
- **修法**:`config/algo_params.yaml` 集中 + git tag `algo-v3.27.4` + 季度 review 紀律
- **工時**:3h | **解鎖**:結論可重算;版本升級有 migration 入口

### B3. Daily JSON 注入 `_calculated_at` + `_data_window` + `_algo_version`
- **需求**:「這個 master profile 用了 5/15-6/12 哪個窗口?」
- **差距**:crawler_output.py 寫出時無 metadata
- **修法**:一個 dict 注入 `meta: {calculated_at, data_window_start/end, algo_version, sourcing_trail}`
- **工時**:2h | **解鎖**:審計可追溯;取代 audit 提的 80h WAL 方案

### B4. 樣本不足三檔顯式標籤
- **需求**:n=4 標 99% CI 是機構紅旗;要顯式承認 sample 不足
- **差距**:10 個 master 只 4 天資料仍給結論
- **修法**:master profile 加 `data_sufficiency: full(≥60d) / partial(20-59d) / insufficient(<20d)`;insufficient 灰階顯示「樣本不足」
- **工時**:2h | **解鎖**:消除假信心 → 機構可信度大躍進

### B5. TWSE/TDCC/TAIFEX ToS 合規 + rate limit 退避
- **需求**:七層 margin-refresh 邊緣,IP 被封整站當機
- **差距**:safe_fetch.py 無 backoff / quota log,無 ToS 文件
- **修法**:exponential backoff + per-source daily quota log + `DATA_SOURCES_COMPLIANCE.md`(ToS 摘要 + 商用限制)
- **工時**:6h | **解鎖**:法律 + 業務連續性(比 DR 更急)

### B6. 操縱/對敲/出貨紅旗(`manipulation_flags.py`)
- **需求**:分點 dashboard 的真機構價值點
- **差距**:純呈現大戶進出,無加值偵測
- **修法**:三條規則
  - `same_branch_daytrade_ratio > 70% AND limit_hit` → 拉抬嫌疑
  - 同股當日 A 買 B 賣量級匹配(Jaccard > 0.6) → wash trade
  - 漲停前 5 min 集中度 > 40% → 主力出貨
  - 輸出 `data/red_flags.json` + 新 Tab「異常旗標」
- **工時**:8h | **解鎖**:從「看盤」進化到「監控」

**P0 合計 25h, 1 週內 ship**

---

### ✅ Sprint 3 P0 全部完成 (2026-06-19 / v3.40.0)

| # | 項目 | 交付 |
|---|---|---|
| B1 | Masters Roster | `data/masters_roster.json` (29 master × added_by/criteria/declared_styles/review_status) |
| B2 | 演算法參數凍結 | `config/algo_params.yaml` (集中 6 模組閾值) + `CHANGELOG_ALGO.md` |
| B3 | Daily JSON `_meta` | crawler raw_output 注入 algo_version + calculated_at + sourcing_trail (11 個欄位→端點映射) |
| B4 | 樣本不足三檔 | master_profile data_sufficiency (full≥60d / partial 20-59d / insufficient<20d) + 前端灰階 + caveat banner |
| B5 | ToS 合規 + backoff | `DATA_SOURCES_COMPLIANCE.md` (7 源 ToS 摘要) + safe_fetch exponential backoff + per-source quota log |
| B6 | manipulation_flags | A_拉抬 / B_對敲 / C_出貨 三規則 + `data/red_flags.json` + tab 13 紅旗面板 + jump-stock 連結 |

**驗證**: 36 套件 0 regression + 新增 43 case (B4×22 / B6×21) PASS

### ✅ Sprint 4 完成 (v3.41.0) — C1/C3/C6/C7 + 4 排程

C1 EventLogger / C3 ReasoningChain / C6 vim 鍵盤 / C7 CSV export + 4 個新 workflow (pre-market 08:50 / intraday 13:35 / settlement-tracking D-3~D+1 / weekly Fri 14:30) + 3 個對應 .py script (pre_market_brief / intraday_settlement / weekly_summary).

### ✅ Sprint 5 完成 (v3.42.0/v3.43.0) — C2 backtest + 真實 data bug 修

C2 Phase B backtest (用內建 temp_history 避 FinMind) + signal_engine 動態載入 + market_regime 偵測 + C8 5 大 methodology disclosure + universe_filter hook.

🔥 **首跑揭穿真實 data bug**: history.py `_fetch_taiex_index` 對 TWSE「漲跌」sign 偶爾空白沒處理 → 30 天 stock_history.market.change_pct 100% 全正 → 修為「拿前日 index 自己算 signed change_pct」+ backfill 30 天 → 真相: 13 漲/9 跌/8 平 → 「分點漲停 extreme-bull」原 spurious 100% hit 真實 41.4% → 自動 disable.

### ✅ Sprint 10 完成 (v3.48.0) — Tier 2 整合進 crawler + 前端 chip

**後端**:
- crawler.py 新 helper `_post_refresh_tier2_market_data` (呼叫 3 個 fetcher 更新獨立 cache)
- crawler.py raw_output 組裝後注入 main_force_cost 5d/20d + premium% 進每筆 stock
- 每日 daily-full 自動更新 4 種資料

**前端** (index.html `renderStockTrace` 個股追蹤):
- 新 `loadTier2Maps()` 一次性 load 3 個 JSON cache (with 5s timeout)
- 新 `renderTier2Chips(code, sampleStock)` 渲染 4 個 chip:
  - 💰 主力成本 5d / 20d + premium% (從 daily JSON 注入欄位)
  - 📅 除權息 D-N (從 dividend_calendar 算)
  - 🔻 借券 N 張 + ratio (從 short_lending)
  - ⚠️ 注意股 累計 N 次 (從 attention_map)
- chips 插在股票標題之後 / stat-row 之前

**驗證**: JS syntax OK (7312 行) + 41 套件 0 regression

---

### ✅ Sprint 9 完成 (v3.47.0) — 後2 crawler.py post-processing 抽 6 helper

| 抽出 helper | 原 line | 抽後 line | 內容 |
|---|---|---|---|
| `_post_generate_reports` | 1152-1169 | 81-98 | 週/月報生成 |
| `_post_build_master_profile` | 1171-1189 | 101-117 | 15 標籤大戶畫像 |
| `_post_upsert_db` | 1191-1206 | 120-134 | SQLite OLAP upsert |
| `_post_archive_rotate` | 1208-1215 | 137-143 | hot/warm/cold 分層 |
| `_post_auto_backfill_history` | 1217-1266 | 146-196 | stock_history 缺天回補 (最大 50 行) |
| `_post_disposal_snapshot` | 1268-1289 | 199-216 | 處置股 JSON+DB 雙份 |

**效益**:
- main() 1225 → **1090 行** (降 135 行, -11%)
- 每個 helper 獨立可測 / 可換序 / 可加新 stage
- 6 個 helper 全 try/except 包圍, backward compat 100%

**defer**: main() 前段 9 個 fetch stage 因共用變數多 (trade_date / results / history / summaries 等), 重構風險高, 排 Sprint 10+ 獨立做 (用 state dict 方案)

**驗證**: 41 套件 0 regression + crawler.main + 6 helper 全可 import

---

### ✅ Sprint 8 完成 (v3.46.0) — Tier 2 競品 gap 4 個 fetcher

| # | 項目 | 交付 |
|---|---|---|
| 後7 | attention_fetcher | TWSE announcement/notice 注意股 (跟處置股對齊風格, stale fallback) |
| 後6 | short_lending_fetcher | TWSE TWTASU 借券+融券, 含 borrow_vs_short_ratio + Top 30 borrow 排行 (實證: 台新新光金借券 11,122 張 vs 融券 3 張 ratio 3707, 機構押空) |
| 後8 | dividend_fetcher | TWSE TWT48U 除權息預告 289 檔 + ROC 日期自動轉 + upcoming_30d 過濾 (8/10 月高峰前必看) |
| 後9 | main_force_cost | 從 60 天 history 算 5d/20d 主力成本線 + premium% (vs today close), 個股可看「主力浮盈/套牢」 |

**驗證**: 41 套件 0 regression + 新增 test_v3460_tier2 20 case PASS

---

### ✅ Sprint 7 完成 (v3.45.0) — Tier 1 後端基礎+質量

| # | 項目 | 交付 |
|---|---|---|
| 運4 | TAIEX 重複日修正 | history.py + backfill_market_history.py 偵測 index 跟前日相同 → 標 `index_diff_stale_duplicate` + pct=0,backtester regime 排除這類 stale 重複日 |
| 運3 | 謝孟恭分點查證 | masters_roster.json review_status = `verified_low_visibility`(9676 富邦-仁愛 已驗證,0 active 是 longterm 風格的合理現象) |
| 後3 | listing_fetcher (TWSE+TPEx) | 1980 檔上市櫃公司 first_listed 自動抓 + 30 天 cache + universe_filter 自動載入 → C8 survivorship 過濾真正可用 |
| 後2 | crawler.py main() 拆 stages | **Defer 到 Sprint 8+** — 1225 行大重構,backward compat 風險高,排獨立 sprint |

**驗證**: 40 套件 0 regression + 新增 test_v3450_tier1 16 case PASS

---

### ✅ Sprint 6 完成 (v3.44.0) — 後端最痛三項

| # | 項目 | 交付 |
|---|---|---|
| 後5 | stock_history MAX_DAYS 30→60 | 配合 master_profile B3 衰減 60 天視窗 + 給 margin_maintenance 60 日均價選項 |
| 後4 | disposal_fetcher 7 天 fallback cache | chengwaye 斷線時用最後 7 天 cache (stale=True + stale_days 標) + parse 0 筆時也試 fallback |
| 後1 | safe_fetch 全 migrate 核心 5 fetcher | history / margin TWSE+TPEx / institutional T86+TPEx3insti+STOCK_DAY_ALL+TPEX_DAILY / disposal_fetcher / futures _post_csv — 統一 backoff + per-source quota log + ToS 合規 |

**驗證**: 39 套件 0 regression, 全部 backward compat (`safe_fetch` import 失敗 fallback 原 requests)

---

## C. P1 提升質感(8 項精簡)

| # | 項目 | 工時 | 一句話 |
|---|---|---|---|
| C1 | Structured event log (JSONL) | 2h | alerts.py 統一 `{ts, event_id, severity}` → 未來接 SIEM |
| C2 | Backtest Phase B 完成(4 信號) | 6h | 取代拍腦袋權重;hit_rate 入 CHANGELOG |
| C3 | 異常 reasoning chain | 6h | 「外資連 3 天淨空 + 結算 D-2」非模板 |
| C4 | Sourcing trail meta | 4h | 欄位→endpoint→fetch date 映射 |
| C5 | 融資維持率三級警示 | 4h | 已實作,擴 narrative |
| C6 | 鍵盤 j/k/`/` 快鍵 | 3h | 別假裝 Bloomberg,但這是廉價 UX 升級 |
| C7 | CSV/JSON export 含 metadata | 3h | 各表格 export 帶 algo_version checksum |
| C8 | Survivorship bias 修正 | 4h | backtest 排除下市/減資/合併扭曲 |

**P1 合計 32h**

---

## D. 排程擴充(6 → 10 workflow)

| 新增 workflow | Cron (UTC) | TW 時間 | 內容 | 工時 |
|---|---|---|---|---|
| `pre-market-alert.yml` | `50 0 * * 2-6` | **8:50** | 讀 latest.json 推 3 行:昨日大戶 Top3 變動 + 新增處置股 + 結算 D-? | 2h |
| `intraday-settlement.yml` | `35 5 * * 2-6` | **13:35** | TWSE JSON API 拉三大法人日況 → Top5 推播;不等 21:17 | 3h |
| `settlement-tracking.yml` | 動態 `0 */4 * * 2-6`(僅 D-3~D+1) | 每 4h | 期交所結算曆驅動;密集監控融資膨脹 + tail risk | 4h |
| `weekly-summary.yml` | `30 6 * * 5` | **週五 14:30** | tdcc_holdings 週 delta + master 週度進出排名 → Markdown | 3h |

**捨棄項目**(對抗式驗證已 flag):
- ❌ `futures-settlement.yml` TAIFEX 16:00 → Cloudflare 繞過違反 ToS,改用官方公布檔批次下載納入 daily-full
- ❌ 盤中 15min 推播 → GitHub Actions 30min+ latency 做不到;不假裝
- ❌ monthly PDF report → Excel 月報已產,PDF 是包裝;降 P2

**現有 6 個 workflow 增強**:
- `heartbeat.yml`:分級告警(warn 30min / page 1h / escalate 2h)+ structured log
- `margin-refresh.yml`:加 `holidays.json` 假日感知 skip
- 全 workflow:時區明示 `Asia/Taipei`

---

## E. Sprint 3-5 升級順序(10 天)

### Sprint 3(4 天, 16h)— 排程 + 信心區間基底
- Day 1:B1 masters_roster + B2 algo_params 凍結(7h)
- Day 2:B3 metadata 注入 + B4 sample sufficiency 三檔(4h)
- Day 3:新增 `pre-market-alert.yml` + `intraday-settlement.yml`(5h)
- Day 4:B5 ToS 合規 + safe_fetch backoff(6h)← 與 Day 3 並行

### Sprint 4(4 天, 16h)— 偵測力 + 可解釋性
- Day 5-6:B6 manipulation_flags + Tab 異常旗標(8h)
- Day 7:C2 backtest Phase B(6h)
- Day 8:C3 reasoning chain + C4 sourcing trail(10h,部分順延)

### Sprint 5(2 天, 8h)— Export + 排程收尾
- Day 9:C7 export 含 metadata + C6 鍵盤快鍵(6h)
- Day 10:`settlement-tracking.yml` + `weekly-summary.yml`(7h,部分順延)

**10 天可 ship P0 全部 + P1 一半**;剩餘 C1/C5/C8 排 Sprint 6。

---

## F. 拒絕清單(機構要的但 chip_radar 沒意義)

1. ❌ **Backend DR / S3 鏡像 / failover DNS (60h)** — 個人 dashboard 掛 30min 無人會死;GitHub Pages SLA 已夠
2. ❌ **RBAC + Private releases (50h)** — 產品本質是公開個人 dashboard,要走機構就整套換 infra,不是補丁
3. ❌ **PDF 含簽名欄 / Multi-Monitor 浮窗 / Draggable grid** — 無投委會、無多螢幕用戶、12 tab 已夠
4. ❌ **替代假設三套並行 (light/normal/aggressive)** — 3x 計算成本回測未驗證的 sensitivity 是噪音
5. ❌ **同業 vs 0050/0056 對標** — Master 是分點不是基金,基準錯位
6. ❌ **簽名 hash compliance_log (35h)** — 過度合規包裝;C1 structured JSONL 已足

**核心紀律**:機構級 ≠ 仿 Bloomberg。是**對外可辯護、對內可重算、對自己可改進**。

---

## G. 對抗式驗證找出的 3 個重大盲點

四份 audit 全部漏掉:

1. **操縱 / Wash trade 偵測**(已納入 B6)— 分點 dashboard 的真機構價值點
2. **Master 名單 owner trail**(已納入 B1)— 最大可追溯性漏洞
3. **資料源 ToS 合規 + rate limit 退避**(已納入 B5)— 七層 margin-refresh 邊緣,被封 IP 整站當機

這三個的共同特徵:**七位 agent 都沒看到,因為他們各自從技術視角看,而不是從「機構合規團隊會問什麼」視角看**。

---

*本文件每 sprint 完成時更新進度。下次評估時點:Sprint 3 結束(4 天後)*
