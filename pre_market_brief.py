# v3.51.0 機構級重整: sys.path 注入
import src  # noqa: F401
from data_dir import resolve_data_dir
"""
========================================================================
Module: pre_market_brief.py  (v3.41.0 Sprint 4)

盤前 08:50 TW 快訊 — workflow: pre-market-alert.yml

讀已存在的 data 檔案 (不爬新資料, 純摘要):
  - master_profiles.json: 昨日大戶 Top 3 變動
  - disposal_history/ 最新: 新增處置股
  - 結算日壓力: 距下個結算日 D 天

輸出 data/pre_market_brief.json + GitHub Actions ::notice::
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _master_movers(mp_data, top_n: int = 3):
    """從 master_profiles.json 抓昨日大戶 Top 3 (按交易次或曝險)."""
    if not mp_data:
        return []
    masters = mp_data.get('masters', {}) or {}
    ranked = []
    for name, p in masters.items():
        if p.get('no_data') or p.get('data_sufficiency', {}).get('level') == 'insufficient':
            continue
        op = p.get('operation_metrics') or {}
        ranked.append({
            'name': name,
            'trades_count': op.get('trades_count', 0),
            'total_buy_amt_wan': op.get('total_buy_amt_wan', 0),
            'strategy': (p.get('label_hierarchy') or {}).get('level2_strategy'),
            'sufficiency': (p.get('data_sufficiency') or {}).get('level'),
        })
    ranked.sort(key=lambda x: -x['total_buy_amt_wan'])
    return ranked[:top_n]


def _new_disposals(data_dir: Path):
    """比對最近兩天 disposal_history 找新增處置股."""
    snap_dir = data_dir / 'disposal_history'
    if not snap_dir.exists():
        return []
    files = sorted(snap_dir.glob('[0-9]' * 8 + '.json'), reverse=True)
    if len(files) < 2:
        return []
    today = _load_json(files[0]) or {}
    yest = _load_json(files[1]) or {}
    today_active = set((today.get('sets') or {}).get('active') or [])
    yest_active = set((yest.get('sets') or {}).get('active') or [])
    today_imm1 = set((today.get('sets') or {}).get('imminent_1') or [])
    yest_imm1 = set((yest.get('sets') or {}).get('imminent_1') or [])
    return {
        'newly_active': sorted(today_active - yest_active),
        'newly_imminent_1': sorted(today_imm1 - yest_imm1),
        'date': today.get('applicable_date'),
    }


def _days_to_settlement(now_dt: datetime):
    """簡化: 距下個月第三週三的天數 (移植自 crawler_pipeline.third_wed)."""
    from datetime import date as _date
    y, m = now_dt.year, now_dt.month
    candidates = []
    for delta in (0, 1, -1):
        mm = m + delta
        yy = y
        if mm > 12: yy += 1; mm -= 12
        if mm < 1: yy -= 1; mm += 12
        first = _date(yy, mm, 1)
        offset = (2 - first.weekday()) % 7
        third_wed = _date(yy, mm, 1 + offset + 14)
        candidates.append(third_wed)
    today = now_dt.date()
    diffs = [(c - today).days for c in candidates]
    relevant = [d for d in diffs if d >= -3]
    if not relevant:
        return diffs[1]
    return min(relevant, key=abs)


def build_brief(data_dir: str = 'data'):
    dd = Path(data_dir)
    now = now_tw()

    # 1. 大戶 Top 3
    mp_data = _load_json(dd / 'master_profiles.json')
    movers = _master_movers(mp_data)

    # 2. 新處置股
    new_disp = _new_disposals(dd)

    # 3. 結算日壓力
    days_to_settle = _days_to_settlement(now)

    brief = {
        'generated_at': now.isoformat(),
        'date': now.strftime('%Y-%m-%d'),
        'master_movers_top3': movers,
        'new_disposals': new_disp,
        'settlement': {
            'days_to_next': days_to_settle,
            'phase': (
                '結算當日±1' if abs(days_to_settle) <= 1
                else '結算週' if abs(days_to_settle) <= 3
                else '非結算週'
            ),
        },
        'source': 'pre_market_brief.py (Sprint 4 C1)',
    }

    out = dd / 'pre_market_brief.json'
    out.parent.mkdir(exist_ok=True)
    tmp = out.with_suffix('.tmp')
    tmp.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(out)
    return brief


def main():
    brief = build_brief(str(resolve_data_dir()))
    # GitHub Actions ::notice::
    movers_str = ', '.join(f"{m['name']}({m['total_buy_amt_wan']:,}萬)" for m in brief['master_movers_top3'][:3])
    disp = brief.get('new_disposals') or {}
    new_a = disp.get('newly_active') or []
    new_i = disp.get('newly_imminent_1') or []
    settle = brief.get('settlement') or {}
    print(f"::notice title=Pre-Market Brief {brief['date']}::"
          f"大戶 Top3: {movers_str} | 新處置 {len(new_a)} 檔 | 新差1次 {len(new_i)} 檔 | "
          f"結算 {settle.get('phase')} (D{settle.get('days_to_next'):+d})")
    print()
    print(f"[Pre-Market Brief] → data/pre_market_brief.json")
    print(f"  大戶 Top 3: {movers_str}")
    if new_a:
        print(f"  新處置股 ({len(new_a)}): {new_a[:5]}")
    if new_i:
        print(f"  新差 1 次 ({len(new_i)}): {new_i[:5]}")
    print(f"  結算: {settle.get('phase')} (D{settle.get('days_to_next'):+d})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
