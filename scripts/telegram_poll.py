"""v3.75.0: 輪詢 Telegram 指令 — 讓手機可以手動觸發「重抓 + 更新」。

為什麼需要:
  處置股圖卡來自 disposal-watch,那是別人的 repo。他修好問題重跑之後會產生
  新的 artifact,但本機下一班排程可能還要等好幾小時。這支讓你在手機打一行
  指令就重抓並更新既有訊息。

為什麼是輪詢,不是常駐 daemon 或 webhook:
  webhook 需要公開網址,家用電腦沒有。常駐 daemon 是多一個要監控、會默默
  掛掉、要自動重啟的東西。改由 scheduler.ps1 每分鐘起一個、聽 55 秒就結束
  —— 效果等同常駐,但掛掉 60 秒內自己就回來,不必另外監控。

指令為什麼是即時的:
  用長輪詢 (getUpdates 帶 timeout),連線掛著不放,訊息一到 Telegram 就立刻
  回傳。不是「每分鐘問一次」而是「幾乎一直在聽」,這是 Telegram 官方推薦
  bot 用的方式。收到訊息後**繼續聽完剩餘時間**而不是直接結束,否則連下兩個
  指令時第二個要等到下一分鐘才有人聽。

★ 為什麼拆成「輪詢」與「工人」兩段 (這是安全關鍵):
  ChipRadar_Scheduler 這個 Windows 排程工作的 MultipleInstances 政策是
  IgnoreNew —— 前一次還在跑時,下一分鐘的觸發會被直接丟掉。實測 8/24~8/28
  的 21:30 settlement 從來沒執行過,就是被 21:17 daily-full (約 19 分鐘)
  整段吃掉的。

  所以輪詢器**絕對不能被同步等待**: 它自己要掛 55 秒聽訊息,/refresh 的
  重抓又要 60-90 秒。壓到 21:17 那一分鐘,當天的 daily-full 就整個不會跑
  (固定時刻只比對那一分鐘)。

  兩層都拆開:
    scheduler.ps1 用 detached 起輪詢器 -> 排程器佔用 8-83 毫秒
    輪詢器用分離行程起工人 (--run)    -> 輪詢器不被重抓拖住,繼續聽指令
  分離時 stdin/stdout/stderr 一律導向 DEVNULL —— 否則 cmd /c 會等管道關閉,
  等於白拆。

權限 (重要):
  只接受管理者 chat 的指令。群組與其他人的訊息一律忽略,而且**不回應** ——
  連「你沒有權限」都不回,免得讓群組裡的人發現這個 bot 吃指令。
  管理者 = TELEGRAM_ADMIN_CHAT_ID,未設則取 TELEGRAM_CHAT_ID 的第一個正數
  id (負數是群組,絕不會被當成管理者)。

為什麼要記 offset:
  Telegram 幫每個 bot 保管一個「未讀信箱」。輪詢器必須把訊息**拿走並標記
  已讀**,否則會重新看到同一條 /refresh 而重複執行。

副作用與補償:
  訊息被拿走之後,push_disposal_telegram.py --list-chats 原本用的 getUpdates
  就看不到東西了。所以這支每看到一則訊息就把來源 chat 記進 .tg_chats.json
  名冊,--list-chats 改讀名冊 —— 反而比原本好: getUpdates 只保留約 24 小時,
  名冊是永久的。

兩個鎖:
  .tg_poll.lock  輪詢用,短。Telegram 對同一個 bot 同時 getUpdates 會回 409
  .tg_work.lock  工人用,長。擋掉同時跑兩個 /refresh 對同一批訊息亂編輯
  都用 O_EXCL 原子建立 (先檢查再建立會有兩個行程同時通過檢查的空隙)。

選單 (不用記指令):
  輸入框左邊的藍色「選單」按鈕 (setMyCommands),點開列出全部操作。
  scope 綁定管理者私訊 —— 用預設 scope 的話,群組成員點開 bot 也會看到
  有哪些指令可用,等於公告這裡吃指令。
  刻意不用 reply keyboard (鍵盤上方的常駐按鈕): 那排會長期佔掉手機下半個
  畫面,而藍色選單已經達到「不用記指令」的目的。
  選單不見了 (換裝置、清聊天記錄) 打 /menu 重裝。

用法:
    python scripts/telegram_poll.py              # 排程每分鐘呼叫,聽 55 秒
    python scripts/telegram_poll.py --setup-menu # 安裝選單 (一次就好)
    python scripts/telegram_poll.py --status     # 只印狀態,不消費 update
    python scripts/telegram_poll.py --run refresh   # 工人 (由輪詢器自動啟動)

任何失敗都印訊息後 exit 0 —— 這是附加通道,不該讓排程判定為失敗。
"""
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
STATUS_ONLY = '--status' in sys.argv
SETUP_MENU = '--setup-menu' in sys.argv
RUN_CMD = ''
if '--run' in sys.argv:
    _i = sys.argv.index('--run')
    RUN_CMD = sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ''


def load_dotenv_into_env() -> None:
    """把 .env 補進 os.environ (不覆蓋既有的) — 對齊 scheduler.ps1:14-26。"""
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


# 必須在算 DATA_DIR 之前載入 (同 push_disposal_telegram.py 的理由)
load_dotenv_into_env()

DATA_DIR = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
OFFSET = DATA_DIR / '.tg_poll_offset'       # 已讀到哪一則 update
ROSTER = DATA_DIR / '.tg_chats.json'        # chat 名冊,供 --list-chats
POLL_LOCK = DATA_DIR / '.tg_poll.lock'
WORK_LOCK = DATA_DIR / '.tg_work.lock'
WORKER_LOG = DATA_DIR / '.tg_worker.log'

# 長輪詢: getUpdates 掛著不放,訊息一到就立刻回傳 (Telegram 官方推薦的用法)。
#   早期版本用短輪詢 (timeout=0) 每 2 分鐘問一次,因為當時輪詢是同步跑在
#   排程器裡,掛 50 秒會佔住它。改成分離行程後這個限制就不存在了。
# POLL_BUDGET_SEC: 這個行程總共聽多久。排程每分鐘叫一次,聽 55 秒 -> 分鐘
#   之間只剩幾秒空窗。收到訊息後**繼續聽完剩餘時間**而不是直接結束,
#   否則連下兩個指令時,第二個要等到下一分鐘才有人聽。
POLL_BUDGET_SEC = 55
LONG_POLL_SEC = 25          # 單次 getUpdates 掛多久 (要小於 budget 才能循環)
POLL_STALE_SEC = 120        # > POLL_BUDGET_SEC,健康的輪詢器不會被誤判成殘骸
# 工人最久 = 2 個子行程 x RUN_TIMEOUT。留足餘裕,免得還活著就被判定成殘骸
# 而讓第二個工人同時開跑 (兩個一起編輯同一批訊息會很難看)。
RUN_TIMEOUT = 600
WORK_STALE_SEC = 1500

HELP = ("點輸入框左邊的藍色「選單」按鈕就會列出全部操作,不用記:\n\n"
        "/refresh — 重抓 disposal-watch 最新 artifact,更新所有訊息\n"
        "/status  — 報表日、最後成功時間、連續失敗次數\n"
        "/help    — 這則訊息")

# Telegram 藍色「選單」按鈕的內容 (setMyCommands)。
# scope 綁定管理者的私訊 —— 用預設 scope 的話,群組成員點開 bot 也會看到
# 有哪些指令可用,等於公告這裡吃指令。
MY_COMMANDS = [
    {'command': 'refresh', 'description': '重抓最新 artifact 並更新所有訊息'},
    {'command': 'status', 'description': '顯示目前狀態'},
    {'command': 'help', 'description': '說明'},
]

# 刻意不用 reply keyboard (鍵盤上方的常駐按鈕): 它會長期佔掉手機下半個畫面。
# 藍色選單按鈕已經達到「不用記指令」的目的,而且不佔版面。
REMOVE_KEYBOARD = {'remove_keyboard': True}


def _api() -> str:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    return f"https://api.telegram.org/bot{token}" if token else ''


def admin_chat_id() -> str:
    """能下指令的 chat。群組 (負數 id) 永遠不會被選中。"""
    explicit = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '').strip()
    if explicit:
        return explicit
    for c in os.environ.get('TELEGRAM_CHAT_ID', '').split(','):
        c = c.strip()
        if c and not c.startswith('-'):
            return c
    return ''


def _send(chat_id: str, text: str, markup: dict = None) -> None:
    try:
        import requests
        data = {'chat_id': chat_id, 'text': text[:4096],
                'disable_web_page_preview': 'true'}
        if markup:
            data['reply_markup'] = json.dumps(markup, ensure_ascii=False)
        requests.post(f"{_api()}/sendMessage", data=data, timeout=15)
    except Exception as e:
        _wlog(f"回覆失敗: {e.__class__.__name__}: {e}")


def setup_menu(admin: str) -> bool:
    """裝上 Telegram 輸入框旁的藍色「選單」按鈕 (setMyCommands)。

    順便送 remove_keyboard: 早期版本裝過鍵盤上方的常駐按鈕,那排會長期
    佔掉手機下半個畫面。這則訊息會把它收掉。

    scope 綁定管理者私訊: 用預設 scope 的話,群組成員點開 bot 也會看到
    有哪些指令可用,等於公告這裡吃指令。
    """
    import requests
    ok = True
    try:
        r = requests.post(f"{_api()}/setMyCommands", data={
            'commands': json.dumps(MY_COMMANDS, ensure_ascii=False),
            'scope': json.dumps({'type': 'chat', 'chat_id': int(admin)})},
            timeout=15)
        if r.status_code != 200:
            _wlog(f"setMyCommands 失敗 HTTP {r.status_code}: {r.text[:200]}")
            ok = False
    except Exception as e:
        _wlog(f"setMyCommands 失敗: {e.__class__.__name__}: {e}")
        ok = False
    _send(admin, "✅ 選單已裝好\n\n" + HELP, REMOVE_KEYBOARD)
    return ok


def _wlog(msg: str) -> None:
    """工人是分離行程,輸出被丟到 DEVNULL —— 這裡留一行紀錄供事後查。"""
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WORKER_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#  鎖 / offset / 名冊
# ════════════════════════════════════════════════════════════════════

def acquire(lock: Path, stale_sec: int, label: str) -> bool:
    """O_EXCL 原子建立。先 exists() 再 write 會有兩個行程同時通過檢查的空隙。"""
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            if age < stale_sec:
                print(f"  [指令] {label}仍在執行中 ({age:.0f}s),本次略過")
                return False
            _wlog(f"{label}鎖檔殘留 {age:.0f}s,視為殘骸並接手")
            lock.unlink(missing_ok=True)
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(f"{os.getpid()} {datetime.datetime.now().isoformat()}")
        return True
    except FileExistsError:
        # 剛好被另一個行程搶先 —— 這正是 O_EXCL 要擋的情況
        print(f"  [指令] {label}已被其他行程取得,本次略過")
        return False
    except Exception as e:
        _wlog(f"{label}取鎖失敗: {e}")
        return False


def release(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except Exception:
        pass


def touch(lock: Path) -> None:
    """工作跑到一半時更新鎖檔時間,免得長工作被誤判成殘骸。"""
    try:
        lock.touch()
    except Exception:
        pass


def load_offset() -> int:
    try:
        return int(OFFSET.read_text(encoding='utf-8').strip())
    except Exception:
        return 0


def save_offset(v: int) -> None:
    try:
        OFFSET.parent.mkdir(parents=True, exist_ok=True)
        OFFSET.write_text(str(v), encoding='utf-8')
    except Exception as e:
        # 存不了 offset = 下次會重看到同一批訊息並重複執行指令,必須講出來
        _wlog(f"⚠️ offset 寫入失敗,下次可能重複執行: {e}")


def remember_chat(chat: dict) -> None:
    """把看過的 chat 記進名冊 (--list-chats 讀它)。"""
    if not chat or not chat.get('id'):
        return
    try:
        roster = json.loads(ROSTER.read_text(encoding='utf-8'))
        if not isinstance(roster, dict):
            roster = {}
    except Exception:
        roster = {}
    name = (chat.get('title')
            or ' '.join(filter(None, [chat.get('first_name'), chat.get('last_name')]))
            or chat.get('username') or '')
    roster[str(chat['id'])] = {
        'type': chat.get('type', ''), 'name': name,
        'last_seen': datetime.datetime.now().isoformat(timespec='seconds')}
    try:
        ROSTER.parent.mkdir(parents=True, exist_ok=True)
        ROSTER.write_text(json.dumps(roster, ensure_ascii=False, indent=1),
                          encoding='utf-8')
    except Exception as e:
        print(f"  [指令] 名冊寫入失敗: {e}")


# ════════════════════════════════════════════════════════════════════
#  工人 (分離行程,--run)
# ════════════════════════════════════════════════════════════════════

def _run(args) -> tuple:
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        p = subprocess.run([sys.executable, *args], cwd=str(ROOT),
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=RUN_TIMEOUT, env=env)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except subprocess.TimeoutExpired:
        return 1, f'逾時 ({RUN_TIMEOUT}s)'
    except Exception as e:
        return 1, f'{e.__class__.__name__}: {e}'


def work_refresh(chat_id: str) -> None:
    """重抓 + 更新全部內容。

    兩支都帶 --force: 略過去重直接重抓,但它們的 --force 是「原地更新」而非
    「重貼一份」,所以不會多出一組重複訊息 (見各自的旗標說明)。
    """
    _send(chat_id, "⏳ 重抓中 — 下載 disposal-watch 最新 artifact 並更新所有訊息…")
    lines = []
    for label, args in (
            ('處置股圖卡', ['scripts/push_disposal_telegram.py', '--force']),
            ('手機摘要 + Excel', ['scripts/send_daily_telegram.py', '--force'])):
        rc, out = _run(args)
        touch(WORK_LOCK)        # 長工作要保鮮,否則第二段跑到一半鎖被判定成殘骸
        tail = [ln.strip() for ln in out.strip().splitlines() if ln.strip()][-5:]
        _wlog(f"{label} rc={rc} | " + " | ".join(tail))
        lines.append(f"{'✅' if rc == 0 else '❌'} {label}")
        lines.extend('   ' + ln for ln in tail)
        lines.append('')
    _send(chat_id, '\n'.join(lines).strip()[:4096])


def work_status(chat_id: str) -> None:
    def _read(name):
        try:
            return json.loads((DATA_DIR / name).read_text(encoding='utf-8'))
        except Exception:
            return {}
    d, s = _read('.tg_disposal_push'), _read('.tg_last_push')
    lines = ["📊 目前狀態", "",
             f"處置股圖卡  報表日 {d.get('report_date') or '—'}",
             f"            artifact #{d.get('artifact_id') or '—'}",
             f"            最後成功 {d.get('last_success_date') or '—'}",
             f"            連續失敗 {d.get('fail_streak') or 0} 次",
             f"            目標 {len(d.get('targets') or {})} 個", "",
             f"手機摘要    交易日 {s.get('trade_date') or '—'}",
             f"            目標 {len(s.get('targets') or {})} 個"]
    if d.get('last_fail'):
        lines += ["", f"最後錯誤: {str(d['last_fail'])[:200]}"]
    _send(chat_id, '\n'.join(lines)[:4096])


def work_help(chat_id: str) -> None:
    _send(chat_id, HELP)


def work_menu(chat_id: str) -> None:
    setup_menu(chat_id)


# /start 是 Telegram 建 bot 時的預設指令,信箱裡常躺著一則。導向 menu ——
# 第一次跟 bot 說話就直接把選單裝上,比回一句「不認得 /start」有用。
# /menu 不列進 MY_COMMANDS: 選單裝好之後就用不到了,列出來只是雜訊。
WORKERS = {'refresh': work_refresh, 'status': work_status,
           'help': work_help, 'menu': work_menu}
ALIASES = {'/refresh': 'refresh', '/update': 'refresh', '/status': 'status',
           '/help': 'help', '/start': 'menu', '/menu': 'menu'}


def run_worker(name: str) -> int:
    admin = admin_chat_id()
    fn = WORKERS.get(name)
    if not fn or not admin:
        _wlog(f"工人啟動失敗: 指令={name!r} admin={admin!r}")
        return 0
    # status / help 是純讀取,不必排隊 —— 只有會動到訊息的 refresh 要鎖
    if name != 'refresh':
        fn(admin)
        return 0
    if not acquire(WORK_LOCK, WORK_STALE_SEC, '前一個指令'):
        _send(admin, "⏳ 上一個 /refresh 還在跑,這次先跳過。稍等一下再試。")
        return 0
    try:
        _wlog(f"工人開始: {name}")
        fn(admin)
        _wlog(f"工人結束: {name}")
    except Exception as e:
        _wlog(f"工人異常: {e.__class__.__name__}: {e}")
        _send(admin, f"❌ 執行 /{name} 時發生未預期錯誤: {e.__class__.__name__}: {e}")
    finally:
        release(WORK_LOCK)
    return 0


def spawn_worker(name: str) -> None:
    """把工作丟給分離行程,輪詢器立刻回去,不佔住排程器。

    stdin/stdout/stderr 必須導向 DEVNULL: 只設 DETACHED_PROCESS 而讓子行程
    繼承管道的話,呼叫端的 cmd /c 仍會等到管道關閉才返回 —— 等於沒拆。
    """
    flags = 0
    if os.name == 'nt':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([sys.executable, str(SELF), '--run', name],
                         cwd=str(ROOT), creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        _wlog(f"已丟出工人: {name}")
    except Exception as e:
        _wlog(f"工人啟動失敗 ({name}): {e.__class__.__name__}: {e}")


# ════════════════════════════════════════════════════════════════════

def main() -> int:
    api, admin = _api(), admin_chat_id()
    if not api:
        print("  [指令] TELEGRAM_BOT_TOKEN 未設,跳過")
        return 0
    if not admin:
        print("  [指令] 找不到管理者 chat (TELEGRAM_ADMIN_CHAT_ID 或 "
              "TELEGRAM_CHAT_ID 的第一個正數 id),跳過")
        return 0

    if RUN_CMD:
        return run_worker(RUN_CMD)

    if SETUP_MENU:
        ok = setup_menu(admin)
        print(f"  選單已送到 {admin}"
              f"{'' if ok else ' (Menu 按鈕設定失敗,見 .tg_worker.log)'}")
        return 0

    if STATUS_ONLY:
        print(f"  管理者 chat : {admin}")
        print(f"  已讀 offset : {load_offset()}")
        print(f"  名冊        : {ROSTER} ({'存在' if ROSTER.exists() else '尚未建立'})")
        print(f"  輪詢鎖      : {'佔用中' if POLL_LOCK.exists() else '空閒'}")
        print(f"  工作鎖      : {'佔用中' if WORK_LOCK.exists() else '空閒'}")
        return 0

    if not acquire(POLL_LOCK, POLL_STALE_SEC, '前一次輪詢'):
        return 0
    try:
        import requests
        deadline = time.time() + POLL_BUDGET_SEC
        while True:
            remaining = deadline - time.time()
            if remaining < 3:       # 剩不到 3 秒不值得再掛一次,交給下一分鐘
                break
            offset = load_offset()
            params = {'timeout': int(min(LONG_POLL_SEC, remaining - 2)),
                      'limit': 50}
            if offset:
                params['offset'] = offset
            # 長輪詢: 連線掛著,訊息一到就回傳。requests 的 timeout 必須比
            # Telegram 的 timeout 大,否則正常的等待會被誤判成連線逾時。
            try:
                r = requests.get(f"{api}/getUpdates", params=params,
                                 timeout=params['timeout'] + 10)
            except requests.Timeout:
                continue            # 網路慢,不是錯誤,再掛一次
            if r.status_code != 200:
                _wlog(f"getUpdates HTTP {r.status_code}: {r.text[:200]}")
                break
            touch(POLL_LOCK)        # 長時間持有,讓鎖保持新鮮
            updates = (r.json() or {}).get('result') or []
            if not updates:
                continue            # 這輪沒訊息,把剩下的時間繼續聽

            jobs, last_id = [], offset
            for u in updates:
                last_id = max(last_id, int(u.get('update_id') or 0))
                msg = u.get('message') or u.get('edited_message') or {}
                chat = msg.get('chat') or {}
                remember_chat(chat)
                if str(chat.get('id')) != admin:
                    # 群組 / 其他人 —— 忽略且不回應。回應等於告訴對方這裡吃指令。
                    continue
                text = (msg.get('text') or '').strip()
                # 只理會斜線指令。否則跟 bot 隨口聊一句都會收到「不認得」。
                if not text.startswith('/'):
                    continue
                cmd = text.split()[0].split('@')[0].lower()      # /refresh@Bot → /refresh
                jobs.append((cmd, ALIASES.get(cmd)))

            # 先存 offset 再丟工作: 指令跑到一半當掉時,重開機不該再跑一次。
            # 寧可漏一次 (你再打一次就好) 也不要重複推播。
            save_offset(last_id + 1)

            # 同一批裡連打好幾次同一個指令只做一次
            for cmd, name in dict.fromkeys(jobs):
                _wlog(f"收到指令 {cmd}")
                if name:
                    spawn_worker(name)
                else:
                    _send(admin, f"不認得 {cmd}\n\n{HELP}")
            # 刻意不 break: 處理完繼續聽完剩餘時間。直接結束的話,連下兩個
            # 指令時第二個要等到下一分鐘才有人聽 —— 那正是要修掉的延遲。
    except Exception as e:
        _wlog(f"輪詢未預期錯誤: {e.__class__.__name__}: {e}")
    finally:
        release(POLL_LOCK)
    return 0


if __name__ == '__main__':
    sys.exit(main())
