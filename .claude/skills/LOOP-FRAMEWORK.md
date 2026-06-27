# LOOP FRAMEWORK — Prompt-to-Loop 完整轉換手冊

> 適用於 Chip Radar TW 所有重複性任務。Skill location: `.claude/skills/`。

## 0. 核心原則
- **Prompt** = 單次指令,人驅動,人停它停
- **Loop** = 目標 + 完成標準 + 放棄規則,AI 自己跑完整個循環
- **先手動跑通一次 → 固化成 Skill → 套上 Loop → 最後才自動化**
- 跳過前面直接自動化 = Loop 在你睡覺時爆炸

---

## 1. Loop 適用性檢查 (四條全滿足才做)

| # | 條件 | 不滿足時 |
|---|---|---|
| 1 | 任務至少每週重複一次 | 用單次高品質 prompt |
| 2 | 壞結果可自動拒絕 (test fail / 數值不達標) | 人工審核 |
| 3 | Agent 能從頭跑到尾 | 拆更小子任務再評估 |
| 4 | 完成可客觀判定 | Rubric 評分但降低自動化期望 |

---

## 2. Prompt → Loop 轉換流程 (六步)

### Step 1: 提取三要素
```
GOAL: 你到底要什麼產物?
SUCCESS CRITERIA: 怎樣算完成? (必須可測量)
ABORT RULE: 什麼情況下放棄?
```

### Step 2: 五步循環骨架
```
DISCOVER → 讀取現有狀態, 找出需要做什麼
PLAN     → 決定這一輪只做什麼 (一次只修一件)
EXECUTE  → 執行修改
VERIFY   → 對照每條 SUCCESS CRITERIA 檢查
ITERATE  → 沒達標 → 記錄失敗 → 回到 DISCOVER
```

### Step 3: Verify 機制 (Loop 的心臟)

| 驗證類型 | 場景 | 範例 |
|---|---|---|
| 硬測試 | 代碼 | pytest 全過 / mypy 0 error |
| 可測量條件 | 數據/量化 | 欄位 = N / 數值在範圍 |
| Rubric 評分 | 文字/分析 | 1-10 分, 每項 ≥8 才過 |
| 比對基準 | 回歸/遷移 | 輸出與基準 diff = 0 |

**關鍵**: Writer (產出者) 跟 Reviewer (檢查者) 必須分開 — 同模型批改自己 = 對自己太寬容。

### Step 4: State Log 結構
```
## Iteration N
- ATTEMPTED: [這輪做了什麼]
- RESULT: PASS / FAIL
- FAILURE REASON: [具體原因]
- SCORES: [若 rubric, 列各項分數]
- NEXT: [下一輪修什麼]
```

### Step 5: Stop Condition
```
SUCCESS EXIT: 所有 criteria 通過 → FINAL → 停
HARD LIMIT:   達 N 次上限 → 停 → 輸出失敗報告
  簡單: 3-5 次 / 中等: 5-8 次 / 複雜: 8-12 次
  > 12 次未收斂 → 任務定義有問題, 不是迭代問題
```

### Step 6: 組裝 Loop Spec
```
═══════════════════════════════════════════
LOOP SPEC: [任務名稱]
═══════════════════════════════════════════
GOAL: [一句話]
SUCCESS CRITERIA:
  - [ ] 標準 1
  - [ ] 標準 2
VERIFY METHOD: [具體驗證]
EACH ITERATION:
  1. DISCOVER 2. PLAN 3. EXECUTE 4. VERIFY 5. UPDATE STATE 6. DECIDE
STOP: SUCCESS / HARD LIMIT N
ON STOP: 總結 + 失敗清單 + 根本原因
CONSTRAINTS:
  - 不問問題, 做合理假設並記錄
  - 每輪只修最低分項
  - 不跳步, 不在未驗證時宣告完成
═══════════════════════════════════════════
```

---

## 3. 任務類型模板

### A. 代碼開發
- 測試全過 + 0 lint + 0 type error + edge case
- VERIFY: pytest / eslint / mypy
- STOP: 8 次

### B. 數據處理 / 量化分析
- 腳本可跑 + 欄位完整 + 數值合理 + edge case
- VERIFY: 抽樣驗算 3 筆 + 下游可讀
- STOP: 6 次

### C. 文件 / 報告
- 涵蓋主題 + 證據支撐 + 無事實錯 + 結構清晰
- VERIFY: Rubric 5 維度 × 1-10 分, 每項 ≥ 8
- STOP: 6 次

### D. 策略 Walk-Forward
- WF Efficiency >50% + OOS PF > 閾值 + OOS DD < 閾值
- VERIFY: 每個 WF 窗口逐一檢查
- STOP: 8 次, 每輪只調一變量

---

## 4. Sub-Agent 分離

```
WRITER (快, 較輕模型) → 產出 → REVIEWER (強, 高推理) → 通過? → FINAL or 回 WRITER
```

---

## 5. 常見失敗模式

| 模式 | 症狀 | 防護 |
|---|---|---|
| Ralph Wiggum | 過早宣告完成 | Verify 必須外部, 不能自評 |
| 無限空轉 | 改但不收斂 | 硬上限 + 每輪修最低分 |
| 重複犯錯 | 每輪犯同一錯 | State log 強制記失敗 |
| 過度擬合 | 為通過做不合理修改 | 標準涵蓋 robustness |
| 上下文爆炸 | context 太大 | 每輪只傳必要 state |
| 驗證太鬆 | 都 PASS | 強模型 reviewer + 刻意嚴格 |

---

## 6. Cheat Sheet

```
1. 最終產物?              → GOAL
2. 怎樣算做好?            → SUCCESS CRITERIA (3-5 可測量)
3. 怎麼驗證?              → VERIFY METHOD
4. 最多幾輪?              → HARD LIMIT
5. 失敗怎辦?              → ON STOP
6. 絕對不能碰?            → CONSTRAINTS
```

---

## 7. 使用方式

存放於 `.claude/skills/LOOP-FRAMEWORK.md`。引用方式:

```
請參考 .claude/skills/LOOP-FRAMEWORK.md 把以下 prompt 轉成 Loop Spec:
[貼 prompt]
```

或:

```
請用 LOOP-FRAMEWORK 模板 [A/B/C/D] 建立以下 Loop:
[描述任務]
```

Loop Spec 完成後存到 `.claude/loops/[task-name].md`,可手動 trigger 或排程 (cron / GitHub Actions / claude code session)。
