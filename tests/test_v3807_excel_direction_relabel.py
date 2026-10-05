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
  2. 手機摘要改顯示 net_weight 強度並註明非預測
  3. (v3.80.10 起) Dashboard 只呈現強共識買超清單, 不再有方向 banner;
     原本 banner 數字格式「正;負;零」三段的檢查隨之移除
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

        # v3.80.10 (使用者 2026-10-05): Dashboard 只呈現強共識買超清單, 方向橫幅
        # (原本的「籌碼偏向」banner 與其數字格式檢查) 隨 TL;DR 卡片一起拿掉.
        # 核心要求不變: 不得出現「明日預測」/「信心」.
        d_blob = ' '.join(v + ' ' + f for _, v, f in texts(ds))
        check("Dashboard 不出現「明日預測」/「信心」", '明日預測' not in d_blob and '信心' not in d_blob)
        check("Dashboard 是強共識清單 (個股/代號/領頭大戶/領頭金額(萬))",
              all(h in d_blob for h in ('個股', '代號', '領頭大戶', '領頭金額(萬)')), d_blob[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)

print(f"\n{'=' * 58}")
print(f"test_v3807_excel_direction_relabel: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
