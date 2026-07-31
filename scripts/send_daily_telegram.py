"""v3.73.4: 本機排程跑完後,把「📱 手機摘要」+ 潛在處置股清單 + latest.xlsx
推到 Telegram。同一個交易日內重跑改為「編輯既有訊息」而非重發。

跟雲端 daily-full.yml 的「Send daily summary to Telegram」等價,但多兩件事:
  1. 額外推一則完整潛在處置股清單 (D-1 + D-2)
  2. 兜底排程重跑時走 editMessageText / editMessageMedia 更新原訊息

為什麼要「更新」而不是「跳過」或「重發」:
  daily-full 有 21:17 / 22:37 / 23:47 三層兜底,每層都完整跑一次爬蟲,
  而後面幾次的資料可能更完整 (實測 21:17 抓到 76 分點、22:37 抓到 77)。
  重發會洗版,單純跳過又拿不到更新後的數字 → 折衷是原地編輯。

狀態檔 local_data/.tg_last_push (JSON):
  {"trade_date": "20260730",
   "summary":  {"message_id": 123, "hash": "..."},
   "disposal": {"message_id": 124, "hash": "..."},
   "document": {"message_id": 125, "hash": "..."}}
  相容舊版純文字格式 (只有 trade_date,無 message_id → 該次改為重發)。

用法:
    python scripts/send_daily_telegram.py            # 正常 (新發 or 更新)
    python scripts/send_daily_telegram.py --force    # 一律當新的重發
    python scripts/send_daily_telegram.py --dry-run  # 只印不推

token 來源 (優先序): 環境變數 → 專案根目錄 .env
兩者皆無 → 印訊息後 exit 0 (不讓排程判定為失敗)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORCE = '--force' in sys.argv
DRY_RUN = '--dry-run' in sys.argv

DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
XLSX = DATA_DIR / 'reports' / 'latest.xlsx'
LATEST = DATA_DIR / 'latest.json'
STATE = DATA_DIR / '.tg_last_push'

MOBILE_SHEET = '📱 手機摘要'


# ════════════════════════════════════════════════════════════════════
#  基礎工具
# ════════════════════════════════════════════════════════════════════

def load_dotenv_into_env() -> None:
    """把 .env 的值補進 os.environ (不覆蓋既有的) — 對齊 scheduler.ps1:14-26."""
    env_file = ROOT / '.env'
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k, v = k.strip(), v.strip()
        if v and not os.environ.get(k):
            os.environ[k] = v


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()[:16]


def read_trade_date() -> str:
    """從 latest.json 的明文外層讀 trade_date (不需密碼)."""
    try:
        return str(json.loads(LATEST.read_text(encoding='utf-8')).get('trade_date', ''))
    except Exception as e:
        print(f"  ⚠️ 讀不到 {LATEST}: {e}")
        return ''


def load_state() -> dict:
    """讀狀態檔。相容 v3.73.1-3 的純文字格式 (只有 trade_date)."""
    if not STATE.exists():
        return {}
    raw = ''
    try:
        raw = STATE.read_text(encoding='utf-8').strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        st = json.loads(raw)
    except Exception:
        st = None
    # 注意: 舊格式內容是純日期字串 "20260730",而它本身就是合法 JSON (數字),
    # json.loads 會成功解析成 int → 必須用 isinstance 檢查而非靠例外分支,
    # 否則舊狀態檔會被誤判為「無狀態」,同一天內重發而非更新。
    if isinstance(st, dict):
        return st
    return {'trade_date': raw}


def save_state(st: dict) -> None:
    try:
        STATE.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f"  [Telegram] ⚠️ 狀態檔寫入失敗 (下次可能重發): {e}")


def extract_mobile_summary() -> str:
    """抓 latest.xlsx 的手機摘要 sheet → 純文字 (邏輯同 extract_mobile_summary_text.py)."""
    from openpyxl import load_workbook
    wb = load_workbook(str(XLSX), data_only=True)
    if MOBILE_SHEET not in wb.sheetnames:
        raise RuntimeError(f"找不到「{MOBILE_SHEET}」sheet — 可用: {wb.sheetnames[:5]}")

    ws = wb[MOBILE_SHEET]
    lines = [('' if ws[f'C{r}'].value is None else str(ws[f'C{r}'].value))
             for r in range(1, ws.max_row + 1)]
    while lines and lines[0] == '':
        lines.pop(0)
    while lines and lines[-1] == '':
        lines.pop()

    out, prev_blank = [], False
    for ln in lines:
        if ln == '':
            if not prev_blank:
                out.append('')
            prev_blank = True
        else:
            out.append(ln)
            prev_blank = False
    return '\n'.join(out)


# ════════════════════════════════════════════════════════════════════
#  潛在處置股清單
# ════════════════════════════════════════════════════════════════════

def build_disposal_message(trade_date: str) -> str:
    """潛在處置股完整清單 (D-1 + D-2)。

    資料源 attstock.tw/api/stocks/risk,由 refresh_attstock_disposal.py 抓下來。
    D-3 以後有 160+ 檔屬長尾,只報數量不列清單 (列了會超過 Telegram 4096 字上限)。

    注意: attstock 網頁上那種「收盤≤46.80元(漲跌0.5%才觸發)」的觸發價,
    API 沒有提供,得自行重算其公式 — 這裡不做,只呈現 API 給的事實欄位。
    """
    path = DATA_DIR / 'disposal_attstock.json'
    if not path.exists():
        return ''
    try:
        d = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return ''

    detail = d.get('detail') or []
    if not detail:
        return ''

    def fmt(x: dict) -> str:
        bits = [f"{x.get('name', '')} {x.get('code', '')}"]
        if x.get('type'):
            bits.append(x['type'])
        if x.get('consecutive_days'):
            bits.append(f"連{x['consecutive_days']}日")
        if x.get('count_in_30d'):
            bits.append(f"30日{x['count_in_30d']}次")
        price, chg = x.get('last_price'), x.get('change_pct')
        if price is not None and chg is not None:
            bits.append(f"{price} ({chg:+.1f}%)")
        return " · ".join(bits)

    # 市場劇烈時 D-1+D-2 可能暴增 (實測 38 檔約 1,860 字, 約可容納 79 檔)。
    # 超過就砍 D-2 尾端 (risk_score 低者排在後面) 並明講砍了幾檔 —
    # 寧可標示「未列 N 檔」,也不要靜默截斷讓人以為看到的是全部。
    BUDGET = 3900

    def render(limit_2d=None):
        out = [f"⚠️ 潛在處置股 · {trade_date}", ""]
        dropped = 0
        for bucket, title, icon in (('in_disposal', '處置中', '⛔'),
                                     ('1d', '最快下一交易日', '🔴'),
                                     ('2d', '最快 2 個交易日', '🟡')):
            rows = [x for x in detail if x.get('bucket') == bucket]
            if not rows:
                continue
            shown = rows
            if bucket == '2d' and limit_2d is not None and len(rows) > limit_2d:
                shown = rows[:limit_2d]
                dropped = len(rows) - limit_2d
            out.append(f"━━ {title} ({len(rows)} 檔) ━━")
            out += [f"{icon} {fmt(x)}" for x in shown]
            if dropped and bucket == '2d':
                out.append(f"…另 {dropped} 檔未列 (訊息長度上限)")
            out.append("")
        return out, dropped

    lines, _ = render()
    if len("\n".join(lines)) > BUDGET:
        n2d = len([x for x in detail if x.get('bucket') == '2d'])
        for limit in range(n2d - 1, -1, -1):
            lines, _ = render(limit_2d=limit)
            if len("\n".join(lines)) <= BUDGET:
                break

    far = d.get('count_pending_3d_plus') or 0
    if far:
        lines.append(f"3 個交易日以上還有 {far} 檔 (未列)")

    fetched = (d.get('fetched_at') or '')[11:16]
    lines.append(f"\n資料: attstock.tw{' · ' + fetched + ' 更新' if fetched else ''}")
    lines.append("僅供風險提示,非投資建議")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
#  處置股圖片渲染 (仿 attstock.tw 卡片風格)
# ════════════════════════════════════════════════════════════════════

_DISPOSAL_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0f172a;
  font-family: 'Microsoft JhengHei', 'Segoe UI', sans-serif;
  color: #f1f5f9;
  padding: 24px;
}
.hdr {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; background: #1e293b;
  border: 1px solid #334155; border-radius: 12px; margin-bottom: 16px;
}
.hdr-t { font-size: 20px; font-weight: 700; }
.hdr-d { font-size: 13px; color: #94a3b8; }
.sec { margin-bottom: 12px; }
.sh {
  padding: 8px 14px; border-radius: 8px; margin-bottom: 6px;
  font-size: 13px; font-weight: 600;
}
.sh-d { background: rgba(239,68,68,0.12); color: #ef4444; border-left: 3px solid #ef4444; }
.sh-1 { background: rgba(248,113,113,0.12); color: #f87171; border-left: 3px solid #f87171; }
.sh-2 { background: rgba(251,191,36,0.12); color: #fbbf24; border-left: 3px solid #fbbf24; }
.sr {
  background: #1e293b; border: 1px solid #334155; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 4px;
  display: flex; align-items: center; gap: 4px;
}
.sr .code { font-size: 15px; font-weight: 700; color: #f1f5f9; min-width: 48px; }
.sr .name {
  font-size: 13px; color: #94a3b8; min-width: 64px; max-width: 80px;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
.b-t { background: #312e81; color: #818cf8; }
.b-p { background: #4c1d95; color: #a78bfa; }
.tp {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: rgba(251,146,60,0.15); color: #fb923c; font-weight: 500;
}
.price {
  font-size: 15px; font-weight: 700; color: #f1f5f9;
  min-width: 72px; text-align: right; margin-left: auto;
}
.chg { font-size: 12px; font-weight: 500; min-width: 64px; text-align: right; }
.chg-u { color: #f87171; }
.chg-d { color: #34d399; }
.chg-f { color: #64748b; }
.stats {
  font-size: 11px; color: #64748b; min-width: 180px; text-align: right;
}
.stats em { color: #cbd5e1; font-style: normal; font-weight: 500; }
.far { text-align: center; padding: 8px; font-size: 12px; color: #64748b; }
.ft {
  margin-top: 12px; padding-top: 10px; border-top: 1px solid #334155;
  font-size: 11px; color: #475569; text-align: center;
}
"""


def _disposal_row_html(s: dict) -> str:
    code = s.get('code', '')
    name = s.get('name', '—')
    stype = s.get('type', '')
    market = s.get('market', '')
    price = s.get('last_price')
    chg = s.get('change_pct')
    consecutive = s.get('consecutive_days')
    count_30 = s.get('count_in_30d')
    day_trade = s.get('day_trade_ratio')

    b_cls = 'b-t' if market == 'TWSE' else 'b-p'
    b_txt = '上市' if market == 'TWSE' else '上櫃'

    if chg is not None and chg > 0:
        c_cls, c_str = 'chg-u', f'+{chg:.1f}%'
    elif chg is not None and chg < 0:
        c_cls, c_str = 'chg-d', f'{chg:.1f}%'
    else:
        c_cls, c_str = 'chg-f', ('0.0%' if chg == 0 else '—')

    sp = []
    if consecutive:
        sp.append(f'連<em>{consecutive}</em>日')
    if count_30:
        sp.append(f'30日<em>{count_30}</em>次')
    if day_trade is not None:
        sp.append(f'當沖<em>{day_trade:.0f}%</em>')
    stats = ' · '.join(sp)
    p_str = str(price) if price is not None else '—'

    return (
        f'<div class="sr">'
        f'<span class="code">{code}</span>'
        f'<span class="name">{name}</span>'
        f'<span class="badge {b_cls}">{b_txt}</span>'
        f'<span class="tp">{stype}</span>'
        f'<span class="price">{p_str}</span>'
        f'<span class="chg {c_cls}">{c_str}</span>'
        f'<span class="stats">{stats}</span>'
        f'</div>'
    )


def render_disposal_image(trade_date: str):
    """Render disposal stocks to a PNG image in attstock.tw card style.
    Returns the path to the generated PNG, or None on failure."""
    disp_path = DATA_DIR / 'disposal_attstock.json'
    if not disp_path.exists():
        return None
    try:
        d = json.loads(disp_path.read_text(encoding='utf-8'))
    except Exception:
        return None

    detail = d.get('detail') or []
    if not detail:
        return None

    _BUCKETS = [
        ('in_disposal', '⛔ 處置中', 'sh-d'),
        ('1d', '🔴 最快下一交易日', 'sh-1'),
        ('2d', '🟡 最快 2 個交易日', 'sh-2'),
    ]

    parts = []
    n_sections = 0
    for key, title, cls in _BUCKETS:
        stocks = [x for x in detail if x.get('bucket') == key]
        if not stocks:
            continue
        n_sections += 1
        parts.append(f'<div class="sec"><div class="sh {cls}">'
                     f'{title} ({len(stocks)} 檔)</div>')
        for s in stocks:
            parts.append(_disposal_row_html(s))
        parts.append('</div>')

    far = d.get('count_pending_3d_plus', 0)
    if far:
        parts.append(f'<div class="far">3 個交易日以上還有 {far} 檔</div>')

    fetched = (d.get('fetched_at') or '')[11:16]
    f_note = f' · {fetched} 更新' if fetched else ''
    parts.append(
        f'<div class="ft">資料: attstock.tw{f_note} · 僅供風險提示,非投資建議</div>'
    )

    html = (
        '<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8">'
        '<style>' + _DISPOSAL_CSS + '</style></head><body>'
        f'<div class="hdr"><span class="hdr-t">⚠️ 潛在處置股雷達</span>'
        f'<span class="hdr-d">{trade_date}</span></div>'
        + '\n'.join(parts)
        + '</body></html>'
    )

    height = 170 + n_sections * 46 + len(detail) * 48
    if far:
        height += 36

    try:
        from html2image import Html2Image
        hti = Html2Image(
            output_path=str(DATA_DIR),
            custom_flags=['--force-device-scale-factor=2'],
        )
        out_name = 'disposal_card.png'
        hti.screenshot(html_str=html, save_as=out_name, size=(800, height))
        out_path = DATA_DIR / out_name
        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"  [Telegram] 處置股圖片已渲染 "
                  f"({out_path.stat().st_size / 1024:.0f} KB, {len(detail)} 檔)")
            return str(out_path)
        print("  [Telegram] ⚠️ 圖片渲染結果異常")
        return None
    except Exception as e:
        print(f"  [Telegram] ⚠️ 圖片渲染失敗: {e}")
        return None


# ════════════════════════════════════════════════════════════════════
#  Telegram 送出 / 編輯
# ════════════════════════════════════════════════════════════════════

def push_text(api: str, chat_id: str, label: str, text: str,
              prev: dict, force_new: bool) -> dict:
    """送出或編輯一則文字訊息。回傳新的 {message_id, hash}。

    內容沒變 → 完全不打 API (Telegram 也會回 400 message is not modified)。
    有 message_id 且內容有變 → editMessageText。
    編輯失敗 (訊息被刪 / 過舊) → 退回重發,不讓使用者漏掉更新。
    """
    import requests
    h = _hash(text)
    mid = (prev or {}).get('message_id')

    if not force_new and mid and (prev or {}).get('hash') == h:
        print(f"  [Telegram] · {label}內容未變,不動")
        return {'message_id': mid, 'hash': h}

    if not force_new and mid:
        r = requests.post(f"{api}/editMessageText", data={
            'chat_id': chat_id, 'message_id': mid,
            'text': text[:4096], 'disable_web_page_preview': 'true',
        }, timeout=20)
        if r.status_code == 200:
            print(f"  [Telegram] ✎ {label}已更新 (msg {mid}, {len(text)} 字元)")
            return {'message_id': mid, 'hash': h}
        desc = ''
        try:
            desc = (r.json() or {}).get('description', '')
        except Exception:
            desc = r.text[:120]
        if 'not modified' in desc:
            print(f"  [Telegram] · {label}內容未變 (API 回報)")
            return {'message_id': mid, 'hash': h}
        print(f"  [Telegram] ⚠️ {label}編輯失敗 ({desc[:80]}),改為重發")

    r = requests.post(f"{api}/sendMessage", data={
        'chat_id': chat_id, 'text': text[:4096],
        'disable_web_page_preview': 'true',
    }, timeout=20)
    if r.status_code != 200:
        print(f"  [Telegram] ✗ {label}推送失敗 HTTP {r.status_code}: {r.text[:200]}")
        return {}
    new_mid = ((r.json() or {}).get('result') or {}).get('message_id')
    print(f"  [Telegram] ✓ {label}已推送 (msg {new_mid}, {len(text)} 字元)")
    return {'message_id': new_mid, 'hash': h}


def push_document(api: str, chat_id: str, caption: str,
                  prev: dict, force_new: bool, data_changed: bool) -> dict:
    """送出或替換 Excel 附件。

    Excel 每次 regen 內部時間戳都會變,檔案 hash 一定不同,拿來當判斷基準
    會導致每次都重傳 570KB。改以「摘要內容有沒有變」為準 — 摘要沒變表示
    當日數據沒有實質更新,附件也不需要換。
    """
    import requests
    if not XLSX.exists():
        print(f"  [Telegram] ⚠️ 找不到 {XLSX},略過附件")
        return prev or {}

    mid = (prev or {}).get('message_id')
    size_kb = XLSX.stat().st_size / 1024

    if not force_new and mid and not data_changed:
        print(f"  [Telegram] · Excel 資料未變,不動")
        return prev

    if not force_new and mid:
        media = json.dumps({'type': 'document', 'media': 'attach://f',
                            'caption': caption}, ensure_ascii=False)
        with open(XLSX, 'rb') as fh:
            r = requests.post(f"{api}/editMessageMedia",
                              data={'chat_id': chat_id, 'message_id': mid,
                                    'media': media},
                              files={'f': ('latest.xlsx', fh)}, timeout=180)
        if r.status_code == 200:
            print(f"  [Telegram] ✎ Excel 已更新 (msg {mid}, {size_kb:,.0f} KB)")
            return {'message_id': mid}
        desc = ''
        try:
            desc = (r.json() or {}).get('description', '')
        except Exception:
            desc = r.text[:120]
        print(f"  [Telegram] ⚠️ Excel 編輯失敗 ({desc[:80]}),改為重發")

    with open(XLSX, 'rb') as fh:
        r = requests.post(f"{api}/sendDocument",
                          data={'chat_id': chat_id, 'caption': caption},
                          files={'document': ('latest.xlsx', fh)}, timeout=180)
    if r.status_code != 200:
        print(f"  [Telegram] ⚠️ Excel 推送失敗 HTTP {r.status_code}: {r.text[:200]}")
        return prev or {}
    new_mid = ((r.json() or {}).get('result') or {}).get('message_id')
    print(f"  [Telegram] ✓ Excel 已推送 (msg {new_mid}, {size_kb:,.0f} KB)")
    return {'message_id': new_mid}


def push_photo(api: str, chat_id: str, label: str, photo_path: str,
               caption: str, prev: dict, force_new: bool,
               data_hash: str) -> dict:
    """送出或編輯一則圖片訊息。回傳 {message_id, hash}。"""
    import requests
    mid = (prev or {}).get('message_id')

    if not force_new and mid and (prev or {}).get('hash') == data_hash:
        print(f"  [Telegram] · {label}資料未變,不動")
        return {'message_id': mid, 'hash': data_hash}

    if not force_new and mid:
        media = json.dumps({'type': 'photo', 'media': 'attach://f',
                            'caption': caption}, ensure_ascii=False)
        with open(photo_path, 'rb') as fh:
            r = requests.post(f"{api}/editMessageMedia",
                              data={'chat_id': chat_id, 'message_id': mid,
                                    'media': media},
                              files={'f': ('disposal.png', fh)}, timeout=30)
        if r.status_code == 200:
            print(f"  [Telegram] ✎ {label}已更新 (msg {mid})")
            return {'message_id': mid, 'hash': data_hash}
        desc = ''
        try:
            desc = (r.json() or {}).get('description', '')
        except Exception:
            desc = r.text[:120]
        if 'not modified' in desc:
            print(f"  [Telegram] · {label}內容未變 (API 回報)")
            return {'message_id': mid, 'hash': data_hash}
        print(f"  [Telegram] ⚠️ {label}編輯失敗 ({desc[:80]}),改為重發")

    with open(photo_path, 'rb') as fh:
        r = requests.post(f"{api}/sendPhoto",
                          data={'chat_id': chat_id, 'caption': caption},
                          files={'photo': ('disposal.png', fh)}, timeout=30)
    if r.status_code != 200:
        print(f"  [Telegram] ✗ {label}推送失敗 HTTP {r.status_code}: {r.text[:200]}")
        return {}
    new_mid = ((r.json() or {}).get('result') or {}).get('message_id')
    print(f"  [Telegram] ✓ {label}已推送 (msg {new_mid})")
    return {'message_id': new_mid, 'hash': data_hash}


# ════════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    load_dotenv_into_env()
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

    if not DRY_RUN and (not token or not chat_id):
        print("  [Telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設,跳過推播")
        print("             (見 docs/TELEGRAM_BOT_SETUP.md)")
        return 0

    trade_date = read_trade_date()
    if not trade_date:
        print("  [Telegram] 拿不到 trade_date,跳過推播")
        return 0

    if not XLSX.exists():
        print(f"  [Telegram] 找不到 {XLSX},跳過推播")
        return 0

    try:
        summary = extract_mobile_summary()
    except Exception as e:
        print(f"  [Telegram] 萃取手機摘要失敗: {e}")
        return 0        # 不讓排程判定為失敗 — 資料本身已經抓好了

    d_fmt = (f"{trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:8]}"
             if len(trade_date) == 8 else trade_date)
    disposal = build_disposal_message(d_fmt)

    if DRY_RUN:
        print(f"  [DRY RUN] trade_date={trade_date}, 摘要 {len(summary)} 字元, "
              f"處置清單 {len(disposal)} 字元")
        print(f"  [DRY RUN] Excel: {XLSX} ({XLSX.stat().st_size / 1024:,.0f} KB)")
        print('─' * 55)
        print(summary)
        if disposal:
            print('─' * 55)
            print(disposal)
        print('─' * 55)
        return 0

    # ── 判斷是「新的一天」還是「同一天重跑」 ──
    st = load_state()
    same_day = (not FORCE) and st.get('trade_date') == trade_date
    if not same_day:
        st = {'trade_date': trade_date}      # 換日 (或 --force) → 全部當新的發
        reason = '強制重發' if FORCE else f'新交易日 {trade_date}'
        print(f"  [Telegram] {reason} → 發送新訊息")
    else:
        # 舊版 (v3.73.1-3) 狀態檔只有 trade_date、沒有 message_id,無從編輯。
        # 此時「重發」會洗版、「跳過」只是少一次更新 → 選跳過,較不擾人。
        # 隔天換日就會寫入新格式,之後都能正常編輯。
        if not any(isinstance(st.get(k), dict) and st[k].get('message_id')
                   for k in ('summary', 'disposal', 'document')):
            print(f"  [Telegram] {trade_date} 今日已推過,但狀態檔為舊格式"
                  f"(無 message_id 可編輯) → 本次跳過,明日起正常更新")
            return 0
        print(f"  [Telegram] {trade_date} 今日已推過 → 有異動則更新原訊息")

    api = f"https://api.telegram.org/bot{token}"
    force_new = not same_day

    summary_prev = st.get('summary') or {}
    summary_new = push_text(api, chat_id, '手機摘要', summary, summary_prev, force_new)
    if summary_new:
        st['summary'] = summary_new
    data_changed = force_new or summary_new.get('hash') != summary_prev.get('hash')

    disposal_img = render_disposal_image(d_fmt)
    if disposal_img:
        disp_hash = _hash(disposal) if disposal else ''
        res = push_photo(api, chat_id, '處置股圖片', disposal_img,
                         f"⚠️ 潛在處置股 · {d_fmt}",
                         st.get('disposal') or {}, force_new, disp_hash)
        if res:
            st['disposal'] = res
    elif disposal:
        res = push_text(api, chat_id, '處置股清單', disposal,
                        st.get('disposal') or {}, force_new)
        if res:
            st['disposal'] = res

    caption = f"📋 Chip Radar · {d_fmt} 完整報表"
    res_doc = push_document(api, chat_id, caption, st.get('document') or {},
                            force_new, data_changed)
    if res_doc:
        st['document'] = res_doc

    save_state(st)
    return 0


if __name__ == '__main__':
    sys.exit(main())
