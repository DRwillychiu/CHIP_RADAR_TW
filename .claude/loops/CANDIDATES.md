# Chip Radar Loop 候選清單

> 用 LOOP-FRAMEWORK 四條件篩選 Chip Radar 內所有任務,標記哪些適合做 Loop。
> 不適合的不勉強,單次 prompt 更好。

## 適用性矩陣

| 任務 | 1.每週重複? | 2.可自動拒絕? | 3.Agent 跑完? | 4.客觀判定? | 結論 |
|---|---|---|---|---|---|
| **新 alpha 探索 (combo backtest)** | ✅ | ✅ hit rate 數值 | ✅ | ✅ | **🎯 適合 Loop** |
| **Phase 3.2 alpha 失效應對** | ✅ alarm 觸發後 | ✅ recall 條件 | ✅ | ✅ | **🎯 適合 Loop** |
| **Master 招募/汰換評估** | 月度 | ✅ vol_spike hit% | ✅ | ✅ | **🎯 適合 Loop** (月度) |
| **Excel sub-banner polish** | ❌ 不重複 | ⚠️ 主觀 | ✅ | ❌ 審美 | ⚪ 單次 prompt |
| **daily-full crawler** | ✅ 每天 | ✅ data integrity | ✅ | ✅ | ⚪ 已 production, 不需 loop |
| **TAIEX 歷史 backfill** | ❌ 一次性 | ✅ | ✅ | ✅ | ⚪ 一次性 |
| **新 fetcher 開發** | ❌ 一次性 | ✅ test pass | ✅ | ✅ | ⚪ 單次 |
| **Mobile / Email polish** | ❌ 不重複 | ⚠️ 主觀 | ✅ | ⚠️ rubric | ⚪ 單次 + 收 user 反饋 |
| **跟單 ROI 月度報告** | ✅ 每月 | ✅ 數字驗算 | ✅ | ✅ | **🎯 適合 Loop** (月度) |

---

## 推薦 First Loop (按 ROI 優先序)

### 1. 「新 alpha 探索」Loop (最高 ROI)
- 目標: 找 hit ≥70% AND n ≥30 的 combo signal
- 對應: 延續 Phase 3.4 combo backtest 探索流程
- 已有 infra: bootstrap_combo_backtest.py + phase34-combo-explore workflow
- Loop 後: agent 自動每週添加新 filter combo → backtest → verify → 收斂到 alpha 或放棄

### 2. 「Phase 3.2 alpha 失效應對」Loop
- 目標: alarm 觸發後 24h 內自動診斷 + 決策 + 通知
- 對應: PHASE32_ALPHA_FAILURE_SOP.md 8 章節
- 已有 infra: quad_hit_log.json + alarm 邏輯 + 4 enrichment sheet
- Loop 後: alarm 觸發 → agent 自動 4 option 評估 → 選一個執行 → state log 記錄

### 3. 「Master 招募/汰換評估」Loop (月度)
- 目標: 每月 review per-master vol_spike 可靠度 + 更新 PREMIUM_MASTERS set
- 已有 infra: analyze_master_vol_spike_reliability.py + quad_hit_log.json
- Loop 後: agent 自動跑 analyzer → 跨月度比較 → 提案 tier 變動 → 用戶批准/拒絕

### 4. 「跟單 ROI 月度報告」Loop (月度)
- 目標: 每月 1 號自動算上個月 quad 跟單實際 ROI (含成本) + email 寄發
- 已有 infra: quad_hit_log.json + 跟單 ROI 邏輯 (v3.71.7 已含)
- Loop 後: 月初 cron → agent 算月度績效 → 對比預期 → 寫月報

---

## 不適合 Loop 的任務 (繼續用 single prompt)

- UI polish (太主觀)
- 一次性 backfill / migration
- Production hotfix (太緊急, 不容 iterate)
- 新 feature 設計 (探索性, 不收斂)

---

## 共用 State Log 位置

`.claude/loops/state/[loop-name]-YYYY-MM-DD.md`

每次 loop 跑完 append 一份 incident log, 累積成 alpha 演化史。
