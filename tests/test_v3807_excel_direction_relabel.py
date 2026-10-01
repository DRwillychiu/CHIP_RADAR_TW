# -*- coding: utf-8 -*-
"""v3.80.7 Excel 「明日預測」→「籌碼偏向 (描述非預測)」

背景 (2026-10-01):
  v3.78.0 用 160 天乾淨資料判定溫度計方向判定無 alpha (Δ+0.0pp) 並退役為「描述」,
  當時改了網站揭露框與 daily_signal headline, 但漏了 Excel 兩處:
    · 📱 手機摘要  「📅 明日預測  ↕ 中性 46.5%」  ← 這就是每日 Email 的第一行
    · 📋 Dashboard 「📅 明日預測 ↑ 偏多 58.7% 信心 — …」
  confidence_pct 是 net_weight 的線性換算, 不是命中率, 讀起來卻像勝率.

本測試鎖住:
  1. 兩處不再出現「明日預測」與「信心」
  2. 改顯示 net_weight 強度並註明非預測
  3. Dashboard 自訂數字格式的「正;負;零」三段都帶前後綴
     (第一版寫成 "+0.00;-0.00" 讓 ';' 把文字切斷, 負值時前綴會消失)
"""
import sys, os, json, re, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import openpyxl
import src.exports.excel_report as er

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1


def make_dir(direction, net, conf):
    d = Path(tempfile.mkdtemp())
    (d / 'daily_signal.json').write_text(json.dumps({
        'market_direction': {'direction': direction, 'net_weight': net,
                             'confidence_pct': conf,
                             'contributing': [{'name': 'P/C Ratio'}]},
        'top_focus_stocks': [{}, {}, {}],
    }, ensure_ascii=False), encoding='utf-8')
    return d


def texts(ws):
    out = []
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                out.append((c.coordinate, str(c.value), c.number_format or ''))
    return out


for direction, net, conf in (('偏多', 0.523, 95.0), ('中性', -0.035, 46.5), ('偏空', -0.148, 35.2)):
    print(f"\n[{direction} net={net:+.3f}]")
    d = make_dir(direction, net, conf)
    try:
        wb = openpyxl.Workbook()
        ms = wb.active
        er.build_mobile_summary_sheet(ms, [], '20261001', data_dir=d)
        ds = wb.create_sheet('dash')
        er.build_dashboard_sheet(ds, [], '20261001', data_dir=d, update_timeseries=False)

        m = texts(ms)
        blob = ' '.join(v + ' ' + f for _, v, f in m)
        check("手機摘要不再出現「明日預測」", '明日預測' not in blob)
        check("手機摘要不再把 confidence 當 % 顯示", f"{conf:.1f}%" not in blob)
        check("手機摘要標題為「今日籌碼偏向」", '今日籌碼偏向' in blob)
        check(f"手機摘要顯示強度 {net:+.2f}", f"強度 {net:+.2f}" in blob, blob[:200])
        check("手機摘要註明描述非預測", '描述非預測' in blob)

        dash = [x for x in texts(ds) if '籌碼偏向' in x[2] or '明日預測' in x[2]]
        check("Dashboard banner 存在", len(dash) == 1, dash)
        if dash:
            coord, val, fmt = dash[0]
            check("Dashboard 不再出現「明日預測」/「信心」",
                  '明日預測' not in fmt and '信心' not in fmt, fmt)
            check("Dashboard 數值是 net_weight 而非 confidence",
                  abs(float(val) - net) < 1e-9, val)
            # 不在引號內的 ';' 才是段落分隔
            sections = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', fmt)
            check("數字格式有 正/負/零 三段", len(sections) == 3, sections)
            check("三段都帶前綴「籌碼偏向」", all('籌碼偏向' in s for s in sections), sections)
            check("三段都帶後綴「描述非預測」", all('描述非預測' in s for s in sections), sections)
    finally:
        shutil.rmtree(d, ignore_errors=True)

print(f"\n{'=' * 58}")
print(f"test_v3807_excel_direction_relabel: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
