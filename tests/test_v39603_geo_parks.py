# v3.96.6 geography: real districts ending in 「園區」 are not science / industrial parks - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""2026-10-13 bug found from the owner's 台光電 地緣 question: 桃園區 / 大園區 / 林園區 were read as parks, their district was
dropped and a road guess put 統一-桃園, 群益金鼎-桃園, 凱基-桃園 (all 桃園區成功路1段32號) in 觀音區."""
from scripts import build_branch_geo as G

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.96.6 地址解析: 桃園區 / 大園區 / 林園區 (離線)")
print("=" * 72)
cases = [("桃園市桃園區成功路1段32號10樓", ("桃園市", "桃園區")), ("桃園縣桃園市成功路2段1號2樓", ("桃園市", "桃園區")),
         ("桃園市大園區大園路1號", ("桃園市", "大園區")), ("高雄市林園區林園北路1號", ("高雄市", "林園區")),
         ("臺中市大雅區科雅路1號(中部科學園區)", ("臺中市", "大雅區"))]
for a, want in cases:
    got = G.parse(a)[:2]
    check(f"{a} -> {want[1]}", got == want, f"got {got}")
check("district table loaded (the guard needs it)", ("桃園市", "桃園區") in G.REAL_DISTRICTS, f"{len(G.REAL_DISTRICTS)} districts")
print("\n" + "─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
