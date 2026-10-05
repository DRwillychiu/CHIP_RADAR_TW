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

v3.80.11 代號更正 (code_aliases): v3.80.11 以前分點頁解析器把「名稱以大寫字母
開頭」的股票代號讀錯 (00961 FT臺灣永續高息 → 00961FT 臺灣永續高息). 讀取時把
清單上的錯代號改回官方代號與名稱, 一樣不改寫歸檔.

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


_alias_cache: Dict[str, Dict[str, tuple]] = {}


def load_aliases(path: Optional[Path] = None) -> Dict[str, tuple]:
    """v3.80.11: {stored wrong stock code: (official code, official name)} from
    data/quarantine.json 'code_aliases'. Missing -> {}."""
    p = Path(path) if path else _DEFAULT_PATH
    key = str(p)
    if key not in _alias_cache:
        table: Dict[str, tuple] = {}
        if p.exists():
            doc = json.loads(p.read_text(encoding='utf-8'))
            for a in doc.get('code_aliases', []):
                table[a['from']] = (a['to'], a.get('name', ''))
        _alias_cache[key] = table
    return _alias_cache[key]


def _fix_rows(rows, aliases):
    """Same list object back when nothing matched (callers test identity)."""
    out = None
    for i, s in enumerate(rows):
        a = aliases.get(s.get('code')) if isinstance(s, dict) else None
        if a:
            if out is None:
                out = list(rows)
            out[i] = {**s, 'code': a[0], 'name': a[1] or s.get('name'), 'code_fixed_from': s.get('code')}
    return rows if out is None else out


def filter_day(data: dict, date: Optional[str] = None, path: Optional[Path] = None) -> dict:
    """Return `data` with quarantined branch records blanked and known-wrong stock
    codes corrected (v3.80.11 code_aliases). Input is not mutated.

    date: the file's trade date (YYYYMMDD). Defaults to data['trade_date'].
    Anything that is not a day dict with a 'branches' list is returned unchanged.
    """
    if not isinstance(data, dict) or not isinstance(data.get('branches'), list):
        return data
    day = str(date or data.get('trade_date') or '')
    table = load(path)
    aliases = load_aliases(path)
    if not aliases and (not day or not table):
        return data
    hit = False
    branches = []
    for b in data['branches']:
        if not isinstance(b, dict):
            branches.append(b)
            continue
        reason = table.get(b.get('code'), {}).get(day) if day else None
        if reason:
            hit = True
            branches.append({**b, 'buys': [], 'sells': [], 'quarantined': True,
                             'error': f'quarantined: {reason}'})
            continue
        if aliases:
            buys, sells = b.get('buys'), b.get('sells')
            nb = _fix_rows(buys, aliases) if buys else buys
            ns = _fix_rows(sells, aliases) if sells else sells
            if nb is not buys or ns is not sells:
                hit = True
                b = {**b, 'buys': nb, 'sells': ns}
        branches.append(b)
    if not hit:
        return data
    return {**data, 'branches': branches}
