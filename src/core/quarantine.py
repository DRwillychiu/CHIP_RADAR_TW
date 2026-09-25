"""
quarantine.py — 已知錯誤的 (分點, 日期) 排除清單 (v3.80.3)

問題: 2026-06-05 ~ 09-24 富邦把 9A9g (永豐金-內湖) 與 9A9G (永豐金-天母) 當成同一
代號, 有 52 個分點日存成了「另一個分點」的資料 (見 data/quarantine.json).
v3.80.1/v3.80.2 已堵住來源; 這裡處理「已經存下來的錯資料」.

做法: 讀取時排除, 不改寫加密歸檔.
  - 被排除的分點紀錄保留 code/name/master, buys/sells 清空, error 註明原因,
    quarantined=True. 下游把它當成「當天沒資料」.
  - 清單移除某筆 → 原始紀錄自動恢復 (檔案從未被動過).
  - 比對用「檔案的交易日 (YYYYMMDD)」+「大小寫完全相同的分點代號」.

所有讀歷史日檔的地方都必須經過 filter_day() — tests/test_v3803_quarantine.py
會掃 repo, 抓出沒經過它的讀取點.
"""
import json
from pathlib import Path
from typing import Dict, Optional

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'quarantine.json'
_cache: Dict[str, Dict[str, Dict[str, str]]] = {}


def load(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """{branch_code: {YYYYMMDD: reason}}. Missing file -> {} (nothing excluded)."""
    p = Path(path) if path else _DEFAULT_PATH
    key = str(p)
    if key not in _cache:
        table: Dict[str, Dict[str, str]] = {}
        if p.exists():
            doc = json.loads(p.read_text(encoding='utf-8'))
            for e in doc.get('entries', []):
                for d in e.get('dates', []):
                    table.setdefault(e['code'], {})[str(d)] = e.get('reason', 'quarantined')
        _cache[key] = table
    return _cache[key]


def is_quarantined(code: str, date: str, path: Optional[Path] = None) -> bool:
    return str(date) in load(path).get(code, {})


def filter_day(data: dict, date: Optional[str] = None, path: Optional[Path] = None) -> dict:
    """Return `data` with quarantined branch records blanked. Input is not mutated.

    date: the file's trade date (YYYYMMDD). Defaults to data['trade_date'].
    Anything that is not a day dict with a 'branches' list is returned unchanged.
    """
    if not isinstance(data, dict) or not isinstance(data.get('branches'), list):
        return data
    day = str(date or data.get('trade_date') or '')
    table = load(path)
    if not day or not table:
        return data
    hit = False
    branches = []
    for b in data['branches']:
        reason = table.get(b.get('code'), {}).get(day) if isinstance(b, dict) else None
        if reason:
            hit = True
            branches.append({**b, 'buys': [], 'sells': [], 'quarantined': True,
                             'error': f'quarantined: {reason}'})
        else:
            branches.append(b)
    if not hit:
        return data
    return {**data, 'branches': branches}
