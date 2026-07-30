# Telegram Bot 推播設定 (v3.54.0 Sprint 16 長2)

> Chip Radar 每日 daily-full crawler 跑完後,把偵測到的警報 (外資爆量/PCR 極端/漲停過熱/結算提醒/內部人) 推播到 Telegram.
>
> 跟 Discord 並行存在,各自獨立 token. 兩個都沒設 → 走 test mode 只 print 不推.

## Token 機制速覽

```
Telegram                              GitHub Actions (cloud)
─────────                              ──────────────────────
@BotFather  ──[ /newbot ]──>  TELEGRAM_BOT_TOKEN
@userinfobot ──[ /start ]──>  TELEGRAM_CHAT_ID

                                     ┌───────────────────┐
       兩個都當作 Repo Secret  ───>  │ env var inject    │
                                     └─────────┬─────────┘
                                               ↓
                                     alerts.send_telegram()
                                     POST api.telegram.org/bot<TOKEN>/sendMessage
                                            {chat_id, text, parse_mode=Markdown}
```

## 設定步驟

### 1. 跟 @BotFather 建 bot 拿 token

1. 在 Telegram 搜尋 [@BotFather](https://t.me/BotFather) 並 start chat
2. 輸入 `/newbot`
3. 給 bot 一個顯示名(如 `My Chip Radar Bot`)
4. 給 bot 一個 username(必須結尾是 `bot`,如 `my_chip_radar_bot`)
5. BotFather 會回覆一個 token,格式如:
   ```
   123456789:ABCdefGhiJklMnOpQrStUvWxYz1234567
   ```
   **這就是 `TELEGRAM_BOT_TOKEN`** — 即刻保存,不要外流(等同 bot 密碼)

### 2. 取得 chat_id

兩個方法:

**方法 A — 個人 chat (推到你自己)**
1. 在 Telegram 搜尋 [@userinfobot](https://t.me/userinfobot)
2. 點 start,bot 會回你的 chat ID(數字,如 `987654321`)
3. **這就是 `TELEGRAM_CHAT_ID`**
4. 重要:你必須先跟你自己建的 bot 對話一次(輸入任何訊息),bot 才能推給你

**方法 B — 群組 chat (推到群組)**
1. 把你的 bot 加進群組
2. 在群組發訊息 @你的 bot
3. 開瀏覽器訪問:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
4. 找 `chat` → `id`,通常是負數(如 `-1001234567890`)
5. **這就是 `TELEGRAM_CHAT_ID`**

### 3. 設定 GitHub Repo Secret

1. 進 GitHub Repo → Settings → Secrets and variables → Actions → New repository secret
2. 加 2 個 secret:
   ```
   Name:  TELEGRAM_BOT_TOKEN
   Value: 123456789:ABCdef...
   ─────────────────────────
   Name:  TELEGRAM_CHAT_ID
   Value: 987654321
   ```
3. 下次 daily-full workflow 跑時自動讀取

### 4. 驗證

**(a) 先看 digest 長什麼樣(不需 token,不會真的推)**

```powershell
python src/alerts/alerts.py
```

會用內建 mock 資料印出完整的每日摘要預覽。

**(b) 真的推一則到你的 Telegram**

```powershell
$env:TELEGRAM_BOT_TOKEN = '123456789:ABCdef...'
$env:TELEGRAM_CHAT_ID = '987654321'
python -c "from src.alerts.alerts import send_telegram; send_telegram('Hello from Chip Radar!')"
```

成功會在 Telegram 收到訊息,console 印 `✓ Telegram 推播成功`.

**(c) 端到端:手動觸發雲端 workflow**

```bash
gh workflow run daily-full.yml --repo DRwillychiu/CHIP_RADAR_TW
```

跑完約 11-15 分鐘後應收到一則完整 digest。若沒收到,看 Actions log 裡
`Run full crawler` step 有沒有印 `✓ Telegram 推播成功` 或 `[TEST MODE]`
(印 TEST MODE = secret 沒讀到)。

## 推播內容 (v3.55.0 起)

每個交易日 daily-full crawler 跑完後**固定推一則** — 沒警報也推,
讓你不必盯 GitHub Actions 綠燈就知道爬蟲跑完了:

```
📊 Chip Radar · 20260729

✅ 爬蟲完成 (full) · 21:23
分點 81/81 · 個股 1,842 · 法人 1,795

━━ 今日籌碼 ━━
🦅 外資現貨 -7,512 張
📈 外資期貨未平倉 -42,180 口
📊 P/C Ratio 1.85
🔥 漲停 32 檔
💰 融資高風險 12 檔 · 斷頭 3 檔

━━ 警報 3 則 ━━
🔴 🦅 外資極端賣超
　　外資現貨賣超 7,512 張 (閾值 5,000)
🔴 📊 PCR 極端看空
　　P/C Ratio = 1.85 (>1.8), 散戶極度看空 → 反指標偏多
🟡 🔥 漲停家數過熱
　　今日漲停 32 檔 (閾值 30), 市場過熱要小心
```

三個區塊各自的降級行為:

| 狀況 | 顯示 |
|---|---|
| 分點有失敗 | `⚠️ 爬蟲部分失敗` + `分點 68/81 · 13 失敗` |
| 期貨/融資抓不到 | 該行直接省略,其他行照常 (不會整則推播失敗) |
| 無警報 | 警報區塊顯示 `今日無重大警報訊號` |
| crawler 整個掛掉 | 由 workflow 補推 `🚨 Daily Full Crawl 失敗` + Actions log 連結 |

crawler 成功時由 `alerts.py` 內部推、失敗時由 workflow 推,**兩條路互斥,永遠恰好一則**。

### 為什麼一天只收到一則(而不是三則)

`daily-full.yml` 有 21:17 / 22:37 / 23:47 三層兜底排程,主排程成功後兜底**仍會完整跑一次 crawler**
(只是 commit 時 `git diff --quiet` 變 no-op)。若不處理,同一天會收到 3 則幾乎一樣的訊息。

去重機制:workflow 在 crawler 跑之前先讀舊 `latest.json` 的 `trade_date`
(明文外層,不需密碼),傳成 `CHIP_RADAR_PREV_TRADE_DATE`。
`alerts.is_redundant_rerun()` 比對後若相同 → 判定為兜底重跑 → 跳過推播。

未設此環境變數時一律推(保守策略:寧可多推也不要漏)。

### 跟 GitHub 通知的關係

**並行,不取代。** GitHub 原有的 Actions 失敗 email 和 heartbeat 自動開 issue 全部保留,
Telegram 是額外多一條管道。要關掉 GitHub email 請自行到帳號的
`Settings → Notifications` 調整 — 建議等 TG 連續正常跑幾天再關。

## 訊息格式與上限

- **parse_mode = HTML**(不是 Markdown)—— 股票名稱/分點名稱可能含 `_` `*` `` ` `` `[`
  等 Markdown 元字元,未轉義會讓 Telegram 回 HTTP 400。HTML 只需轉義 `< > &`,
  由 `alerts._esc()` 統一處理。
- 單則 4096 字 (digest 通常 < 800 字, 不會超)
- 推到群組需 bot 是 admin 或 group privacy mode off
- API rate limit: 30 msg/sec, 我們一天最多推 1 次, 不會撞

## 安全性

- TELEGRAM_BOT_TOKEN 等同 bot 密碼 — 不要 commit 進 repo
- 萬一 leak → @BotFather → /revoke 重發 token
- chat_id 沒密碼性質但是 PII, 也用 Secret 存放

## 取消推播

刪掉 GitHub Secret 之一就好:
- 缺 `TELEGRAM_BOT_TOKEN` 或 `TELEGRAM_CHAT_ID` 任一 → 自動降回 test mode (print only)

## 跟 Discord 共存

Discord (DISCORD_WEBHOOK_URL) 跟 Telegram (TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID) 各自獨立:
- 都設 → 都推
- 只設一個 → 只推那個
- 都沒設 → 全 test mode

## 故障排除

| 症狀 | 可能原因 |
|---|---|
| HTTP 401 Unauthorized | TELEGRAM_BOT_TOKEN 錯了, /revoke 重發 |
| HTTP 400 Bad Request | text 含未轉義字元 — v3.55.0 起走 HTML + `_esc()`,若仍發生表示有新欄位沒過 `_esc()` |
| HTTP 403 Forbidden | bot 還沒收過你的訊息 (個人 chat 需先 start 一次) |
| HTTP 429 Too Many Requests | rate limit (一天 1 次不會撞, 除非你手動 trigger 多次) |
| 沒推但 console 印「test mode」 | env var 沒設或值為空, 檢查 GitHub Secret 名稱有沒有打錯 |
| console 印「兜底排程重跑…跳過」 | 正常 — 今天已推過, 這是 22:37/23:47 兜底那次 |
| 一天收到 3 則重複 | `CHIP_RADAR_PREV_TRADE_DATE` 沒傳進去, 檢查 workflow 的 `Record previous trade date` step |
| 摘要裡「外資現貨」那行不見 | `institutional_rankings.foreign.total_net_lots` 沒產出, 見 crawler.py `build_inst_ranking()` |
