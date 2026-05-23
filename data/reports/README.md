# Chip Radar 老闆版 Excel 日報

由 `excel_report.py` v3.26 自動生成,模仿手動版「分點觀察」格式。

## 最新檔案

- [**latest.xlsx**](./latest.xlsx) — 多 sheet, 最近 30 個交易日
  - 每個 sheet 命名 = `YYYYMMDD`,開啟時顯示最新一日

## 結構

- 13 位高手 / 42 個分點 slot (含跨高手共用分點)
- 每分點固定 10 列 (不足以空白填補)
- 12 欄: 高手 / 分點 / 代號 / 標的 / 買進(張) / 賣出(張) / 買進(萬元) / 賣出(萬元) / 淨買差(萬元) / 買均 / 賣均 / 損益(萬)
- L 欄公式: `=F*(K-J)` (賣出張數 × (賣均-買均)),負值紅字

## v3.26 風格分流規則

資料源依 `branches.py` 的 `MASTER_STYLES` 自動切換:

| Master 風格 | Top 10 資料源 |
|---|---|
| ⚡ 隔日沖 (`next_day_flipper`) | **今日漲停股 by 買進金額** (漲跌幅 ≥ 9.5%) |
| 🔥 當沖 (`day_trader`) | **今日漲停股 by 買進金額** (漲跌幅 ≥ 9.5%) |
| 🌙 波段 (`swing`) | 全部個股 by 買進金額 |
| 💎 長線 (`longterm`) | 全部個股 by 買進金額 |

隔日沖/當沖 master 今天若沒搶任何漲停股 → 整 10 列空白 (不 fallback,維持風格純度)

## 每日歷史

近 12 個交易日 (共 12 個檔案):

| 日期 | 檔案 | 大小 |
|------|------|------|
| 2026-05-22 | [chip_radar_2026-05-22.xlsx](./chip_radar_2026-05-22.xlsx) | 37.7 KB |
| 2026-05-21 | [chip_radar_2026-05-21.xlsx](./chip_radar_2026-05-21.xlsx) | 37.3 KB |
| 2026-05-20 | [chip_radar_2026-05-20.xlsx](./chip_radar_2026-05-20.xlsx) | 35.7 KB |
| 2026-05-19 | [chip_radar_2026-05-19.xlsx](./chip_radar_2026-05-19.xlsx) | 35.3 KB |
| 2026-05-18 | [chip_radar_2026-05-18.xlsx](./chip_radar_2026-05-18.xlsx) | 36.0 KB |
| 2026-05-15 | [chip_radar_2026-05-15.xlsx](./chip_radar_2026-05-15.xlsx) | 35.7 KB |
| 2026-05-14 | [chip_radar_2026-05-14.xlsx](./chip_radar_2026-05-14.xlsx) | 36.6 KB |
| 2026-05-13 | [chip_radar_2026-05-13.xlsx](./chip_radar_2026-05-13.xlsx) | 35.6 KB |
| 2026-05-12 | [chip_radar_2026-05-12.xlsx](./chip_radar_2026-05-12.xlsx) | 37.4 KB |
| 2026-05-11 | [chip_radar_2026-05-11.xlsx](./chip_radar_2026-05-11.xlsx) | 37.3 KB |
| 2026-05-08 | [chip_radar_2026-05-08.xlsx](./chip_radar_2026-05-08.xlsx) | 35.0 KB |
| 2026-05-07 | [chip_radar_2026-05-07.xlsx](./chip_radar_2026-05-07.xlsx) | 336.6 KB |

---

*Updated: 2026-05-23 08:44*