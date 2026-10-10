# v3.85.7 dev soak - retired in v3.95.0 when dev was merged into main - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-10 "這四項，現在立即解決": dev (Fubon pacing v3.85.6, cp950 v3.85.8) is merged
into main before the soak week ended, so the nightly production run uses that code and the
08:30 TEST-run scheduler (dev-soak.yml) is removed, as its own header asked."""

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.85.7 dev soak 已收 (v3.95.0, 離線)")
print("=" * 72)
check("08:30 試跑排程已移除 (dev 已併入 main)", not (ROOT / '.github/workflows/dev-soak.yml').exists())
check("試跑驗的程式在 main 上: 富邦間隔 + cp950 解碼",
      (ROOT / 'src/core/fubon_pacing.py').exists() and (ROOT / 'src/core/fubon_codec.py').exists())
wf = (ROOT / '.github/workflows/daily-full.yml').read_text(encoding='utf-8')
check("dev 推送不再自動觸發 TEST run", 'branches: [dev]' not in wf)
print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
