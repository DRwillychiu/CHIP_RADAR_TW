# Chip Radar TW — 系統圖・流程圖・架構圖

> 依 2026-10-06 對 repo 的完整盤點（v3.80.14）繪製。圖檔在 `docs/diagrams/`；
> 每張圖的 Mermaid 原始碼放在圖下方的展開區塊，GitHub 會直接畫出來。
> **修改流程或程式結構時，原始碼與圖檔要一起更新**（圖檔由同一份原始碼渲染）。

| 圖 | 回答的問題 |
|---|---|
| 1. 系統圖 | 資料從哪來、在哪裡跑、存在哪裡、最後給你什麼 |
| 2-1. 流程圖（一個交易日） | 每天幾點跑什麼，非交易日怎麼處理 |
| 2-2. 流程圖（每日籌碼內部） | 每日籌碼 daily-full 一輪裡面依序做哪些事 |
| 3. 架構圖 | 程式碼怎麼分工、誰呼叫誰 |

## 1. 系統圖 — 資料從哪來、在哪跑、存哪裡、給誰

![1. 系統圖 — 資料從哪來、在哪跑、存哪裡、給誰](diagrams/system.png)

<details><summary>Mermaid 原始碼</summary>

```mermaid
flowchart LR
  subgraph SRC["外部資料來源"]
    direction TB
    FB["富邦 DJ<br/>82 個分點進出・個股分點排行"]
    TWSE["證交所 TWSE<br/>行情・法人・融資・大盤・休市表"]
    TPEX["櫃買中心 TPEx<br/>行情・法人・融資"]
    TAIFEX["期交所 TAIFEX<br/>期貨・選擇權・P/C"]
    MOPS["公開資訊觀測站<br/>重大訊息・董監持股"]
    TDCC["集保 TDCC<br/>股權分散（每週）"]
    ATT["attstock<br/>處置中・明日恐處置"]
    OTH["chengwaye（處置預測）<br/>histock（交叉驗證）"]
  end
  subgraph GHA["GitHub Actions 雲端排程"]
    direction TB
    GATE{{"交易日開關<br/>非交易日整輪跳過"}}
    DF["每日籌碼 daily-full<br/>21:17・22:37・23:47"]
    MR["融資更新<br/>晚間輪 + 隔日早上補跑"]
    DAY["盤前簡報・盤中試算<br/>結算追蹤・週報"]
    MON["監控：每日健康檢查<br/>每週稽核・資安・健康報告"]
    TDJ["集保週資料（週六）"]
  end
  subgraph STORE["資料儲存"]
    direction TB
    REPO[("GitHub repo data/<br/>加密日檔・歷史・持倉・主力統計")]
    DB[("SQLite 資料庫<br/>Actions artifact 保留 90 天")]
  end
  subgraph OUT["輸出給你"]
    direction TB
    XLSX["Excel 月檔<br/>Dashboard・Pinned・每日分點表"]
    SITE["GitHub Pages 網站"]
    MAIL["每日 Email（Gmail）"]
    ISSUE["GitHub Issue 告警"]
  end
  PC["你的電腦<br/>Windows 工作排程器"]
  SRC -- "全部來源" --> GATE
  GATE --> DF & MR & DAY
  TDCC --> TDJ
  DF & MR & DAY & TDJ --> REPO
  DF <--> DB
  REPO --> XLSX & SITE
  DF --> MAIL
  MON --> ISSUE
  PC -. "手動觸發 daily-full" .-> DF
```

</details>

## 2-1. 流程圖 — 一個交易日的時間軸（每一輪都先過交易日開關）

![2-1. 流程圖 — 一個交易日的時間軸（每一輪都先過交易日開關）](diagrams/flow_day.png)

<details><summary>Mermaid 原始碼</summary>

```mermaid
flowchart LR
  A["08:50<br/>盤前簡報"] --> B["13:30・13:35<br/>結算追蹤・盤中試算"]
  B --> C["14:30<br/>週報<br/>（只在本週最後交易日）"]
  C --> D["17:30・21:30<br/>結算追蹤"]
  D --> E["21:17・22:37・23:47<br/>每日籌碼 daily-full<br/>Excel + Email"]
  E --> F["22:30 ～ 02:00<br/>融資晚間輪"]
  F --> G["隔日 08:00・09:00・12:00<br/>融資補跑<br/>（前一交易日融資未驗證才做）"]
  N["GitHub 排程常延遲 1～5 小時：<br/>中午前跑的一輪算前一天<br/>非交易日（國定假日・颱風假）整輪跳過"]
  style N fill:#fff8e1,stroke:#c9a227
```

</details>

## 2-2. 流程圖 — 每日籌碼 daily-full 內部步驟

![2-2. 流程圖 — 每日籌碼 daily-full 內部步驟](diagrams/flow_crawl.png)

<details><summary>Mermaid 原始碼</summary>

```mermaid
flowchart LR
  subgraph P1["① 抓取"]
    direction TB
    G{{"交易日開關"}} --> F1["抓 82 個分點<br/>金額頁 + 張數頁<br/>hex 代號・頁面身分檢查"]
    F1 --> F2["失敗分點同一輪補抓"]
    F2 --> F3["FIFO 持倉更新"]
    F3 --> F4["行情・三大法人<br/>TWSE / TPEx<br/>過期改用 MIS"]
  end
  subgraph P2["② 加工"]
    direction TB
    F5["注入收盤價・估算張數<br/>精確漲停"] --> F6["彙總・漲停共識<br/>漲停股第一名買家"]
    F6 --> F7["融資融券・維持率"]
    F7 --> F8["處置預測・產業<br/>集保・紅旗"]
    F8 --> F9["個股歷史 stock_history<br/>含大盤缺口自我修復"]
    F9 --> F10["期貨選擇權・MOPS"]
  end
  subgraph P3["③ 存檔與第一次產表"]
    direction TB
    F11["Excel 第一次產表<br/>自動稽核（最新每日分頁）"] --> F12["籌碼溫度・每日訊號"]
    F12 --> F13["加密存檔<br/>YYYYMMDD.json・latest.json"]
    F13 --> F14["週/月報・主力統計<br/>資料庫・歸檔"]
  end
  subgraph P4["④ workflow 後段"]
    direction TB
    W1["attstock 處置股清單"] --> W2["滾動回測 + Excel 重建（最終版）<br/>mobile_summary.txt"]
    W2 --> W3["commit & push data/"]
    W3 --> W4["每日 Email<br/>內文 mobile_summary.txt<br/>附件 Excel"]
  end
  P1 --> P2 --> P3 --> P4
```

</details>

## 3. 架構圖 — 程式怎麼分工

![3. 架構圖 — 程式怎麼分工](diagrams/architecture.png)

<details><summary>Mermaid 原始碼</summary>

```mermaid
flowchart TB
  WF[".github/workflows<br/>15 支排程 + 交易日開關 gate"]
  CRW["crawler.py<br/>主流程：STAGE=full / margin_only"]
  SCR["scripts/<br/>CI 每日：滾動回測・處置股・信件擷取<br/>CI 每週：回測・稽核<br/>手動：回補・驗證工具"]
  subgraph SRCP["src/"]
    direction TB
    FET["fetchers<br/>法人・融資・歷史/大盤・期貨<br/>MOPS・產業・處置・個股分點"]
    PIPE["pipelines<br/>富邦抓取層・FIFO/彙總<br/>加密・資料庫・歸檔・週月報"]
    ANA["analyzers<br/>主力統計・訊號引擎・派系<br/>隔日沖・紅旗・主力成本"]
    EXP["exports<br/>Excel 報表"]
    ALR["alerts<br/>告警・每日訊號・事件紀錄"]
    AUD["audit<br/>自動稽核・histock 驗證"]
    BT["backtest<br/>回測（多為手動）"]
    CORE["core<br/>分點登錄・大戶分級・交易日曆<br/>排除清單・價格工具"]
  end
  DATA[("data/<br/>加密日檔・歷史・報表")]
  TST["tests/run_all.py<br/>60 支測試（目前只在本機跑）"]
  WF --> CRW & SCR
  CRW -- "呼叫" --> SRCP
  SCR -- "呼叫" --> SRCP
  FET & PIPE & ANA & EXP --> CORE
  SRCP -- "讀寫" --> DATA
  TST -. "驗證" .-> SRCP
```

</details>

## 附：盤點時發現、尚未處理的事項

| 事項 | 狀態 | 依據 |
|---|---|---|
| 主力貢獻度 `data/master_contribution.json` 停在 2026-08-29 | 已確認，未處理 | 檔內 updated_at；每日滾動更新會執行它，推測一直失敗 |
| 測試只在本機跑，沒有任何雲端排程執行 `tests/run_all.py` | 已確認，未處理 | 15 支 workflow 都沒有呼叫 |
| 結算追蹤的時間窗檢查可能永遠提早結束 | 推測，未驗證 | `settlement-tracking.yml` 的 python -c 沒有先 import src |
| Excel 月檔是明碼、放在公開 repo | 使用者 2026-10-06 確認可供下載 | — |
