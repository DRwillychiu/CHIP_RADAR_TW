# -*- coding: utf-8 -*-
"""Clean-room extractor for MOPS query6_1 (insider holding change) pages.

Usage: python -X utf8 -I cleanroom.py [--debug]
Reads {code}_{YYYYMM}.html in this folder, writes cleanroom.csv (UTF-8).
Standard library only.
"""
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPOUSE_SUFFIX = "之配偶及未成年子女"  # spouse + minor children
SPOUSE_TAG = "之配偶"  # "of spouse"
COMMON = "普通股"  # common stock

ROW_RE = re.compile(r"<tr class='(?:odd|even)'>(.*?)</tr>", re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def clean(txt):
    return re.sub(r"\s+", "", TAG_RE.sub("", txt))


def nums(cell):
    """Return the first five <br>-separated integers of a numeric cell."""
    parts = cell.split("<br>")
    out = []
    for p in parts[:5]:
        p = p.strip()
        if not re.fullmatch(r"[\d,]+", p):
            raise ValueError("non-numeric token %r" % p)
        out.append(int(p.replace(",", "")))
    if len(out) != 5:
        raise ValueError("cell has %d numbers" % len(out))
    return tuple(out)


def parse_page(path):
    s = open(path, encoding="utf-8").read()
    rows = []
    for m in ROW_RE.finditer(s):
        tds = TD_RE.findall(m.group(1))
        if len(tds) != 7:
            raise ValueError("%s: row with %d cells" % (path, len(tds)))
        role = clean(tds[0])
        name = clean(tds[1])
        stype = clean(tds[2])
        prev = nums(tds[3])
        inc = nums(tds[4])
        dec = nums(tds[5])
        cur = nums(tds[6])  # first five numbers; notes follow after them
        rows.append(dict(role=role, name=name, stype=stype,
                         prev=prev, inc=inc, dec=dec, cur=cur))
    return rows


def process(rows, log, tag):
    # 1) label nameless spouse rows with the nearest preceding principal row
    for i, r in enumerate(rows):
        if r["stype"] != COMMON:
            continue
        if r["name"]:
            continue
        if r["role"].endswith(SPOUSE_SUFFIX):
            prefix = r["role"][: -len(SPOUSE_SUFFIX)]
            who = None
            for j in range(i - 1, -1, -1):
                q = rows[j]
                if q["stype"] == COMMON and q["name"] and q["role"] == prefix:
                    who = q["name"]
                    break
            if who is None:
                log.append("%s: spouse row role=%s idx=%d has no preceding named row of role %s"
                           % (tag, r["role"], i, prefix))
                r["label"] = None
            else:
                r["label"] = who + SPOUSE_TAG
                r["spouse"] = True
        else:
            log.append("%s: nameless non-spouse row role=%s idx=%d" % (tag, r["role"], i))
            r["label"] = None
    for r in rows:
        if r["name"]:
            r["label"] = r["name"]

    def numkey(r):
        return (r["prev"], r["inc"], r["dec"], r["cur"])

    named_keys = {}
    for r in rows:
        if r["stype"] == COMMON and r["name"]:
            named_keys.setdefault(numkey(r), []).append(r["name"])

    kept = []
    seen = {}
    for i, r in enumerate(rows):
        if r["stype"] != COMMON:
            continue
        # spouse row identical to a named row -> same person, drop
        if r.get("spouse") and numkey(r) in named_keys:
            if r["inc"][0] or r["dec"][0]:
                log.append("%s: DROP spouse row (%s) idx=%d identical to named %s buy=%d sell=%d"
                           % (tag, r["role"], i, named_keys[numkey(r)], r["inc"][0], r["dec"][0]))
            continue
        key = (r["label"], numkey(r))
        if key in seen:
            if r["inc"][0] or r["dec"][0]:
                log.append("%s: MERGE role=%s into role=%s name=%s buy=%d sell=%d"
                           % (tag, r["role"], seen[key]["role"], r["label"], r["inc"][0], r["dec"][0]))
            seen[key]["merged_roles"].append(r["role"])
            continue
        r["merged_roles"] = []
        seen[key] = r
        kept.append(r)
    return kept


def main():
    debug = "--debug" in sys.argv
    files = sorted(glob.glob(os.path.join(HERE, "*_*.html")))
    out = []
    log = []
    for f in files:
        base = os.path.basename(f)[:-5]
        code, ym = base.split("_")
        rows = parse_page(f)
        kept = process(rows, log, base)
        for r in kept:
            buy, sell = r["inc"][0], r["dec"][0]
            if buy == 0 and sell == 0:
                continue
            out.append([code, ym, r["role"], r["label"] or "", buy, sell, r["cur"][0]])
        if debug:
            print("%s rows=%d kept=%d" % (base, len(rows), len(kept)))
    with open(os.path.join(HERE, "cleanroom.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(out)
    print("pages=%d lines=%d" % (len(files), len(out)))
    for l in log:
        print(l)


if __name__ == "__main__":
    main()
