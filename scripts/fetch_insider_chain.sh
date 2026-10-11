#!/usr/bin/env bash
# v3.96.0 insider radar: owner 2026-10-11 "先抓一年資料，在繼續往上慢慢推上去" / "如果一年的資料完整抓取，
# 就繼續推進抓取第二年". Year 1 (2025-09..2026-08) first; only when it finishes cleanly (exit 0) the
# second year (2024-10..2025-08) follows after a 2-minute pause. Block / cycle pass through.
#   bash scripts/fetch_insider_chain.sh <block> <cycle_s> [first_delay_s]
cd "$(dirname "$0")/.." || exit 1
B=${1:-7}; C=${2:-120}; D=${3:-0}
export PYTHONIOENCODING=utf-8
python scripts/fetch_insider_people.py --since 202509 --block "$B" --cycle "$C" --delay "$D" --max-requests 1500 >> logs/insider_people.log 2>&1 \
  || { echo "[chain] $(date +%H:%M:%S) year 1 did not finish cleanly - year 2 not started" >> logs/insider_people.log; exit 1; }
echo "[chain] $(date +%H:%M:%S) year 1 complete - year 2 (since 202410) in 2 min" >> logs/insider_people.log
python scripts/fetch_insider_people.py --since 202410 --block "$B" --cycle "$C" --delay 120 --max-requests 2500 >> logs/insider_people.log 2>&1   || { echo "[chain] $(date +%H:%M:%S) year 2 did not finish cleanly - year 3 not started" >> logs/insider_people.log; exit 1; }
echo "[chain] $(date +%H:%M:%S) year 2 complete - year 3 (since 202309) in 2 min" >> logs/insider_people.log
# owner 2026-10-11: 「其他年份繼續抓」 - year 3 = 2023-09..2024-09 (the summary table goes back at least to 2023-09)
python scripts/fetch_insider_people.py --since 202309 --block "$B" --cycle "$C" --delay 120 --max-requests 2500 >> logs/insider_people.log 2>&1
echo "[chain] $(date +%H:%M:%S) year 3 exit $?" >> logs/insider_people.log
