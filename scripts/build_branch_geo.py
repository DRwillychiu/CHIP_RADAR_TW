"""v3.82.0 six-municipality branch / company geography from open data (2026-10-08).

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
OLD_COUNTY = {"臺北縣": "新北市", "桃園縣": "桃園市", "臺中縣": "臺中市", "臺南縣": "臺南市", "高雄縣": "高雄市"}


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
    # old county towns became districts in 2010 (e.g. 臺北縣板橋市 -> 新北市板橋區)
    if city in SIX and not dist:
        t = re.match(r"^(.{1,3}?[市鎮鄉])", rest)
        if t and not re.match(r"^.{0,3}[路街]", rest):
            dist, rest = t.group(1)[:-1] + "區", rest[len(t.group(1)):]
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
        if city in SIX and dist and road:
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
        if city not in SIX:
            return {"city": city, "dist": None, "src": "outside six"}
        if dist:
            return {"city": city, "dist": dist, "src": "address"}
        d = infer(city, road) if road else None
        return {"city": city, "dist": d, "src": "gazetteer" if d else "unknown"}

    companies = {}
    for k in ("L", "O"):
        for code, name, addr in comp[k]:
            if code:
                companies[code] = {"name": name, "market": "TWSE" if k == "L" else "TPEx", **locate(addr)}
    branches = {}
    for b in brk:
        code = str(b.get("證券商代號") or "").strip()
        branches[code] = {"name": str(b.get("證券商名稱") or "").strip(), **locate(b.get("地址"))}
    doc = {"_doc": ("Six-municipality geography of broker branches (TWSE OpenData_BRK02) and listed / OTC "
                    "companies (MOPS open data t187ap03_L / _O). dist from the address, else learned road "
                    "gazetteer (majority >= 80%, >= 2 samples), else null. Built by scripts/build_branch_geo.py."),
           "companies": {k: {kk: v[kk] for kk in ("city", "dist", "src")} for k, v in companies.items()},
           "branches": {k: {kk: v[kk] for kk in ("name", "city", "dist", "src")} for k, v in branches.items()}}
    (ROOT / "data" / "branch_geo.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                                   encoding="utf-8")
    for label, d in (("companies (listed+OTC)", companies), ("branches", branches)):
        six = [v for v in d.values() if v["city"] in SIX]
        print(f"{label}: {len(d)} total, in six cities {len(six)}, district known {sum(1 for v in six if v['dist'])} "
              f"(address {sum(1 for v in six if v['src'] == 'address')}, gazetteer "
              f"{sum(1 for v in six if v['src'] == 'gazetteer')}, unknown {sum(1 for v in six if v['src'] == 'unknown')})")
    print("gazetteer keys:", len(votes_rs), "road+section,", len(votes_r), "road")
    print("unknown samples:", [norm(b.get('地址'))[:16] for b in brk
                                if branches[str(b.get('證券商代號')).strip()]['src'] == 'unknown'][:6])


if __name__ == "__main__":
    main()
