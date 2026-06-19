"""
========================================================================
Module: backfill_market_history.py  (v3.43.0)

一次性 backfill — 修正 stock_history.json market 區段的 change_pct
重算 temp_history.json next_day_change_pct

bug 根因 (見 history.py v3.43.0 fix):
  TWSE OpenAPI MI_INDEX 的「漲跌百分比」是絕對值, 由「漲跌」('+' / '-') 給符號.
  歷史觀察到 sign 欄位偶爾空白 → 30 天 stock_history.market 全部 stored 為正.
  5/14 index 從 41898 → 41374 跌 1.25% 卻 stored +1.25%.

修法:
  逐日用 (today_index - prev_index) / prev_index × 100 重算
  同步把 temp_history[i].next_day_change_pct 重設為 stock_history.market[i+1].change_pct

用法:
  python backfill_market_history.py [--dry-run]
"""
import sys
import json
from pathlib import Path


def backfill_market(data_dir: str = 'data', dry_run: bool = False) -> dict:
    """重算 stock_history.json market 區段 change_pct."""
    sh_path = Path(data_dir) / 'stock_history.json'
    if not sh_path.exists():
        print(f"❌ {sh_path} 不存在")
        return {}
    sh = json.loads(sh_path.read_text(encoding='utf-8'))
    market = sh.get('market', {}) or {}
    if not market:
        print(f"❌ stock_history.market 為空")
        return {}

    dates = sorted(market.keys())
    print(f"[Backfill] {len(dates)} 天 market 資料: {dates[0]} ~ {dates[-1]}")

    changes = []
    for i, date in enumerate(dates):
        rec = market[date]
        cur_idx = rec.get('index')
        if not cur_idx:
            continue
        if i == 0:
            # 首日無前日可比, 保留 API 值, 加 source 標記
            new_pct = rec.get('change_pct')
            source = 'api_only_first_day'
        else:
            prev_idx = market[dates[i - 1]].get('index')
            if not prev_idx or prev_idx <= 0:
                new_pct = rec.get('change_pct')
                source = 'api_only_no_prev'
            else:
                new_pct = round((cur_idx - prev_idx) / prev_idx * 100, 2)
                source = 'index_diff_verified'
        old_pct = rec.get('change_pct')
        if old_pct != new_pct:
            changes.append({
                'date': date, 'index': cur_idx,
                'old_pct': old_pct, 'new_pct': new_pct, 'source': source,
            })
        rec['change_pct'] = new_pct
        rec['change_pct_source'] = source

    print(f"\n[Backfill] {len(changes)} 天 change_pct 改變:")
    for ch in changes[:15]:
        print(f"  {ch['date']}: idx={ch['index']} pct {ch['old_pct']:+.2f}% → {ch['new_pct']:+.2f}% ({ch['source']})")
    if len(changes) > 15:
        print(f"  ... +{len(changes) - 15} 更多")
    # 統計新 distribution
    pos = sum(1 for d in dates if (market[d].get('change_pct') or 0) > 0)
    neg = sum(1 for d in dates if (market[d].get('change_pct') or 0) < 0)
    zero = sum(1 for d in dates if (market[d].get('change_pct') or 0) == 0)
    print(f"[Backfill] 新分布: 漲 {pos} / 跌 {neg} / 平 {zero}")

    if dry_run:
        print(f"[Backfill] 🧪 dry-run, 不寫檔")
        return {'changes': changes, 'pos': pos, 'neg': neg, 'zero': zero}

    # write atomic
    tmp = sh_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(sh, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(sh_path)
    print(f"[Backfill] ✓ 寫回 {sh_path}")

    # 同步重算 temp_history.json next_day_change_pct
    th_path = Path(data_dir) / 'temp_history.json'
    if th_path.exists():
        th = json.loads(th_path.read_text(encoding='utf-8'))
        history = th.get('history', []) or []
        th_dates = sorted([h.get('date') for h in history if h.get('date')])
        updated = 0
        # 建索引
        idx_map = {h['date']: h for h in history if h.get('date')}
        for h_date in th_dates:
            h = idx_map[h_date]
            # 找 stock_history.market 裡 h_date 之後最近的交易日
            next_dates = [d for d in dates if d > h_date]
            if next_dates:
                next_date = next_dates[0]
                next_chg = market[next_date].get('change_pct')
                if next_chg is not None and h.get('next_day_change_pct') != next_chg:
                    h['next_day_change_pct'] = next_chg
                    updated += 1
            # 同步 taiex_change_pct
            if h_date in market:
                today_chg = market[h_date].get('change_pct')
                if today_chg is not None:
                    h['taiex_change_pct'] = today_chg
        print(f"[Backfill] 重算 temp_history.next_day_change_pct: {updated} 筆更新")
        tmp = th_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(th, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(th_path)
        print(f"[Backfill] ✓ 寫回 {th_path}")

    return {'changes': changes, 'pos': pos, 'neg': neg, 'zero': zero}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    backfill_market(args.data_dir, args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
