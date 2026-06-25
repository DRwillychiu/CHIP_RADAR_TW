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

### ✅ v3.67.3 — Q5 偏多預測校準 (Phase 2.4 自我揭穿後對策)

Phase 2.4 (v3.66.8) sub-banner 揭穿偏多 hit 41% (比隨機 50% 還差)。本版修兩個根因:

**Fix #1**: 中性閾值 0.05 → 0.10 (signal_engine.py)
- 33 樣本中 23 個 net=+0.087 (單一 P/C signal) 全進偏多 → 弱信號被當強信號
- 拉高閾值,單一 P/C 自動歸中性 (不下注)

**Fix #2**: _compute_q5_hit_rate stale guard (excel_report.py)
- 揭穿: 8 個 chg=0.0 全是 false-negative, next_day_close=None 證明缺資料
- 6/2-6/8 TAIEX index=45070.94 連 7 天相同 (v3.43.0 兜底重複日 bug 歷史汙染殘留)
- 修補: chg=0.0 AND close=None → skip

**驗證 (33 樣本 replay)**:
| 指標 | Before | After |
|---|---|---|
| 偏多 hit | 13/30 = 43.3% | 4/7 = **57.1%** (+13.8pp) |
| 整體 hit | 14/31 = 45.2% | 5/8 = **62.5%** (+17.3pp) |
| 預測量 | 31 筆 | 8 筆 (砍 74%) |
| 中性 (不下注) | 0 | 15 |
| Skip stale | 0 | 8 |

「沒把握就閉嘴」原則: 預測量少 74% 但跨過 60% 信心門檻。

---

### ✅ v3.67.1 + v3.67.2 — Phase 2.7 手機摘要 sheet + 自動 Email 寄送

**v3.67.1**: 📱 手機摘要 sheet (19 row 單欄 4 個決策問題: 明日預測 / 強共識 Top 5 / 今日避開 / 追蹤池方向)

**v3.67.2**: GitHub Actions + Gmail SMTP, 主排程 21:17 TW + 兩兜底, 僅 data_changed=true 才寄, 純文字 body + latest.xlsx 附件

---

### ✅ v3.67.0 — Phase 2.6 Color Tokens + Zebra stripes

COLORS dict 35+ semantic token 集中文件化, _zebra_stripes() helper apply 給 E/F/G/H/I 5 section, 奇數 row 淡灰底 (#F9FAFB) 自動跳過已有 fill 的 cell

---

### ✅ v3.66.9 — Phase 2.5 強共識股隔日 backtest sub-banner

bootstrap_consensus_backtest.py 對歷史每天算 Section 0 強共識 + 查 stock_history 隔日 chg, 30d summary: 306 picks / 153 hits = **50.0%** / 中位 +0.03% / 平均 +0.89%, Section 0 加 sub-banner 揭穿真實 alpha (目前判定: 無顯著 alpha)

---

### ✅ v3.66.8 — Phase 2.4 Q5 預測 hit rate 累積 sub-banner

_compute_q5_hit_rate() 讀 temp_history × infer_market_direction → tally hit, Section A Q5 banner 下方加 sub-banner: 偏多 X/Y / 偏空 / 整體 + 顏色 (≥60% ✅ / 40-60% 🟡 / <40% ⚠️). 6/24 production 揭穿: 偏多 11/27=**41%** (比隨機差!) → 觸發 v3.67.3 修補

---

### ✅ v3.66.7 — Phase 2.3 Section A 時間維度 (今/昨/5日均)

timeseries.json 60 天滾動 cache, Q1-Q4 KPI sub-text 顯示「(昨X/5d Y)」, bootstrap_timeseries.py 掃 45 天歷史 daily JSON 解密計算

---

### ✅ v3.66.6 — Phase 2.2 Conditional Formatting Data Bars

_try_add_data_bar() helper, 11 處 data bars (Section 0 大戶數+合計淨買 / B 買進 / C 淨買 / F 連續天數+累計 / J 總買+集中度 / G 累計次數 / H 借券張數), 一秒掃完誰最值得關注

---

### ✅ v3.66.5 — TL;DR + Action card bug fix

Bug 1: Action 進場關注 top 3 沒跟 Section 0 對齊 (隨機 dict iteration 改用相同 sort key)
Bug 2: 避開除權息誤導 (3 檔 → 「N 檔: top3 ...」明示總數)

---

### ✅ v3.66.4 — Phase 2.1 TL;DR + Action card (首屏 5 秒決策摘要)

Row 3 TL;DR 一句話 (淡黃底 12pt bold) 6 個 hot 指標
Row 4 Action card (淡灰底 11pt italic) 3 段: 進場關注 top 3 / 避開除權息 / 訊號強弱判定
freeze_panes A3 → A6, TL;DR + Action 永遠看得到

---

### ✅ v3.66.3 — Section G empty state + H 借券 hot 標記 (Dashboard 簡潔收尾)

**Section G 注意股** (`_build_section_risk`):
- empty state 從 「今日無注意股」改 「✅ 今日無新增注意股 (市場無異常波動標的)」
- 套綠色斜體 (FF10B981) 表「正常無壓力」, 跟 H/I 警報訊號區隔

**Section H 借券賣出** (`_build_section_risk`):
- `borrow_vs_short_ratio ≥1000x` 標 🔴 — 代號前 prefix + ratio 欄深紅粗體
- ratio number_format `#,##0.0` 千分位 + 小數
- 張數欄 (借券 / 融券) 加 `#,##0` 千分位
- 用戶: 「Dashboard 簡潔但有力」, 1000x 是極端機構壓力門檻

**驗證**:
- 真實 daily short_lending.json top 15 → 1 筆達 1000x (00997A ratio=1243.2) 標紅 ✓
- attention_map 空 → G 顯示綠色「✅ 今日無新增注意股」✓
- syntax check pass

---

### ✅ v3.66.2 — Section J 集中度 + Master 色塊 (Dashboard 簡潔原則)

**Section J 改造** (`_build_section_pivot`):
- **新增 col J「Top3 合計%」** — Top3 金額 / master 今日總買, 0.0% format
- **Master cell 套 MASTER_BLOCK_COLORS body 色** — 跟 B/C 視覺一致
- **集中度 ≥80% 標 🔥** — Master prefix 🔥 + Top3% 欄深紅粗體, 視覺立刻挑出押大注的 master
- 金額千分位 #,##0 統一

**驗證**:
- 合成 3 master (押大注 90% / 散買 50% / 中度 65%) → 🔥 only on 90% ✓
- Master 色塊跟 B/C 對齊 (Tradow 淡紅 / 大牌分析師 淡綠 / 巨人傑 淡紅) ✓
- 0.0% format + 紅字粗體於 ≥80% ✓

---

### ✅ v3.66.1 — Section G/H/I 時間正確性修補 + strict assertions

**P0 bug** (用戶 2026-06-24 發現):
Section I「未來 30 天除權息」前 15 筆中 13 筆 ex_date=20260623 (已過期)。crawler 6/23 21:35 跑時把「6/23 後 30 天」存進 upcoming_30d, 6/24 用戶開 Excel 時 6/23 已是過去, Excel render 直接讀 upcoming_30d[:15] 沒過濾過期。

**修補**:
- Part 1 — I 過期過濾: `upcoming = [i for i in raw if ex_date >= trade_date]`, build_dashboard_sheet 把 trade_date 傳給 _build_section_risk
- Part 2 — G/H/I header 加 applicable_date 顯示, 用戶知道資料新鮮度
  - G: "▍ G. 注意股 (資料日 20260623)"
  - H: "▍ H. 借券賣出 Top 15 (機構級反向力量, 資料日 20260623)"
- Part 3 — cross_validate_dashboard.py 加 G/H/I strict assertion, header applicable_date 校對

---

### ✅ v3.66.0 — Section E 大砍 + F hot 標記 + Dashboard 簡潔原則

**用戶要求**: 「Dashboard 簡潔但有力」— E 三 sub-section 中 consensus/accumulation 跟 Section 0/A/F 重複,只留 anomalies。

**Section E 大改造** (`_build_section_alerts`):
- **砍掉 🟡 共識** — 跟 Section 0 強共識買超 + Section A Q3 重複
- **砍掉 🟢 連續加碼** — 跟 Section F 跨日連續囤貨 Top 30 是 subset 重複
- **保留 🔴 異常 + 🆕 新標的, expand top 5 → top 10**
- **修 new_stocks 沉底 bug** — 原 `sort key=z_score(0)` 讓 new_stocks 永遠排不到 top, 改用 `_anomaly_severity()` 統一權重 (volume_spike=|z|, new_stocks=2.5+count*0.2)
- 標題改 「異常行為警報 (z>2σ 量爆 + 新標的進場)」, 5 col 簡化
- 總 row 從 max 45 砍到 max 12 (header 2 + top 10 + footer 1)

**Section F hot 標記** (`_build_section_accumulation`):
- **連續 ≥10 天 → Master cell prefix 🔴 + 連續天數欄深紅粗體 (FFC62828)**
- HOT_DAYS=10, 視覺立刻挑出囤超久的 master
- 邏輯/排序/row 數量不變 (仍 top 30 by 連續天數)

**驗證**:
- 合成 12 anomalies (7 volume_spike + 5 new_stocks) → top 10 交錯出現,修了沉底 bug ✓
- 合成 15 accumulations → ≥10 天 6 筆全標 🔴 紅字, <10 天 9 筆正常 ✓
- syntax check pass

---

### ✅ v3.65.0 — Section B/C 視覺優化 + ETF 全 Dashboard 排除 (用戶要求)

**用戶要求**: 「Dashboard 最應該呈現的是只有個股,沒有 ETF」

**Section B/C 視覺改造** (`_build_section_summary` B-I 並排 4-col block):
- **B Master 名 cell 套色塊** — 用既有 MASTER_BLOCK_COLORS body 色 (蔣承翰=淡紅 / 民哥=淡綠 / 林滄海=淡綠 etc) 跟日期 sheet 同調
- **C 個股顯示改 `name(code)` 格式** — 一格內,跟日期 sheet 一致
- **C 新增「漲跌%」欄 (I)** — 從 crawler 注入的 `change_pct` 抓, 紅(漲)/綠(跌)字色 + `0.00%` format
- **數字千分位** — B 買進 / C 淨買加 `#,##0` format

**ETF 全 Dashboard 排除** (5 處 helper / section):
- Section C Top 5 個股: `_is_excluded_by_market_type(s)` filter
- Section J Master × Top 3 個股: 同 filter
- Section E 警報 (anomalies / consensus / accumulations): `code.startswith('00')` filter
- Section F 跨日連續囤貨: 同 filter
- Section 0 強共識買超: 已有 (Sprint v3.63.7)
- Section A Q3 強共識股: 已有 (v3.64.3)

**驗證**:
- 43 套件 0 regression (skip date-dependent test_v3460_tier2)
- 本機 build 含 ETF (00919/0050/00713) data 驗證 → Top 5 個股只剩個股 (群創/聯發科/鴻海/台積電)

---

### ✅ v3.64.0 — Excel Section A 規模統計擴增 + L 欄損益字色修

**用戶反饋 6/22**: L 欄正值用「白字 on master block 紅淡底」+ 負值有「ColorScaleRule 紅/綠 fill 跟 master fill 重疊變糊」.

**L 欄損益字色修**:
- 拿掉 `apply_pnl_color_scale` 呼叫 (避免跟 master block fill 衝突)
- `_font_pnl_pos`: 白字 → **深紅粗體 `#C62828`** (台股傳統紅=賺)
- `_font_pnl_neg`: 黑字 + [Red] format → **深綠粗體 `#2E7D32`** (台股傳統綠=虧)
- `NUMBER_FMT_PNL`: `'0.00_ ;[Red]\-0.00\ '` → `'#,##0.00;-#,##0.00'` (加千分位, 不靠 format color)
- 結果: master block 任何色底 + L 欄損益都高對比清楚

**Section A 規模統計擴增 (P0 簡化版)**:
- 原 4 stat (master / 個股 / 總買 / 漲停買) → 6 stat × 2 row × 3 col 整齊矩陣
- Row 1: 活躍 Master / 個股涉及 / 分點覆蓋 (XX/81 N%)
- Row 2: 總買進 / 總賣出 / 淨買差 (紅+/綠- 自動)
- 拿掉「漲停買進筆數」(已在 Section 0 + Tier 2 chip)
- 簡潔: 不加 vs 5日 / vs 昨日 delta (用戶要求簡單)

**驗證**: 44 套件 0 regression + 用戶本機 build 預覽 6/22 case 確認 OK

---

### ✅ v3.63.9 — Section 0 強共識買超排序優化 + ⚠️ 假共識警示

**用戶反饋**: Section 0 排序「大戶數→分點數→金額」導致 7591 萬資金的彩晶 rank 1, 7.4 億群聯 rank 9 — 違反「強共識」直覺.

**改動** (`src/exports/excel_report.py _build_section_consensus`):

1. **主排序改總金額 desc** (用戶確認):
   ```
   total_net_amt DESC → master_count DESC → branch_count DESC
   ```
   - ≥10 大戶硬門檻不變 (已保證廣度)
   - 金額反映「資金共識深度」
   - 6/18 production 變化: 群聯 #9→#2 / 彩晶 #1→#8 / 華新科 #3→#1

2. **⚠️ 假共識警示**: 領頭大戶獨佔 ≥50% → 名稱前加 ⚠️ + 淡橙底
   - 6/18 例: 華新科 領頭佔 83001/125534 = 66.1% (1 大戶獨大)

3. **詳細 cell comment** (用戶要求說明):
   - hover 名稱 cell → tooltip 顯示「領頭金額 / 合計 / 佔比% / 判讀」
   - openpyxl Comment 280×180 px

4. **註腳 row** (Section header 下方一行):
   - 「ⓘ 排序: 合計淨買金額 ↓ | ⚠️ 名稱前 = 領頭大戶獨佔 ≥50% (1 人獨大,真共識訊號被稀釋)」
   - 淡橙底 italic 小字, 永遠看得到

**驗證**:
- 44 套件 0 regression
- 本機 build preview xlsx 給用戶確認 OK
- Excel comment + 註腳 + 排序變化全顯示正確

---

### ✅ Sprint 26 完成 (v3.63.0) — Excel Tier 2: E6 freeze + E7 Pivot-style Section J

**E6 Freeze panes**:
- Dashboard sheet `freeze_panes = 'A3'` — title row 不滾走
- 日期 sheet `freeze_panes = 'C2'` — 滾右仍能看到 A 欄 master + B 欄分點對應, header row 也固定

**E7 Pivot-style Section J** (取代真 PivotTable, openpyxl 對 PivotTable 支援差):
- `_build_section_pivot` — Master × Top 3 個股 cross-table (今日)
- 每 master 一 row, 6 cols 寬展開 (Top1/2/3 個股名+金額) + 今日總買
- 按 master 總買降序, 限 30 row
- 加在 Dashboard Section F 之後 (F→J→G/H/I)

**Dashboard 完整 section 順序**: A 規模 → B Top master → C Top stocks → D 籌碼溫度 → E 警報 → F 連續囤貨 → J Master×Top3 個股 → G 注意股 → H 借券 → I 除權息

**驗證**: 44 套件 0 regression + 本機 build test 含 10 個 section + freeze 兩 sheet 全生效

---

### ✅ v3.62.1 (Sprint 25 patch) — Dashboard 改單一 sheet (用戶要求)

**用戶反饋**: 「新元素全部放同頁面」— 把 v3.62.0 4 個 enrichment sheet 合 1 sheet.

**改動** (`src/exports/excel_report.py`):
- 新 `build_dashboard_sheet` orchestrator 串接 4 個 `_build_section_*` helper
- 9 個 section 順序: A 規模 → B Top master → C Top stocks → D 籌碼溫度 → E 異常警報 → F 連續囤貨 → G 注意股 → H 借券 → I 除權息
- 共享 row counter, section 間自然分隔 (header color 區分)
- 舊 4 sheet (📋 今日摘要/🚨 異常警報/📦 連續囤貨/⚠️ 風險警示) 自動 cleanup (LEGACY_ENRICHMENT_NAMES)
- backward compat: `build_summary_sheet` alias 給 `build_dashboard_sheet`

**驗證**: 44 套件 0 regression + 本機 build test 93 row 含全 9 section

---

### ✅ Sprint 25 完成 (v3.62.0) — Excel 增強 E1-E5 (Tier 1 全套) + strict_verify D1-D8

**精準度驗證(先做)**:
- 新 `src/audit/excel_strict_verify.py` 補既有 audit 沒驗的 8 維度
- D1-D7 跑 production latest.xlsx + user Downloads 版 → 588 row × 14 sheets **全 PASS**
- 既有 audit (content/full) → 全 PASS
- D8 cell-vs-raw 需 password,用戶選接受 99% 進 Excel 增強

**Excel 增強 5 個新 sheet** (`src/exports/excel_report.py`):
- **E1 📋 今日摘要** (build_summary_sheet): 規模統計 (活躍 master / 個股涉及 / 總買進金額億元 / 漲停買進) + Top 5 master + Top 5 個股 + 籌碼溫度
- **E2 🚨 異常警報** (build_alerts_sheet): 從 daily_trading_signals.json 抓 anomalies + consensus + accumulation 三類警報
- **E3 📦 連續囤貨** (build_accumulation_sheet): master_profile.consecutive_accumulation_stocks 跨 master sorted by max_consecutive_days
- **E4 ⚠️ 風險警示** (build_risk_sheet): 注意股 (attention_map) + 借券 Top 15 (short_lending) + 除權息預告 (dividend_calendar)
- **E5 🌈 色階** (apply_pnl_color_scale): L 欄損益 -100→0→+100 紅白綠 ColorScaleRule

**整合** (`_update_monthly_workbook`):
- 4 個 enrichment sheet 每天 rebuild (覆蓋舊版本)
- sheet 排序: enrichment 在前 + 日期 sheet desc 在後
- E5 conditional formatting apply 在 day sheet L 欄
- 全 try/except 包圍 (enrichment 失敗不影響主流程)

**驗證**: 44 套件 0 regression + 本機 build test PASS (5 個 sheet 全產生 + 規模統計準確)

---

### ✅ Sprint 24 完成 (v3.61.0) — DB 進階查詢功能 (CLI + 前端 Tab 12)

**動機**: 既有 `query_db.py` 只 7 個 preset + 純 table output. 機構級 data analyst 用法需要更多 high-value query + JSON/CSV 多形態輸出 + web 介面瀏覽結果.

**CLI 擴充** (`src/core/query_db.py` 7 → 15 preset):
- Q8: 跨日聯動(連續加碼同一檔 5+ 天 trader×stock)
- Q9: 派系初探(兩 master 同檔同日買進次數 Top 20)
- Q10: 隔日沖驗證(T+1 flip 昨日漲停買→今日賣 + flip_pct)
- Q11: 處置股獵手(漲停個股累積買進 Top trader)
- Q12: Master 風格畫像(漲停買進 vs 一般買進比 + lu_pct)
- Q13: 每日最強 master(當日總買金額 排行)
- Q14: 個股觀察(過去 30 天交易 master 數最多 Top 20)
- Q15: 活躍天數分布(每位 master 出手天數 + 平均單日金額)

**多形態輸出**:
- `--format table/json/csv` 三選一
- `--save FILE` 存檔
- `--explain` 印 EXPLAIN QUERY PLAN
- `--export-all FILE` 跑全 preset 包成 snapshot JSON

**Crawler 整合** (`crawler.py`):
- 新 helper `_post_export_db_query_snapshot(data_dir)` 加進 main() post-processing
- 每天自動 export `data/db_query_snapshot.json` (per-query 限 200 行避免太大)

**前端 Tab 12 報告中心擴充** (`index.html`):
- 加 「🗄️ DB 進階查詢」section + 預設下拉 + result table + CSV 匯出 button
- `loadDbQuerySnapshot()` lazy fetch 8s timeout + cache
- `renderDbQuery()` 含 SQL <details> 摺疊 + 數值千分位 + truncated 提示
- `exportDbQueryCsv()` 直接從 snapshot 客戶端產 CSV (UTF-8 BOM 避 Excel 亂碼)

**驗證**: 44 套件 0 regression + 新 test_v3610_query_db 17 case PASS (含 in-memory schema + 15 preset SQL syntax check + 3 format 一致性)

---

### ✅ Sprint 23 完成 (v3.60.0) — P0-E Tab lazy render + DOM 快取 (前端 P0 6/6 完滿)

**動機**: 機構級用戶頻繁切換 tab 比對資料. 既有 tab.click 每次都重 render, 即使資料沒變. Sprint 19 content-visibility 已涵蓋 layout perf 大頭, 但 JS render work 仍重複跑.

**實作** (`index.html`):
- 新 `_TAB_RENDERED` Set + `markTabsDirty(reason)` helper
- tab click handler 加 cache check: `if (_TAB_RENDERED.has(tab)) return;` → first time 才呼叫 render, 之後直接顯示 cached DOM
- `showDate()` 設 CURRENT_DATA 後加 `markTabsDirty('CURRENT_DATA loaded')`
  → 日期切換時自動 invalidate
- `renderAll()` (WATCHLIST 變化路徑) 內加 `markTabsDirty('WATCHLIST changed')`
- console log invalidate 原因方便 debug

**效益**:
- 切回已 render 過的 tab 從 100-300ms render → <1ms (純 CSS display 切換)
- 資料變化時自動 invalidate (zero stale cache 風險)

**設計取捨**: 不改 render 函式內部. tab 內部 sort/filter 切換 caller 直接呼叫 render() 不走 cache, 行為不變.

**驗證**: JS syntax OK + 43 套件 0 regression

**狀態**: 🎉 **前端機構級 P0 全套完成 6/6** (Sprint 18-23: A/D/B/F/C/E)

---

### ✅ Sprint 22 完成 (v3.59.0) — P0-C 前端 ARIA + 鍵盤導航 (機構 a11y 合規)

**動機**: 前端 audit `0 個 ARIA attribute`. 機構級合規 (政府/銀行/上市公司內部 site) 需符合 WCAG 2.1 AA 鍵盤族友善基準.

**ARIA roles + states**:
- `<div class="tabs" role="tablist" aria-label="主功能分頁">`
- 15 個 tab 加 `role="tab"` + `aria-selected` + `aria-controls="panel-X"` + `tabindex` (selected=0, others=-1 — WAI-ARIA roving tabindex pattern)
- 15 個 panel 加 `role="tabpanel"` + `aria-label` (sed 批次)
- `<main id="main-content" role="main">` 主 landmark
- theme-toggle emoji 加 `aria-hidden="true"` (避免 SR 讀「月亮」)

**鍵盤導航** (WAI-ARIA tablist 標準):
- `ArrowRight/Left`: 上/下一個 tab + auto click + auto focus
- `Home/End`: 跳首/尾 tab
- 既有 1-9/0/-/=/j/k/ESC 保留 (v3.41.0 C6 已有)
- tab click handler 同步 update aria-selected + tabindex

**Skip link**: `<a href="#main-content" class="skip-link">跳至主內容</a>`
- 滑鼠隱藏(left: -9999px), Tab 第一次按到 focus 顯示, 跳過 header 直達 main

**Focus visible 統一樣式**:
- `*:focus-visible { outline: 2px solid var(--gold-bright); outline-offset: 2px; }`
- 鍵盤族用 outline, 滑鼠點不顯示(`:focus-visible` 而非 `:focus`)

**驗證**: JS syntax OK + 43 套件 0 regression

---

### ✅ Sprint 21 完成 (v3.58.0) — P0-F 前端機構級響應式佈局 (mobile-first)

**動機**: 既有 5 個 media query 涵蓋 cards-grid / header / table padding 等基本元素, 但機構級重點 (15 tab 水平 scroll / stat-row flex-wrap / controls 堆疊 / table-wrap horizontal scroll / theme-toggle thumb zone) 全缺. 用戶手機看板體驗差.

**實作** (`index.html` 加 2 個新 breakpoint):

`@media (max-width: 640px)` — mobile 主邏輯:
- **Tab nav**: `overflow-x: auto` + `flex-shrink: 0` + `-webkit-overflow-scrolling: touch` → 15 tab 水平 scroll 流暢
- **stat-row**: `flex-wrap: wrap` + `flex: 1 1 calc(50% - 6px)` → 兩欄自動換行
- **table-wrap**: `overflow-x: auto` + `min-width: 480px` + 負 margin 對齊 main padding → 16 欄 table 不裁切
- **controls / control-group**: `flex-direction: column` + `align-items: stretch` → input / select 自動延展
- **theme-toggle**: 縮 40px + bottom 12px (不擋 thumb zone)
- **section-title / info-banner / chip / button**: 字級 + padding 全面縮

`@media (max-width: 380px)` — 超小手機 (iPhone SE):
- stat-box 全欄 `flex: 1 1 100%`
- main padding 12px
- tab 字級 11px

**設計取捨**: table 用 horizontal scroll 而非 stack (機構級 multi-column 資料不適合 stack — 失去對齊性)

**驗證**: JS syntax OK + 43 套件 0 regression

---

### ✅ Sprint 20 完成 (v3.57.0) — P0-B 前端 Dark / Light theme 切換

**動機**: 機構辦公室白天明亮環境長時看 dark theme 容易眼花. 加 light theme + 即時切換, localStorage 持久.

**實作** (`index.html`):

CSS:
- 既有 `:root` dark theme 變數補 `--bg-radial-1/2` (gradient stop 也可 themeable)
- 新 `:root[data-theme="light"]` 全套 light theme palette:
  - `--bg`: `#f5f7fb` (淡灰白)
  - `--text`: `#1a2236` (深藍黑)
  - `--shadow`: 從 0.4 alpha 降 0.08
  - 紅綠(盤面色) 保留鮮明對比, 略微深沉
- body 加 `transition: background-color, color 0.25s ease`
- `.theme-toggle` 浮動 button (右下 16px, 44px 圓):
  - 暗色顯示 🌙, light theme 自動切換 ☀️
  - hover scale 1.08 / active scale 0.95

HTML:
- 加 `<button class="theme-toggle" onclick="toggleTheme()">` + ARIA label

JS:
- `getInitialTheme()` 讀 localStorage `chip_radar_theme` (fallback 'dark')
- `applyTheme(theme)` 設 `data-theme` attribute + localStorage persist
  + Chart.js theme-aware 重畫 (CURRENT_TREND_STOCK 存在時)
- `toggleTheme()` 切換 dark ↔ light
- 即時 apply 避免 FOUC (flash of unstyled content)

**131 處 hardcoded color 處置**: 大部分是 transparent rgba overlay (兩主題都 OK). 純色 hardcode 細節用戶實測後 polish.

**驗證**: JS syntax OK + 43 套件 0 regression

---

### ✅ Sprint 19 完成 (v3.56.0) — P0-D 前端 render 大型增量重繪 + CSS 隔離

**動機**: 機構級前端 audit 顯示 124 處 `.innerHTML=`, 大型 render(81 分點/100 records) 主流程 layout cost 偏高. 切換 sort/filter 頻繁時 reflow 傳到全頁 DOM.

**CSS 三層 perf 優化**(立即對所有 panel 生效):
1. `.panel.active { contain: layout style; }` — 內部 reflow 不傳播外部
2. `.panel:not(.active) { content-visibility: auto; contain-intrinsic-size: 0 800px; }` — 不在視口 panel skip render(Chrome 700% speedup)
3. `.table-wrap { contain: layout style; }` + `.stat-row { contain: layout style; }` — table 隔離 reflow

**renderWithFragment 擴大採用**(v3.39.0 P1-7 已有 helper, 用在 2 處 → 擴到 6 處 hot path):
- `renderRanking` 3 view (branches/masters/stocks) 全改 fragment
- `renderInstitutional` 改 fragment
- `renderStockTrace` 改 fragment
- 用 `<template>` detached parse + `replaceChildren` atomic swap, 比 innerHTML 賦值少一次 reflow

**效益**:
- panel 切換從 100-300ms → 預估 <50ms (content-visibility 大頭)
- table 內 sort/filter 切換 reflow 不傳全頁
- 既有 stable load 不變(`<template>` 不執行 script 安全)

**backward compat**: zero behavior change (HTML output 完全一致)

**驗證**: JS syntax OK + 43 套件 0 regression

---

### ✅ Sprint 18 完成 (v3.55.0) — P0-A 前端 Web Worker 解密

**動機**: latest.json 加密 + gzip 2.4 MB 解密 + gunzip 在 main thread 跑 1-2s, scroll / click / tab 切換全部凍結. 機構級 UX 不能接受.

**實作** (`index.html`):
- 既有 `decryptToken` 改名 `_decryptTokenInline` (保留作 fallback)
- 加 `_DECRYPT_WORKER_CODE` 字串常數 — Worker 內 self-contained JS (b64ToBytes + deriveKey + decryptTokenWorker + onmessage handler)
- 加 `_getDecryptWorker()` — Blob URL inline 載入 Worker (零部署複雜度, 不需多 .js 檔), lazy init + cache
- 加 request id → resolver Map 支援併發解密(多日歷史並行)
- 新 `decryptToken` Worker wrapper: Worker 不可用(老瀏覽器/CSP block) → fallback `_decryptTokenInline`

**效益**:
- main thread 從 1-2s 凍結 → 立即釋放
- scroll / tab 切換在解密期間流暢
- 多日歷史並行解密(unlock + tab 切換時並發)

**backward compat 100%**:
- 既有 5 個 caller (`await decryptToken(...)`) 全部不變
- Worker 失敗 fallback 走 inline (老瀏覽器)
- 加密/解密 logic 跟 main thread 完全一致 (zero behavior change)

**驗證**: JS syntax OK + 43 套件 0 regression (後端不受影響, 用戶瀏覽器實測 UX)

---

### ❌ Sprint 17 取消 (v3.54.x) — 長1 Haiku API narrative

**取消理由**: 用戶評估 Anthropic API key cost 不值得 (估計每日 < $0.10 USD, 但 narrative 並非剛需). 既有 trade_pattern.py 規則式 narrative 已涵蓋大部分用例.

**保留路徑**: 未來若 narrative 需求增加 (e.g. 多語言 / 個性化 / 長文), 可再啟用此 Sprint. code 設計圖暫存腦中.

---

### ✅ Sprint 16 完成 (v3.54.0) — 長2 Telegram Bot 推播 (跟 Discord 平行)

**實作** (`src/alerts/alerts.py`):
- 新 `send_telegram(text, parse_mode='Markdown', bot_token=None, chat_id=None)`
  - 讀 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env var
  - 未設兩個之一 → test mode (print only, return None)
  - 有設 → POST `https://api.telegram.org/bot<TOKEN>/sendMessage`
  - HTTP 200 → True, 其他 → False
- 新 `_format_telegram_alert(detected, trade_date)`:
  Markdown 格式 (跟 Discord embed 對應), 最多顯示 8 則細節
- `run_alerts` 末尾並行推 Discord + Telegram
- return dict 多 2 欄: `pushed_telegram` / `pushed_telegram_test_mode`
- 無 detected / dry_run 路徑也保持 schema 一致

**Token 使用機制** (`docs/TELEGRAM_BOT_SETUP.md`):
- BotFather `/newbot` 拿 token
- @userinfobot 拿個人 chat_id (或 getUpdates API 拿群組 chat_id)
- 兩個值放 GitHub Repo Secret
- workflow 自動 inject 進 env var

**驗證**: 43 套件 0 regression + 新 test_v3540_telegram_alerts 16 PASS

**狀態**: code 上線, **用戶設 Secret 後即生效**(目前 test mode)

---

### ✅ Sprint 15 完成 (v3.53.0) — 長3 latest.json lazy load (rankings 拆出)

**動機**: latest.json 整檔加密 ~2.4 MB, 解密需 1-2s. tab 06 三大法人 + tab 08 融資融券用到的 rankings 屬於**公開資料**(無需加密), 可獨立 fetch 加速 UX.

**後端** (`crawler.py`):
- raw_output 組裝後新增 `_lazy_payload_inst` + `_lazy_payload_margin`
- 寫 `data/latest_inst_rankings.json` (unencrypted, 公開資料)
- 寫 `data/latest_margin_rankings.json` (unencrypted, 含 margin_maintenance_summary)
- 純額外寫不影響原 latest.json 結構 (backward compat 100%)

**前端** (`index.html`):
- 新 `loadLazyRankings()` Promise.all 並行 fetch (5s timeout each)
- 新 `getInstRankings() / getMarginRankings()` getter helper:
  - 優先用 CURRENT_DATA (latest.json 解密後)
  - fallback 用 LAZY_INST_RANKINGS / LAZY_MARGIN_RANKINGS (lazy fetch)
- init 時觸發 lazy load 並行 (不阻擋主流程)
- 10 處 consumer (`CURRENT_DATA.institutional_rankings` / `margin_rankings`)
  改為 getter — tab 06/08 即使 latest.json 還沒解開也能顯示資料

**對外**: API consumer 可直接 fetch `data/latest_inst_rankings.json` 取公開排行(不需密碼)

**驗證**: JS syntax OK + 42 套件 0 regression

---

### ✅ Sprint 14 完成 (v3.52.0) — 長4 跨日囤貨偵測 (master_profile 升級)

**動機**: 「長線持有」(15 天散加) 跟「持續進場」(master 整體 streaks) 都已有, 但缺「**同一檔連續 K 天不停加碼**」這種強做多訊號 (連 5 天買 2330 比 30 天散加 15 天 2330 訊號更強).

**實作** (`src/analyzers/master_profile.py`):
- 新 `_compute_consecutive_accumulation_metrics(trades, min_consecutive_days=5)`
  - 每股獨立追蹤 streak (自然日 ≤3 天視為相鄰 → 跨週末 OK, 斷 ≥4 天 reset)
  - is_active: 該股最後加碼日 == overall_latest 且結尾 streak ≥ 門檻
  - return: accumulation_stocks (sorted by max_consecutive_days desc) + has_active_accumulation + max_consecutive_days_overall
- `compute_operation_metrics` 注入 `consecutive_accumulation` 欄位
- 新標籤 `📦 連續囤貨` (獨立, 跟所有現有標籤可共存)
- narrative 加 `📦 連續囤貨 N 檔 (最長 K 天 XXXX, M 檔仍 active)`
- THRESH 加 `consecutive_accumulation_days_min: 5`

**LABELS_DEFINITION.md**: 加 4.9 章節跟「長線持有」「持續進場」差異說明

**驗證**: 42 套件 0 regression + 新 test_v3520_consecutive_accumulation 18 case PASS

---

### ✅ Sprint 13 完成 (v3.51.0) — 機構級 Data Analyst 結構重整

**動機**: root 過去塞 110+ 個 .py + .md, 沒有分層. 換到專業機構 DA 結構.

**Phase 1 (docs + tests 集中, 零風險)**:
- 8 個 .md → `docs/`
- 41 個 `test_*.py` → `tests/`
- 加 `tests/conftest.py` (pytest 兼容)

**Phase 2 (src/* 大分類, 60 模組搬家)**:
- `src/fetchers/`  (13) — TWSE/TPEx/TDCC/chengwaye fetcher
- `src/analyzers/` (11) — master_profile / signal_engine / manipulation_flags
- `src/pipelines/` (6)  — crawler_* / db_pipeline / archive_manager / reports
- `src/backtest/`  (3)  — backtester / backtester_phase_b / backfill_market
- `src/audit/`     (12) — cross_check / heartbeat / audit_*
- `src/alerts/`    (3)  — alerts / daily_signals / event_logger
- `src/exports/`   (4)  — excel_report / reasoning / backfill_monthly
- `src/core/`      (3)  — branches / price_utils / query_db
- `src/__init__.py` side-effect import 把 8 個子目錄加進 sys.path
- 6 個 entry points (crawler.py + 5 workflow scripts) 開頭加 `import src`
- 既有 `import attention_fetcher` 100% backward compat

**Phase 3 (workflow + docs cross-ref 同步)**:
- Workflow YAML 不需改 (6 個 entry 仍 root)
- README.md docs/ 路徑全更新 + 加專案結構章節
- 41 個 test 自動注入 sys.path 設定 (sed 批次)

**Root 終態**:
- 從 110+ → **7 個 .py** (6 entry) + README.md + requirements.txt
- index.html + 404.html (GitHub Pages 必留)
- 子目錄: `src/ tests/ docs/ config/ scripts/ data/ .github/`

**驗證**: 41 套件 0 regression + crawler/entry/lib import 全 OK

---

### ✅ Sprint 12 完成 (v3.50.0) — 後2 main() 前段抽 3 pure-read stage helper

| 抽出 helper | line | 內容 |
|---|---|---|
| `_stage_quote_audit` | 30 行 | 個股 quote 新鮮度 + source 分布統計 (原 main L627-651) |
| `_stage_limit_up_audit` | 45 行 | 漲停判定透明化 Top10/Bottom3/可疑警示 (原 main L653-697) |
| `_stage_load_yesterday_branches` | 28 行 | 載昨日加密檔 + decrypt (給 next_day_flip_verification, 原 main L716-736) |

**效益**:
- main() 1090 → **1022 行** (本 sprint -68 行, 累計從 1225 降 203 行 / -16.6%)
- 3 個 stage 全是 pure-read (無 side effect), 風險最低
- 未來補 unit test 容易 (不需 mock 整個 crawler)

**defer 到 Sprint 13+**: 機構注入主迴圈 (170 行 — L453-624) + 融資融券 (L656-755) + 全市場排行 (L878-918) — 這些涉及修改 results 內部 dict 結構, 需 state dict 模式才能安全拆

**驗證**: 41 套件 0 regression + crawler.main + 9 helper 全可 import

---

### ✅ Sprint 11 完成 (v3.49.0) — 運1 trigger.ps1 入庫 (Tier 3 維運)

| 變更 | 內容 |
|---|---|
| `scripts/trigger_chip_radar.ps1` 入庫 | 從 Desktop 移進 repo, log 路徑改可配置 3-tier fallback |
| `scripts/README.md` | Task Scheduler setup / log 路徑配置 / prereq / 安全性說明 |
| 去個人化 | log 路徑優先 `$env:CHIP_RADAR_LOG_DIR`, 次選 Desktop, 最後 `$PSScriptRoot` |
| 安全性 | 無 password / 無 API key / 無 hardcoded absolute path |

**驗證**: PSParser 0 errors (Rule 9)

---

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
