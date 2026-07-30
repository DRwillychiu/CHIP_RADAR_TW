"""v3.70.0 Phase 3.2 rolling update.

daily-full.yml 在 crawler.py 完成後執行此 script, 達成:
  1. 重 bootstrap phase32_backtest.json (新增今日 → 新樣本進入滾動統計)
  2. 重 regen 今日 Excel (Dashboard 的 alpha sub-banner / quad 命中狀態抓最新)

之所以要 regen Excel:
  crawler.py 內呼叫 excel_report.generate_excel_report 時, phase32_backtest.json
  是「昨日 snapshot」(crawler 還沒重算今日 quad). 等本 script 重 bootstrap 後,
  再 regen 一次 Excel 才能讓今日 dashboard 顯示最新滾動 hit rate.

執行順序 (workflow):
  1. crawler.py (fetch + initial Excel)
  2. daily_rolling_update.py (本 script — refresh backtest + hit log + regen Excel)
  3. extract_mobile_summary_text.py (萃取 email body)
  4. Commit + push + email

steps:
  Step 1: re-bootstrap phase32_backtest.json (滾動 alpha 統計)
  Step 2: update quad_hit_log.json (實戰 hit 追蹤)
  Step 3: regen Excel (Dashboard 抓最新 backtest + hit 數字)
"""
import json, os, sys, shutil, subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# v3.73.1: 尊重 CHIP_RADAR_DATA_DIR (本機排程用 local_data/, 雲端維持 data/)。
#   原本寫死 ROOT/'data' — 本機跑會去讀寫 git 追蹤的 data/, 污染工作目錄。
DATA = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')

# 1. 抓最新交易日
with open(DATA / 'index.json', 'r', encoding='utf-8') as f:
    idx = json.load(f)
target_date = idx.get('latest')
if not target_date:
    print("X No latest date in data/index.json")
    sys.exit(1)
print(f"== Rolling update target_date: {target_date} ==")

def _run_script(rel_path, step_label):
    print()
    print(f"{step_label}: {rel_path}")
    result = subprocess.run(
        [sys.executable, str(ROOT / rel_path)],
        capture_output=True, env=os.environ
    )
    if result.returncode != 0:
        print(f"X {rel_path} failed (exit={result.returncode})")
        if result.stderr:
            try: print(result.stderr.decode('utf-8', errors='replace')[-500:])
            except: pass
        return False
    try:
        out_str = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
        print('\n'.join(out_str.strip().split('\n')[-6:]))
    except Exception as e:
        print(f"  (stdout decode skip: {e})")
    return True


# 2. Re-bootstrap phase32_backtest.json (滾動 alpha 統計)
if not _run_script('scripts/bootstrap_phase32_e_anomaly.py', 'Step 1/3'):
    sys.exit(1)

# 3. Update quad_hit_log.json (實戰 hit 追蹤)
if not _run_script('scripts/update_quad_hit_log.py', 'Step 2/3'):
    print("  ! quad hit log failed (繼續)")   # 非 critical, 不阻擋

# 4. Re-regen Excel
print()
print("Step 3/3: regen Excel with refreshed backtest + hit log")
from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import _update_monthly_workbook

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("X CHIP_RADAR_PASSWORD not set"); sys.exit(1)

src = DATA / f'{target_date}.json'
if not src.exists():
    src = DATA / 'archive' / f'{target_date}.json'
    if not src.exists():
        print(f"X data file not found: {target_date}")
        sys.exit(1)
print(f"  Reading: {src}")

with open(src, 'r', encoding='utf-8') as f:
    enc = json.load(f)
plain = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
data = json.loads(plain)

month_str = f"{target_date[:4]}-{target_date[4:6]}"
mp = DATA / 'reports' / f'chip_radar_{month_str}.xlsx'
lp = DATA / 'reports' / 'latest.xlsx'
_update_monthly_workbook(mp, data['branches'], target_date)
shutil.copy2(str(mp), str(lp))
print(f"  Regen OK: {mp.name} + latest.xlsx")
print()
print(f"== Rolling update DONE ==")
