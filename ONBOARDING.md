# Chip Radar TW · 7 天上手指南

> **目的**:讓「接手這個 repo 的另一個工程師」在 1 週內能獨立修 bug + 發版本。
> **前置知識**:Python 基礎、git 基礎、會用瀏覽器 DevTools。**不需要**台股知識(邊用邊學)。
> **配套**:讀本檔前 / 同時請翻 `ARCHITECTURE.md`(系統設計)。
> **最後修訂**:2026-05-24,版本 v3.30.1。

---

## Day 1:環境建置 + Hello World

### 1.1 假設環境

| 項目 | 推薦 | 最低 |
|---|---|---|
| OS | Windows 11(production 用) | macOS / Linux 也行 |
| Python | 3.11 | 3.10 |
| git | 2.40+ | 2.30+ |
| 編輯器 | VS Code | 任何 |
| GitHub | 有寫權限的 account | — |
| Claude Code(可選) | 1.0+ | — |

### 1.2 Clone repo

```powershell
# Windows PowerShell
cd C:/tmp
git clone https://github.com/DRwillychiu/CHIP_RADAR_TW.git chip_radar
cd chip_radar
```

Production clone path 慣例:`C:/tmp/chip_radar_v327_4/`(歷史命名,別改名,memory.md 引用著)。

### 1.3 裝依賴

`requirements.txt` 目前**只列 `requests`**(技術債,v3.31+ 補完),其他要手動裝:

```powershell
pip install requests cryptography openpyxl beautifulsoup4 lxml
```

完整套件清單(實際使用):
- `requests` — HTTP
- `cryptography` — AES-256-GCM + PBKDF2
- `openpyxl` — Excel 寫入
- `beautifulsoup4` + `lxml` — TWSE HTML 分點頁面 parse

### 1.4 環境變數

```powershell
# 測試用密碼(production 不同!)
$env:CHIP_RADAR_PASSWORD = "testpass123"
$env:PYTHONIOENCODING = "utf-8"        # 避免 cp950 中文錯誤
```

permanently 設(可選):
```powershell
[Environment]::SetEnvironmentVariable("CHIP_RADAR_PASSWORD", "testpass123", "User")
[Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "User")
```

### 1.5 第一個 smoke test

跑一個獨立測試確認 cryptography 裝對:

```powershell
python test_v3301_gzip_encrypt.py
```

期望輸出:`整體: ✅ ALL PASS`(5 case)。如果失敗 → 看「Day 6 故障排除」。

---

## Day 2:第一次 local crawl

### 2.1 跑完整流程

```powershell
python crawler.py
```

**正常會跑 5-8 分鐘**。會看到:

```
[1/9] 環境檢查...
[2/9] 56 分點抓取... (序列,避免 IP 封鎖)
  分點 9251 (元大-永和) c=B 完成
  分點 9251 (元大-永和) c=E 完成
  ...
[3/9] 行情合併...
  [Stale Detect] OpenAPI 回傳 20260520 != 預期 20260524 → 全量 MIS fallback
[4/9] 漲停判定...
  [Limit-Up Audit] Top 10:
    3443 創意    close=4985  prev=4530  +10.04%  ✅ limit_up(tick=5)
[5/9] FIFO 部位...
[6/9] 期貨/選擇權...
[7/9] 融資 + 內部人...
[8/9] 信號層...
  [Trade Pattern v3.30] 注入 N 筆模式 + narrative
[9/9] 寫出...
  Excel: data/reports/chip_radar_20260524.xlsx
  Encrypted: data/latest.json (3.2 MB, gzip on)
```

**如果週末跑**:會自動找最近一個交易日,但 TWSE 16:30 前資料可能不全(用 `--date 20260523` 指定日期)。

### 2.2 看產出

```
data/
├── latest.json              ← 加密 + gzipped(這個 push 上去前端解)
├── 20260524.json            ← 同上,日期歸檔
├── stock_history.json       ← 30 天個股,未加密
├── temp_history.json        ← 60 天信號歷史
├── daily_audit.json         ← auto_audit verdict
├── daily_signal.json        ← signal_engine 輸出
└── reports/
    ├── latest.xlsx
    └── chip_radar_20260524.xlsx
```

### 2.3 在 Python REPL 驗加密

```python
import json
from crawler import decrypt_data

with open("data/latest.json") as f:
    enc = json.load(f)

plaintext = decrypt_data(enc["data"], "testpass123")
data = json.loads(plaintext)
print(f"分點數: {len(data['branches'])}")
print(f"日期: {data['trade_date']}")
print(f"version: {data['version']}")
```

如果 `decrypt_data` 拋 `InvalidTag` → password 不對。
如果拋 `UnicodeDecodeError` → magic bytes 邏輯壞了(極罕見)。

---

## Day 3:GitHub 部署

### 3.1 三步必做

#### Step 1:設 GitHub Secret

`Settings → Secrets and variables → Actions → New repository secret`:

```
Name:  CHIP_RADAR_PASSWORD
Value: <production 密碼,跟本機測試用的不同>
```

⚠️ **本機 testpass123 跟 production 不能同個**,測試環境洩漏不會影響 production。

#### Step 2:GitHub Pages

`Settings → Pages`:
- Source: **Deploy from a branch**
- Branch: `main` / `(root)`
- Save

等 1-2 分鐘 → `https://<your-user>.github.io/CHIP_RADAR_TW/`。

#### Step 3:授權 Actions 寫入

`Settings → Actions → General → Workflow permissions`:
- ☑ **Read and write permissions**
- ☑ Allow GitHub Actions to create and approve pull requests

### 3.2 第一次手動跑 workflow

`Actions → "1. Daily Full Crawl (20:00)" → Run workflow`。

成功的指標:
- 綠色 ✅(5-8 分鐘)
- repo 多一個 commit `🔒 [FULL] Daily chip data ...`
- `data/latest.json` mtime 更新

失敗常見原因:
1. Secret 沒設 → log 看到 `CHIP_RADAR_PASSWORD not set`
2. Actions 沒授寫權限 → log 看到 push permission denied
3. TWSE 封 IP → 重跑通常 OK

---

## Day 4:Windows Task Scheduler(可選,但 production 強推)

### 4.1 為何需要

GitHub Actions cron 整點塞車**實測 90 分鐘+ 延遲**。Windows Task Scheduler 觸發 `gh api workflow_dispatch` 延遲 **< 1 秒**。

### 4.2 trigger 腳本(`trigger_chip_radar.ps1`)

**這個檔案在桌面,不在 repo**(避免洩漏 path)。範本:

```powershell
# trigger_chip_radar.ps1
$ErrorActionPreference = 'Stop'

# 1. 觸發 workflow
gh workflow run daily-full.yml --repo DRwillychiu/CHIP_RADAR_TW

# 2. Poll 直到完成(最多 30 min)
$start = Get-Date
do {
    Start-Sleep -Seconds 30
    $runs = gh run list --workflow=daily-full.yml --limit 1 --json status,conclusion | ConvertFrom-Json
    $elapsed = (Get-Date) - $start
    if ($elapsed.TotalMinutes -gt 30) { break }
} while ($runs[0].status -ne 'completed')

# 3. Pull 最新 data
git -C C:/tmp/chip_radar_v327_4 pull --rebase origin main

# 4. 讀 daily_audit.json 決定 toast 顏色
$audit = Get-Content C:/tmp/chip_radar_v327_4/data/daily_audit.json | ConvertFrom-Json
$verdict = $audit.verdict

# 5. Windows toast(BurntToast 或 BalloonTip fallback)
if (Get-Module -ListAvailable BurntToast) {
    Import-Module BurntToast
    New-BurntToastNotification -Text "Chip Radar $verdict", "$($audit.summary)"
} else {
    Add-Type -AssemblyName System.Windows.Forms
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.Visible = $true
    $notify.ShowBalloonTip(5000, "Chip Radar $verdict", $audit.summary, 'Info')
}
```

### 4.3 Task Scheduler 設定

```
Task name:   ChipRadar_DailyFull
Triggers:    週一-五 21:17 TW
Action:      Program: powershell.exe
             Args:    -NoProfile -ExecutionPolicy Bypass -File "C:/Users/User/Desktop/trigger_chip_radar.ps1"

兜底:       ChipRadar_DailyFull_Backup,週一-五 22:37 TW(同腳本)
```

`gh` 須先 `gh auth login` 過。

### 4.4 ⚠️ 改完 .ps1 務必驗語法(5/22-5/28 事故教訓)

**真實事故**:`trigger_chip_radar.ps1` 某次改動引入 `"$verdict: $summary"` —— PowerShell 把 `$verdict:` 當成 drive-qualified 變數(像 `$env:`),冒號後沒接合法變數名 → **整檔 parse 失敗**。

`powershell.exe -File` 執行會**先 parse 整個腳本**,語法錯誤就**一行都不跑**(連寫 log 第一行都沒執行)→ exit 1。後果:Task Scheduler 每天準時觸發,但腳本 **silent fail 連續 7 天**,沒 log、沒 toast、沒人知道,資料一直停在舊日。

**鐵則**:
1. 字串內變數後接冒號要用 `"${var}:"` 不是 `"$var:"`
2. 改完 .ps1 **一定**跑語法檢查(不執行就能抓 parse error):
   ```powershell
   $errors = $null
   [System.Management.Automation.PSParser]::Tokenize((Get-Content 腳本.ps1 -Raw), [ref]$errors)
   $errors   # 應該空
   ```
3. 診斷「Task 有沒有真的跑」看兩個地方:
   ```powershell
   Get-ScheduledTask -TaskName "ChipRadar_DailyFull" | Get-ScheduledTaskInfo
   # LastTaskResult 0x0 = 成功, 0x1 = 腳本 exit 1 (多半 parse fail 或 dispatch fail)
   Get-Content "$env:USERPROFILE\Desktop\chip_radar_trigger.log" -Tail 20
   # 完全沒新 entry = 腳本 parse 階段就掛 (一行都沒跑)
   ```

> 這就是為什麼 v3.30.3 加了 `heartbeat.yml` —— 不管根因是 cron / 腳本 / crash,只要資料 stale,GitHub 會主動開 issue email 你,不再靠人眼發現。

---

## Day 5:跑測試 + 看 audit

### 5.1 跑全 15 套測試

```powershell
$tests = Get-ChildItem test_*.py | Where-Object { $_.Name -notmatch 'cache' }
foreach ($t in $tests) {
    Write-Host "─── $($t.Name) ───" -ForegroundColor Cyan
    python $t.FullName
}
```

正常每個都 exit 0 + 印 `✅ ALL PASS`。

預期數量:15 suite / 159 case(v3.30.1)。任何 fail 都不能 push。

### 5.2 看 auto_audit verdict

跑完 crawler 後 `data/daily_audit.json`:

```json
{
  "verdict": "PASS",       // PASS / WARN / FAIL
  "trade_date": "20260524",
  "checks": {
    "branches_covered": {"actual": 56, "expected": 56, "ok": true},
    "limit_up_count": {"actual": 12, "ok": true},
    "etf_in_top_n": {"actual": 0, "ok": true},
    "net_sellers_in_top_n": {"actual": 0, "ok": true},
    ...
  },
  "summary": "全 56 分點,12 漲停,0 ETF/淨賣污染"
}
```

`WARN` = 可上線但要查,`FAIL` = 必須查清楚才能 push。

### 5.3 看 GitHub Actions log 重點

`Actions → 點失敗 run → 點 job → 找 `::error::` 或 `::warning::``。

`auto_audit` 會自動 emit:
- `::notice::` PASS
- `::warning::` WARN
- `::error::` FAIL(但 workflow exit 0,不會擋 push,只是 highlight)

---

## Day 6:常見故障 + 自救

### 6.1 解密失敗

| 症狀 | 診斷 | 解法 |
|---|---|---|
| `InvalidTag` exception | password 對嗎 | 確認 env var / GitHub Secret |
| `UnicodeDecodeError` 解密後 | magic bytes 邏輯 broke 了 | 看 git blame `crawler.py:decrypt_data` |
| 前端 console `DecompressionStream is not defined` | 瀏覽器太舊 | Chrome 80+ / Safari 16.4+ / Firefox 113+ |
| 前端 console `OperationError` | salt/iv 長度不對 | 看 latest.json 是否被截斷 |

### 6.2 Workflow 失敗

| 症狀 | 解法 |
|---|---|
| timeout 25 min | TWSE 封 IP(分點抓太快)→ 加 `time.sleep(2)` between branches |
| `git push` denied | Settings → Actions → workflow permissions 沒給 read+write |
| `cryptography` 裝不起來 | workflow.yml 加 `pip install cryptography openpyxl` 顯式列出 |
| Excel 生成卡住 | openpyxl 在大 sheet merge 慢,看 `excel_report.py` 是否誤生成 1000+ rows |

### 6.3 資料異常

| 症狀 | 第一步診斷 | 修法位置 |
|---|---|---|
| Excel 出現 ETF 個股 | `EXCLUDED_MARKET_TYPES` 是 lowercase 嗎 | `excel_report.py` 開頭常數區 |
| 出現淨賣股(`net_amt < 0`) | filter 順序對嗎 | `excel_report.py:_top_stocks_for_branch` |
| 漲停判定錯(FP) | 用的 9.5% threshold 還是 tick-size? | `price_utils.calc_limit_up_price` |
| OpenAPI 21:30 還舊資料 | `[Stale Detect]` log 有印嗎 | `institutional.py:fetch_all_public_data` |
| 高價股 buy_lot=0 | `lot_source` 是 `estimated_from_close` 嗎 | `branches.py:fetch_branch_combined` |
| 三大法人 dealer_net_lot ±1 張誤差 | v3.21 已修(整數除法 floor) | `institutional.py` |

### 6.4 Encoding 地獄

Windows PowerShell 預設 cp950,跑 crawler 印中文會 `UnicodeEncodeError`:

```powershell
# 方法 1: env var(推薦)
$env:PYTHONIOENCODING = "utf-8"
python crawler.py

# 方法 2: 加 BOM
python -X utf8 crawler.py
```

如果 PowerShell 還是亂碼,試 Windows Terminal + Cascadia Code font。

---

## Day 7:第一次 contribute

### 7.1 紀律規則(用戶明示,違反會被擋)

| Rule | 內容 |
|---|---|
| **Rule 1 三層同步** | 每次重要版本:GitHub push + 桌面 `chip_radar_outputs/v*/` 封存 + 跨 session memory.md 更新 |
| **Rule 2 大功能先確認設計** | 新 module + 前端改動 → **先給 2-3 個關鍵設計問題**,使用者確認後一次性實作。**不接受邊做邊問** |
| **Rule 3 給選項用 A/B/C 表格** | 推薦放第一位 + 標「(推薦)」 |
| **Rule 4 不接受「順便加 X」** | 範圍漂移會擋。要加新東西 → 滾入 v3.31+ backlog 下個版本 |
| **Rule 5 直接修 bug 不評估** | 發現 bug 直接修,**不要說「我評估範圍再回報」** |
| **Rule 7 驗證階段不開發** | 使用者在驗證時若發現 bug,**就只修那個 bug**,不要趁機加新功能 |

### 7.2 Commit message 規範

```
feat(v3.31): <短標,中文 OK>

- 細節 bullet 1
- 細節 bullet 2
- 測試結果: 13/13 PASS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

前綴 vocab:
- `feat(vX.Y)` 新功能,minor 升版(0.X+1)
- `fix(vX.Y.Z)` Bug fix,patch 升版(0.0.X+1)
- `docs(memory)` 更新 memory.md / ARCHITECTURE.md / ONBOARDING.md
- `chore` 沒影響邏輯的設定
- `🔒 [FULL]` workflow 自動 commit(別用)

### 7.3 三層同步 SOP

```powershell
# 1. push GitHub
cd C:/tmp/chip_radar_v327_4
git pull --rebase origin main
# ...做改動...
python test_*.py    # 確認所有測試 PASS
git add <specific files>
git commit -m "feat(v3.31): ..."
git push origin main

# 2. 桌面封存
$dest = "C:/Users/User/Desktop/chip_radar_outputs/v3.31"
New-Item -ItemType Directory -Path $dest -Force
Copy-Item *.py, *.md, .github/workflows/*.yml $dest -Recurse
# 寫 CHANGES.md 描述這版改了什麼

# 3. 跨 session memory
# 編輯 C:/Users/User/.claude/projects/C--Users-User-Desktop/memory/project_chip_radar_tw.md
# 升版本號 + 加入 Recent deploys timeline + 更新評分
```

### 7.4 版本號 bump 規則

| 改動類型 | bump | 範例 |
|---|---|---|
| Bug fix(行為一致,只修錯) | patch | v3.30.0 → v3.30.1 |
| 新功能(後相容) | minor | v3.30.x → v3.31.0 |
| 破壞性(前端要重抓 latest.json) | major | v3.x → v4.0 |

### 7.5 第一個建議練習任務

從 v3.31+ backlog 挑 🟠 短期那一檔(難度由低到高):

1. **`data/audit_history.json` 累積化**(最簡單,~30 行)
   - 改 `auto_audit.py`:append verdict + timestamp 進 `audit_history.json`
   - 加測試 `test_v331_audit_history.py`
   - 三層同步 → 完成第一個版本

2. **`test_integration_crawler_smoke.py`**(中等,~100 行)
   - mock TWSE/TAIFEX 回傳 → 全 crawler.py main() 跑通
   - 確認 `data/latest.json` 結構合預期
   - 是防禦性測試,不會看到「新功能」但能擋未來 regression

3. **`config/trade_pattern_rules.yaml`**(較難,~200 行 + module 重構)
   - 規則從 `trade_pattern.py` 抽到 YAML
   - 加 schema validation
   - 讓非工程師也能調規則(雖然目前沒這需求)

---

## 8. Reference Map

| 想知道什麼 | 看哪個檔 |
|---|---|
| 系統怎麼工作 | `ARCHITECTURE.md` |
| 怎麼上手 | 本檔 |
| 終端使用者文件 | `README.md`(老舊,部分指 v3.26) |
| 每個版本變更歷史 | git log + 桌面 `chip_radar_outputs/v*/CHANGES.md` |
| 跨 session 記憶 | `memory.md`(repo)+ `C:/Users/User/.claude/.../project_chip_radar_tw.md`(local) |
| 紀律規則完整版 | `C:/Users/User/.claude/.../feedback_chip_radar_discipline.md` |
| 任何測試的 fixture | `test_*.py` 開頭的 `_make_mock_*` helper |

---

## 9. 緊急聯絡

- Repo owner:DRwillychiu(`willychiu77761@gmail.com`)
- GitHub repo:https://github.com/DRwillychiu/CHIP_RADAR_TW
- Live site:https://drwillychiu.github.io/CHIP_RADAR_TW/

接手前最後一個提醒:**永遠先看 `memory.md` 知道現在版本是什麼狀態**。本檔可能比 memory 慢半步。
