"""v3.82.0 branch / company geography from open data (2026-10-08); v3.96.6 (2026-10-12, owner: 「先把地緣券商全部補齊才對」)
every county and city, not only the six municipalities (county towns keep 市/鎮/鄉), plus the science parks.

Addresses often omit the district ("台北市和平西路一段30號"). A road gazetteer is
learned from every open-data address that does name its district (listed, OTC,
emerging, public companies + broker branches): (city, road[+section]) ->
district by majority (>= 80% and >= 2 samples), else road-only key, else
unknown. Nothing is typed in by hand.
Output: data/branch_geo.json {companies: {code: {city, dist, src}}, branches: {code: {name, city, dist, src}}}
Downloads are cached in the system temp folder.
"""
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import requests

import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(tempfile.gettempdir()) / "chip_radar_geo"
OUT.mkdir(exist_ok=True)
BRK02_URL = "https://openapi.twse.com.tw/v1/opendata/OpenData_BRK02"
SIX = ("臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市")
MOPS = "https://mopsfin.twse.com.tw/opendata/t187ap03_{}.csv"     # L listed, O OTC, R emerging, P public
UA = {"User-Agent": "Mozilla/5.0"}
CITY_RE = re.compile(r"^(.{2}[縣市])")
DIST_RE = re.compile(r"^.{2}[縣市](.{1,4}?[區])")
ROAD_RE = re.compile(r"^(.{1,8}?(?:路|街|大道))([一二三四五六七八九十0-9]+段)?")
PARKS = (("新竹科學", ("新竹市", "東區")), ("竹南科學", ("苗栗縣", "竹南鎮")), ("銅鑼科學", ("苗栗縣", "銅鑼鄉")),
         ("中部科學", ("臺中市", "西屯區")), ("南部科學", ("臺南市", "新市區")), ("臺南科學", ("臺南市", "新市區")),
         ("高雄科學", ("高雄市", "路竹區")), ("龍潭科學", ("桃園市", "龍潭區")), ("虎尾科學", ("雲林縣", "虎尾鎮")))
COUNTY_SEAT = {"南投市": "南投縣", "彰化市": "彰化縣", "屏東市": "屏東縣", "宜蘭市": "宜蘭縣", "花蓮市": "花蓮縣", "臺東市": "臺東縣",
               "苗栗市": "苗栗縣", "竹北市": "新竹縣", "斗六市": "雲林縣", "太保市": "嘉義縣"}
UPGRADED = {"員林鎮": "員林市", "頭份鎮": "頭份市"}
OLD_COUNTY = {"臺北縣": "新北市", "桃園縣": "桃園市", "臺中縣": "臺中市", "臺南縣": "臺南市", "高雄縣": "高雄市"}
# 2026-10-13 bug (owner's 台光電 地緣 question): 桃園區 / 大園區 / 林園區 end in 「園區」 and were read as a science /
# industrial park, so their district was dropped and a road guess put 統一-桃園 etc. in 觀音區. Real districts (the
# Chunghwa Post district table, data/district_centers.json) are never treated as parks.
_CENTERS = Path(__file__).resolve().parent.parent / "data" / "district_centers.json"
REAL_DISTRICTS = ({(c, d) for c, ds in json.loads(_CENTERS.read_text(encoding="utf-8")).items() for d in ds}
                  if _CENTERS.exists() else set())


def norm(a):
    a = str(a or "").replace("台", "臺").replace("巿", "市").replace(" ", "").replace("　", "")
    a = re.sub(r"^[\d\-－()（）]+", "", a)
    for p in ("中華民國", "臺灣省", "臺灣"):
        if a.startswith(p):
            a = a[len(p):]
    for old, new in OLD_COUNTY.items():
        if a.startswith(old):
            a = new + a[len(old):]
    return a


def parse(addr):
    a = norm(addr)
    c = CITY_RE.match(a)
    city = c.group(1) if c else None
    d = DIST_RE.match(a)
    dist = d.group(1) if d else None
    rest = a[len(city) + (len(dist) if dist else 0):] if city else ""
    # old county towns became districts in 2010 (e.g. 臺北縣板橋市 -> 新北市板橋區); in a county the town is the unit
    if city and not dist:
        t = re.match(r"^(.{1,3}?[市鎮鄉])", rest)
        if t and not re.match(r"^.{0,3}[路街]", rest):
            dist = t.group(1)[:-1] + "區" if city in SIX else t.group(1)
            rest = rest[len(t.group(1)):]
    # v3.96.6 clean-ups found against the district centre table: a county seat written without its county, towns that
    # became cities (2015), industrial / science parks read as a district
    if city in COUNTY_SEAT:
        city, dist = COUNTY_SEAT[city], city
    dist = UPGRADED.get(dist, dist)
    if dist and dist.endswith("園區") and (city, dist) not in REAL_DISTRICTS:
        park = next((v for k, v in PARKS if k[:2] in dist or k in a), None)
        city, dist = park if park else (city, {"新竹市": "東區", "新竹縣": "寶山鄉"}.get(city))
    elif dist and dist.endswith("工業區") and (city, dist) not in REAL_DISTRICTS:
        dist = dist[:-3] + "區" if len(dist) > 3 else {"臺中市": "西屯區"}.get(city)
    r = ROAD_RE.match(rest)
    road = (r.group(1), r.group(2) or "") if r else None
    return city, dist, road


def fetch_mops(k):
    p = OUT / f"mops_{k}.csv"
    if not p.exists():
        r = requests.get(MOPS.format(k), headers=UA, timeout=60)
        r.raise_for_status()
        p.write_bytes(r.content)
    rows = list(csv.DictReader(io.StringIO(p.read_bytes().decode("utf-8-sig", errors="replace"))))
    return [(row.get("公司代號", "").strip(), row.get("公司簡稱", "").strip(), row.get("住址", "")) for row in rows]


def main():
    comp = {k: fetch_mops(k) for k in ("L", "O", "R", "P")}
    bp = OUT / "brk02.json"
    if not bp.exists():
        r = requests.get(BRK02_URL, headers=UA, timeout=60)
        r.raise_for_status()
        bp.write_text(r.content.decode("utf-8-sig"), encoding="utf-8")
    brk = json.loads(bp.read_text(encoding="utf-8"))
    corpus = [a for k in comp for _, _, a in comp[k]] + [b.get("地址") for b in brk]
    votes_rs, votes_r = defaultdict(Counter), defaultdict(Counter)
    for a in corpus:
        city, dist, road = parse(a)
        if city and dist and road:
            votes_rs[(city,) + road][dist] += 1
            votes_r[(city, road[0])][dist] += 1

    def infer(city, road):
        for table, key in ((votes_rs, (city,) + road), (votes_r, (city, road[0]))):
            c = table.get(key)
            if c:
                d, n = c.most_common(1)[0]
                if n >= 2 and n / sum(c.values()) >= 0.8:
                    return d
        return None

    def locate(addr):
        city, dist, road = parse(addr)
        if not city:                                  # 2454 「新竹科學園區篤行一路1號」: a park address without a city
            a = norm(addr)
            park = next((v for k, v in PARKS if k in a), None)
            if park:
                return {"city": park[0], "dist": park[1], "src": "science park"}
            return {"city": None, "dist": None, "src": "unknown"}
        if dist:
            return {"city": city, "dist": dist, "src": "address"}
        d = infer(city, road) if road else None
        if d:
            return {"city": city, "dist": d, "src": "gazetteer"}
        # v3.96.6 weaker: one or more samples, all the same district (leave-one-out 2026-10-12: 1,521 / 1,597 = 95.2 % right)
        for table, key in ((votes_rs, (city,) + road), (votes_r, (city, road[0]))) if road else ():
            c = table.get(key)
            if c and len(c) == 1:
                return {"city": city, "dist": next(iter(c)), "src": "gazetteer-1"}
            if c:
                break
        return {"city": city, "dist": None, "src": "unknown"}

    companies = {}
    for k in ("L", "O"):
        for code, name, addr in comp[k]:
            if code:
                companies[code] = {"name": name, "market": "TWSE" if k == "L" else "TPEx", **locate(addr)}
    branches = {}
    for b in brk:
        code = str(b.get("證券商代號") or "").strip()
        branches[code] = {"name": str(b.get("證券商名稱") or "").strip(), **locate(b.get("地址"))}
    # the district is often the branch's own name (凱基-岡山, 元大-中壢): fill it only when name + 區/市/鎮/鄉 is a real
    # district of the same city (the district list comes from the addresses, nothing typed by hand)
    dists = defaultdict(set)
    for v in list(companies.values()) + list(branches.values()):
        if v["city"] and v["dist"]:
            dists[v["city"]].add(v["dist"])
    for v in branches.values():
        if v["city"] and not v["dist"] and "-" in v["name"]:
            suf = v["name"].split("-")[-1].strip()
            hit = [d for d in dists[v["city"]] if d[:-1] == suf or d[:-1] == suf[:2]] if suf else []
            if len(hit) == 1:
                v["dist"], v["src"] = hit[0], "branch name"
    doc = {"_doc": ("Geography (every county and city; county towns keep 市/鎮/鄉) of broker branches (TWSE OpenData_BRK02) and listed / OTC "
                    "companies (MOPS open data t187ap03_L / _O). dist from the address, else learned road "
                    "gazetteer (majority >= 80%, >= 2 samples; gazetteer-1 = unanimous single samples, 95 % right in a leave-one-out test), else the branch name when it is a district of the same city, else null. "
                    "Built by scripts/build_branch_geo.py."),
           "companies": {k: {kk: v[kk] for kk in ("city", "dist", "src")} for k, v in companies.items()},
           "branches": {k: {kk: v[kk] for kk in ("name", "city", "dist", "src")} for k, v in branches.items()}}
    (ROOT / "data" / "branch_geo.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                                   encoding="utf-8")
    for label, d in (("companies (listed+OTC)", companies), ("branches", branches)):
        print(f"{label}: all {len(d)}, city known {sum(1 for v in d.values() if v['city'])}, district known "
              f"{sum(1 for v in d.values() if v['dist'])}, by source {dict(Counter(v['src'] for v in d.values()))}")
        six = [v for v in d.values() if v["city"] in SIX]
        print(f"{label}: {len(d)} total, in six cities {len(six)}, district known {sum(1 for v in six if v['dist'])} "
              f"(address {sum(1 for v in six if v['src'] == 'address')}, gazetteer "
              f"{sum(1 for v in six if v['src'] == 'gazetteer')}, unknown {sum(1 for v in six if v['src'] == 'unknown')})")
    print("gazetteer keys:", len(votes_rs), "road+section,", len(votes_r), "road")
    print("unknown samples:", [norm(b.get('地址'))[:16] for b in brk
                                if branches[str(b.get('證券商代號')).strip()]['src'] == 'unknown'][:6])


if __name__ == "__main__":
    main()
