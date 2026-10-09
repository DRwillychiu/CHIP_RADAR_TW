"""v3.85.8 one decoder for every Fubon / MoneyDJ page.

The pages declare charset=big5 but are written in cp950 (Microsoft Big5).
Python's "big5" codec has no cp950 extension row F9D6-F9FE, so names with
碁 恒 銹 裏 墻 粧 嫺 came out as U+FFFD, and a bad pair shifted the bytes
after it: 立碁(8111) -> 立??, 富邦恒生國企正2(00665L) -> 富邦?琪肭碪囓?2.
Owner 2026-10-09: "8111 名稱是立碁".

cp950 and big5 differ on 11 punctuation codes (a145 a14e a1c2 a1e3 a1f2
a1f3 a241 a242 a244 a246 a247); none of them occur in the stored data
(checked on the 2026-10-08 data set), so switching changes no stored name
other than the broken ones.
"""

FUBON_ENCODING = "cp950"


def decode_fubon(body: bytes) -> str:
    return body.decode(FUBON_ENCODING, errors="replace")


# Names already stored with U+FFFD do not heal by themselves: stock_history
# fills a name only when it is empty, master_profiles keeps the oldest name,
# positions keep it until the branch trades the stock again.
BROKEN = "�"


def is_broken(name) -> bool:
    return BROKEN in (name or "")


def repair_stock_names(node, names) -> int:
    """In place: each broken 'stock_name' gets names[code], code being the
    dict's 'stock_code' or else the key the dict sits under. Branch fields
    ('name', 'branch_name') are never touched - a branch code can equal a
    stock code (1440 美林 / 1440 南紡). Returns how many names were fixed."""
    fixed = 0
    stack = [(node, None)]
    while stack:
        o, key = stack.pop()
        if isinstance(o, dict):
            if is_broken(o.get("stock_name")):
                good = names.get(str(o.get("stock_code") or key or ""))
                if good and not is_broken(good):
                    o["stock_name"] = good
                    fixed += 1
            stack.extend((v, k) for k, v in o.items() if isinstance(v, (dict, list)))
        elif isinstance(o, list):
            stack.extend((v, None) for v in o if isinstance(v, (dict, list)))
    return fixed
