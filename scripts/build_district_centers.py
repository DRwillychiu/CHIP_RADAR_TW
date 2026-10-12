"""v3.96.6 district centre coordinates for the 地緣 distance (owner 2026-10-12: 「地緣分點其實就是總公司所在地周圍的
券商分點」). Source: Chunghwa Post download area 8.1 「3碼郵遞區號與行政區中心點經緯度對照表」 (XML, 2016-08-12,
政府資料開放授權條款), https://www.post.gov.tw/post/internet/Download/index.jsp?ID=220306
    python scripts/build_district_centers.py <downloaded xml>
Output: data/district_centers.json {"臺北市": {"中正區": [lat, lon], ...}, ...}
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    t = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = {}
    for name, lon, lat in re.findall(r"<行政區名>(.+?)</行政區名>.*?<中心點經度>([\d.]+)</中心點經度>\s*<中心點緯度>([\d.]+)</中心點緯度>", t, re.S):
        name = name.replace("台", "臺").strip()
        city, dist = name[:3], name[3:]
        if dist:
            out.setdefault(city, {})[dist] = [round(float(lat), 5), round(float(lon), 5)]
    (ROOT / "data" / "district_centers.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[centers] {sum(len(v) for v in out.values())} districts in {len(out)} cities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
