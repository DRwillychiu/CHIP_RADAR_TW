# Chip Radar TW · 系統架構設計文件

> **目的**:給「接手這個 repo 的另一個工程師」一張完整地圖。
> **受眾**:讀程式碼前需要先建心智模型的開發者(非終端使用者 — 那份請看 `README.md`)。
> **適用版本**:v3.30.1(2026-05-24),累計戰力 100/100,production-grade 6.0/10。
> **最後修訂**:2026-05-24。

---

## 0. 一句話定位

```
資料源 (公開 API)  →  Python crawler  →  加密 JSON + Excel
                                              ↓
                              GitHub Pages 靜態網頁(瀏覽器解密)
```

只有「寫」是自動排程的;**沒有後端 server、沒有 DB、沒有付費 API**。所有「動態」其實是 daily-cron 寫死的 JSON。

---

## 1. 系統整體資料流

```
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 1: 資料源 (公開,免登入,無 API key)                             │
│  ├─ TWSE   分點 c=B/c=E、STOCK_DAY、T86、MI_INDEX、MI_MARGN            │
│  ├─ TPEx   afterTrading/BIG5、OTC 分點                                 │
│  ├─ TAIFEX futContractsDateDown、callsAndPutsDateDown、pcRatioDown    │
│  └─ MOPS   ajax_stapap1(董監持股)、ajax_t05st01(重大訊息)             │
└─────────────────┬────────────────────────────────────────────────────┘
                  ↓  (requests + retry,v3.31+ 將 migrate 至 safe_fetch)
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 2: crawler.py 主流程(9 階段, v3.35.0 拆三層 fetch/pipeline/output)│
│  ① 分點抓取  ② 行情合併  ③ FIFO 部位累積  ④ 期貨/選擇權               │
│  ⑤ 融資融券  ⑥ 內部人/重大訊息  ⑦ 信號層(溫度計+引擎)               │
│  ⑧ AI 解讀層注入(v3.30.0)  ⑨ Excel + 加密 JSON 寫出                 │
└─────────────────┬────────────────────────────────────────────────────┘
                  ↓  encrypt_data(gzip=True) + base64
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 3: 輸出產物(commit 進 repo)                                   │
│  ├─ data/latest.json          加密 + gzip(預期 3-4 MB)               │
│  ├─ data/YYYYMMDD.json        每日歷史                                │
│  ├─ data/stock_history.json   30 天個股歷史(未加密)                  │
│  ├─ data/temp_history.json    60 天溫度計信號                         │
│  ├─ data/daily_audit.json     auto_audit verdict                      │
│  ├─ data/daily_signal.json    signal_engine 輸出                      │
│  └─ data/reports/*.xlsx       老闆版 Excel(latest + 30 sheet)        │
└─────────────────┬────────────────────────────────────────────────────┘
                  ↓  git commit + push by GitHub Actions
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 4: GitHub Pages(靜態託管)                                     │
│  瀏覽器 fetch latest.json → AES-256-GCM 解密 → gzip 解壓 → render     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module Inventory(27 個 production + 15 個 test)

按職責分層:

### 2.1 資料抓取層(Data Fetch · 7 個)

| Module | 行數 | 職責 | 關鍵函式 |
|---|---|---|---|
| `branches.py` | 516 | 56 watched branches + 13 master + style mapping | `WATCHED_BRANCHES`, `MASTER_STYLES` |
| `institutional.py` | 643 | 三大法人(TWSE + TPEx)+ 個股行情 | `fetch_all_public_data`, `_yyyymmdd_to_roc` |
| `margin.py` | 490 | 融資融券(TWSE + HiStock 雙源) | `fetch_margin_*`, `inject_margin_into_stocks` |
| `futures.py` | 971 | TAIFEX 期貨/選擇權(83 欄位審計過) | `fetch_*` 各端點函式 |
| `insiders.py` | 428 | MOPS 董監持股 + 重大訊息 | `fetch_*`, classify_event |
| `history.py` | 387 | 30 天個股歷史累積 | `update_history`, `load_history` |
| `safe_fetch.py` | ~80 | **v3.30.1 新** HTTP size limit defense | `safe_get`, `safe_post`, `ResponseTooLargeError` |

### 2.2 分析層(Analytics · 5 個)

| Module | 行數 | 職責 |
|---|---|---|
| `market_classifier.py` | 385 | 上市/上櫃/興櫃/ETF/ETF_active/preferred/KY 分類 |
| `industry_classifier.py` | 360 | 1965 檔產業分類(TWSE 1082 + TPEx 883) |
| `price_utils.py` | ~150 | **v3.28** Tick-size 精確漲停價(6 區間) |
| `signal_engine.py` | 323 | **v3.29** Backtest-driven 信號加權引擎 |
| `trade_pattern.py` | 249 | **v3.30.0** 隔日沖/當沖/波段/部分當沖 分類 + 模板 narrative |

### 2.3 輸出層(Output · 2 個)

| Module | 行數 | 職責 |
|---|---|---|
| `excel_report.py` | 822 | 老闆版 multi-sheet Excel(13 master 並列,每分點 10 row,8563 例外 20 row,ETF 排除) |
| `reports.py` | 796 | 週報/月報 markdown 生成 |

### 2.4 審計/交叉驗證層(Audit & Cross-Check · 7 個)

| Module | 行數 | 職責 | 觸發 |
|---|---|---|---|
| `audit_branches.py` | 249 | 分點 3 層審計(v3.21) | crawler 內 |
| `audit_margin.py` | 199 | 融資融券審計(v3.21) | crawler 內 |
| `signal_audit.py` | 218 | 信號 hit-rate 校準(v3.27.1) | 累積 30+ 天後手動跑 |
| `auto_audit.py` | 251 | **v3.29.3** V1 自動 daily audit(PASS/WARN/FAIL) | crawler 結尾自動 |
| `excel_full_audit.py` | 217 | V1 全分點 row 數 + filter 完整掃描 | manual |
| `excel_content_audit.py` | 309 | V2 9 維度 Excel ↔ JSON 比對 | manual |
| `stock_cross_check.py` | 210 | V2 個股 close vs TWSE STOCK_DAY 對齊 | manual |
| `margin_cross_check.py` | 147 | W1 融資 vs TWSE MI_MARGN | manual |
| `insider_cross_check.py` | ~150 | U1 內部人 vs MOPS 原始 | manual |
| `histock_verifier.py` | 316 | HiStock 融資融券交叉驗證 | margin.py 內 |
| `backtester.py` | 490 | **v3.29** 1 年回測(247 配對,信號 hit rate) | manual 一次性 |
| `alerts.py` | 348 | Discord 警報(v3.20,目前 PARKED) | crawler 結尾(可關) |

### 2.5 主程式(Entry Point · 1 個 + 三層 · v3.35.0 B1 拆分)

| Module | 行數 | 職責 |
|---|---|---|
| `crawler.py` | **~1314** | 薄編排層: main() 9 階段 + main_margin_only() + **re-export hub** |
| `crawler_fetch.py` | ~240 | 抓取層: TWSE 分點雙模式爬取 + merge_rows (trade_style 判定源頭) |
| `crawler_pipeline.py` | ~1479 | 計算層: 溫度計 7 信號 + FIFO 部位 + 期間/漲停/隔日沖/master 彙總 |
| `crawler_output.py` | ~73 | 輸出層: AES-256-GCM + gzip 加密 (magic bytes auto-detect) |

**v3.35.0 (B1, 2026-06-11) 拆分原則**:
- daily-cron 進入點不變: `python crawler.py`
- **向後相容 re-export**: 33 個公開名稱 (encrypt_data/decrypt_data/fetch_branch_combined/
  compute_chip_temperature 等) 全部在 crawler.py re-export — 7 個 module + tests 的
  `from crawler import X` 一行不用改
- 依賴方向: crawler.py → pipeline → output (加密), crawler.py → fetch (無循環)
- main() 1000 行編排邏輯留在 crawler.py (sequential orchestration, 拆 stage 是 Phase 2)

### 2.6 測試(Test · 15 套件 / 159 case)

所有測試獨立可跑,不用 pytest framework:
```bash
python test_v3301_gzip_encrypt.py     # exit 0 = PASS
```

完整列表見 `README.md` 或 memory.md。

---

## 3. crawler.py 主流程(9 階段)

`main()` 從 line 1788 開始。流程編號對應 stdout `[1/9]` … `[9/9]` 訊息(實際數字可能因版本微調):

```
[1] 環境 + 參數驗證
    └─ 讀 CHIP_RADAR_PASSWORD env(無則 fail-fast)
    └─ 決定 trade_date(預設今天,週末/假日往前找)
    └─ TW_TZ = UTC+8

[2] 分點抓取(序列,避免 TWSE 封 IP)
    └─ 56 branches × 2 modes(c=B 金額 + c=E 張數)
    └─ fetch_branch_combined 合併雙模式 → 每個 stock dict 有 buy_lot/buy_amt 等
    └─ MASTER_MAPPING 標記 master/style/branch_name

[3] 行情合併(institutional.fetch_all_public_data)
    └─ TWSE STOCK_DAY_ALL + TPEx + MI_INDEX(三大法人個股版)
    └─ 偵測 stale(v3.27.3 防 21:30 還在 publish 舊資料)
    └─ priority_codes fallback 至 MIS 即時 API
    └─ 注入 prev_close → 精確 change_pct(v3.28)

[4] 漲停判定(price_utils.calc_limit_up_price)
    └─ 用 prev_close + tick-size 反推今日漲停價
    └─ 比對 close,is_limit_up = True/False
    └─ v3.27.4 Limit-Up Audit 印 Top10/Bottom3/邊界

[5] FIFO 部位追蹤(累積 PnL,基準日 2026/4/21)
    └─ load_positions(decrypt positions.json)
    └─ apply_day_to_positions 把今天交易扣進 FIFO queue
    └─ compute_period_summaries(累積/週/月)
    └─ save_positions(encrypt 寫回)

[6] 期貨/選擇權(futures.py)
    └─ 9 個 TAIFEX 端點全抓
    └─ 散戶小台 + 外資等效大台 等衍生指標
    └─ 結算日推算(永遠驗國定假日,不假設第三週三)

[7] 融資融券 + 內部人 + 重大訊息
    └─ margin.fetch_margin_data + inject 入分點個股
    └─ insiders.fetch_director_holdings(50 watched 個股)
    └─ insiders.fetch_material_events(sii + otc)
    └─ alerts.run_alerts (Discord webhook 推播,目前 PARKED)

[8] 信號層(v3.27/v3.29)
    └─ compute_chip_temperature 7 信號 → 0-100 分
    └─ update_temp_history(累積 60 天,給 signal_audit 校準)
    └─ signal_engine.compute_daily_signal → daily_signal.json
    └─ auto_audit.run_audit → daily_audit.json + GH Actions ::error::

[9] 輸出層
    └─ trade_pattern.inject_trade_patterns(v3.30.0,每 stock 加 2 field)
    └─ excel_report.build_workbook → latest.xlsx + chip_radar_YYYYMMDD.xlsx
    └─ encrypt_data(use_gzip=True, v3.30.1)
    └─ 寫 data/latest.json + data/YYYYMMDD.json
    └─ git commit + push(由 GitHub Actions workflow 完成)
```

**margin_only 模式**(`CHIP_RADAR_STAGE=margin_only`):跳過 [2][3][6][8][9],只重抓融資、解密既有 latest.json、更新 margin_data + 重加密。供 Margin Refresh 7-schedule 用。

---

## 4. 加密協議(Encryption Protocol)

**安全模型**:單一 password 對稱加密。資料公開於 GitHub,只有知道 password 的瀏覽器能解。

### 4.1 加密層(crawler.py `encrypt_data`)

```
plaintext (JSON UTF-8)
  ↓  [v3.30.1] gzip.compress(level=9)
  ↓
plain_bytes (gzipped, magic 1F 8B 開頭)
  ↓
AES-256-GCM encrypt:
  salt = os.urandom(16)
  iv   = os.urandom(12)
  key  = PBKDF2-SHA256(password, salt, 100_000 iterations, 32 bytes)
  ct   = AESGCM(key).encrypt(iv, plain_bytes, None)
  ↓
base64(salt + iv + ct)
  ↓
Token string(寫入 latest.json["data"])
```

### 4.2 解密層(crawler.py `decrypt_data` + index.html `decryptToken`)

**Magic bytes auto-detect** 是 v3.30.1 backward compat 的核心 trick:

```
token (base64)
  ↓
salt(16) + iv(12) + ct(rest)
  ↓
key = PBKDF2(password, salt, 100k, 32)
  ↓
plain_bytes = AESGCM(key).decrypt(iv, ct, None)
  ↓
if plain_bytes[0:2] == b'\x1F\x8B':     ← v3.30.1+ gzipped
    plain_bytes = gzip.decompress(plain_bytes)
elif plain_bytes[0:1] == b'{':           ← legacy plaintext JSON
    pass                                  ← 直接用,100% backward compat
  ↓
plaintext = plain_bytes.decode('utf-8')
```

**為何用 magic bytes 而非 metadata 旗標?**
- 加密 token 外層的 `{"encrypted": true, "algorithm": ...}` 是明文 metadata,但 *內層* plaintext 是否壓縮不能寫進明文(攻擊者也看得到)
- AES-GCM 解密後第一個 byte 是「最便宜的真實情報」— gzip 0x1F、JSON `{` 0x7B,永遠不衝突
- 結果:**舊未壓縮 ciphertext 完全不需 re-encrypt 就能繼續工作**

### 4.3 前端解密(index.html `decryptToken`)

瀏覽器原生 API,無外部依賴:

```javascript
const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' }, ...);
const plainBuf = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
const bytes = new Uint8Array(plainBuf);
if (bytes[0] === 0x1F && bytes[1] === 0x8B) {
    const stream = new Blob([plainBuf]).stream().pipeThrough(new DecompressionStream('gzip'));
    return new TextDecoder().decode(await new Response(stream).arrayBuffer());
}
return new TextDecoder().decode(plainBuf);
```

`DecompressionStream('gzip')` 是 Web Streams Standard,**Chrome 80+ / Safari 16.4+ / Firefox 113+** 支援。

### 4.4 改動加密層的鐵則

🚨 **backward compat 是不能破的合約**。舊 latest.json + 舊 dated JSON 是 read-only 歷史,如果改加密邏輯讓舊檔解不開,等於毀資料。

新加密改動 checklist:
- [ ] 解密層用 magic bytes / version field 自動分路
- [ ] 寫測試讀「假的舊格式 ciphertext」確認仍能解
- [ ] 前端 JS 同步加 fallback 分支
- [ ] PBKDF2 iteration 數**永不下調**(只能升)

---

## 5. 排程體系(4 GitHub workflows + Windows Task Scheduler)

### 5.1 為什麼用 Windows Task Scheduler 觸發,不全靠 GitHub cron?

**GitHub Actions cron 不可靠**:
- 整點(`0 12`)塞車,實測延遲 90 分鐘+
- 6/1 觀察到 21:00 排程 22:30 才跑

**Windows Task Scheduler 本地觸發**(< 1 秒延遲):
- `trigger_chip_radar.ps1`(在桌機,**不在 repo**)用 `gh api workflow_dispatch` 直接觸發
- Poll workflow 結束後讀 `daily_audit.json`
- BurntToast / BalloonTip → Windows 桌面通知 PASS/WARN/FAIL

### 5.2 4 個 GitHub workflows

| Workflow | Cron(UTC) | TW 時間 | 用途 |
|---|---|---|---|
| `daily-full.yml` | `17 13 * * 1-5` + `37 14 * * 1-5` | 21:17 + 22:37(兜底) | 主流程,timeout 25 min |
| `margin-refresh.yml` | 7 個 schedule | 22:30/23:30/00:30/02:00/08:00/09:00/12:00 | 融資補抓(margin_only) |
| `keepalive.yml` | `0 20 * * 0` | 週日 04:00 | 空 commit 防 60 天 disable |
| `security-audit.yml` | `0 19 * * 0` | **週一 03:00**(v3.30.1) | pip-audit + safety scan |

雙保險:即使本地 Task Scheduler 沒觸發,GitHub cron 還是會跑(只是晚)。

### 5.3 Workflow → main_only 切換

```yaml
# daily-full.yml
env:
  CHIP_RADAR_STAGE: full         # 或 margin_only
```

crawler 結尾讀 env var 決定 `main()` vs `main_margin_only()`。

---

## 6. 資料源契約(Data Sources Contract)

所有 API **公開、免登入、無 key、無 rate limit 文件**。實測 retry 規則靠經驗。

| 來源 | 端點範例 | 公告時間(TW) | 已知特性 |
|---|---|---|---|
| TWSE 分點 | `bsr_zero/twse_bsr.html?c=B&s={code}` | T+0 16:30 | HTML scrape,16:00 前抓會缺尾盤;分點頁面 publish Top 15 買 + Top 15 賣(高價低張可能漏,v3.27.2 用 close 反推) |
| TWSE 個股 | `STOCK_DAY_ALL` / `STOCK_DAY` | T+0 17:30 | OpenAPI,**會 stale**(v3.27.3 偵測) |
| TWSE 三大法人 | `T86` | T+0 17:00 | OpenAPI |
| TWSE 融資 | `MI_MARGN` | T+0 22:00 | 22:00 後才 stable,故有 7-schedule |
| TWSE 漲跌 | `MI_INDEX` | T+0 17:00 | 含全市場 |
| TPEx 分點 | `afterTrading` BIG5 編碼 | T+0 17:00 | 編碼陷阱 |
| TPEx 個股 | OTC 對應端點 | T+0 17:30 | |
| TAIFEX 期貨 | `futContractsDateDown` | T+0 15:00 | CSV |
| TAIFEX 選擇權 | `callsAndPutsDateDown` | T+0 15:00 | |
| TAIFEX PCR | `/cht/3/pcRatio` | T+0 15:00 | v3.17.5 修對齊 |
| TAIFEX 夜盤 | `futContractsDateAhDown` | T+1 05:30 | |
| MOPS 董監 | `ajax_stapap1` | 不固定(月初) | POST 表單 |
| MOPS 重大訊息 | `ajax_t05st01` | 即時 | sii + otc 兩市場分開抓 |

### 6.1 容錯規則(從歷史 bug 沉澱)

1. **OpenAPI stale 偵測**:`fetch_all_public_data` 比對回傳 `Date` 欄位 ≠ 預期 → 全量 fallback 至 MIS 即時 API
2. **TWSE 分點 Top 15 盲點**:高價股(>2000 元)張數少擠不進張數榜 → 用 `close` 反推 `lot = amt / close`,加 `lot_source: estimated_from_close` 旗標保留誠實
3. **Net-seller 污染**:TWSE 分點頁面同時 publish 買榜 + 賣榜,一檔股票兩邊都可能上 → `_top_stocks_for_branch` 對所有 master 加 `net_amt > 0 or net_lot > 0` filter(v3.29.1)
4. **ETF 漏網**:`market_classifier` 回傳 lowercase `"etf"` / `"etf_active"`,filter set 也必須 lowercase + heuristic `code.startswith('00')` 不限長度(v3.29.7)
5. **Response size 防禦**(v3.30.1):`safe_fetch.safe_get(max_bytes=50_000_000)` stream + chunk monitor,目前 module 寫好,**未 migrate 至 crawler 既有 requests** — v3.31+ 漸進取代

---

## 7. 關鍵設計決策(ADR-style)

### ADR-1:為何單一 password,不做 OAuth/JWT?
- **Context**:私人工具,只服務 1-3 個信任使用者
- **Decision**:GitHub Secret 存 password,前端 prompt 輸入解鎖
- **Trade-off**:無 audit log、無撤銷機制 — 但省下後端整套
- **逃生口**:需要時改 password、重新加密 latest.json 即可

### ADR-2:為何 GitHub Pages 而非 Cloudflare Pages / Vercel?
- 已經在 GitHub commit data,GitHub Pages 零額外設定
- 不需 build step(純 static HTML)
- 免費、無流量限制(個人用)

### ADR-3:為何 Excel 用 openpyxl 不用 pandas?
- pandas 是 100MB+ 依賴,只為了寫 Excel 不值得
- openpyxl 直接操作 cell merge / font / fill,對齊手動範本更精準

### ADR-4:為何 trade_pattern 用 rule-based 不直接上 Claude API?
- **v3.30.0 MVP**:零 API 成本驗證 UX
- Phase 2(v3.31+):確認使用者看得懂後升級 Anthropic Claude Haiku(narrative 品質 75% → 95%)
- 規則寫死有透明度優勢(可解釋,可測)

### ADR-5:為何 latest.json 加 gzip 不拆 multi-file lazy load?
- gzip 是 1 個變數翻轉的最小改動
- multi-file lazy load 涉及前端 routing/state,改動面大
- gzip 拿 60-70% 縮減後,multi-file 邊際收益遞減(壓縮後 3-4 MB 可接受)
- 真要拆是 v3.31+ 中期工作

### ADR-6:為何 alerts.py 是 PARKED 而非刪除?
- v3.20 Discord 警報寫好但沒整合(等推播平台決策)
- 程式碼 348 行,刪可惜 — 改 PARKED 等 LINE/Telegram 上線時 wake up

### ADR-7:為何 27 個 module 沒拆 src/ 目錄?
- **Context**:`crawler.py` import 都是 `from branches import ...`
- 加目錄要全改 `from chip_radar.branches import ...`
- 改動面大、收益小,留到 v3.31+ 拆 module 時一併處理

### ADR-8:為何 requirements.txt 只有 `requests>=2.31.0`?
- **這是技術債**。`cryptography`、`openpyxl`、`beautifulsoup4` 都隱式依賴
- v3.30.1 pip-audit CI 跑 `--requirement requirements.txt` + 全 transitive 兩個 mode,部分緩解
- v3.31+ 待補完 requirements.txt

---

## 8. v3.31+ 擴充點(從審視 backlog 落地)

| 優先 | 任務 | 影響 module |
|---|---|---|
| 🔴 可維護性 | 寫 `ARCHITECTURE.md` + `ONBOARDING.md`(本檔 ✅) | docs only |
| 🟠 觀測 | `data/audit_history.json` 趨勢化 | auto_audit.py |
| 🟠 觀測 | `test_integration_crawler_smoke.py` + `test_api_contracts.py` | 新 test |
| ~~🟡 架構~~ | ~~`crawler.py` 2905 行拆 module(分 fetch / pipeline / output 三層)~~ ✅ v3.35.0 (B1) 完成 | crawler.py |
| 🟡 業務 | 規則外配化 `config/trade_pattern_rules.yaml` + `config/signal_weights.yaml` | trade_pattern.py + signal_engine.py |
| 🟡 一致性 | Excel 加「模式」欄(對齊網站 popup) | excel_report.py |
| 🟡 安全 | safe_fetch 整合進 crawler 主流程,migrate 既有 requests | crawler.py + 6 fetch module |
| 🟢 解讀 | 真 AI 取代模板(Anthropic Claude Haiku) | trade_pattern.py |
| 🟢 規模化 | latest.json 拆 multi-file lazy load | encrypt_data + 前端 |
| 🟢 通知 | LINE / Telegram 推播(wake alerts.py) | alerts.py |

---

## 9. 故障排除地圖

| 症狀 | 第一個查 | 第二個查 |
|---|---|---|
| 網站「解密驗證中」卡住 | `latest.json` 大小,> 10 MB 表示 v3.30.1 gzip 沒生效 | 瀏覽器 console 看 `decryptToken` 錯誤 |
| 網站解鎖失敗 | GitHub Secret `CHIP_RADAR_PASSWORD` 對嗎 | crawler log 看 encrypt_data 用對 password 嗎 |
| daily-full workflow timeout(>25 min) | TWSE 是否封 IP(分點抓太快) | TAIFEX 端點是否異常 |
| Excel 出現 ETF / 淨賣股 | `_top_stocks_for_branch` filter 順序對嗎(v3.29.1/v3.29.7) | `EXCLUDED_MARKET_TYPES` 是 lowercase 嗎 |
| 三大法人 dealer_net_lot ±1 張誤差 | v3.21 已修(institutional.py 整數除法 floor) | 仍誤差 → 看 `compute_alignment` |
| 漲停判定 False Positive | 是否 v3.27.4 之前版本(用 9.5% threshold) | 升 v3.28 `price_utils.calc_limit_up_price` |
| OpenAPI stale 21:30 還是舊資料 | `fetch_all_public_data` 印 `[Stale Detect]` warning 嗎 | priority_codes fallback 至 MIS 觸發了嗎 |
| pip-audit CI 紅 | repo Actions tab 看 `security-audit` log | 哪個套件 CVE,有 upgrade 路徑嗎 |

---

## 10. Map 速查

- 終端使用者文件:`README.md`
- 上手指南:`ONBOARDING.md`(7 天 day-by-day)
- 跨 session 記憶:`memory.md`
- 版本變更:每次 commit message + 桌面 `chip_radar_outputs/v*/CHANGES.md`
- 紀律規則:見 ONBOARDING.md §7
