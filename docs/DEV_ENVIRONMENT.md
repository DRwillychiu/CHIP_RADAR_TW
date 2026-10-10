# dev 環境（測試模式）

> v3.80.19（2026-10-06，使用者要求「建一個 dev，環境就不會干涉」）。
> v3.85.5（2026-10-09）：dev 從 main 重開（舊 dev 有 29 個舊本機模式 commit、已和 main 分岔，保留為 `dev-legacy-local`）；
> 使用者要求「確保不會在優化過程，影響到 main 的主系統運作」→ push 不再自動跑爬蟲，測試跑改手動且避開正式時段。
> 分支名稱用 `dev`：git 分支不能以「.」開頭，所以不是 `.dev`。

## 兩個環境

| | main（正式） | dev（測試） |
|---|---|---|
| 誰會觸發 daily-full | 21:17 / 22:37 / 23:47 排程、手動觸發 | **只有手動**：Actions → Daily Full Crawl → Run workflow → 分支選 `dev` |
| 什麼時段可以跑 | 不限 | **07:00–20:30（台北）**；20:30–07:00 屬於正式爬蟲，測試跑第一步就擋下（還沒發出任何富邦請求） |
| 用哪份程式 | main | dev |
| 用哪份資料 | main 的 `data/` | 也是 main 最新的 `data/`（dev 自己的 data 可能是舊的） |
| 寫回雲端 | commit 資料、上傳資料庫、開 Issue | **全部不做** |
| 信件 | 正式日報 | 主旨與內文第一段標「🧪【測試】」，附件 Excel 的 Dashboard 標題也標測試 |
| 排隊群組 | `daily-full-crawl` | `daily-full-test`，不會讓正式排程排隊、延遲或被取消 |
| 雲端自動測試（tests.yml） | 每次 push | 每次 push（不碰富邦，只跑測試） |

手動觸發 main 時勾 `test_run`，也會用測試模式跑（不寫回，同樣受時段限制）。任何不是 main 的分支觸發 daily-full，一律是測試模式。

## 平常怎麼用

1. 改動推到 `dev`：雲端只跑全套測試（tests.yml），**不會**自動爬。
2. 需要整輪實測時，白天（07:00–20:30）手動觸發 dev 的 daily-full，收一封標【測試】的信。一個改動只跑必要的次數：每次測試跑約 264 個富邦請求。
3. 測試與 Actions 紀錄都沒問題、負責人核准後，把 dev 合進 main：`git checkout main && git merge --ff-only dev && git push`。
4. 開始下一個改動前，先把 main 的最新內容（含每晚的資料 commit）帶回 dev：`git checkout dev && git merge main`。

## 不會被測試模式影響的東西

- `data/` 的任何檔案（測試跑完只留在雲端那台機器上，結束就丟掉）
- 資料庫 artifact（下一輪正式排程照常用正式那份）
- GitHub Issue（測試模式不開）
- 正式爬蟲時段的富邦負載（20:30–07:00 不會有測試跑）

規則由 `tests/test_v38019_dev_environment.py` 逐一檢查：沒有 push 觸發、正式排程不變；正式排程、手動 main、手動 main 勾 test_run、手動 dev、手動 dev 勾 test_run 五種情境各自是否為測試模式、排在哪一組；時段守門是 checkout 後第一步、擋 20:30–07:00。
