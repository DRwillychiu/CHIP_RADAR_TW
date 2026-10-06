# dev 環境（測試模式）

> v3.80.19（2026-10-06，使用者要求「建一個 dev，環境就不會干涉」）。
> 分支名稱用 `dev`：git 分支不能以「.」開頭，所以不是 `.dev`。

## 兩個環境

| | main（正式） | dev（測試） |
|---|---|---|
| 誰會觸發 daily-full | 21:17 / 22:37 / 23:47 排程、手動觸發 | 每次 push 到 `dev` |
| 用哪份程式 | main | dev |
| 用哪份資料 | main 的 `data/` | 也是 main 最新的 `data/`（dev 自己的 data 可能是舊的） |
| 寫回雲端 | commit 資料、上傳資料庫、開 Issue | **全部不做** |
| 信件 | 正式日報 | 主旨與內文第一段標「🧪【測試】」，附件 Excel 的 Dashboard 標題也標測試 |
| 排隊群組 | `daily-full-crawl` | `daily-full-test`，不會讓正式排程排隊、延遲或被取消 |
| 雲端自動測試（tests.yml） | 每次 push | 每次 push |

手動觸發 main 時勾 `test_run`，也會用測試模式跑（不寫回）。任何不是 main 的分支觸發 daily-full，一律是測試模式。

## 平常怎麼用

1. 改動先推到 `dev`：雲端跑全套測試，同時用測試模式跑一輪 daily-full（約 25–30 分鐘），寄一封標【測試】的信。
2. 測試信與 Actions 紀錄都沒問題後，把 dev 合進 main：`git checkout main && git merge --ff-only dev && git push`。
3. 開始下一個改動前，先把 main 的最新內容帶回 dev：`git checkout dev && git merge main`。

## 不會被測試模式影響的東西

- `data/` 的任何檔案（測試跑完只留在雲端那台機器上，結束就丟掉）
- 資料庫 artifact（下一輪正式排程照常用正式那份）
- GitHub Issue（測試模式不開）

規則由 `tests/test_v38019_dev_environment.py` 逐一檢查：正式排程、手動觸發 main、手動觸發 main 勾 test_run、push dev、手動觸發 dev，五種情境各自是否為測試模式、排在哪一組。
