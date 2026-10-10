# v3.95.0 one rule for "foreign": us / eu / asia - offline
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-09: foreign brokers are listed on their own; 9200 / 9600 stay domestic.
Before v3.95.0 three places said "not domestic = foreign" and counted 官股, the 10 local
hot-spot branches and the two company totals as foreign (get_foreign_branches gave 20, not 8)."""
from src.core import branches as B
from src.analyzers import daily_summary as DS
from src.pipelines import reports as RP

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.95.0 外資 = us / eu / asia (離線)")
print("=" * 72)
f = B.get_foreign_branches()
codes = sorted(b["code"] for b in f)
check("外資分點正好 8 家, 都是 us / eu / asia", codes == ['1360', '1440', '1470', '1480', '1590', '1650', '8440', '8960']
      and all(b["region"] in ("us", "eu", "asia") for b in f), codes)
d = {b["code"]: b["region"] for b in B.get_domestic_branches()}
check("熱點分點和公司總計 (9200 / 9600) 算國內", '9200' in d and '9600' in d and sum(r == 'area_hotspot' for r in d.values()) == 10)
check("官股不算外資也不算國內", not any(b["region"] == "public" for b in f) and 'public' not in d.values())
check("只有一份規則: 總整理用的就是 branches 的", DS.FOREIGN_REGIONS is B.FOREIGN_REGIONS)
day = {"branches": [
    {"code": "1480", "name": "美商高盛", "master": "高盛", "region": "us", "buys": [{"code": "2330", "net_lot": 10, "net_amt": 5.0}]},
    {"code": "1040", "name": "臺銀", "master": "官股", "region": "public", "buys": [{"code": "2330", "net_lot": 1, "net_amt": 1.0}]},
    {"code": "585U", "name": "統一-南京", "master": "熱點", "region": "area_hotspot", "buys": [{"code": "2330", "net_lot": 1, "net_amt": 1.0}]},
    {"code": "9200", "name": "凱基證券", "master": "公司", "region": "company_total", "buys": [{"code": "2330", "net_lot": 1, "net_amt": 1.0}]},
    {"code": "9B25", "name": "台新-五權西", "master": "本土", "region": "domestic", "buys": [{"code": "2330", "net_lot": 1, "net_amt": 1.0}]},
]}
rep = RP.analyze_foreign_branches({"daily_data": {"20261008": day}})
check("週/月報「外資分點動向」只列外資", [r["code"] for r in rep] == ["1480"], [r["code"] for r in rep])
h = (ROOT / 'index.html').read_text(encoding='utf-8')
check("關注設定「只顯示外資」用同一條規則", "const foreign = ['us', 'eu', 'asia'].includes(r);" in h
      and "if (regionType === 'foreign' && foreign) WATCHLIST.add(b.code);" in h and "r !== 'domestic') WATCHLIST" not in h)
print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
