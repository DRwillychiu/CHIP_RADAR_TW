# P2 技術債清理 — 2026-08-30

三項掛帳已久的技術債。依既定原則**先量現況再決定該不該做**,
結果三項各自走向不同結局:一項是資料還沒到、一項挖出三個實際缺陷、一項證明不需要做。

---

## P2-1 融資餘額加權成本 —— 卡在資料累積,程式沒問題

現行維持率用 **30 天均價**估算融資成本。更準的做法是用**融資餘額加權**
(餘額增加的那幾天,權重應該更高),但那需要每日 `margin_balance` 的歷史。

v3.74.1 已把寫入接上。**這次確認它真的有在寫**(不是接了但沒作用):

| 項目 | 實測 |
|---|---|
| `crawler.py:1060` 是否傳入 `margin_all` | ✅ 有 |
| 有 `margin_balance` 的檔數 | 2,207 / 15,675 |
| 累積天數 | **5 天**(20260824 ~ 20260828) |
| 需要 | 30 天 |

**結論:程式面已就緒,純粹等資料。預計 2026-10 初可動工。**
這次驗證的價值在於:不用等到 10 月才發現接線是壞的。

---

## P2-2 Master 名單集中化 —— 挖出 3 個實際缺陷

原本以為只是「同一份名單抄了三次」的整潔問題。量下去發現**已經出事了**。

### 缺陷 ① PREMIUM_MASTERS 漂移到零交集

| 位置 | 內容 |
|---|---|
| `excel_report`(動態,v3.75.0 起依實測 LOO) | `{巨人傑}` |
| `bootstrap_multiday_backtest.py:40`(硬寫) | `{陳律師, 竹科主力分點, 陳族元}` |

**交集是空的。** 每週的 multiday backtest 一直在分析三個早已不符資格的人。

### 缺陷 ② SNIPER_MASTERS 兩份定義不同

| 位置 | 內容 |
|---|---|
| `crawler.py:780` | `{蔣承翰}` |
| `audit/histock_branch_audit.py:80` | `{蔣承翰, 迷你哥, Tradow, 巨人傑}` |

查下去發現這**不是 bug,是兩個不同概念共用一個名字**:
一個是「哪些人要標黃底」(功能範圍,用戶指定),
一個是「誰的風格是搶漲停」(風格分類)。
共用名字才會讓分歧沒人發現。

### 缺陷 ③ `'迷你哥'` 這個名字不存在 —— silent no-op

`MASTER_STYLES` 裡的正式名稱是 **`'迷你哥/松山哥'`**(分點 9217 凱基-松山)。
audit 寫的 `'迷你哥'` 讓 `br.get('master') in SNIPER_MASTERS` **對他永遠不成立**。

沒有例外、沒有警告、沒有變紅 —— 就是不作用。
這正是這幾天一直在抓的那一類 bug。

### 處置

新建 `src/core/master_tiers.py` 作為唯一真相來源:

| 常數 | 內容 | 性質 |
|---|---|---|
| `LIMIT_UP_SNIPERS` | 蔣承翰 / **迷你哥/松山哥** / Tradow / 巨人傑 | 風格分類 |
| `TOP_BUYER_HIGHLIGHT_MASTERS` | 蔣承翰 | 功能範圍(用戶指定) |
| `PREMIUM_MASTERS` | 動態,依實測 LOO | 儀表板用 |
| `PREMIUM_MASTERS_SNAPSHOT` | 2026-06-26 凍結 | **回測用** |

**關鍵防護:`validate_master_names()` 在 import 時就驗證每個名字真的存在於
`MASTER_STYLES`,打錯直接 raise。** 讓缺陷 ③ 那一類不可能再發生。

### ⚠️ 差點做錯的地方(留檔)

第一直覺是把 `bootstrap_multiday_backtest.py` 的硬編碼名單換成動態
`PREMIUM_MASTERS` —— 畢竟「單一真相來源」嘛。**那樣會毀掉那支回測。**

原因:名單本身是**依績效挑出來的**。用「今天算出的名單」去篩「全部歷史」
= 完整 look-ahead —— 先知道誰後來表現好,再回頭說他們表現好。

該回測已有 IS/OOS 切分(`is_cutoff_date=20260630`),
而凍結名單是 2026-06-26 依當時資料選出 → 對 cutoff 之後的 OOS 段是合法的前瞻測試。
換成動態名單(資料到 8/28)會讓整個 OOS 視窗被污染。

**→ 回測要的是時點快照,儀表板要的是當前值。兩個都留,但名字必須說清楚是哪一種。**

另加 `check_snapshot_leakage(is_cutoff_date)`:OOS 起點早於快照日就出警告。
現況 `20260630 > 20260626` → 無警告,OOS 乾淨。

順帶把選擇偏誤寫進輸出(`premium_selection.bias_note`)——
該回測自己的 over-fit 偵測本來就會叫(premium_only IS 54.8% vs OOS 15.4%,
diff +39.5pp ⚠️ OVER-FIT),現在 JSON 裡也留下理由。

---

## P2-3 histock 第三來源 fallback —— 量完發現不需要

v3.73.0 把 primary 從 histock(更新晚於排程,永遠 T-1)換成
**富邦 zco.djhtm**(同日資料)。當時掛了一筆「histock 被限流時要不要加第三來源」。

依「零觸發先問該不該存在」原則,**先量**。實測 10 檔(大中小型 + 上市上櫃混合):

```
富邦成功 10/10 | histock 補上 0/10 | 兩者皆失敗 0/10
```

富邦全數命中,histock **一次都沒被觸發**。

**結論:第三來源解決的是不存在的問題,不做。**
histock 作為既有的第二層 fallback 保留 —— 零觸發代表 primary 健康,
不代表 fallback 沒用;因為主來源目前正常就拆掉備援是反過來的。

---

## 順帶量到的問題(已另開任務,不在 P2 範圍)

`data/stock_history.json` 已達 **32.2 MB**,30 天內被 commit **100 次**,
`.git` 現在 **2.5 GB**。

拆解 `stocks` 的 15,675 筆:

| 類型 | 筆數 | 大小 | 被用到嗎 |
|---|---|---|---|
| 4 碼個股 | 1,989 | 4.4 MB | ✅ |
| **7x 開頭權證** | **13,274** | **~12.6 MB** | ❌ **五個分析產物中零出現** |
| 00 開頭 ETF/ETN | 234 | — | ✅ 實戰信號 5 處 / master 畫像 19 處 |

**注意:不能一律砍 6 碼。** `00981A`、`00953B` 這些 ETF 有在用,
只有 `7x` 權證是純浪費。已開獨立任務處理。

---

## 驗收

```
新測 test_v3790_master_tiers          36 PASS
全套回歸                              337 case 全過
6 個 entry point import smoke         全數 OK
  (crawler / heartbeat_check / tdcc_holdings /
   pre_market_brief / weekly_summary / intraday_settlement)
```

回歸中修掉一處:`test_v3750` 用 `er._PREMIUM_CACHE`,
定義搬家後找不到 → `excel_report` 一併 re-export(是同一個 dict 物件,
既有的 `.clear()` 仍有效)。
