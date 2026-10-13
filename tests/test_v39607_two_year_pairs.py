# v3.96.7 the 12 insider branches found in both years: tracked nightly, shown in the encrypted alerts - offline
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-13: 「要，同時記錄到網頁正式版中」 - the pairs found by year 1 and year 2 on their own
(scripts/find_insider_branches.py) go to the nightly crawl and to the S08 分點警示 block with the matched person."""
from scripts import run_insider_radar as RR
from src.core import branches as B

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.96.7 兩年都找到的內部人分點 (離線)")
print("=" * 72)
pairs = RR.TWO_YEAR_PAIRS
tracked = {b["code"] for b in B.WATCHED_BRANCHES if b.get("enabled")}
NO_BRANCH_PAGE = {"9B17"}     # 2026-10-13: Fubon has no branch page for 台新-營業部 (no data date) - alert only
check("a branch without a Fubon branch page is not crawled", not (NO_BRANCH_PAGE & tracked))
# the pairs are research conclusions: data/research/alert_pairs.json (not in git). Without it (CI) only the public checks run
if (ROOT / "data" / "research" / "alert_pairs.json").exists():
    check("12 pairs, each with a person", len(pairs) == 12 and all(p[4] for p in pairs), f"{len(pairs)}")
    miss = [p[1] for p in pairs if p[1] not in tracked and p[1] not in NO_BRANCH_PAGE]
    check("every pair's branch is crawled nightly (except the ones without a branch page)", not miss, f"missing {miss}")
    public = "".join((ROOT / f).read_text(encoding="utf-8") for f in ("scripts/run_insider_radar.py", "src/core/branches.py", "index.html"))
    leak = [p[4] for p in pairs if p[4].split("（")[0] in public] + [p[0] for p in pairs if f'"{p[0]}", "{p[1]}"' in public]
    check("no pair (stock + branch) or person in the public code", not leak, f"{leak[:3]}")
else:
    print("  ⏭  data/research/alert_pairs.json not here (CI): pair checks skipped")
upper = {}
for b in B.WATCHED_BRANCHES:
    upper.setdefault(b["code"].upper(), set()).add(b["code"])
new = {"5380", "9813", "8840", "989m", "918P", "9800", "9229"}
clash = {c: upper[c.upper()] for c in new if len(upper[c.upper()]) > 1}
check("no letter-case twin among the 8 new branches", not clash, f"{clash}")
pub = json.loads((ROOT / "data" / "insider_radar.json").read_text(encoding="utf-8"))
check("public radar file has no alerts / branch fields", "alerts" not in pub and "兩年都找到" not in json.dumps(pub, ensure_ascii=False))
html = (ROOT / "index.html").read_text(encoding="utf-8")
check("page shows the tier and the person", "x.tier === '兩年都找到'" in html and "escHtml(x.person)" in html)
check("alerts read only from the decrypted part", "(INSIDER_PRIV || {}).alerts" in html)
print("\n" + "─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
