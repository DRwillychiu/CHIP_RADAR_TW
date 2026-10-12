"""v3.96.0 insider radar 1.1: monthly insider holdings for the whole market, two official tables.

Source (verified 2026-10-11, scratchpad mops_probe/): MOPS publishes each month as static Big5 pages
    https://siis.twse.com.tw/publish/{sii|otc}/{ROC year}{IRB110|IRB140}_{MM}.HTM
  IRB110 company table: issued shares; directors+supervisors month increase / decrease / held / % ;
         managers held; >10 % shareholders held. Excludes financial-holding subsidiaries.
  IRB140 person table: every insider transfer of >= 1,000,000 shares (company, 身份別, name, shares).
The page carries its own publish date ("資料日期:115/09/22", about the 18th-22nd of the next month) -
that date, not a deadline, is when the data became public (the signal day comes after it).
Not yet published: the page says 查詢之年月尚未公告 -> None.
"""
from __future__ import annotations

import html
import re

URL = "https://siis.twse.com.tw/publish/{mkt}/{roc}{table}_{mm:02d}.HTM"
_ROW = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
_CELL = re.compile(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>")
_DATE = re.compile(r"資\s*料\s*日\s*期\s*[:：]\s*(\d{2,3})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")
_CO = re.compile(r"^([0-9A-Z]{4,6})(.*)$")


def url(table: str, mkt: str, ym: str) -> str:
    return URL.format(mkt=mkt, roc=int(ym[:4]) - 1911, table=table, mm=int(ym[4:]))


def decode(raw: bytes) -> str:
    return raw.decode("big5hkscs", errors="replace")   # the server's ISO-8859-1 header is wrong


def _cells(t):
    for r in _ROW.findall(t):
        yield [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip() for c in _CELL.findall(r)]


def _int(s):
    s = str(s).replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def publish_date(t: str):
    m = _DATE.search(t)
    return f"{int(m.group(1)) + 1911:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else None


def parse_irb110(t: str):
    """-> (publish date, {code: row}) or None when the month is not published yet."""
    if "尚未公告" in t:
        return None
    out = {}
    for c in _cells(t):
        if len(c) != 8:
            continue
        m = _CO.match(c[0])
        nums = [_int(x) for x in c[1:5]] + [_int(x) for x in c[6:8]]
        if not m or any(v is None for v in nums):
            continue
        out[m.group(1)] = {
            "name": m.group(2).strip(), "issued": nums[0], "dir_inc": nums[1], "dir_dec": nums[2],
            "dir_held": nums[3], "dir_pct": float(c[5]) if re.fullmatch(r"\d+(\.\d+)?", c[5]) else None,
            "mgr_held": nums[4], "big10_held": nums[5],
        }
    return publish_date(t), out


def parse_irb140(t: str):
    """-> (publish date, [transfer]) or None. The header row also carries the first record."""
    if "尚未公告" in t:
        return None
    flat = [x for c in _cells(t) for x in c]
    out = []
    for i in range(len(flat) - 3):
        m = _CO.match(flat[i])
        n = _int(flat[i + 3])
        if m and n is not None and flat[i + 1].endswith(("本人", "他人名義持有者", "配偶", "未成年子女")):
            out.append({"code": m.group(1), "company": m.group(2).strip(), "role": flat[i + 1],
                        "name": flat[i + 2], "shares": n})
    return publish_date(t), out


# ---- per person, one company and month (MOPS query6_1; used only for flagged companies) ----
Q61_URL = "https://mopsov.twse.com.tw/mops/web/ajax_query6_1"


def q61_form(code: str, ym: str) -> dict:
    return {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
            "inpuType": "co_id", "TYPEK": "all", "isnew": "false", "co_id": code,
            "year": str(int(ym[:4]) - 1911), "month": ym[4:]}


def _nums(s):
    return [int(x.replace(",", "")) for x in re.findall(r"-?[\d,]+", s or "")]


def parse_query6_1(t: str, code: str, ym: str):
    """-> person records for insider_radar.merge_people. Rules from the page itself:
    - "內部人若具二種以上身份，每種身份別會揭露同樣股數，勿重複累計": a person listed under two roles
      is counted once (the first role).
    - spouse / minor-children rows have no name and nominee rows name the nominee: they belong to the
      principal ("…本人") listed just before them with the same role prefix.
    Change = market buys (集中) + other increases - market sells - other decreases; 私募 / 信託 / 設質
    columns are not trades and stay out."""
    cells = [c for c in _cells(t) if len(c) == 7 and c[0] and c[0] != "身份別" and "普通股" in c[2]]
    # a spouse who is an insider too appears twice: as "…本人" and as the other one's "…之配偶" row
    own = {(tuple(_nums(c[4])), tuple(_nums(c[5])), tuple(_nums(c[6])[:1])) for c in cells if c[0].endswith("本人")}
    out, seen, principal, fam, named = [], set(), {}, set(), set()
    # 2024 2025-10 / 6965 2026-01 (independent check 2026-10-12): one holding is listed again as an unnamed
    # spouse row of another role (董事長之法人代表人之配偶, 大股東本人之配偶, 其他之配偶 ...), all numbers equal.
    # An unnamed spouse row equal to a named row, or to an earlier unnamed one, is the same holding: count once.
    def full(c):
        return tuple(tuple(_nums(c[k])[:5]) for k in (3, 4, 5, 6))   # 5 official values per cell (7769: a remark adds a 6th)
    named_full, unnamed_full = {full(c) for c in cells if c[1].strip()}, set()
    for c in cells:
        if len(c) != 7 or not c[0] or c[0] == "身份別" or "普通股" not in c[2]:
            continue
        role_full, name = c[0], c[1]
        prev, inc, dec, end = _nums(c[3]), _nums(c[4]), _nums(c[5]), _nums(c[6])
        if len(inc) < 2 or len(dec) < 2 or not end:
            continue
        if not name.strip() and role_full.endswith("之配偶及未成年子女"):
            if full(c) in named_full or full(c) in unnamed_full:
                continue
            unnamed_full.add(full(c))
        m = re.match(r"^(.*?)(本人之配偶及未成年子女|利用他人名義持有者|本人|之法人代表人)$", role_full)
        role, kind = (m.group(1), m.group(2)) if m else (role_full, "本人")
        if kind == "本人":
            principal[role] = name
        # the same holding listed under another role (2540 2024-10: 仰山林廣告 as 董事本人 and again as
        # 董事法人代表人利用他人名義持有者, same name and numbers) - count it once
        sig_named = (name, tuple(inc), tuple(dec), tuple(end[:1]))
        if name and sig_named in named:
            continue
        if name:
            named.add(sig_named)
        if kind == "本人":
            key = name
        elif kind == "之法人代表人":
            key = name
        else:
            # 董事長法人代表人利用他人名義持有者 belongs to the 董事長 row's holder (2646 2024-10)
            key = principal.get(role) or principal.get(role.replace("法人代表人", "")) or role
            if kind == "本人之配偶及未成年子女":
                sig = (tuple(inc), tuple(dec), tuple(end[:1]))
                if (key, sig) in fam or sig in own:
                    continue             # the same family counted once; a spouse listed as an insider counts as herself
                fam.add((key, sig))
        if kind in ("本人", "之法人代表人") and name.strip():   # unnamed rows are different families (1466 2026-07)
            if name in seen:
                continue                 # same person, second role: same shares, do not add twice
            seen.add(name)
        out.append({"code": code, "ym": ym, "role": role, "name": key + ("(他人名義)" if kind == "利用他人名義持有者" else ""),
                    "nominee": kind != "本人", "kind": kind, "holder": name,
                    "delta_shares": inc[0] + inc[1] - dec[0] - dec[1], "market_buy": inc[0], "market_sell": dec[0],
                    "other_buy": inc[1], "other_sell": dec[1],
                    "end_shares": end[0], "pledge_shares": end[3] if len(end) > 3 else None})
    return out


# ---- pre-transfer declarations (MOPS t56sb21, whole market, by month range) - the leading signal ----
T56_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t56sb21"
# sold on the exchange (regular, after-hours fixed price, block trade); 洽特定人 / 贈與 / 信託 are off-market
MARKET_SALE = {"一般交易", "一般交易盤後定價交易", "盤後定價交易", "鉅額逐筆交易"}


def t56_form(mkt: str, ym: str) -> dict:
    m = str(int(ym[4:]))
    return {"encodeURIComponent": "1", "run": "", "step": "1", "TYPEK": mkt, "year": str(int(ym[:4]) - 1911),
            "smonth": m, "emonth": m, "sstep": "1", "firstin": "true"}


def _roc(s):
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s or "")
    return f"{int(m.group(1)) + 1911:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else None


def parse_t56sb21(t: str):
    """-> [declaration]. 一般交易 = a planned sale in the market; 贈與 / 信託 / ... are not market sales."""
    out = []
    for c in _cells(t):
        if len(c) != 18 or not _roc(c[1]):
            continue
        planned = _int(c[12]) if _int(c[12]) is not None else _int(c[7])
        period = re.findall(r"\d{2,3}/\d{1,2}/\d{1,2}", c[16])
        out.append({"declared_on": _roc(c[1]), "code": c[2], "company": c[3], "role": c[4], "name": c[5],
                    "method": c[6], "market_sale": c[6] in MARKET_SALE, "planned_shares": planned,
                    "held_before": _int(c[10]), "held_after": _int(c[14]), "transferee": c[9],
                    "from": _roc(period[0]) if period else None, "to": _roc(period[-1]) if period else None,
                    "change_note": c[0]})
    return out


# ---- which company-months get the per-person page (IRB110 misstates trades, spec 5.1: screen only) ----
SCREEN_PCT = 0.2     # the directors' month increase or decrease >= 0.2 % of the shares ...
SCREEN_YI = 1.0      # ... or >= 1 億 at the month's average close


def screen(month: dict, avg_px: dict, prev: dict = None):
    """month = one data/insider_monthly/YYYYMM.json; avg_px[code] = that month's average close;
    prev = the month before (for the holdings change of managers and > 10 % shareholders).
    -> [(priority, code)]: 1 buy side, 2 sell side, 3 only in the >= 1M-share transfer table (IRB140),
    4 only a manager / > 10 % shareholder holdings change of the same size.
    Priority 4 since 2026-10-11: the control sample of NOT screened company-months (44) held 8 trades
    of signal size, 7 of them by > 10 % shareholders, legal-person representatives or nominees that
    IRB110's director columns leave out (2515 2025-10: a > 10 % holder bought 6.6 % of the shares)."""
    t140 = {x["code"] for x in month.get("transfers") or []}

    def big(n, iss, px):
        return bool(n) and ((iss and n / iss * 100 >= SCREEN_PCT) or (px and n * px >= SCREEN_YI * 1e8))
    out = []
    for code, r in month.get("companies", {}).items():
        if not re.fullmatch(r"\d{4}", code):     # owner 2026-10-11: Taiwan company codes are 4 digits (674191 is not one)
            continue
        iss, px = r.get("issued") or 0, avg_px.get(code)
        if big(r.get("dir_inc") or 0, iss, px):
            out.append((1, code))
        elif big(r.get("dir_dec") or 0, iss, px):
            out.append((2, code))
        elif code in t140:
            out.append((3, code))
        elif prev is not None:
            o = (prev.get("companies") or {}).get(code)
            if o and any(big(abs((r.get(k) or 0) - (o.get(k) or 0)), iss, px) for k in ("mgr_held", "big10_held")):
                out.append((4, code))
    return out
