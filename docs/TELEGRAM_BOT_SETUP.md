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

```powershell
# 本地測試 (Windows PowerShell)
$env:TELEGRAM_BOT_TOKEN = '123456789:ABCdef...'
$env:TELEGRAM_CHAT_ID = '987654321'
python -c "from src.alerts.alerts import send_telegram; send_telegram('Hello from Chip Radar!')"
```

成功會在 Telegram 收到訊息,console 印 `✓ Telegram 推播成功`.

## 推播內容

每日 daily-full crawler 跑完後推一則(僅當有警報):

```
📊 Chip Radar 20260621

共 3 則警報  (foreign_extreme: 1 / limit_up: 2)

▸ 外資爆量
  +5500 張 (門檻 5000)
▸ 漲停過熱
  32 檔 (門檻 30)
▸ 結算提醒
  D-2 (settlement_date: 20260625)
```

無警報日 → 推 `今日無重大警報訊號` (還是會推一則, 讓你知道 crawler 跑了).

## 訊息上限

- 單則 4096 字 (我們 alert 通常 < 1000 字, 不會超)
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
| HTTP 400 Bad Request | text 含未轉義的 Markdown 字元 (改 parse_mode=None 試試) |
| HTTP 403 Forbidden | bot 還沒收過你的訊息 (個人 chat 需先 start 一次) |
| HTTP 429 Too Many Requests | rate limit (一天 1 次不會撞, 除非你手動 trigger 多次) |
| 沒推但 console 印「test mode」 | env var 沒設或值為空, 檢查 GitHub Secret |
