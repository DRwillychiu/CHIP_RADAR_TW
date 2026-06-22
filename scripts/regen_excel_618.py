"""v3.63.2/3 重生 6/18 Excel — 把 chip_radar_2026-06.xlsx 內的 Dashboard 用新邏輯重建.

執行前先設環境變數:
  $env:CHIP_RADAR_PASSWORD = '...'
"""
import json, sys, os
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import _update_monthly_workbook

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("❌ CHIP_RADAR_PASSWORD 環境變數沒設")
    sys.exit(1)

target_date = '20260618'
src_json = ROOT / 'data' / f'{target_date}.json'
print(f"讀: {src_json}")

with open(src_json, 'r', encoding='utf-8') as f:
    enc = json.load(f)

plaintext = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
data = json.loads(plaintext)
branches_data = data.get('branches', [])
print(f"branches: {len(branches_data)}")

# v3.63 regen: 用新邏輯重建月檔 + latest
monthly_path = ROOT / 'data' / 'reports' / 'chip_radar_2026-06.xlsx'
latest_path = ROOT / 'data' / 'reports' / 'latest.xlsx'
print(f"重生月檔: {monthly_path}")

_update_monthly_workbook(monthly_path, branches_data, target_date)

# Copy to latest
import shutil
shutil.copy2(str(monthly_path), str(latest_path))
print(f"copied to latest: {latest_path}")

print(f"✓ Done. 開啟 {monthly_path} 檢視 Dashboard sheet (應已套用 v3.63.2 嚴格邏輯)")
