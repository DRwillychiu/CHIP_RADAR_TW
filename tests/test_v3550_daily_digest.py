# v3.55.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""
test_v3550_daily_digest.py — v3.55.0 每日 Telegram 摘要

驗證:
  1. detect_foreign_extreme 吃「真實」institutional_rankings shape (回歸測試)
  2. is_redundant_rerun 三層兜底排程去重
  3. build_daily_digest 三個區塊 (執行狀態 / 籌碼 / 警報)
  4. HTML 轉義 (股票名稱含元字元不會讓 Telegram 噴 HTTP 400)
  5. run_alerts 無警報也推 Telegram, 但 Discord 維持不推
  6. run_alerts 兜底重跑 → 完全不呼叫 Telegram API
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from unittest.mock import patch, MagicMock
from alerts import (build_daily_digest, is_redundant_rerun, run_alerts,
                    detect_foreign_extreme, _esc)

PASS = 0
FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


# 乾淨 env — 避免本機 .env / CI secret 污染測試
for _k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'DISCORD_WEBHOOK_URL',
           'CHIP_RADAR_PREV_TRADE_DATE'):
    os.environ.pop(_k, None)

# crawler.py build_inst_ranking() 的真實回傳 shape
REAL_DATA = {
    'trade_date': '20260729',
    'crawled_at': '2026-07-29T21:23:11+08:00',
    'stage': 'full',
    'success': 81, 'failed': 0, 'empty': 0,
    'quotes_count': 1842, 'institutional_count': 1795,
    'institutional_rankings': {
        'foreign': {'buy': [], 'sell': [], 'total_net_lots': -7512},
    },
    'futures_data': {'summary': {'pc_ratio_oi': 1.85,
                                  'foreign_equivalent_net_oi': -42180}},
    'limit_up_summary': {'limit_up_stocks': [{'code': str(i)} for i in range(32)]},
    'margin_maintenance_summary': {'counts': {'high_risk': 12, 'margin_call': 3}},
}


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] 回歸: detect_foreign_extreme 吃真實 shape")
# v3.55.0 之前 build_inst_ranking 只回 {buy, sell},沒有 total_net_lots,
# 導致這個偵測器永遠讀到 0 → 從未觸發過。crawler.py 已補上該欄位。
sig = detect_foreign_extreme(REAL_DATA['institutional_rankings'])
check("真實 shape 能觸發外資極端警報", sig is not None,
      "→ crawler.build_inst_ranking 可能又漏掉 total_net_lots")
check("方向判定為賣超", sig and '賣超' in sig['title'])
check("張數正確", sig and abs(sig['value']) == 7512)

# 沒有 total_net_lots 的舊 shape → 不該爆炸,只是不觸發
old_shape = {'foreign': {'buy': [], 'sell': []}}
check("缺欄位時安全 return None", detect_foreign_extreme(old_shape) is None)


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] is_redundant_rerun — 三層兜底去重")
os.environ.pop('CHIP_RADAR_PREV_TRADE_DATE', None)
check("未設 env → False (保守: 寧可多推)", is_redundant_rerun('20260729') is False)

os.environ['CHIP_RADAR_PREV_TRADE_DATE'] = '20260729'
check("prev == 本次 → True (兜底重跑)", is_redundant_rerun('20260729') is True)
check("格式不同仍可比對 (2026-07-29)", is_redundant_rerun('2026-07-29') is True)
check("格式不同仍可比對 (2026/07/29)", is_redundant_rerun('2026/07/29') is True)

os.environ['CHIP_RADAR_PREV_TRADE_DATE'] = '20260728'
check("prev != 本次 → False (今天第一次跑)", is_redundant_rerun('20260729') is False)

os.environ['CHIP_RADAR_PREV_TRADE_DATE'] = ''
check("env 為空字串 → False", is_redundant_rerun('20260729') is False)
os.environ.pop('CHIP_RADAR_PREV_TRADE_DATE', None)


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] build_daily_digest — 三個區塊")
digest = build_daily_digest(REAL_DATA, [])
check("含日期", '20260729' in digest)
check("含執行狀態 (爬蟲完成)", '爬蟲完成' in digest)
check("含分點成功數", '81/81' in digest)
check("含籌碼區塊標題", '今日籌碼' in digest)
check("含外資張數 (帶負號千分位)", '-7,512' in digest)
check("含期貨未平倉", '-42,180' in digest)
check("含 PCR", '1.85' in digest)
check("含漲停家數", '32 檔' in digest)
check("含融資風險", '高風險 12 檔' in digest)
check("無警報時仍有警報區塊", '無重大警報訊號' in digest)


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] build_daily_digest — 部分失敗 / 資料缺漏")
partial = dict(REAL_DATA, success=68, failed=13)
d2 = build_daily_digest(partial, [])
check("失敗時標題改為「部分失敗」", '部分失敗' in d2)
check("顯示失敗分點數", '13 失敗' in d2)

# 期貨常常抓不到 — 少一行但不能整則爆掉
no_futures = dict(REAL_DATA)
no_futures['futures_data'] = None
d3 = build_daily_digest(no_futures, [])
check("期貨缺漏不影響其他行", '外資現貨' in d3 and 'P/C Ratio' not in d3)

check("空 dict 不拋例外", isinstance(build_daily_digest({}, []), str))
check("None 不拋例外", isinstance(build_daily_digest(None, None), str))


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] HTML 轉義 — 防 Telegram HTTP 400")
check("< 被轉義", _esc('<b>') == '&lt;b&gt;')
check("& 被轉義", _esc('A&B') == 'A&amp;B')

evil = [{'type': 'x', 'severity': 'high',
         'title': '測試 <script>', 'message': 'PCR > 1.8 & 散戶 <極端>'}]
d4 = build_daily_digest(REAL_DATA, evil)
check("警報標題被轉義", '&lt;script&gt;' in d4)
check("警報內文被轉義", '&gt;' in d4 and '&amp;' in d4)
check("未轉義的裸 < 不存在於警報內文", '<script>' not in d4)


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] run_alerts — 無警報也推 Telegram, Discord 不推")
quiet = dict(REAL_DATA)
quiet['institutional_rankings'] = {'foreign': {'buy': [], 'sell': [], 'total_net_lots': 100}}
quiet['futures_data'] = {'summary': {'pc_ratio_oi': 1.0}}
quiet['limit_up_summary'] = {'limit_up_stocks': []}

mock_resp = MagicMock(status_code=200)
with patch('alerts.requests.post', return_value=mock_resp) as m:
    with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123:ABC',
                                  'TELEGRAM_CHAT_ID': '789'}, clear=False):
        os.environ.pop('DISCORD_WEBHOOK_URL', None)
        res = run_alerts(quiet, dry_run=False)

    check("確實無警報", len(res['detected']) == 0)
    check("Telegram 仍有推 (無警報也推)", res['pushed_telegram'] is True)
    check("只呼叫一次 POST (Discord 沒推)", m.call_count == 1)
    payload = m.call_args[1].get('json', {})
    check("parse_mode = HTML", payload.get('parse_mode') == 'HTML')
    check("內容是 digest 不是純警報", '爬蟲完成' in payload.get('text', ''))
    check("未推 Discord", res['pushed'] is False)


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] run_alerts — 兜底重跑完全不推")
with patch('alerts.requests.post', return_value=mock_resp) as m2:
    with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123:ABC',
                                  'TELEGRAM_CHAT_ID': '789',
                                  'CHIP_RADAR_PREV_TRADE_DATE': '20260729'},
                     clear=False):
        os.environ.pop('DISCORD_WEBHOOK_URL', None)
        res2 = run_alerts(REAL_DATA, dry_run=False)

    check("標記為兜底跳過", res2['telegram_skipped_rerun'] is True)
    check("pushed_telegram 為 False", res2['pushed_telegram'] is False)
    tg_calls = [c for c in m2.call_args_list
                if 'telegram' in str(c).lower()]
    check("完全沒打 Telegram API", len(tg_calls) == 0)
    check("警報仍有偵測到 (只是不推)", len(res2['detected']) > 0)


# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3550_daily_digest: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
