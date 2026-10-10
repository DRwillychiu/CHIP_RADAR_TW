# v3.95.0 = V1.0: header label, version history, polite backfill tool, 0917 futures hole - offline
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-10 "這四項，現在立即解決" + V1.0 once they are done."""
ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.95.0 正式版 V1.0 (離線)")
print("=" * 72)
h = (ROOT / 'index.html').read_text(encoding='utf-8')
check("頁首顯示 V1.0, 滑過看 build 號", 'title="build v3.95.0 ・ 點 📋 更新看版本歷史">Chip Radar V1.0</div>' in h and 'Chip Radar v3.80.14' not in h)
cl = h[h.index('const CHANGELOG_ENTRIES = ['):h.index('];', h.index('const CHANGELOG_ENTRIES = ['))]
vs = re.findall(r"\{ v: '([^']+)'", cl)
check("版本歷史第一筆是 V1.0, 維持近 10 筆", vs[:1] == ['V1.0'] and len(vs) == 10, vs)
bf = (ROOT / 'scripts/backfill_futures_day.py').read_text(encoding='utf-8')
gap = float(re.search(r'^GAP_S = ([0-9.]+)', bf, re.M).group(1))
mx = int(re.search(r'^MAX_REQUESTS = (\d+)', bf, re.M).group(1))
check("補資料工具守規矩: 間隔 >= 5 秒、最多 50 次內、遇 403/429/5xx 立刻停", gap >= 5 and mx <= 50
      and 'r.status_code in (403, 429) or r.status_code >= 500' in bf, (gap, mx))
check("補資料工具: 抓回來還是缺 (0 / 沒 P/C / 估算值) 就不寫", 'if not oi or pc is None or "備援" in str(src):' in bf)
fut = json.loads((ROOT / 'data/stock_history.json').read_text(encoding='utf-8')).get('futures', {})
x = fut.get('20260917')
check("9/17 期貨不再是 0 (還在 60 日歷史裡才檢查)", x is None or (x.get('foreign_equivalent_net_oi') and x.get('pc_ratio_oi') is not None),
      x and (x.get('foreign_equivalent_net_oi'), x.get('pc_ratio_oi')))
print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
