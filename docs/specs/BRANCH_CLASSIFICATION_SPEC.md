# Branch classification spec (v3.82.0, 2026-10-08)

Owner decisions 2026-10-08: classify broker branches by their position in the
market (aggregator, strong, potential strong, big player, local); profit and
performance must follow the generally accepted, complete financial model;
local analysis covers the six municipalities only.

## 1. Data

| Source | Use | Status |
|---|---|---|
| `data/chip_radar_v2.db` daily_chips (DB artifact) | daily top-50 net-buy / net-sell rows of the tracked branches | 83 branches, 85 dates |
| `data/stock_history.json` | 60 trading days of closes and TAIEX | window of the model |
| `data/branch_geo.json` (`scripts/build_branch_geo.py`) | six-city district of branches and companies, open data only | 595 branches (84% located), 1,555 companies (95%) |
| whole-market branch data | needed for "position in the whole market" | on hold: data-provider terms, inquiry letter pending |

## 2. Performance model (`src/analyzers/branch_performance.py`)

- FIFO lots per (branch, stock); commission 0.1425% both sides, securities
  transaction tax 0.3% on sells (undiscounted, conservative).
- Realized + unrealized (open lots marked to the close). Opening inventory
  enters at the window-start close (GIPS beginning market value).
- Returns: Modified Dietz (GIPS) and daily time-weighted return.
- Risk: annualized volatility, Sharpe, Sortino, max drawdown.
- Benchmark: beta and Jensen's alpha vs TAIEX (daily OLS), information
  ratio (IR), excess PnL of the same cash flows in TAIEX.
- Positions: win rate, payoff, profit factor, expectancy, PnL per NT$10M.
- Owner's legacy 每千萬期望值 is reproduced unchanged and in 萬 (the sheet's
  `sell lots x price difference` is 仟元, so the legacy value is 10x).
- Every result carries its limits: share of rows whose lots were estimated,
  unmatched-sell ratio (sells without known inventory), daily top-50
  visibility.

## 3. Classes

A branch can hold more than one class; aggregators are ranked separately.

| Class | Rule (2026-10-08 thresholds) |
|---|---|
| Aggregator (head office, foreign broker) | window buys >= NT$150bn, or a foreign broker / head-office code |
| Strong | IR (60 d) >= 1, alpha > 0, >= 40 return days, >= 100 positions |
| Potential strong | among non-aggregators: IR (last 20 d) in the top quartile of peers, IR (60 d) not above the peer median, alpha (20 d) > 0. Peer-relative because the absolute 20-day IR moves with the market regime |
| Big player | the owner's labelled branches (`src/core/branches.py` masters); features for finding new ones come later |
| Local (six cities) | branch district known; share of its buys in companies of the same district >= 3%, >= 3 local stocks, lift over the all-branch average >= 3 (or same city >= 10% with lift >= 2) |
| Insufficient sample | position value below NT$1m on most days -> no risk statistics |

## 4. Next phase: branch relationships (owner request 2026-10-08)

| Study | Question | Method | Acceptance case |
|---|---|---|---|
| R1 account transfer (匯撥) | shares bought at branch A and later sold at branch B | a transfer is not a trade: B shows sells without visible buys (unmatched ratio) after A stopped accumulating; match stock, timing and size | 焦家: 984K accumulates, 989N / 585b sell (2492, 4919, 6173) |
| R2 co-trading | when branch X buys big, do other branches buy the same stock the same day or +-1 day | lift of co-buy probability over the base rate on X's top-decile buy days; network of pairs with lift >= 3 and enough co-occurrences | compare with the DB snapshot Q9 pair counts |
| R3 peer spillover | when a stock is bought big, are its industry peers or its runner-up bought too | same-industry and runner-up (2nd by market value in the sub-industry) net buying on day 0..+3 vs base rate, by the same branch and market-wide (XQ main-force net, licensed, kept local) | owner examples to be given |
