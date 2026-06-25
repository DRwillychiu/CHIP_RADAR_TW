"""
resolve_data_dir() — 統一解析資料目錄路徑.

優先讀 CHIP_RADAR_DATA_DIR 環境變數；未設定時回傳 <project>/data/。
"""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def resolve_data_dir() -> Path:
    env = os.environ.get("CHIP_RADAR_DATA_DIR", "").strip()
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = _PROJECT_ROOT / env
    else:
        p = _PROJECT_ROOT / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p
