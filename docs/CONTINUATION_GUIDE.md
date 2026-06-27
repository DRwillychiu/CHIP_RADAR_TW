# 🚀 Claude 新對話接手 1-Pager

> 任何 Claude 新對話接手此專案,先讀完這份 (5 分鐘) → 不必重讀全 history。

## 系統現況 (2026-06-27, v3.71.12)

### 核心是什麼
- **Chip Radar TW**: 台股「13 位追蹤大戶分點」每日觀察站
- **網站**: https://drwillychiu.github.io/CHIP_RADAR_TW/ (前端 12K 行 single SPA, AES 加密 data)
- **Email**: 每日 21:17 TW 自動寄 daily summary 到 willychiu77761@gmail.com
- **Excel**: monthly workbook (chip_radar_YYYY-MM.xlsx) + Dashboard sheet + 📱 手機摘要 + Quad 追蹤 + Quad 失效歸因 4 sheet

### Alpha 體系 (Phase 3 系列)
- **⭐ Phase 3.2 quad** (78.9% hit, n=38, CI [63.7-88.9%]): 共識 ∩ Q5 偏多 ∩ master 量爆 = **唯一證實 alpha**
- **⭐⭐ Premium tier** (snapshot 2026-06-26): 陳律師 / 竹科主力分點 / 陳族元 (歷史 ≥77% hit)
- **🔬 Phase 3.5 multiday** (觀察期): peak_5d 86.8% / premium cum_3d 92.9% (n=38 待累積)
- **💰 跟單實際淨報酬** (扣 0.585% 成本): 74% 淨 hit, +3.79% mean, 累積 +144% (n=38)
- **🔁 跨日 dedup**: 過去 7 天 trigger 重複 pick 標記
- **⚠️ TRAP**: mild_up_only 41.7% hit (Phase 3.4 ROLLBACK 教訓)

## 常用 path

```
crawler.py                          # 1619 行 主流程
src/exports/excel_report.py         # 3501 行 Excel + Dashboard 9 section + 4 enrichment sheet
src/pipelines/crawler_output.py     # AES 加密 / 解密
src/analyzers/signal_engine.py      # Q5 市場方向預測
src/fetchers/                       # 14 個 fetcher
.github/workflows/                  # 14 個 workflow (含 v3.71.12 weekly LOOP + workflow-health)
scripts/                            # 28 scripts (見 scripts/README.md 分類)
tests/                              # 44 home-grown print runner (`python tests/run_all.py`)
.claude/skills/LOOP-FRAMEWORK.md    # Prompt-to-Loop 手冊
.claude/loops/                      # Loop spec + state log
data/                               # 加密 daily JSON + open JSON (master_profiles / quad_hit_log etc)
docs/                               # 13 文件 (見 docs/README.md)
config/algo_params.yaml             # 演算法閾值 (algo_version)
```

## 重要規範 (從用戶 memory 提取)

1. **對話語言**: 繁體中文 (code/identifiers 英文)
2. **「更新 git」一律 commit + push** (不只本機 commit)
3. **不問休息問題** (主動推進, 100% 努力 + 100% 準確)
4. **Dashboard 簡潔但有力** (砍重複 section, 留獨有 signal)
5. **Filter 重疊度雙重檢查** (新 filter 必 grep 既有 conditions)
6. **驗證 GitHub 檔案用 `git show origin/main:path`** (不信 raw.githubusercontent CDN cache)
7. **改完 .ps1 必跑 PSParser 驗語法**
8. **Version 同步紀律**: algo_params / README / INSTITUTIONAL_ROADMAP / 2 memory file (每次 bump)

## Production 監控 (v3.71.12 加)

- **D4**: Email 失敗 → 自動 GitHub Issue (你 Gmail 收 GH notification)
- **D6**: weekly-loop-audit.yml 週日 22:00 TW 自動重跑 4 audit (Phase 3.4/3.5/overlap/per-master)
- **D1**: workflow-health.yml 週日 22:30 TW 統計 12 workflow 健康度,fail >30% 自動 issue

## 重要 SOP

- **alarm 觸發 (quad 30d <50%)** → 看 `docs/PHASE32_ALPHA_FAILURE_SOP.md` (4 option: recall / 暫停 / 嚴格化 / short)
- **月度 master review** → 看 `docs/MASTER_REVIEW_SOP.md`
- **新增 fetcher / script** → 命名前綴對齊 `scripts/README.md` 規範

## 接手後第一步

1. `cd C:/tmp/chip_radar_v327_4 && git pull origin main` (永遠 sync)
2. 看 `docs/INSTITUTIONAL_ROADMAP.md` 最上 1-2 entry (最新版本做什麼)
3. 看 `data/quad_hit_log.json` rolling_30d (alpha 健康嗎?)
4. 看 `docs/WORKFLOW_HEALTH.md` (production 健康嗎? — 若不存在表示尚未跑 weekly cron)
5. 問用戶今天要做什麼

## 不要做的事

- ❌ 不要 push 不必要的 backup / cleanup commit
- ❌ 不要建新 .md doc 除非用戶明確 request (memory 提到 "Don't create documentation unless requested")
- ❌ 不要重構 production stable 的大檔 (excel_report.py 3501 行 / crawler.py 1619 行)
- ❌ 不要做策略建議 / 投資建議 (系統提供資訊, 用戶自己決定)
