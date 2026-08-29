"""v3.74.1: 借 disposal-watch 產「當日潛在處置股」圖卡,推到 Telegram。

為什麼是「借跑」而不是自己畫:
  disposal-watch (github.com/DRwillychiu/disposal-watch) 已有完整管線 —
  attstock 撈取 → 反解明日觸發價 / MoneyDJ 概念標籤 / 快照差集算進出關 /
  命中率回測 → Pillow 產圖 → 寄 Email。本專案曾自行渲染一份,結果同一天
  出現兩張內容對不上的處置股圖 (v3.74.0 已移除)。唯一資料源只能有一個。

為什麼在副本跑而不是原地跑:
  fetch_disposal.py 會寫 snapshots/ / transitions.csv / 每日紀錄.csv /
  biz_cache.json / exemption_track.json —— 這些都是 disposal-watch 的
  版控檔,雲端 GHA 每晚也會寫同一批並 commit。本機原地跑會讓那個 clone
  一直處於 dirty 狀態,之後 git pull 必衝突。故改為:
      git fetch (只更新 refs) → git archive origin/main → 解壓到工作副本
  → 在副本裡跑。disposal-watch 的工作目錄自始至終不被碰。

代價 (誠實揭露):
  這等於把雲端 21:17 已經算過的東西在本機再算一次 (約 1-2 分鐘 +
  十來個 attstock API 呼叫)。同一支程式、同一個資料源、收盤後資料已靜止,
  所以產出的圖與 email 附的那張實務上一致 —— 但「一致」是推論不是保證,
  真要位元級相同得改抓雲端 artifact (需 gh CLI 或 PAT,目前未裝)。

用法:
    python scripts/push_disposal_telegram.py             # 正常
    python scripts/push_disposal_telegram.py --force     # 忽略當日去重,重發
    python scripts/push_disposal_telegram.py --dry-run   # 只產圖不推
    python scripts/push_disposal_telegram.py --keep      # 保留工作副本供除錯
    python scripts/push_disposal_telegram.py --fallback  # 兜底班次: 當日推過就跳過

環境變數:
    DISPOSAL_WATCH_DIR   disposal-watch 路徑 (預設 ~/Desktop/projects/disposal-watch)
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   同 send_daily_telegram.py,讀 .env

任何一步失敗都印訊息後 exit 0 —— 這是附加通道,不該讓排程判定為失敗。
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
FORCE = '--force' in sys.argv
DRY_RUN = '--dry-run' in sys.argv
KEEP = '--keep' in sys.argv
# 兜底班次 (22:37 / 23:47): 當日已成功推過就整個跳過,不重算。
# 收盤後處置資料已靜止,重算只會得到同一張圖 (editMessageMedia 回 not modified),
# 卻要付 1-2 分鐘 + 十來個 API 呼叫 x2。只在 21:17 那班失敗時才需要它們接手。
FALLBACK = '--fallback' in sys.argv

DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
STATE = DATA_DIR / '.tg_disposal_push'      # 自己的狀態檔,不跟手機摘要那支共用
WORK = DATA_DIR / '.disposal_watch_run'     # 工作副本 (local_data 已 gitignore)

DEFAULT_REPO = Path.home() / 'Desktop' / 'projects' / 'disposal-watch'
PNG_NAME = '當日重點.png'
TXT_NAME = '當日重點.txt'


def load_dotenv_into_env() -> None:
    """把 .env 補進 os.environ (不覆蓋既有的) — 對齊 send_daily_telegram.py。"""
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


def _run(args, cwd=None, timeout=900):
    """跑外部指令,回傳 (returncode, 合併輸出)。"""
    p = subprocess.run(args, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def find_repo() -> Path | None:
    d = Path(os.environ.get('DISPOSAL_WATCH_DIR') or DEFAULT_REPO)
    if (d / 'fetch_disposal.py').exists():
        return d
    print(f"  [處置] 找不到 disposal-watch ({d})")
    print(f"         設環境變數 DISPOSAL_WATCH_DIR 指到正確路徑")
    return None


def export_snapshot(repo: Path) -> bool:
    """git fetch + git archive origin/main → 解壓到 WORK。

    刻意不用 pull/checkout/worktree: 那些都會動到 repo 的工作目錄或
    .git/worktrees。fetch 只寫 refs 與 objects,archive 只讀 —— 對那個
    clone 而言等同唯讀。fetch 失敗 (離線/SSH 問題) 就退回用現有 HEAD,
    圖可能舊一天但總比沒有好。
    """
    rc, out = _run(['git', '-C', str(repo), 'fetch', 'origin', '--quiet'], timeout=180)
    ref = 'origin/main'
    if rc != 0:
        print(f"  [處置] git fetch 失敗,改用本機 HEAD: {out.strip()[:120]}")
        ref = 'HEAD'

    rc, out = _run(['git', '-C', str(repo), 'log', '-1', '--format=%h %ci %s', ref])
    print(f"  [處置] 來源 {ref}: {out.strip()[:90]}")

    zip_path = DATA_DIR / '.disposal_watch.zip'
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    rc, out = _run(['git', '-C', str(repo), 'archive', '--format=zip',
                    '-o', str(zip_path.resolve()), ref], timeout=300)
    if rc != 0:
        print(f"  [處置] git archive 失敗: {out.strip()[:200]}")
        return False

    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(WORK)
    finally:
        zip_path.unlink(missing_ok=True)
    return (WORK / 'fetch_disposal.py').exists()


def run_pipeline() -> Path | None:
    """在副本裡跑 fetch_disposal.py --no-email,回傳 PNG 路徑。

    --no-email 是關鍵: 雲端 21:17 已經寄過信,本機再寄會收到兩封。

    刻意不傳 --force-run: 那會繞過上游的非交易日防護。國定假日照跑會拿到
    前一交易日的舊資料再產一次圖,等於假日也推一則重複的。假日就該安靜跳過。
    """
    env = dict(os.environ)
    env.pop('GMAIL_SENDER', None)          # 雙保險: 沒憑證就算旗標失效也寄不出去
    env.pop('GMAIL_APP_PASSWORD', None)
    env.pop('TELEGRAM_BOT_TOKEN', None)    # 推播由本腳本負責,不讓子行程搶著推
    env.pop('TELEGRAM_CHAT_ID', None)

    print("  [處置] 執行 fetch_disposal.py (約 1-2 分鐘) ...")
    p = subprocess.run([sys.executable, 'fetch_disposal.py', '--no-email'],
                       cwd=str(WORK), capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=1800, env=env)
    lines = ((p.stdout or '') + (p.stderr or '')).strip().splitlines()
    hol = next((ln for ln in lines if '非交易日' in ln), '')
    if hol:
        print(f"  [處置] {hol.strip()[:90]}")
        return None
    for ln in lines[-6:]:
        print(f"         | {ln}")
    if p.returncode != 0:
        print(f"  [處置] 執行失敗 (exit {p.returncode})")
        return None
    png = WORK / PNG_NAME
    if not (png.exists() and png.stat().st_size > 1000):
        print(f"  [處置] 沒產出 {PNG_NAME}")
        return None
    print(f"  [處置] 圖卡已產出 ({png.stat().st_size / 1024:.0f} KB)")
    return png


def _report_date() -> str:
    """從副本的 當日重點.txt 首行取報表日期 (fetch_disposal 會對齊資料日)。"""
    try:
        first = (WORK / TXT_NAME).read_text(encoding='utf-8-sig').splitlines()[0]
        for tok in first.replace('｜', ' ').split():
            if len(tok) == 10 and tok[4] == '-' and tok[7] == '-':
                return tok
    except Exception:
        pass
    return ''


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_state(report_date: str, message_id) -> None:
    """report_date = 報表資料日; pushed_on = 實際推送的當地日期。

    兩者刻意分開: 跨午夜補跑時報表日仍是前一交易日,--fallback 要看的是
    「今天這台機器推過沒」,拿 report_date 判斷會在午夜後誤判成沒推過。
    """
    try:
        STATE.write_text(json.dumps(
            {'report_date': report_date, 'message_id': message_id,
             'pushed_on': datetime.date.today().isoformat()},
            ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f"  [處置] ⚠️ 狀態檔寫入失敗 (下次可能重發): {e}")


def push(png: Path, report_date: str) -> bool:
    """sendPhoto,同一報表日重跑走 editMessageMedia 更新原訊息。

    對齊 send_daily_telegram.py 的行為: 21:17 / 22:37 / 23:47 三班都會跑到
    這裡,重發會洗版、純跳過又拿不到更新後的數字 → 原地編輯。
    """
    import requests
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        print("  [處置] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設,跳過推播")
        return False

    api = f"https://api.telegram.org/bot{token}"
    caption = f"⚠️ 當日潛在處置股 · {report_date}" if report_date else "⚠️ 當日潛在處置股"
    st = load_state()
    same_day = (not FORCE) and report_date and st.get('report_date') == report_date
    mid = st.get('message_id') if same_day else None

    if mid:
        media = json.dumps({'type': 'photo', 'media': 'attach://f',
                            'caption': caption}, ensure_ascii=False)
        with open(png, 'rb') as fh:
            r = requests.post(f"{api}/editMessageMedia",
                              data={'chat_id': chat_id, 'message_id': mid,
                                    'media': media},
                              files={'f': (PNG_NAME, fh)}, timeout=60)
        if r.status_code == 200:
            print(f"  [處置] ✎ 已更新原訊息 (msg {mid})")
            save_state(report_date, mid)
            return True
        desc = ''
        try:
            desc = (r.json() or {}).get('description', '')
        except Exception:
            desc = r.text[:120]
        if 'not modified' in desc:
            print(f"  [處置] · 內容未變 (msg {mid})")
            save_state(report_date, mid)
            return True
        print(f"  [處置] ⚠️ 編輯失敗 ({desc[:80]}),改為重發")

    with open(png, 'rb') as fh:
        r = requests.post(f"{api}/sendPhoto",
                          data={'chat_id': chat_id, 'caption': caption},
                          files={'photo': (PNG_NAME, fh)}, timeout=60)
    if r.status_code != 200:
        print(f"  [處置] ✗ 推送失敗 HTTP {r.status_code}: {r.text[:200]}")
        return False
    new_mid = ((r.json() or {}).get('result') or {}).get('message_id')
    print(f"  [處置] ✓ 已推送 (msg {new_mid})")
    save_state(report_date, new_mid)
    return True


def main() -> int:
    load_dotenv_into_env()
    if FALLBACK and not FORCE:
        st = load_state()
        if st.get('message_id') and st.get('pushed_on') == datetime.date.today().isoformat():
            print(f"  [處置] 今日已推送過 (報表日 {st.get('report_date') or '?'}),"
                  f"兜底班次略過重算")
            return 0
    repo = find_repo()
    if not repo:
        return 0
    try:
        if not export_snapshot(repo):
            print("  [處置] 匯出工作副本失敗")
            return 0
        png = run_pipeline()
        if not png:
            return 0
        rd = _report_date()
        if DRY_RUN:
            print(f"  [DRY RUN] 報表日 {rd or '(未知)'},圖: {png}")
            return 0
        push(png, rd)
    except subprocess.TimeoutExpired:
        print("  [處置] 逾時,略過本次推播")
    except Exception as e:
        print(f"  [處置] 未預期錯誤: {e.__class__.__name__}: {e}")
    finally:
        if KEEP:
            print(f"  [處置] 工作副本保留於 {WORK}")
        else:
            shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
