# Chip Radar TW · 資料源 ToS 合規檢視

> **目的**:文件化每個第三方資料源的服務條款、商業使用限制、rate-limit policy,防七層 margin-refresh 被封 IP
> **版本**:v3.40.0 (B5 機構級 P0)
> **最後修訂**:2026-06-19

---

## 1. 各資料源 ToS 摘要

### TWSE (台灣證券交易所)
- **官方資料源**:`https://openapi.twse.com.tw/` (OpenAPI)+ `https://www.twse.com.tw/exchangeReport/` (CSV)
- **ToS 來源**:[TWSE 公開資訊觀測站使用條款](https://www.twse.com.tw/zh/page/about/about_use.html)
- **個人/教育使用**:✅ 允許
- **商業使用**:⚠️ 需向證交所申請授權 (本專案目前定位個人使用研究)
- **重新散布**:⚠️ 不可直接 redistribute raw data; 衍生分析可以
- **Rate limit**:無明文公告,經驗值「< 60 req/min」安全
- **本系統 source_id**:`TWSE_*` (MI_MARGN / MI_INDEX / STOCK_DAY_ALL / BFI82U 等)
- **本系統頻率**:約 50-100 次/日 (daily-full + margin-refresh 7 重) — 軟 quota 200/日

### TPEx (證券櫃買中心)
- **官方資料源**:`https://www.tpex.org.tw/openapi/v1/` + 舊 endpoint
- **ToS**:同 TWSE 類似條款,以「公開資訊」開放使用
- **本系統 source_id**:`TPEx_*`
- **本系統頻率**:< 50 次/日 — 軟 quota 100/日

### TAIFEX (期貨交易所)
- **官方資料源**:`https://www.taifex.com.tw/` (download endpoints)
- **ToS 來源**:[TAIFEX 公開資訊使用規範](https://www.taifex.com.tw/cht/9/aboutTaifex)
- **個人/教育使用**:✅ 允許
- **商業使用**:⚠️ 需向期交所詢問
- **Rate limit**:已知 Cloudflare 反爬;** 不可規避 CF_BOT 機制**(違反 ToS)
- **本系統 source_id**:`TAIFEX_*`
- **本系統頻率**:約 10-30 次/日 — 軟 quota 100/日

### TDCC (集保結算所)
- **官方資料源**:`https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5` (CSV, 每週六上午公布上週五資料)
- **ToS 來源**:[TDCC 集保戶股權分散表開放資料條款](https://www.tdcc.com.tw/portal/zh/smWeb/qryStock)
- **使用授權**:✅ 政府資料開放平台條款 (data.gov.tw),允許再利用,需註明來源
- **本系統 source_id**:`TDCC`
- **本系統頻率**:每週 1-2 次 (週六主排程 + 兜底)— 軟 quota 5/日

### chengwaye 台股盤面觀測站
- **資料源**:`https://chengwaye.com/disposal-forecast.html` (HTML)
- **ToS**:第三方民間網站,**官方 robots.txt 允許**
- **使用授權**:⚠️ 無明文授權,僅以「公開觀測」性質使用
- **風險**:他們改 HTML 或關站 → 處置股偵測 break (已 fallback)
- **本系統 source_id**:`chengwaye_disposal_forecast`
- **本系統頻率**:每日 1 次 (TTL 1 天 cache)— 軟 quota 10/日

### HiStock 嗨投資
- **資料源**:`https://histock.tw/stock/branch.aspx?no={code}` (HTML)
- **ToS**:第三方付費網站,**有公開查詢頁** (免費)
- **使用授權**:⚠️ 僅 cross-check 用途 (個股×分點 audit, 非主流程)
- **風險**:免費頁面隨時可能收費或下架
- **本系統 source_id**:`histock_branch_audit`
- **本系統頻率**:手動實跑 < 50 次/次 — 軟 quota 100/日

### MOPS (公開資訊觀測站)
- **資料源**:`https://mops.twse.com.tw/` (HTML + form-data POST)
- **ToS 來源**:[MOPS 使用約定](https://mops.twse.com.tw/mops/web/index)
- **使用授權**:✅ 公開資訊允許
- **本系統 source_id**:`MOPS_*` (內部人 + 重大訊息)
- **本系統頻率**:每日 50 檔 × 2 端點 — 軟 quota 200/日

---

## 2. Rate Limit Policy (B5 backoff 規範)

| 場景 | 策略 |
|---|---|
| HTTP 200 | 正常累計 quota |
| HTTP 429 / 503 | exponential backoff 1s → 2s → 4s → 8s (`DEFAULT_MAX_RETRIES=3`) |
| 連續 4 次失敗 | raise `RateLimitedError`,上游 try/except 接 |
| 軟 quota 達標 | `::warning::` GitHub Actions 提示,**不阻擋** |
| 同一日 connection refused 多次 | heartbeat 告警觸發 |

---

## 3. 七層 margin-refresh 自查 (B5 緊迫項)

`margin-refresh.yml` 目前 cron:
```
22:30 / 23:30 / 00:30 / 02:00 / 08:00 / 09:00 / 12:00
```

**每次跑會打:**
- `fetch_twse_margin()`(TWSE MI_MARGN) × 1
- `fetch_tpex_margin()`(TPEx) × 1
- `verify_margin_with_histock()` 可能多檔 stock 比對

**每日合計**:約 7 × 2 = 14 次 TWSE/TPEx call → 軟 quota 200 內,**OK**。

但 daily-full 也會打:
- TWSE OpenAPI(7-10 個端點 × 三層兜底)= 21-30 次/日

**合計每日 TWSE 約 35-44 次,遠在 200 安全範圍。**

**風險點**:若 margin-refresh 跨日重疊(例如 23:30 跑當天 + 00:30 跑次日),quota 紀錄正確切日 (`fetch_quota.json` 按 TW 日期分桶)。

---

## 4. 商業使用前置 (未來機構化 checklist)

若本專案要商業化或機構部署,必須先處理:

- [ ] 向 TWSE 申請商業資料授權 (有費)
- [ ] 向 TPEx 申請商業資料授權
- [ ] 向 TAIFEX 申請商業資料授權
- [ ] chengwaye + histock 改用付費 API 或停用該功能
- [ ] 加 `User-Agent: ChipRadar-Institutional/v3.40.0 (legal-contact@xxx)` 透明識別
- [ ] 加 fallback / cache TTL 機制 (B5 已有 backoff,需擴 cache)

---

## 5. 本文件變更紀錄

| 日期 | 版本 | 動作 |
|---|---|---|
| 2026-06-19 | v3.40.0 | 本文件首版,7 個資料源 ToS 摘要 + backoff policy 規範 + 七層 margin 自查 |

---

*本文件每半年 review。下次:2026-12-19*
