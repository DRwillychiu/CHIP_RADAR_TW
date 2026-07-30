"""v3.73.1: 本機排程跑完後,把「📱 手機摘要」+ latest.xlsx 推到 Telegram。

跟雲端 daily-full.yml 的「Send daily summary to Telegram」step 等價,
推的是同一份內容 (latest.xlsx 的手機摘要 sheet)。

差別在去重機制:
  雲端  用 git 的 data_changed (資料沒變 → 不寄)
  本機  不 commit,改用 marker 檔記錄「上次推的是哪個 trade_date」。
        scheduler.ps1 的 daily-full 有 21:17 / 22:37 / 23:47 三層,
        21:17 推完寫 marker,後兩次看到同一個 trade_date 就跳過。

用法:
    python scripts/send_daily_telegram.py            # 正常 (含去重)
    python scripts/send_daily_telegram.py --force    # 忽略去重,強制推
    python scripts/send_daily_telegram.py --dry-run  # 只印不推

token 來源 (優先序): 環境變數 → 專案根目錄 .env
兩者皆無 → 印訊息後 exit 0 (不讓排程判定為失敗)
"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORCE = '--force' in sys.argv
DRY_RUN = '--dry-run' in sys.argv

# data_dir 跟 crawler 一致 — 本機是 local_data,雲端是 data
DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
XLSX = DATA_DIR / 'reports' / 'latest.xlsx'
LATEST = DATA_DIR / 'latest.json'
MARKER = DATA_DIR / '.tg_last_push'          # 內容 = 上次推播的 trade_date

MOBILE_SHEET = '📱 手機摘要'


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


def read_trade_date() -> str:
    """從 latest.json 的明文外層讀 trade_date (不需密碼)."""
    try:
        return str(json.loads(LATEST.read_text(encoding='utf-8')).get('trade_date', ''))
    except Exception as e:
        print(f"  ⚠️ 讀不到 {LATEST}: {e}")
        return ''


def extract_mobile_summary() -> str:
    """抓 latest.xlsx 的手機摘要 sheet → 純文字。

    邏輯與 scripts/extract_mobile_summary_text.py 相同 (C 欄, 壓縮連續空行)。
    """
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


def build_disposal_message(trade_date: str) -> str:
    """v3.73.3: 潛在處置股完整清單 (D-1 + D-2)。

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
        price = x.get('last_price')
        chg = x.get('change_pct')
        if price is not None and chg is not None:
            bits.append(f"{price} ({chg:+.1f}%)")
        return "· ".join([bits[0] + " "] + [b + " " for b in bits[1:]]).rstrip()

    # 市場劇烈時 D-1+D-2 可能暴增 (實測 38 檔約 1,860 字, 約可容納 79 檔)。
    # 超過就砍 D-2 尾端 (risk_score 已由低到高排在後面) 並明講砍了幾檔 —
    # 寧可標示「未列 N 檔」,也不要靜默截斷讓人以為看到的是全部。
    BUDGET = 3900          # 留 ~200 字給結尾區塊

    def render(limit_2d=None) -> tuple:
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

    # ── 去重: 這個 trade_date 已經推過就不再推 ──
    if not FORCE and MARKER.exists():
        try:
            last = MARKER.read_text(encoding='utf-8').strip()
        except Exception:
            last = ''
        if last == trade_date:
            print(f"  [Telegram] {trade_date} 已推播過,跳過 (兜底排程重跑)")
            return 0

    if not XLSX.exists():
        print(f"  [Telegram] 找不到 {XLSX},跳過推播")
        return 0

    try:
        summary = extract_mobile_summary()
    except Exception as e:
        print(f"  [Telegram] 萃取手機摘要失敗: {e}")
        return 0        # 不讓排程判定為失敗 — 資料本身已經抓好了

    d_fmt = f"{trade_date[:4]}/{trade_date[4:6]}/{trade_date[6:8]}" \
        if len(trade_date) == 8 else trade_date
    disposal = build_disposal_message(d_fmt)

    if DRY_RUN:
        print(f"  [DRY RUN] trade_date={trade_date}, 摘要 {len(summary)} 字元, "
              f"處置清單 {len(disposal)} 字元")
        print(f"  [DRY RUN] Excel: {XLSX} "
              f"({XLSX.stat().st_size / 1024:,.0f} KB)")
        print('─' * 55)
        print(summary)
        if disposal:
            print('─' * 55)
            print(disposal)
        print('─' * 55)
        return 0

    import requests
    api = f"https://api.telegram.org/bot{token}"

    # ── 1) 手機摘要純文字 (不設 parse_mode — 摘要含「國巨*」等星號) ──
    r = requests.post(f"{api}/sendMessage", data={
        'chat_id': chat_id,
        'text': summary[:4096],
        'disable_web_page_preview': 'true',
    }, timeout=20)
    if r.status_code != 200:
        print(f"  [Telegram] ✗ 摘要推播失敗 HTTP {r.status_code}: {r.text[:200]}")
        return 0
    print(f"  [Telegram] ✓ 手機摘要已推送 ({trade_date}, {len(summary)} 字元)")

    # ── 2) 潛在處置股完整清單 (v3.73.3, 獨立一則) ──
    #    另外發而不併進手機摘要, 是為了讓摘要維持跟 email 逐字相同。
    if disposal:
        try:
            r_d = requests.post(f"{api}/sendMessage", data={
                'chat_id': chat_id,
                'text': disposal[:4096],
                'disable_web_page_preview': 'true',
            }, timeout=20)
            if r_d.status_code == 200:
                print(f"  [Telegram] ✓ 處置股清單已推送 ({len(disposal)} 字元)")
            else:
                print(f"  [Telegram] ⚠️ 處置股清單失敗 HTTP {r_d.status_code}: "
                      f"{r_d.text[:200]}")
        except Exception as e:
            print(f"  [Telegram] ⚠️ 處置股清單例外: {e}")

    # ── 3) Excel 附件 ──
    try:
        d = d_fmt
        with open(XLSX, 'rb') as fh:
            r2 = requests.post(f"{api}/sendDocument",
                               data={'chat_id': chat_id,
                                     'caption': f"📋 Chip Radar · {d} 完整報表"},
                               files={'document': ('latest.xlsx', fh)},
                               timeout=120)
        if r2.status_code == 200:
            print(f"  [Telegram] ✓ Excel 已推送 ({XLSX.stat().st_size / 1024:,.0f} KB)")
        else:
            print(f"  [Telegram] ⚠️ Excel 推播失敗 HTTP {r2.status_code}: {r2.text[:200]}")
    except Exception as e:
        print(f"  [Telegram] ⚠️ Excel 推播例外: {e}")

    # ── 3) 寫 marker (文字推成功就寫, 讓兜底不再重推) ──
    try:
        MARKER.write_text(trade_date, encoding='utf-8')
    except Exception as e:
        print(f"  [Telegram] ⚠️ marker 寫入失敗 (兜底可能重推): {e}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
