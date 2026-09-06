# Telegram Bot 推播設定 (v3.75.0)

> 本機 (PC) 排程跑完 daily-full 後,推「📱 手機摘要」+ `latest.xlsx` + 處置股圖卡。
>
> **跟雲端 email 並行,不取代。** 雲端 GitHub Actions 照常寄 email,
> 這裡講的是本機這條獨立的管道。

## 兩條路的分工

| | track 1 — 雲端 | track 2 — 本機 PC |
|---|---|---|
| 跑在哪 | GitHub Actions | Windows 工作排程器 |
| 分支 | `main` | `dev` |
| 資料寫到 | `data/` (commit 進 repo) | `local_data/` (不進 git) |
| 通知管道 | email + Excel 附件 | **Telegram** (本文件) |
| 設定在哪 | GitHub Repo Secrets | 專案根目錄 `.env` |

兩條完全獨立,互不影響。雲端那側**未做任何改動**。

## 本機每日推播

`scripts/scheduler.ps1` 的 daily-full 在 21:17 / 22:37 / 23:47 各跑一次完整鏈:

```
pre   refresh_attstock_disposal.py    抓 attstock 處置資料 → local_data/ (餵 Excel)
cmd   crawler.py                      完整爬蟲 + 產 Excel (含手機摘要 sheet),約 19 分鐘
post  daily_rolling_update.py         重算 quad + 重產 Excel
post  send_daily_telegram.py          推手機摘要 + latest.xlsx
post  push_disposal_telegram.py       推處置股圖卡 (下載 disposal-watch 雲端 artifact)
```

推播內容:

| # | 內容 | 大小 |
|---|---|---|
| 1 | 📱 手機摘要 (跟雲端 email 內容同構) | 約 500 字 |
| 2 | 📋 `latest.xlsx` | 約 570 KB |
| 3 | ⚠️ 處置股圖卡 × 4 (media group) | 約 1.4 MB |

### 多目標:同一份內容推給私訊 + 群組 (v3.75.0)

`TELEGRAM_CHAT_ID` 用**逗號分隔**就能指定多個對象,三項內容都會各推一份:

```
TELEGRAM_CHAT_ID=987654321,-1001234567890
```

群組是負數 id(超級群組 `-100` 開頭)。取得方式見下方「處置股圖卡」的
`--list-chats`,同一份清單兩支腳本共用。

`TELEGRAM_DISPOSAL_CHAT_ID` 只有在「處置股圖卡要推去跟摘要不同的地方」時才需要設,
**留空 = 跟著 `TELEGRAM_CHAT_ID` 推同一批**。

> ⚠️ `message_id` 是**該 chat 專屬**的 —— 拿 A chat 的 id 去 B chat 呼叫
> `editMessageMedia` 會直接失敗。所以狀態檔按 chat_id 分開存(見下節的 `targets`),
> 不是共用一組 id。中途加新對象時,那個對象當天沒有自己的 message_id,
> 會直接發新訊息而不是被 same_day 判定成「已推過」而整天收不到。

### 同一交易日重跑 → 編輯原訊息,不重發 (v3.73.4)

三層兜底每層都完整跑爬蟲,而後面幾次的資料可能更完整
(實測 21:17 抓到 76 分點、22:37 抓到 77)。所以:

| 情況 | 行為 |
|---|---|
| 新的交易日 | 發新訊息,記下 `message_id` |
| 同一天 + 內容有變 | `editMessageText` / `editMessageMedia` **原地更新** |
| 同一天 + 內容沒變 | 完全不打 API |
| 編輯失敗 (訊息被刪等) | 退回重發,不讓你漏掉更新 |

狀態存在 `local_data/.tg_last_push`,按 chat_id 分開存:

```json
{"trade_date": "20260904",
 "targets": {
   "987654321":  {"summary": {"message_id": 123, "hash": "..."},
                   "document": {"message_id": 125, "hash": "..."}},
   "-1001234567890": {"summary": {"...": "..."}, "document": {"...": "..."}}}}
```

會自動吃掉兩種舊格式:v3.73.1-3 的純日期字串、v3.73.4 的頂層
`summary`/`document`(自動歸給第一個 chat_id,避免升級後對它重發一次)。

Excel 附件不以檔案 hash 判斷是否更新 —— 每次 regen 內部時間戳都會變、
hash 必然不同,拿它當基準會導致每次重傳 570KB。改以「手機摘要有沒有變」為準。

### 處置股圖卡 (v3.75.0)

由 `scripts/push_disposal_telegram.py` 從 **disposal-watch 的雲端 artifact** 取圖,
本專案既不自己畫、也不在本機重跑上游管線。

```
disposal-watch (另一個 repo, 只有 main)
  GitHub Actions 21:17 台北
    fetch_disposal.py → 4 張 PNG + xlsx + txt
    ├─ 寄 Email (他自己的通道)
    └─ upload-artifact "disposal-report" (保留 14 天)
                          │
本機 21:37 (crawler 跑完後) ─┘ 下載 → 解壓 → 推 TG media group
```

推出去的四張依上游 `stamp_index` 的順序,圖上有「第 N 張 ‧ 共 N 張」角標:

| # | 檔名 | 內容 |
|---|---|---|
| 1 | `當日重點.png` | 即將進處置 (D-1 / D-2) 逐條件拆解 |
| 2 | `處置中清單.png` | 目前處置中的完整清單 |
| 3 | `自結預告.png` | 自結財報預告 (上游附帶,與處置無關) |
| 4 | `明日法說會.png` | 明日法說會,標注哪些是風險股 |

第 3、4 張上游允許產生失敗,缺了就少推幾張,不影響前兩張。

**為什麼是下載 artifact 而不是本機重算**

v3.74.x 用 `git archive origin/main` 把 disposal-watch 解到工作副本、在本機重跑
一次。2026-08-24 attstock 開始擋非瀏覽器 UA,本機 IP 隨後被封 —— 8/26~8/29
連四天沒推出任何圖卡,而舊版任何失敗都 `exit 0`,**靜默無感**。改抓 artifact 後:

- 資料 / 程式碼 / 產物三者都來自雲端那唯一一次執行,不是「應該會一樣」
- 本機不再呼叫 attstock,不會再因為對方限流而斷掉
- artifact 是穩定介面;上游仍在高速改版 (圖卡 8 月就從 1 張變成 4 張),
  借跑等於每天執行別人改到一半的程式碼

**為什麼不在 disposal-watch 那邊直接推**:那是另一個人的 repo,而且 GitHub Actions
的 `schedule` 只在預設分支觸發,workflow 放非預設分支不會被 cron 叫起來 ——
等於一定要動他的 `main`。不碰。

**認證**(二擇一,腳本優先用 gh):

```
gh CLI       winget install --id GitHub.cli 後 gh auth login
GITHUB_PAT   .env 放 fine-grained PAT,需 disposal-watch 的 Actions: Read-only
```

**收件對象**:預設跟著 `TELEGRAM_CHAT_ID`(私訊 + 群組都推)。只有要推去不同的地方
才設 `TELEGRAM_DISPOSAL_CHAT_ID`,一樣支援逗號分隔多個。查群組 id:

1. 把 bot 加進群組,**在群裡隨便發一則訊息**(這步不能省 —— Telegram 沒有
   「列出我加入哪些群組」的 API,只能從 `getUpdates` 的近期事件反推)
2. `python scripts/push_disposal_telegram.py --list-chats`
3. 把 id 加進 `.env` 的 `TELEGRAM_CHAT_ID`(逗號分隔)

Telegram 只保留約 24 小時的 update,第 1、2 步別隔太久。
推群組時 bot 需為群組成員(見下方「訊息格式與上限」的權限說明)。

> 一般群組(id 不是 `-100` 開頭)被 Telegram 升級成超級群組時 id 會整個換掉,
> 屆時推播會失敗並觸發告警,重跑一次 `--list-chats` 換新 id 即可。

**去重與告警** —— 三班(21:17 / 22:37 / 23:47)一律照跑,由 artifact id 決定要不要動。

> v3.74.x 的 `--fallback` 是「今天推過就整個跳過,連 artifact 都不看」,那是因為
> 當時要在本機重跑上游管線(1-2 分鐘 + 十幾個 attstock 呼叫),成功過就不值得
> 再算一次。改抓 artifact 後成本只剩一次清單查詢,再跳過反而讓雲端 22:17 備援
> 跑出的更新版本永遠推不出去。v3.75.0 起 `--fallback` 已是 no-op(保留只為了
> 不讓舊排程設定壞掉)。

| 情況 | 行為 |
|---|---|
| 同一份 artifact | 不重推 |
| 同報表日、artifact 更新了 | 逐則 `editMessageMedia` 原地更新,不洗版 |
| 雲端還沒產出新的 | 靜靜跳過,**不計入失敗**(21:37 常比雲端快,假日更是本來就沒有) |
| 抓不到 / 推不出去,連續 6 次 | 推一則純文字告警(同一天最多一則) |
| 距上次成功推送 ≥ 5 天 | 推一則純文字告警 |

門檻刻意用「天數」而非「次數」判斷陳舊:一天跑三班,連假四天就會累積十幾次,
用次數必然誤報。

狀態存在 `local_data/.tg_disposal_push`,`message_ids` 同樣按 chat_id 分開存:

```json
{"report_date": "2026-09-04", "artifact_id": 9938544355,
 "targets": {"987654321":  {"message_ids": [101, 102, 103, 104]},
             "-1001234567890": {"message_ids": [55, 56, 57, 58]}},
 "pushed_on": "2026-09-04", "last_success_date": "2026-09-04", "fail_streak": 0}
```

## 手機下指令:手動重抓 (v3.75.0)

disposal-watch 是別人的 repo。他修好問題重跑會產生新的 artifact,但本機下一班
排程可能還要等好幾小時。`scripts/telegram_poll.py` 讓你在手機點一下就重抓。

### 選單(不用記指令)

```bash
python scripts/telegram_poll.py --setup-menu   # 裝一次就好
```

裝的是**輸入框左邊的藍色「選單」按鈕**(`setMyCommands`),點開就列出全部操作,
不用記也不用打字。選單不見了(換裝置、清聊天記錄)打 `/menu` 重裝。

`scope` 綁定管理者私訊:用預設 scope 的話,群組成員點開 bot 也會看到有哪些
指令可用,等於公告這裡吃指令。

> **刻意不用 reply keyboard**(鍵盤上方的常駐按鈕)。它確實更好按,但會長期
> 佔掉手機下半個畫面,而藍色選單已經達到「不用記指令」的目的。
> 若之後改回常駐按鈕,注意按鈕送出的是**按鈕文字**而非斜線指令,
> 指令比對那段要一起改。

### 指令一覽

| 指令 | 做什麼 |
|---|---|
| `/refresh`(或 `/update`)| 重抓最新 artifact → 更新四張圖卡；重算摘要 + Excel → 更新。私訊和群組一起 |
| `/status` | 報表日、artifact id、最後成功時間、連續失敗次數 |
| `/help` | 列出操作 |
| `/menu`(或 `/start`)| 重裝選單。刻意不列進選單本身 —— 裝好之後就用不到,列出來只是雜訊 |

**是更新不是重貼。** 已經有訊息就原地換掉,沒有就發新的。訊息被你手動刪掉導致
更新失敗時,自動退回發新訊息。所以連下好幾次 `/refresh` 也不會洗版。

不是斜線指令的訊息一律不回應 —— 跟 bot 隨口打一句不會收到「不認得」。

### 權限

只接受 `TELEGRAM_ADMIN_CHAT_ID`,未設則取 `TELEGRAM_CHAT_ID` 的**第一個正數 id**
(群組是負數,永遠不會被當成管理者)。

群組與其他人的訊息一律忽略,而且**不回應** —— 連「你沒有權限」都不回,免得讓
群組裡的人發現這個 bot 吃指令。

### 為什麼是輪詢,以及為什麼指令是即時的

`scheduler.ps1` 加了 `every=1`(每分鐘)的 job —— 這是 v3.75.0 新增的排程型態,
原本只支援固定時刻,指令要能隨時下,列 1440 個時刻不現實。

- **webhook** 需要公開網址,家用電腦沒有
- **常駐 daemon** 反應即時,但多一個要監控、會默默掛掉、要自動重啟的東西
- **每分鐘起一個、聽 55 秒就結束**:效果等同常駐,但掛掉 60 秒內自己就回來,
  不必另外監控。`scheduler.ps1` 掛了整條排程也掛了,少一個獨立的故障點

**不是「每分鐘問一次 API」,是「幾乎一直掛著聽」。** 用的是長輪詢
(`getUpdates` 帶 `timeout`),連線掛著不放,訊息一到 Telegram 就立刻回傳 ——
這是官方推薦 bot 用的方式。指令送出到收到回應通常 1-2 秒。

> 早期版本用短輪詢(`timeout=0`)每 2 分鐘問一次,按下指令最久要等 2 分鐘,
> 而且那 2 分鐘完全沒有任何回應。當時輪詢是**同步**跑在排程器裡,掛 50 秒
> 會佔住它,只好如此。改成分離執行後這個限制就不存在了。

收到訊息後**繼續聽完剩餘時間**而不是直接結束 —— 否則連下兩個指令時,第二個
要等到下一分鐘才有人聽。

該 job 標了 `quiet=$true`:沒收到指令時完全不寫 log。一天 1440 次會把真正
有用的紀錄淹掉。

### ⚠️ 為什麼拆成「輪詢」與「工人」兩段

**這是安全關鍵,不是設計潔癖。**

`ChipRadar_Scheduler` 這個 Windows 排程工作的 `MultipleInstances` 政策是
**`IgnoreNew`** —— 前一次還在跑時,下一分鐘的觸發**直接被丟掉**。

實例:`21:30` 的 settlement job 在 2026-08-24 ~ 08-28 **一次都沒執行過**。
因為 21:17 的 daily-full 要跑約 19 分鐘(crawler),佔住排程器到 21:36,
中間每一分鐘的觸發全被吃掉。固定時刻只比對那一分鐘,錯過就是錯過。
(這是既有問題,與輪詢器無關,但它證明這個機制真的會吃掉別的 job。)

所以輪詢器**絕對不能被同步等待**:它自己就要掛 55 秒聽訊息,`/refresh` 的重抓
又要 60-90 秒。壓到 21:17 那一分鐘,當天的 daily-full 就整個不會跑。

兩層都拆開:

```
scheduler.ps1  --detached-->  輪詢器      排程器佔用 8-83 毫秒
輪詢器         --DETACHED-->  工人        輪詢器不被重抓拖住,繼續聽下一個指令

輪詢器 (每分鐘一個)  長輪詢聽 55 秒 → 收到就丟工人 → 繼續聽完剩餘時間
工人   (--run)       真正的重抓與推送,想跑多久都行
```

分離時 `stdin/stdout/stderr` **必須**導向 `DEVNULL`。只設 `DETACHED_PROCESS`
而讓子行程繼承管道的話,呼叫端的 `cmd /c` 仍會等到管道關閉才返回 —— 等於白拆。

實測(完全比照 `scheduler.ps1` 的 `& cmd /c "cd /d ... && $cmd"` 呼叫方式):
工人睡 12 秒,`cmd /c` **80 毫秒**返回,工人照樣活到工作結束。

### offset 與名冊

Telegram 幫每個 bot 保管一個「未讀信箱」。輪詢器必須把訊息**拿走並標記已讀**,
否則會重看到同一條 `/refresh` 而重複執行。已讀到哪存在 `.tg_poll_offset`。

副作用是:訊息被拿走後,`--list-chats` 原本用的 `getUpdates` 就看不到東西了。
所以輪詢器每看到一則訊息就把來源 chat 記進 `.tg_chats.json` 名冊,`--list-chats`
改讀名冊 —— 反而比原本好用,`getUpdates` 只保留約 24 小時,名冊是永久的。

offset **先存再執行指令**:指令跑到一半當掉時,重開機不該再跑一次。寧可漏一次
(再打一次就好)也不要重複推播。

### 兩個鎖

| 鎖檔 | 擋什麼 | 殘骸判定 |
|---|---|---|
| `.tg_poll.lock` | 同時 `getUpdates` —— Telegram 對同一個 bot 會回 **409** | 120 秒(> 輪詢的 55 秒budget,健康的不會被誤判) |
| `.tg_work.lock` | 同時跑兩個 `/refresh` 去編輯同一批訊息 | 1500 秒(> 工人最長 2×600 秒) |

兩個都用 `O_EXCL` **原子建立** —— 「先 `exists()` 檢查、再寫入」中間有空隙,
兩個行程可能同時通過檢查。工人在兩段工作之間會 `touch` 鎖檔保鮮,免得長工作
跑到一半被下一輪誤判成殘骸而讓第二個工人同時開跑。

殘骸判定是必要的:程序被砍、機器重開時鎖檔會留在原地,沒有這個機制就會永久
癱瘓指令通道。

工人是分離行程、輸出被丟到 `DEVNULL`,所以它會把每次執行的結果寫一行到
`.tg_worker.log` 供事後追查。

```bash
python scripts/telegram_poll.py --status   # 看管理者 id / offset / 兩個鎖的狀態
```

### attstock 直連(給 Excel 用,非圖卡)

`scripts/refresh_attstock_disposal.py` 仍直接打 `attstock.tw`,寫
`disposal_attstock.json` 供 `src/exports/excel_report.py` 的「今日避開」使用。
跟圖卡是兩條獨立的路。

> ⚠️ **UA 必須是完整瀏覽器字串。** 2026-08-24 起 attstock 擋非瀏覽器 UA,
> 實測(2026-09-06)短字串 `Mozilla/5.0` 一律 403,完整 Chrome UA 才 200。
> 逐檔請求之間也要保留 0.5 秒節流,403/429 出現時立刻中止 —— 重打只會讓封鎖更久。

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

> **最快的方法**:`python scripts/push_disposal_telegram.py --list-chats`
> 會一次列出 bot 近期看得到的所有 chat(私訊與群組都有,含名稱)。
> 下面兩個方法是它拿不到東西時的備援。
>
> 個人與群組**兩個都要收**的話,`TELEGRAM_CHAT_ID` 用逗號分隔填兩個即可。

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

### 3. 設定 token

**本機 (track 2)** — 寫進專案根目錄 `.env`(已在 .gitignore,不會進 git):

```
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_CHAT_ID=987654321,-1001234567890
# TELEGRAM_DISPOSAL_CHAT_ID=   # 留空 = 跟著 TELEGRAM_CHAT_ID 推同一批
```

`TELEGRAM_CHAT_ID` 逗號分隔 = 每則內容都推給每個對象。

`scheduler.ps1` 每次執行會自動載入。改完不需重啟排程。

**雲端 (track 1)** — 若之後也要讓雲端推 TG,才需要設 Repo Secret:

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

## 附錄:籌碼 digest (預設關閉)

> ⚠️ 這是 v3.55.0 做的另一種格式,**目前預設不推**。
> 現行主線是上面的「手機摘要 + 處置股清單」。
>
> 要啟用請設環境變數 `CHIP_RADAR_TG_DIGEST=1` — 但會變成一天收到兩種
> 不同格式的訊息,建議二擇一。

由 `alerts.py` 在 crawler 內部產生,偏「爬蟲有沒有跑 + 大盤氣氛」,
跟手機摘要的「買什麼」互補:

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

啟用時由 `alerts.py` 在 crawler 內部推送,去重靠 `CHIP_RADAR_PREV_TRADE_DATE`
環境變數(本機 `scheduler.ps1` 未設,故啟用後三層兜底會各推一則)。

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
