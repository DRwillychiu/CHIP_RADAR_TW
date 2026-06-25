# v3.51.0 機構級重整: sys.path 注入
import src  # noqa: F401
from data_dir import resolve_data_dir
"""
========================================================================
Module: weekly_summary.py  (v3.41.0 Sprint 4)

週五 14:30 TW 收盤後綜合 — workflow: weekly-summary.yml
產出 Markdown 週報 → data/reports/weekly_YYYY_WXX.md

內容:
  - TDCC 大戶比例本週 movers (top risers/fallers)
  - master 週度進出排名 (大戶曝險變動)
  - 處置股名單本週變動
  - 5 天市場溫度趨勢
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


def build_markdown(data_dir: str = 'data') -> str:
    dd = Path(data_dir)
    now = now_tw()
    iso = now.isocalendar()
    week_id = f"{iso[0]}-W{iso[1]:02d}"

    lines = [f"# Chip Radar TW · 週度綜合報告 · {week_id}",
              "",
              f"> **產生時間**: {now.isoformat()}",
              f"> **資料源**: data/tdcc_holdings.json + data/master_profiles.json + data/disposal_map.json",
              "",
              "---", ""]

    # 1. TDCC 大戶 movers
    tdcc = _load_json(dd / 'tdcc_holdings.json')
    if tdcc:
        eff = tdcc.get('effective_date', '?')
        lines.append(f"## 🏦 集保大戶持股結構 (資料期 {eff})")
        lines.append("")
        holdings = tdcc.get('holdings', {}) or {}
        risers = []
        fallers = []
        for code, h in holdings.items():
            vp = h.get('vs_prev_week') or {}
            delta = vp.get('big400_delta_pp')
            if delta is None:
                continue
            entry = {'code': code, 'big400_pct': h.get('big400_pct'), 'delta': delta}
            risers.append(entry); fallers.append(entry)
        risers.sort(key=lambda x: -x['delta'])
        fallers.sort(key=lambda x: x['delta'])
        if risers and risers[0]['delta'] > 0:
            lines.append("### 🔺 大戶比例上升 Top 10 (籌碼集中)")
            lines.append("")
            lines.append("| # | 代號 | 本週 % | +pp |")
            lines.append("|---|---|---|---|")
            for i, r in enumerate(risers[:10], 1):
                lines.append(f"| {i} | {r['code']} | {r['big400_pct']:.1f}% | +{r['delta']:.2f} |")
            lines.append("")
        if fallers and fallers[0]['delta'] < 0:
            lines.append("### 🔻 大戶比例下降 Top 10 (大戶出貨)")
            lines.append("")
            lines.append("| # | 代號 | 本週 % | −pp |")
            lines.append("|---|---|---|---|")
            for i, f in enumerate(fallers[:10], 1):
                lines.append(f"| {i} | {f['code']} | {f['big400_pct']:.1f}% | {f['delta']:.2f} |")
            lines.append("")
    else:
        lines.append("⏭️ TDCC 資料尚未產生 (週六 11:00 後生效)")
        lines.append("")

    # 2. master 週度曝險 Top 5
    mp = _load_json(dd / 'master_profiles.json')
    if mp:
        lines.append("---")
        lines.append("")
        lines.append(f"## 👤 個人大戶曝險 Top 5 (窗口 {mp.get('window_days', '?')} 天)")
        lines.append("")
        masters = mp.get('masters', {}) or {}
        ranked = []
        for name, p in masters.items():
            if p.get('no_data'):
                continue
            op = p.get('operation_metrics') or {}
            ranked.append({
                'name': name,
                'total_buy_amt_wan': op.get('total_buy_amt_wan', 0),
                'strategy': (p.get('label_hierarchy') or {}).get('level2_strategy'),
                'sufficiency': (p.get('data_sufficiency') or {}).get('level'),
            })
        ranked.sort(key=lambda x: -x['total_buy_amt_wan'])
        lines.append("| # | Master | 累積買進 (萬) | 策略 | 樣本 |")
        lines.append("|---|---|---|---|---|")
        for i, r in enumerate(ranked[:5], 1):
            suff = {'full': '✓ 充足', 'partial': '🟡 部分', 'insufficient': '⏳ 不足'}.get(r['sufficiency'], '?')
            lines.append(f"| {i} | {r['name']} | {r['total_buy_amt_wan']:,} | {r['strategy'] or '-'} | {suff} |")
        lines.append("")

    # 3. 處置股本週
    disp = _load_json(dd / 'disposal_map.json')
    if disp:
        lines.append("---")
        lines.append("")
        sets = disp.get('sets', {}) or {}
        lines.append(f"## ⚠️ 處置股清單 (資料期 {disp.get('applicable_date', '?')})")
        lines.append("")
        lines.append(f"- 處置中: {len(sets.get('active') or [])} 檔")
        lines.append(f"- 差 1 次: {len(sets.get('imminent_1') or [])} 檔 — {(sets.get('imminent_1') or [])[:5]}")
        lines.append(f"- 差 2 次: {len(sets.get('imminent_2') or [])} 檔")
        lines.append("")

    # 4. 溫度
    temp = _load_json(dd / 'temp_history.json')
    if temp:
        h = temp.get('history') or []
        last5 = h[-5:] if len(h) >= 5 else h
        if last5:
            lines.append("---")
            lines.append("")
            lines.append("## 🌡️ 籌碼溫度近 5 日")
            lines.append("")
            lines.append("| 日期 | 溫度 |")
            lines.append("|---|---|")
            for d in last5:
                lines.append(f"| {d.get('date', '?')} | {d.get('score', '?')} |")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*本報告由 weekly_summary.py 自動產生 · {now.strftime('%Y-%m-%d %H:%M %z')}*")
    return '\n'.join(lines)


def main():
    dd = resolve_data_dir()
    md = build_markdown(str(dd))
    now = now_tw()
    iso = now.isocalendar()
    week_id = f"{iso[0]}_W{iso[1]:02d}"
    out = dd / 'reports' / f'weekly_{week_id}.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding='utf-8')
    print(f"::notice title=Weekly Summary {week_id}::已產生 {out}")
    print(f"[Weekly Summary] → {out} ({len(md)} chars)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
