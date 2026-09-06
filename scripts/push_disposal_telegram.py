"""v3.75.0: 取 disposal-watch 雲端 artifact 的處置股圖卡,推到 Telegram。

為什麼改成「下載雲端產物」而不是「本機重跑」(v3.74.x 的做法):
  v3.74.x 用 git archive origin/main 把 disposal-watch 解到工作副本,在本機
  跑一次 fetch_disposal.py。2026-08-24 attstock 開始擋非瀏覽器 UA,本機 IP
  隨後被封 (首頁 200、API 全 403,換成完整 Chrome UA 也無效),那條路整個斷掉
  —— 8/26~8/29 連四天沒推出任何圖卡,而舊版任何失敗都 exit 0,靜默無感。

  改抓 artifact 的三個理由:
    1. 資料 / 程式碼 / 產物三者都來自雲端那唯一一次執行,不是「應該會一樣」
    2. 本機完全不再呼叫 attstock —— 這是讓 IP 封鎖有機會過期的前提
    3. artifact 是穩定介面。disposal-watch 仍在高速改版 (8/11→8/28 共 80 個
       commit,圖卡從 1 張變成 4 張),借跑等於每天執行別人改到一半的程式碼

為什麼不乾脆在 disposal-watch 那邊直接推:
  那是另一個人的 repo。而且 GitHub Actions 的 schedule 只在預設分支觸發,
  workflow 放在非預設分支不會被 cron 叫起來 —— 等於一定要動他的 main。不碰。

時序:
  雲端 21:17 (台北) 開跑,約 1-3 分鐘產完圖並上傳 artifact (實測 21:20-21:25)。
  本機 21:17 那班的 crawler.py 要跑約 19 分鐘,本腳本實際在 21:37 左右才執行,
  屆時 artifact 早已就緒。22:37 / 23:47 兩班是兜底。

用法:
    python scripts/push_disposal_telegram.py              # 正常
    python scripts/push_disposal_telegram.py --force      # 忽略去重重抓,仍原地更新
    python scripts/push_disposal_telegram.py --dry-run    # 只下載不推
    python scripts/push_disposal_telegram.py --keep       # 保留工作副本供除錯
    python scripts/push_disposal_telegram.py --list-chats # 列出 chat_id (設群組用)

一天三班 (21:17 / 22:37 / 23:47) 一律照跑,行為由 artifact_id 決定:
    artifact 沒變 -> 什麼都不做      artifact 變了 -> 原地更新既有訊息
這跟 send_daily_telegram.py 的「沒有就送、有就更新」一致。

認證 (二擇一,優先用 gh):
    gh CLI       使用者已 gh auth login (PATH 或 C:/Program Files/GitHub CLI)
    GITHUB_PAT   .env 裡的 fine-grained PAT,需 disposal-watch 的 Actions: Read-only

環境變數:
    TELEGRAM_BOT_TOKEN          同 send_daily_telegram.py,讀 .env
    TELEGRAM_CHAT_ID            收件對象,逗號分隔可多個 (私訊 + 群組都推)
    TELEGRAM_DISPOSAL_CHAT_ID   只有「處置股圖卡要推去別的地方」時才設;
                                未設 = 跟著 TELEGRAM_CHAT_ID 推同一批
    DISPOSAL_WATCH_REPO         預設 DRwillychiu/disposal-watch

任何一步失敗都印訊息後 exit 0 —— 這是附加通道,不該讓排程判定為失敗。
但連續失敗會推一則純文字告警: v3.74.x 就是缺這個才會靜默漏推四天。
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
# --force: 忽略 artifact 去重,重抓最新的。但仍走原地更新 (editMessageMedia),
#   不會再貼一組新的洗版 —— 手動重送的情境幾乎都是「剛才那份有問題,換掉它」。
#   訊息被刪導致更新失敗時,push() 會自動退回發新訊息。
FORCE = '--force' in sys.argv
DRY_RUN = '--dry-run' in sys.argv
KEEP = '--keep' in sys.argv
# --fallback: v3.75.0 起為 no-op,保留只為了不讓舊排程設定壞掉。
#   舊語意是「今天推過就整個跳過」,那是因為當時要在本機重跑上游管線
#   (1-2 分鐘 + 十幾個 attstock 呼叫),成功過就不值得再算一次。
#   改抓 artifact 後成本只剩一次清單查詢,跳過反而讓雲端 22:17 備援跑出的
#   更新版本永遠推不出去。現在三班一律照跑,由 artifact_id 決定要不要動。
LIST_CHATS = '--list-chats' in sys.argv


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


# 必須在算 DATA_DIR 之前載入: scheduler.ps1 會先設好 CHIP_RADAR_DATA_DIR
# (=local_data),手動執行則只有 .env 有。晚一步載入會讓兩種跑法讀到不同的
# 狀態檔,去重與 fail_streak 就各算各的。
load_dotenv_into_env()

DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
STATE = DATA_DIR / '.tg_disposal_push'      # 自己的狀態檔,不跟手機摘要那支共用
WORK = DATA_DIR / '.disposal_watch_run'     # 解壓目的地 (已 gitignore)
ZIP_PATH = DATA_DIR / '.disposal_watch.zip'

DEFAULT_REPO = 'DRwillychiu/disposal-watch'
ARTIFACT_NAME = 'disposal-report'

# 順序 = 上游 stamp_index 烙在圖上的「第 N 張 ‧ 共 N 張」順序,不可調換。
# 上游第 3、4 張 (自結預告 / 明日法說會) 產生失敗時不影響本業,故允許缺。
CARD_NAMES = ['當日重點.png', '處置中清單.png', '自結預告.png', '明日法說會.png']
TXT_NAME = '當日重點.txt'

# 硬失敗 (抓不到 / 推不出去) 連續幾次才告警。一天三班 -> 6 次約等於連兩天。
FAIL_ALERT_AT = 6
# 雲端幾天沒有新報表才告警。不能用次數: 一天三班,連假四天就累積十幾次而誤報。
# 5 天可容忍最長的國定連假 (週末+兩天),真的斷線才會叫。
STALE_ALERT_DAYS = 5

# gh 裝在 Program Files 時不一定進 PATH (尤其排程器繼承的是舊環境)
GH_CANDIDATES = [
    'C:/Program Files/GitHub CLI/gh.exe',
    'C:/Program Files (x86)/GitHub CLI/gh.exe',
]


# ════════════════════════════════════════════════════════════════════
#  狀態檔
# ════════════════════════════════════════════════════════════════════

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_state(patch: dict) -> None:
    """合併寫入 —— fail_streak / last_success_date 要跨次累積,不能整份覆蓋。"""
    st = load_state()
    st.update(patch)
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f"  [處置] ⚠️ 狀態檔寫入失敗 (下次可能重發): {e}")


def record_failure(reason: str) -> None:
    """記一次失敗並在達門檻時告警。呼叫端記完就 return,不要再往下走。"""
    streak = int(load_state().get('fail_streak') or 0) + 1
    save_state({'fail_streak': streak, 'last_fail': reason[:200],
                'last_fail_at': datetime.datetime.now().isoformat(timespec='seconds')})
    print(f"  [處置] ✗ {reason} (連續失敗 {streak} 次)")
    maybe_alert(streak, reason)


def maybe_alert(streak: int, reason: str) -> None:
    """連續失敗達門檻就推純文字告警,同一天最多一則。

    2026-08-26~29 連四天沒推出圖卡卻無人察覺 —— 舊版任何失敗都靜默 exit 0。
    附加通道不該讓排程轉紅,但壞掉必須有人知道。同日去重是為了避免三班各推一則。
    """
    if streak < FAIL_ALERT_AT or DRY_RUN:
        return
    today = datetime.date.today().isoformat()
    st = load_state()
    if st.get('last_alert_date') == today:
        return
    last_ok = st.get('last_success_date') or '(無紀錄)'
    text = ("⚠️ 處置股圖卡推播異常\n"
            f"連續 {streak} 次取不到圖卡,最後一次成功: {last_ok}\n"
            f"原因: {reason[:300]}")
    if _send_text(text):
        save_state({'last_alert_date': today})


# ════════════════════════════════════════════════════════════════════
#  GitHub artifact
# ════════════════════════════════════════════════════════════════════

def _gh_exe():
    p = shutil.which('gh')
    if p:
        return p
    return next((c for c in GH_CANDIDATES if Path(c).exists()), None)


def _api_bytes(path: str):
    """GET GitHub API,回傳原始 bytes (zip 也走這裡,故不用 text 模式)。

    優先 gh CLI: 使用者 gh auth login 後 token 由 gh 保管,不必在 .env 放憑證。
    沒有 gh 才退回 .env 的 GITHUB_PAT。
    """
    gh = _gh_exe()
    if gh:
        try:
            p = subprocess.run([gh, 'api', path], capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("  [處置] gh api 逾時")
            return None
        if p.returncode == 0:
            return p.stdout
        err = (p.stderr or b'').decode('utf-8', 'replace').strip()
        print(f"  [處置] gh api 失敗: {err[:200]}")
        return None

    pat = os.environ.get('GITHUB_PAT', '').strip()
    if not pat:
        print("  [處置] 沒有 gh CLI 也沒有 GITHUB_PAT,無法下載雲端 artifact")
        print("         擇一: (1) winget install --id GitHub.cli 後 gh auth login")
        print("               (2) .env 加 GITHUB_PAT=<PAT, disposal-watch Actions: Read-only>")
        return None
    import requests
    r = requests.get(f"https://api.github.com/{path.lstrip('/')}",
                     headers={'Authorization': f'Bearer {pat}',
                              'Accept': 'application/vnd.github+json'},
                     timeout=180)
    if r.status_code != 200:
        print(f"  [處置] GitHub API HTTP {r.status_code}: {r.text[:200]}")
        return None
    return r.content


def find_artifact(repo: str):
    """挑最新一份未過期的 disposal-report。

    刻意用 artifacts 清單而不是「最後一次成功的 run」: 上游有 schedule /
    repository_dispatch / workflow_dispatch 三種觸發,誰產出的不重要,
    要的是最新那份產物。
    """
    raw = _api_bytes(f'repos/{repo}/actions/artifacts?per_page=30')
    if not raw:
        return None
    try:
        arts = (json.loads(raw) or {}).get('artifacts') or []
    except Exception as e:
        print(f"  [處置] artifact 清單解析失敗: {e}")
        return None
    cand = [a for a in arts if a.get('name') == ARTIFACT_NAME and not a.get('expired')]
    if not cand:
        print(f"  [處置] {repo} 沒有可用的 {ARTIFACT_NAME} (保留期 14 天)")
        return None
    cand.sort(key=lambda a: a.get('created_at') or '', reverse=True)
    a = cand[0]
    print(f"  [處置] artifact #{a['id']} 產於 {a.get('created_at')} "
          f"({(a.get('size_in_bytes') or 0) / 1024:.0f} KB)")
    return a


def download_artifact(repo: str, art: dict) -> bool:
    """下載並解壓到 WORK。artifact zip 有設 UTF-8 旗標,中文檔名可直接解。"""
    raw = _api_bytes(f"repos/{repo}/actions/artifacts/{art['id']}/zip")
    if not raw:
        return False
    try:
        ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
        ZIP_PATH.write_bytes(raw)
        if WORK.exists():
            shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ZIP_PATH) as z:
            z.extractall(WORK)
    except Exception as e:
        print(f"  [處置] 解壓失敗: {e.__class__.__name__}: {e}")
        return False
    finally:
        ZIP_PATH.unlink(missing_ok=True)
    return True


def collect_cards():
    """依 CARD_NAMES 的順序收圖。缺的跳過 (上游第 3、4 張允許產生失敗)。"""
    cards = []
    for n in CARD_NAMES:
        p = WORK / n
        if p.exists() and p.stat().st_size > 1000:
            cards.append(p)
    return cards


def _report_date() -> str:
    """從 當日重點.txt 首行取報表日 — 格式: 當日潛在處置股重點 ｜ YYYY-MM-DD 盤後"""
    try:
        first = (WORK / TXT_NAME).read_text(encoding='utf-8-sig').splitlines()[0]
        for tok in first.replace('｜', ' ').split():
            if len(tok) == 10 and tok[4] == '-' and tok[7] == '-':
                return tok
    except Exception:
        pass
    return ''


def check_staleness() -> None:
    """雲端太久沒有新報表就告警。「沒有新的」本身不是失敗 —— 21:37 那班常
    比雲端快、週末與國定假日更是本來就不會有新報表,計成失敗會天天誤報。

    所以改看「距離上次成功推送過了幾天」: 長週末最多四天不會誤觸,
    2026-08-26~29 那種真的斷掉四天以上才會叫。
    """
    st = load_state()
    last = st.get('last_success_date')
    if not last:
        return          # 還沒成功過就沒有基準,交給硬失敗那條路
    try:
        gap = (datetime.date.today() - datetime.date.fromisoformat(last)).days
    except Exception:
        return
    today = datetime.date.today().isoformat()
    if gap < STALE_ALERT_DAYS or st.get('last_alert_date') == today:
        return
    if _send_text(f"⚠️ 處置股圖卡已 {gap} 天沒有更新\n"
                  f"最後一次成功推送: {last}\n"
                  f"雲端 disposal-watch 可能沒跑或跑失敗,請查 GitHub Actions。"):
        save_state({'last_alert_date': today})


# ════════════════════════════════════════════════════════════════════
#  Telegram
# ════════════════════════════════════════════════════════════════════

def _chat_ids() -> list:
    """處置股圖卡的收件對象,逗號分隔可指定多個 (私訊 + 群組)。

    未設 TELEGRAM_DISPOSAL_CHAT_ID 就跟著手機摘要走同一批 —— 多數情況
    「處置股推去哪」跟「摘要推去哪」是同一個答案,分開設容易漏掉其中一邊。
    群組是負數 id (超級群組 -100 開頭)。
    """
    raw = (os.environ.get('TELEGRAM_DISPOSAL_CHAT_ID', '').strip()
           or os.environ.get('TELEGRAM_CHAT_ID', '').strip())
    return [c.strip() for c in raw.split(',') if c.strip()]


def _api_base() -> str:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    return f"https://api.telegram.org/bot{token}" if token else ''


def _send_text(text: str) -> bool:
    """告警用的純文字,推給所有收件對象。任一成功即算數。

    失敗只印訊息,不要讓告警本身再拋例外 —— 告警壞掉不該蓋掉原本的錯誤。
    """
    api, ids = _api_base(), _chat_ids()
    if not api or not ids:
        print("  [處置] 告警無法送出: TELEGRAM_BOT_TOKEN / chat_id 未設")
        return False
    ok = False
    import requests
    for cid in ids:
        try:
            r = requests.post(f"{api}/sendMessage",
                              data={'chat_id': cid, 'text': text[:4096],
                                    'disable_web_page_preview': 'true'}, timeout=30)
            if r.status_code == 200:
                ok = True
                continue
            print(f"  [處置] 告警推送失敗 {cid} HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"  [處置] 告警推送失敗 {cid}: {e.__class__.__name__}: {e}")
    if ok:
        print("  [處置] ⚠️ 已推送異常告警")
    return ok


def _edit_group(api, chat_id, mids, cards, caption) -> bool:
    """同一報表日重跑 -> 逐則 editMessageMedia 原地更新,不重發洗版。

    caption 只掛在第一則 (跟 sendMediaGroup 的行為一致)。
    任何一則硬失敗就回 False,由呼叫端整組重發 —— 只更新一半會比較難看懂。
    """
    import requests
    for i, (mid, p) in enumerate(zip(mids, cards)):
        media = {'type': 'photo', 'media': 'attach://f'}
        if i == 0:
            media['caption'] = caption
        with open(p, 'rb') as fh:
            r = requests.post(f"{api}/editMessageMedia",
                              data={'chat_id': chat_id, 'message_id': mid,
                                    'media': json.dumps(media, ensure_ascii=False)},
                              files={'f': (p.name, fh)}, timeout=120)
        if r.status_code == 200:
            continue
        desc = ''
        try:
            desc = (r.json() or {}).get('description', '')
        except Exception:
            desc = r.text[:120]
        if 'not modified' in desc:
            continue        # 內容一模一樣,視為成功
        print(f"  [處置] ⚠️ 第 {i + 1} 張編輯失敗 ({desc[:80]})")
        return False
    print(f"  [處置] ✎ 已原地更新 {len(cards)} 張 (msg {mids[0]}...)")
    return True


def _send_group(api, chat_id, cards, caption):
    """送出圖組,回傳 message_id 陣列。單張時 sendMediaGroup 不受理,改 sendPhoto。"""
    import requests
    if len(cards) == 1:
        with open(cards[0], 'rb') as fh:
            r = requests.post(f"{api}/sendPhoto",
                              data={'chat_id': chat_id, 'caption': caption},
                              files={'photo': (cards[0].name, fh)}, timeout=120)
        if r.status_code != 200:
            print(f"  [處置] ✗ 推送失敗 HTTP {r.status_code}: {r.text[:200]}")
            return []
        mid = ((r.json() or {}).get('result') or {}).get('message_id')
        return [mid] if mid else []

    media, files, handles = [], {}, []
    try:
        for i, p in enumerate(cards):
            key = f'f{i}'
            item = {'type': 'photo', 'media': f'attach://{key}'}
            if i == 0:
                item['caption'] = caption
            media.append(item)
            fh = open(p, 'rb')
            handles.append(fh)
            files[key] = (p.name, fh)
        r = requests.post(f"{api}/sendMediaGroup",
                          data={'chat_id': chat_id,
                                'media': json.dumps(media, ensure_ascii=False)},
                          files=files, timeout=180)
    finally:
        for fh in handles:
            fh.close()
    if r.status_code != 200:
        print(f"  [處置] ✗ 推送失敗 HTTP {r.status_code}: {r.text[:200]}")
        return []
    return [m.get('message_id') for m in ((r.json() or {}).get('result') or [])]


def push(cards, report_date: str, artifact_id) -> bool:
    """推給每個收件對象。任一成功即算這次成功。

    message_id 是「該 chat 專屬」的,所以 targets 要按 chat_id 分開存;
    拿 A chat 的 id 去 B chat 編輯會直接失敗。
    """
    api, ids = _api_base(), _chat_ids()
    if not api or not ids:
        print("  [處置] TELEGRAM_BOT_TOKEN / chat_id 未設,跳過推播")
        return False

    caption = (f"⚠️ 當日潛在處置股 · {report_date}" if report_date
               else "⚠️ 當日潛在處置股")
    st = load_state()
    targets = st.get('targets') if isinstance(st.get('targets'), dict) else {}
    if not targets and st.get('message_ids'):
        # v3.75.0 之前是單目標,message_ids 放在頂層。歸給第一個對象,
        # 否則升級後它會被當成全新目標而重發一次。
        targets = {ids[0]: {'message_ids': st['message_ids']}}
    # 刻意不看 FORCE: --force 的意思是「忽略去重、重抓」,不是「重貼一份」。
    # 只要報表日沒變就走原地更新,編輯失敗才退回重發 (見下方)。
    same_day = bool(report_date) and st.get('report_date') == report_date

    ok_any = False
    for cid in ids:
        mids = (targets.get(cid) or {}).get('message_ids') or []
        # 張數變了 (上游某張產生失敗) 就不能對號入座編輯,整組重發
        if same_day and mids and len(mids) == len(cards):
            if _edit_group(api, cid, mids, cards, caption):
                targets[cid] = {'message_ids': mids}
                ok_any = True
                continue
            print(f"  [處置] {cid}: 改為重發")
        new_mids = _send_group(api, cid, cards, caption)
        if not new_mids:
            print(f"  [處置] ✗ {cid} 推送失敗")
            continue
        print(f"  [處置] ✓ {cid} 已推送 {len(new_mids)} 張 (msg {new_mids[0]}...)")
        targets[cid] = {'message_ids': new_mids}
        ok_any = True

    if ok_any:
        _mark_success(report_date, targets, artifact_id)
    return ok_any


def _mark_success(report_date: str, targets: dict, artifact_id) -> None:
    """report_date = 報表資料日; pushed_on = 實際推送的當地日期。

    兩者刻意分開: 跨午夜補跑時報表日仍是前一交易日,--fallback 要問的是
    「今天這台機器推過沒」,拿 report_date 判斷會在午夜後誤判成沒推過。
    artifact_id 則是「有沒有新東西」的判準,見 main()。
    """
    today = datetime.date.today().isoformat()
    save_state({'report_date': report_date, 'targets': targets,
                'artifact_id': artifact_id,
                'pushed_on': today, 'last_success_date': today,
                'fail_streak': 0})


def list_chats() -> int:
    """列出 bot 看得到的 chat,給設定收件對象用。

    優先讀 telegram_poll.py 維護的名冊: 輪詢器必須把 update「拿走並標記已讀」
    (否則每 2 分鐘會重跑同一條指令),之後直接呼叫 getUpdates 就看不到東西了。
    名冊反而比 getUpdates 好用 —— getUpdates 只保留約 24 小時,名冊是永久的。

    名冊還不存在 (輪詢器沒跑過) 才退回 getUpdates,讓首次設定仍然可用。
    """
    roster_file = DATA_DIR / '.tg_chats.json'
    seen, src = {}, ''
    try:
        data = json.loads(roster_file.read_text(encoding='utf-8'))
        if isinstance(data, dict) and data:
            seen, src = data, f'名冊 {roster_file.name}'
    except Exception:
        pass

    if not seen:
        api = _api_base()
        if not api:
            print("TELEGRAM_BOT_TOKEN 未設")
            return 1
        import requests
        r = requests.get(f"{api}/getUpdates", params={'limit': 100}, timeout=30)
        if r.status_code != 200:
            print(f"getUpdates HTTP {r.status_code}: {r.text[:200]}")
            return 1
        for u in (r.json() or {}).get('result') or []:
            for key in ('message', 'channel_post', 'edited_message',
                        'my_chat_member', 'chat_member'):
                c = (u.get(key) or {}).get('chat')
                if c and str(c.get('id')) not in seen:
                    seen[str(c['id'])] = {
                        'type': c.get('type', ''),
                        'name': (c.get('title')
                                 or ' '.join(filter(None, [c.get('first_name'),
                                                           c.get('last_name')]))
                                 or c.get('username') or '')}
        src = 'getUpdates (名冊尚未建立)'

    if not seen:
        print("沒有任何紀錄。請先把 bot 加進群組,並在群裡發一則訊息後重跑。")
        print("(輪詢器未啟用時,Telegram 只保留約 24 小時的 update)")
        return 0

    print(f"來源: {src}\n")
    print(f"{'chat_id':>16}  {'type':<10} 名稱")
    for cid, c in sorted(seen.items(), key=lambda kv: kv[0]):
        print(f"{cid:>16}  {(c.get('type') or ''):<10} {c.get('name') or ''}")
    print("\n把要用的 id 寫進 .env 的 TELEGRAM_CHAT_ID (逗號分隔可多個)。")
    print("群組是負數 (超級群組 -100 開頭)。bot 需為群組成員才推得進去。")
    return 0


# ════════════════════════════════════════════════════════════════════

def main() -> int:
    if LIST_CHATS:
        return list_chats()

    repo = os.environ.get('DISPOSAL_WATCH_REPO', '').strip() or DEFAULT_REPO
    try:
        art = find_artifact(repo)
        if not art:
            record_failure(f'取不到 {repo} 的 {ARTIFACT_NAME} artifact')
            return 0

        # 「有沒有新東西」看 artifact id,不看日期。21:37 那班常比雲端快,
        # 週末與國定假日更是本來就不會有新報表 —— 這些都不是失敗,不可計入
        # fail_streak (否則連假必誤報)。真的太久沒新的由 check_staleness 負責。
        st = load_state()
        if not FORCE and st.get('targets') and st.get('artifact_id') == art['id']:
            print(f"  [處置] artifact #{art['id']} 已推送過,無新內容")
            check_staleness()
            return 0

        if not download_artifact(repo, art):
            record_failure('artifact 下載或解壓失敗')
            return 0

        cards = collect_cards()
        if not cards:
            record_failure(f'artifact 裡沒有任何圖卡 (預期 {CARD_NAMES[0]} 等)')
            return 0
        rd = _report_date()
        print(f"  [處置] 報表日 {rd or '(未知)'},取得 {len(cards)} 張: "
              + " / ".join(p.name for p in cards))

        if DRY_RUN:
            for p in cards:
                print(f"  [DRY RUN] {p.name}  {p.stat().st_size / 1024:.0f} KB")
            return 0

        if not push(cards, rd, art['id']):
            record_failure('Telegram 推送失敗')
    except Exception as e:
        record_failure(f'未預期錯誤 {e.__class__.__name__}: {e}')
    finally:
        if KEEP:
            print(f"  [處置] 工作副本保留於 {WORK}")
        else:
            shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
