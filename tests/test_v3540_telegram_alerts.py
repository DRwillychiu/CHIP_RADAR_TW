# v3.54.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""
test_v3540_telegram_alerts.py — v3.54.0 Sprint 16 長2

驗證 src/alerts/alerts.py 新加 send_telegram + 整合 run_alerts:
  1. send_telegram 未設 token / chat_id → test mode (return None)
  2. send_telegram 有 token + chat_id (mock requests) → return True
  3. _format_telegram_alert 空 detected → 「無重大警報」訊息
  4. _format_telegram_alert 含 alerts → emoji + alert title + body
  5. run_alerts 加入 pushed_telegram + pushed_telegram_test_mode 欄位
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from unittest.mock import patch, MagicMock
from alerts import send_telegram, _format_telegram_alert, run_alerts

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


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] send_telegram 未設 → test mode")
# 確保 env 清空
old_token = os.environ.pop('TELEGRAM_BOT_TOKEN', '')
old_cid = os.environ.pop('TELEGRAM_CHAT_ID', '')
r = send_telegram('test message')
check("無 token/chat_id → return None (test mode)", r is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] send_telegram 顯式傳 token+chat_id → POST")
mock_resp = MagicMock(status_code=200)
with patch('alerts.requests.post', return_value=mock_resp) as m:
    r = send_telegram('alert', bot_token='123:ABC', chat_id='789')
    check("有 token+chat_id → return True", r is True)
    check("POST 被呼叫", m.called)
    call_args = m.call_args
    url = call_args[0][0]
    check("URL 含 telegram api + token", 'api.telegram.org/bot123:ABC/sendMessage' in url)
    payload = call_args[1].get('json', {})
    check("payload chat_id 正確", payload.get('chat_id') == '789')
    check("payload text 正確", payload.get('text') == 'alert')
    check("payload parse_mode = Markdown", payload.get('parse_mode') == 'Markdown')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] send_telegram HTTP 400 → return False")
mock_resp_fail = MagicMock(status_code=400, text='Bad chat_id')
with patch('alerts.requests.post', return_value=mock_resp_fail):
    r = send_telegram('test', bot_token='x', chat_id='y')
    check("HTTP fail → False", r is False)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] _format_telegram_alert — 空 detected")
text = _format_telegram_alert([], '20260621')
check("含「無重大警報」", '無重大警報' in text)
check("含日期", '20260621' in text)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] _format_telegram_alert — 含 alerts")
detected = [
    {'type': 'foreign_extreme', 'severity': 'high',
     'title': '外資爆量', 'message': '+5500 張'},
    {'type': 'limit_up', 'severity': 'medium',
     'title': '漲停過熱', 'message': '32 檔'},
]
text2 = _format_telegram_alert(detected, '20260621')
check("含 master alert title", '外資爆量' in text2 and '漲停過熱' in text2)
check("含 message body", '+5500 張' in text2 and '32 檔' in text2)
check("含 count summary", '共 2 則警報' in text2)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] run_alerts 加 pushed_telegram 欄位")
fake_data = {
    'institutional_rankings': {},
    'futures_data': {},
    'limit_up_summary': {},
    'insider_data': None,
    'announcements': [],
}
with patch('alerts.requests.post', return_value=mock_resp):
    # token+chat_id 都未設 (test mode), discord 也未設
    result = run_alerts(fake_data, dry_run=False)
    check("result 含 pushed_telegram 欄位", 'pushed_telegram' in result)
    check("result 含 pushed_telegram_test_mode 欄位",
          'pushed_telegram_test_mode' in result)
    check("Telegram 走 test mode (未設 token)", result['pushed_telegram_test_mode'] is True)

# 恢復原 env
if old_token: os.environ['TELEGRAM_BOT_TOKEN'] = old_token
if old_cid: os.environ['TELEGRAM_CHAT_ID'] = old_cid

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3540_telegram_alerts: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
