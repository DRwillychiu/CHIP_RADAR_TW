#!/usr/bin/env python3
# Hand-laid-out SVG diagrams for Chip Radar TW, rendered to PNG with headless Chrome.
# Usage: python docs/diagrams/build_diagrams.py [key ...]   (keys: system flow_day flow_crawl architecture)
import os, sys, json, re, html, subprocess
from PIL import ImageFont, Image

BASE = os.path.dirname(os.path.abspath(__file__))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UDD = os.path.join(BASE, "chrome_profile")
FONT_PATH = r"C:\Windows\Fonts\NotoSansTC-VF.ttf"
FONT_STACK = "'Noto Sans TC','Microsoft JhengHei',sans-serif"
GFONT = "https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=block"

# ---------------- palette (sampled from reference images) ----------------
NAVY = "#1F3A5F"
LINE_NAVY = "#22385A"
TEXT = "#1E2A38"
TEXT2 = "#4A5563"
SUB = "#5D656B"
HDR_GRAY = "#878C96"
HAIR = "#E3E7EC"
EXT_STROKE = "#A4A9AA"
EXT_FILL = "#FAFBFC"
PANEL_FILL = "#F2F6FC"
SW_STROKE = "#BDC7CF"
CYL_STROKE = "#9FAFC2"
CYL_TOP = "#EDF3F8"
ORANGE = "#D08A3C"
ORANGE_FILL = "#FFF6EA"
ORANGE_TEXT = "#8A4E12"
CARD_HDR = "#2F6DB5"
CARD_BODY = "#EFF4FB"
CARD_STROKE = "#376EA5"
RED = "#C94040"
RED_FILL = "#FDEBEA"
RED_TEXT = "#B03A2E"
GB_FILL = "#F3F5F7"
GB_STROKE = "#9BA5AD"
GB_TEXT = "#3C464C"
DASH_STROKE = "#9A9EA3"
DASH_TEXT = "#80858C"
PROC_FILL = "#EEF4FB"
PROC_STROKE = "#3D6FB6"
DIA_FILL = "#FFF8E6"
DIA_STROKE = "#D1A133"
GREEN = "#2E8B57"
GREEN_FILL = "#E8F5EC"
GREEN_TEXT = "#1F5E3A"
GP_STROKE = "#8A8F98"
GP_FILL = "#F1F2F4"
GP_TEXT = "#3D454E"
FLOW_LINE = "#4D5058"
NOTE_STROKE = "#ADB1B4"
NOTE_TEXT = "#636164"
NOTE_LINE = "#9DA3A8"
START_FILL = "#1F3B5F"
BANDS = ["#F4F8FB", "#F6F5EE", "#FAF4F0", "#F4F9F5"]
PAUSE_STROKE = "#8C9095"
PAUSE_FILL = "#F3F5F7"
PAUSE_TEXT = "#636D77"

FOOT_LEFT = "依據：repo 盤點（2026/10/06，v3.80.16）"
FOOT_RIGHT = "Chip Radar TW"

# ---------------- text measurement ----------------
_F = {}


def tw(s, size, weight=400, ls=0.0):
    f = _F.get(weight)
    if f is None:
        f = ImageFont.truetype(FONT_PATH, 200)
        f.set_variation_by_axes([weight])
        _F[weight] = f
    return f.getlength(s) * size / 200.0 + ls * len(s)


def esc(s):
    return html.escape(s, quote=False)


# ---------------- geometry ----------------
class Shape:
    def __init__(self, name, kind, x, y, w, h, container=False, ry=0):
        self.name, self.kind = name, kind
        self.x, self.y, self.w, self.h = x, y, w, h
        self.container = container
        self.ry = ry

    def contains(self, px, py, shrink=0.0):
        if self.kind == "diamond":
            cx, cy = self.x + self.w / 2, self.y + self.h / 2
            hw, hh = self.w / 2, self.h / 2
            v = abs(px - cx) / hw + abs(py - cy) / hh
            # shrink approx in normalized units
            return v < 1.0 - shrink / min(hw, hh)
        return (self.x + shrink < px < self.x + self.w - shrink) and (
            self.y + shrink < py < self.y + self.h - shrink)


class Dia:
    def __init__(self, key, W, H):
        self.key, self.W, self.H = key, W, H
        self.els = []
        self.shapes = {}
        self.segs = []
        self.texts = []
        self.n = 0
        self.dropped = []

    # ---- shapes ----
    def _reg(self, name, kind, x, y, w, h, container=False, ry=0):
        if name is None:
            return None
        assert name not in self.shapes, name
        sh = Shape(name, kind, x, y, w, h, container, ry)
        self.shapes[name] = sh
        return sh

    def rect(self, name, x, y, w, h, fill, stroke, sw=1.5, rx=6, dash=None,
             container=False, kind="rect"):
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.els.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" fill="{fill}"{st}{d}/>')
        return self._reg(name, kind, x, y, w, h, container)

    def pill(self, name, x, y, w, h, fill, stroke, sw=1.5, dash=None):
        return self.rect(name, x, y, w, h, fill, stroke, sw, rx=h / 2, dash=dash, kind="pill")

    def diamond(self, name, cx, cy, w, h, fill=DIA_FILL, stroke=DIA_STROKE, sw=1.6):
        pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
        self.els.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                        f'stroke-width="{sw}" stroke-linejoin="round"/>')
        return self._reg(name, "diamond", cx - w / 2, cy - h / 2, w, h)

    def cylinder(self, name, x, y, w, h, ry, fill="#FFFFFF", top=CYL_TOP,
                 stroke=CYL_STROKE, sw=1.4):
        rx = w / 2
        p = (f"M{x},{y + ry} V{y + h - ry} A{rx},{ry} 0 0 0 {x + w},{y + h - ry} "
             f"V{y + ry} A{rx},{ry} 0 0 0 {x},{y + ry} Z")
        self.els.append(f'<path d="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        self.els.append(f'<ellipse cx="{x + rx}" cy="{y + ry}" rx="{rx}" ry="{ry}" '
                        f'fill="{top}" stroke="{stroke}" stroke-width="{sw}"/>')
        return self._reg(name, "cyl", x, y, w, h, ry=ry)

    def raw(self, s):
        self.els.append(s)

    # ---- text ----
    def text(self, x, yc, t, size, weight=400, fill=TEXT, anchor="middle",
             container=None, ls=0.0, group=None):
        self.n += 1
        tid = f"{self.key}_t{self.n}"
        w = tw(t, size, weight, ls)
        xx = x
        if anchor == "middle":
            left = x - w / 2
            xx = x + ls / 2.0  # trailing letter-spacing compensation
        elif anchor == "start":
            left = x
        else:
            left = x - w
        base = yc + 0.355 * size
        lsa = f' letter-spacing="{ls}"' if ls else ""
        self.els.append(
            f'<text id="{tid}" x="{xx:.1f}" y="{base:.1f}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{lsa}>{esc(t)}</text>')
        self.texts.append(dict(id=tid, left=left, w=w, top=yc - 0.45 * size,
                               bot=yc + 0.5 * size, container=container, t=t, group=group))
        return w

    def block(self, x, cy, items, anchor="middle", container=None, lead=1.38):
        """items: list of (text, size, weight, fill); vertically centred on cy."""
        hs = [it[1] * lead for it in items]
        y = cy - sum(hs) / 2
        for it, h in zip(items, hs):
            self.text(x, y + h / 2, it[0], it[1], it[2], it[3], anchor, container)
            y += h

    # ---- lines ----
    def path(self, pts, color, sw=1.6, end=True, start=False, dash=None, hl=9.0, hw=4.5,
             register=True, chevron=False):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            assert abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6, ("not orthogonal", pts)
        p = [list(q) for q in pts]

        def shorten(a, b, L):
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = (dx * dx + dy * dy) ** 0.5
            return [b[0] - dx / n * L, b[1] - dy / n * L]

        if end and not chevron:
            p[-1] = shorten(p[-2], p[-1], hl - 1)
        if start:
            p[0] = shorten(p[1], p[0], hl - 1)
        d = f' stroke-dasharray="{dash}"' if dash else ""
        cap = "round" if chevron else "butt"
        ptxt = " ".join(f"{a:.1f},{b:.1f}" for a, b in p)
        self.els.append(f'<polyline points="{ptxt}" fill="none" stroke="{color}" '
                        f'stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="{cap}"{d}/>')

        def head(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = (dx * dx + dy * dy) ** 0.5
            ux, uy = dx / n, dy / n
            bx, by = b[0] - ux * hl, b[1] - uy * hl
            px, py = -uy * hw, ux * hw
            if chevron:
                self.els.append(
                    f'<polyline points="{bx + px:.1f},{by + py:.1f} {b[0]:.1f},{b[1]:.1f} '
                    f'{bx - px:.1f},{by - py:.1f}" fill="none" stroke="{color}" '
                    f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>')
            else:
                self.els.append(
                    f'<polygon points="{b[0]:.1f},{b[1]:.1f} {bx + px:.1f},{by + py:.1f} '
                    f'{bx - px:.1f},{by - py:.1f}" fill="{color}"/>')

        if end:
            head(pts[-2], pts[-1])
        if start:
            head(pts[1], pts[0])
        if register:
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                self.segs.append((x1, y1, x2, y2))

    def dot(self, x, y, color, r=3.5):
        self.els.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')

    # ---- output ----
    def svg(self, standalone=True):
        style = (f"<style>@import url('{GFONT}');text{{font-family:{FONT_STACK};}}</style>"
                 if standalone else
                 f"<style>text{{font-family:{FONT_STACK};}}</style>")
        body = "\n".join(self.els)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.W}" height="{self.H}" '
                f'viewBox="0 0 {self.W} {self.H}">{style}'
                f'<rect x="0" y="0" width="{self.W}" height="{self.H}" fill="#FFFFFF"/>\n'
                f'{body}\n</svg>')


# ---------------- shared chrome ----------------
def header(d, title, subtitle, rule_y=90):
    tws = d.text(40, 56, title, 34, 700, NAVY, "start")
    base = 56 + 0.355 * 34
    d.text(40 + tws + 20, base - 0.355 * 16, subtitle, 16, 400, SUB, "start")
    d.raw(f'<rect x="40" y="{rule_y - 1.5}" width="{d.W - 80}" height="3" fill="{NAVY}"/>')


def footer(d, yc):
    d.text(40, yc, FOOT_LEFT, 14, 400, SUB, "start")
    d.text(d.W - 40, yc, FOOT_RIGHT, 14, 400, SUB, "end")


def legend(d, x, yc, items, size=14):
    i = 0
    for it in items:
        kind, label = it[0], it[-1]
        i += 1
        nm = f"legend_{i}"
        if kind == "rect":
            fill, stroke, dash = it[1], it[2], it[3]
            d.rect(None, x, yc - 8, 26, 16, fill, stroke, 1.5, rx=4, dash=dash)
            d._reg(nm, "rect", x, yc - 8, 26, 16)
            iw = 26
        elif kind == "pill":
            fill, stroke = it[1], it[2]
            d.rect(None, x, yc - 8, 28, 16, fill, stroke, 1.5, rx=8)
            d._reg(nm, "rect", x, yc - 8, 28, 16)
            iw = 28
        elif kind == "diamond":
            d.diamond(None, x + 13, yc, 26, 18)
            d._reg(nm, "rect", x, yc - 9, 26, 18)
            iw = 26
        elif kind == "cyl":
            d.cylinder(None, x + 2, yc - 9, 22, 18, 4, sw=1.3)
            d._reg(nm, "rect", x + 2, yc - 9, 22, 18)
            iw = 26
        elif kind == "arrow":
            color, dash = it[1], it[2]
            d.path([(x, yc), (x + 34, yc)], color, 1.8, dash=dash, hl=8, hw=4, register=False)
            d._reg(nm, "rect", x, yc - 5, 34, 10)
            iw = 34
        d.text(x + iw + 8, yc, label, size, 400, SUB, "start")
        x += iw + 8 + tw(label, size) + 26
    return x


def col_header(d, x0, x1, yc, label, line_y, tail=""):
    if tail:
        w1 = tw(label, 15, 500, 3)
        w2 = tw(tail, 15, 500)
        x = (x0 + x1) / 2 - (w1 + w2) / 2
        d.text(x, yc, label, 15, 500, HDR_GRAY, "start", ls=3, group=label)
        d.text(x + w1, yc, tail, 15, 500, HDR_GRAY, "start", group=label)
    else:
        d.text((x0 + x1) / 2, yc, label, 15, 500, HDR_GRAY, "middle", ls=3)
    d.raw(f'<rect x="{x0}" y="{line_y}" width="{x1 - x0}" height="1.5" fill="{HAIR}"/>')


# =====================================================================
# A. system architecture
# =====================================================================
def build_system():
    W, H = 1280, 780
    d = Dia("system", W, H)
    header(d, "系統架構圖", "台股籌碼雷達　資料來源 → 雲端排程 → 輸出")
    LX0, LX1 = 40, 260
    MX0, MX1 = 340, 940
    RX0, RX1 = 1010, 1240
    col_header(d, LX0, LX1, 124, "資料來源", 140)
    col_header(d, MX0, MX1, 124, "雲端", 140, tail="（GitHub）")
    col_header(d, RX0, RX1, 124, "輸出", 140)

    # ---- panel 1: GitHub Actions ----
    P1Y, P1H = 160, 222
    d.rect("panel1", MX0, P1Y, MX1 - MX0, P1H, PANEL_FILL, NAVY, 1.8, rx=12, container=True)
    d.text(MX0 + 24, P1Y + 30, "GitHub Actions　雲端排程", 19, 700, NAVY, "start",
           container="panel1")
    gx, gw, gy, gh = 640 - 145, 290, 210, 38
    d.rect("gate", gx, gy, gw, gh, "#FFFFFF", SW_STROKE, 1.4, rx=6)
    d.text(640, gy + gh / 2, "交易日開關（非交易日整輪跳過）", 15, 500, NAVY, container="gate")
    bw, bgap, bx0, by, bh = 126, 16, MX0 + 24, 292, 66
    centers = [bx0 + i * (bw + bgap) + bw / 2 for i in range(4)]
    progs = [
        [("每日籌碼", 16, 700, TEXT), ("daily-full", 14, 500, TEXT2)],
        [("融資更新", 16, 700, TEXT)],
        [("盤前・盤中", 16, 700, TEXT), ("結算・週報", 16, 700, TEXT)],
        [("監控・稽核", 16, 700, TEXT)],
    ]
    for i, items in enumerate(progs):
        x = bx0 + i * (bw + bgap)
        d.rect(f"prog{i}", x, by, bw, bh, "#FFFFFF", SW_STROKE, 1.4, rx=6)
        d.block(x + bw / 2, by + bh / 2, items, container=f"prog{i}")
    bus_y = 268
    d.path([(640, gy + gh), (640, bus_y)], LINE_NAVY, 1.8, end=False)
    d.path([(centers[0], bus_y), (centers[3], bus_y)], LINE_NAVY, 1.8, end=False)
    for c in centers:
        d.path([(c, bus_y), (c, by)], LINE_NAVY, 1.8)
    for c in (640, centers[1], centers[2]):
        d.dot(c, bus_y, LINE_NAVY)

    # ---- panel 2: storage ----
    P2Y, P2H = 482, 168
    d.rect("panel2", MX0, P2Y, MX1 - MX0, P2H, PANEL_FILL, NAVY, 1.8, rx=12, container=True)
    d.text(MX0 + 24, P2Y + 30, "資料儲存", 19, 700, NAVY, "start", container="panel2")
    cy_, ch, cry = 530, 100, 12
    for i, (x, items) in enumerate([
        (380, [("data/", 16, 700, TEXT), ("加密日檔・歷史", 15, 400, TEXT2)]),
        (660, [("SQLite 資料庫", 16, 700, TEXT), ("保留 90 天", 15, 400, TEXT2)]),
    ]):
        d.cylinder(f"cyl{i}", x, cy_, 240, ch, cry)
        d.block(x + 120, cy_ + cry + ch / 2, items, container=f"cyl{i}")

    # two-way read/write
    d.path([(640, P1Y + P1H), (640, P2Y)], LINE_NAVY, 1.8, start=True, end=True)
    d.text(654, (P1Y + P1H + P2Y) / 2, "讀寫", 15, 500, NAVY, "start")

    # ---- orange: user's PC re-trigger ----
    ox, ow, oy, oh = centers[0] - 82, 164, 404, 56
    d.rect("pc", ox, oy, ow, oh, ORANGE_FILL, ORANGE, 1.5, rx=8)
    d.block(centers[0], oy + oh / 2, [("你的電腦", 15, 700, ORANGE_TEXT),
                                      ("工作排程器補觸發", 14, 500, ORANGE_TEXT)], container="pc")
    d.path([(centers[0], oy), (centers[0], by + bh)], ORANGE, 1.8, dash="5 4")

    # ---- sources ----
    srcs = ["富邦 DJ（82 個分點）", "證交所 TWSE", "櫃買中心 TPEx", "期交所 TAIFEX",
            "公開資訊觀測站 MOPS", "集保 TDCC（每週）", "attstock（處置股）"]
    sh_, sy0, sstep = 40, 166, 74
    bus_x = 300
    scs = []
    for i, s in enumerate(srcs):
        y = sy0 + i * sstep
        d.rect(f"src{i}", LX0, y, LX1 - LX0, sh_, EXT_FILL, EXT_STROKE, 1.2, rx=6, dash="4 3")
        d.text((LX0 + LX1) / 2, y + sh_ / 2, s, 15, 500, "#3A3F45", container=f"src{i}")
        cy = y + sh_ / 2
        scs.append(cy)
        d.path([(LX1, cy), (bus_x, cy)], LINE_NAVY, 1.8, end=False)
    d.path([(bus_x, scs[0]), (bus_x, scs[-1])], LINE_NAVY, 1.8, end=False)
    for cy in scs[1:-1]:
        d.dot(bus_x, cy, LINE_NAVY)
    in_y = (scs[1] + scs[2]) / 2
    d.path([(bus_x, in_y), (MX0, in_y)], LINE_NAVY, 1.8)
    d.dot(bus_x, in_y, LINE_NAVY)

    # ---- outputs ----
    outs = ["Excel 月檔", "每日 Email（附 Excel）", "GitHub Pages 網站", "GitHub Issue 告警"]
    out_y = by + bh / 2
    oh2, ostep = 44, 66
    ocs = [out_y + (i - 1.5) * ostep for i in range(4)]
    rbus = 975
    d.path([(MX1, out_y), (rbus, out_y)], LINE_NAVY, 1.8, end=False)
    d.path([(rbus, ocs[0]), (rbus, ocs[-1])], LINE_NAVY, 1.8, end=False)
    d.dot(rbus, out_y, LINE_NAVY)
    for i, (o, cy) in enumerate(zip(outs, ocs)):
        d.rect(f"out{i}", RX0, cy - oh2 / 2, RX1 - RX0, oh2, "#FFFFFF", NAVY, 1.6, rx=6)
        d.text((RX0 + RX1) / 2, cy, o, 15, 700, TEXT, container=f"out{i}")
        d.path([(rbus, cy), (RX0, cy)], LINE_NAVY, 1.8)
        if 0 < i < 3:
            d.dot(rbus, cy, LINE_NAVY)

    legend(d, 40, 706, [
        ("rect", PANEL_FILL, NAVY, None, "雲端"),
        ("rect", "#FFFFFF", SW_STROKE, None, "程式"),
        ("rect", EXT_FILL, EXT_STROKE, "3 2", "外部"),
        ("cyl", "儲存"),
        ("arrow", LINE_NAVY, None, "平時"),
        ("arrow", ORANGE, "4 3", "補觸發"),
    ])
    footer(d, 748)
    return d


# =====================================================================
# B. one trading day (cards + bands)
# =====================================================================
def build_flow_day():
    W, H = 1280, 690
    d = Dia("flow_day", W, H)
    header(d, "系統運作圖", "一個交易日的排程（每一輪都先過交易日開關）")
    cards = [
        ("1", "盤前", "08:50", [["盤前簡報"], ["GitHub 排程常延遲，", "實際多在下午才到"]]),
        ("2", "收盤", "13:30", [["結算追蹤"], ["盤中試算 13:35"]]),
        ("3", "盤後", "14:30–21:30", [["週報（本週最後交易日）"], ["結算追蹤 17:30、21:30"]]),
        ("4", "晚間", "21:17", [["每日籌碼：抓 82 個分點"], ["產 Excel、寄 Email"],
                               ["兜底 22:37、23:47"]]),
        ("5", "深夜～隔日", "22:30–12:00", [["融資晚間輪"],
                                         ["隔日 08:00、09:00、", "12:00 補跑：", "前一日未驗證才做"]]),
    ]
    cw, cgap, cy0, chh, hh = 212, 35, 116, 210, 74
    r = 8
    for i, (num, title, tm, bullets) in enumerate(cards):
        x = 40 + i * (cw + cgap)
        nm = f"card{i}"
        d.rect(nm, x, cy0, cw, chh, CARD_BODY, None, rx=r)
        hp = (f"M{x},{cy0 + hh} V{cy0 + r} A{r},{r} 0 0 1 {x + r},{cy0} H{x + cw - r} "
              f"A{r},{r} 0 0 1 {x + cw},{cy0 + r} V{cy0 + hh} Z")
        d.raw(f'<path d="{hp}" fill="{CARD_HDR}"/>')
        d.raw(f'<rect x="{x}" y="{cy0}" width="{cw}" height="{chh}" rx="{r}" fill="none" '
              f'stroke="{CARD_STROKE}" stroke-width="1.6"/>')
        d.raw(f'<circle cx="{x + 27}" cy="{cy0 + 28}" r="12.5" fill="#FFFFFF"/>')
        d.text(x + 27, cy0 + 28, num, 15, 700, CARD_HDR, container=nm)
        d.text(x + 47, cy0 + 28, title, 19, 700, "#FFFFFF", "start", container=nm)
        d.text(x + 15, cy0 + 56, tm, 14, 400, "#DCE7F5", "start", container=nm)
        ly = cy0 + hh + 24
        for b in bullets:
            d.raw(f'<circle cx="{x + 21}" cy="{ly}" r="2.6" fill="{TEXT}"/>')
            for ln in b:
                d.text(x + 32, ly, ln, 15, 400, TEXT, "start", container=nm)
                ly += 26
        if i < 4:
            ay = cy0 + hh + 52
            d.path([(x + cw + 7, ay), (x + cw + cgap - 7, ay)], NAVY, 2.6, hl=7, hw=6,
                   chevron=True)

    def band(nm, y, h, fill, stroke, dash, title, sub, tcolor, pills, pstroke, ptext, pfill):
        d.rect(nm, 40, y, 1200, h, fill, stroke, 1.6, rx=8, dash=dash, container=True)
        cy = y + h / 2
        if sub:
            d.text(64, cy - 14, title, 18, 700, tcolor, "start", container=nm)
            d.text(64, cy + 14, sub, 14, 400, tcolor, "start", container=nm)
        else:
            d.text(64, cy, title, 18, 700, tcolor, "start", container=nm)
        x = 240
        for j, p in enumerate(pills):
            w = tw(p, 15, 500) + 40
            d.pill(f"{nm}_p{j}", x, cy - 19, w, 38, pfill, pstroke, 1.3)
            d.text(x + w / 2, cy, p, 15, 500, ptext, container=f"{nm}_p{j}")
            x += w + 12

    band("b_safe", 350, 90, RED_FILL, RED, None, "安全機制", "全程有效", RED_TEXT,
         ["非交易日整輪跳過", "頁面身分檢查", "失敗分點同輪補抓", "錯誤天數排除清單", "同時只跑一輪"],
         "#D07A70", RED_TEXT, "#FFFAF9")
    band("b_ops", 460, 70, GB_FILL, GB_STROKE, None, "營運支援", None, GB_TEXT,
         ["每日健康檢查", "每週稽核", "資安檢查", "集保週資料（週六）", "每次推送自動測試", "每晚來源逐列比對"],
         "#6B7178", "#42464C", "#FFFFFF")
    band("b_next", 550, 70, "#FFFFFF", DASH_STROKE, "6 4", "下一步", None, DASH_TEXT,
         ["主力貢獻度修復", "分點勝率研究"],
         "#A9ADB2", DASH_TEXT, "#FFFFFF")
    footer(d, 656)
    return d


# =====================================================================
# C. daily-full crawl flow (vertical, phase bands)
# =====================================================================
def build_flow_crawl():
    W, H = 960, 1692
    d = Dia("flow_crawl", W, H)
    header(d, "每日籌碼流程圖", "daily-full 一輪從開關到寄信")
    legend(d, 40, 124, [
        ("rect", PROC_FILL, PROC_STROKE, None, "步驟"),
        ("diamond", "判斷"),
        ("pill", GREEN_FILL, GREEN, "正常結束"),
        ("pill", GP_FILL, GP_STROKE, "不輸出"),
    ])
    CX = 460
    BW, BH = 320, 44
    DW, DH = 230, 90
    RX, RW = 660, 236
    RC = RX + RW / 2
    NX, NW = 62, 222
    L = FLOW_LINE

    def band(i, y, h, title, sub):
        nm = f"band{i}"
        d.rect(nm, 40, y, 880, h, BANDS[i], None, rx=10, container=True)
        d.text(62, y + 26, title, 17, 700, NAVY, "start", container=nm)
        if sub:
            d.text(62, y + 50, sub, 14, 400, SUB, "start", container=nm)

    def box(nm, cy, lines, x=None, w=BW, h=BH):
        x = CX - w / 2 if x is None else x
        d.rect(nm, x, cy - h / 2, w, h, PROC_FILL, PROC_STROKE, 1.5, rx=6)
        d.block(x + w / 2, cy, [(t, 15, 500, TEXT) for t in lines], container=nm)

    def endpill(nm, cy, lines, fill, stroke, tcol, x, w, h):
        d.pill(nm, x, cy - h / 2, w, h, fill, stroke, 1.6)
        d.block(x + w / 2, cy, [(t, 15, 700, tcol) for t in lines], container=nm)

    def dia(nm, cy, lines):
        d.diamond(nm, CX, cy, DW, DH)
        d.block(CX, cy, [(t, 15, 500, TEXT) for t in lines], container=nm, lead=1.35)

    def note(nm, x, cy, lines, w=NW):
        h = len(lines) * 20 + 24
        d.rect(nm, x, cy - h / 2, w, h, "#FFFFFF", NOTE_STROKE, 1.2, rx=6, dash="4 3")
        d.block(x + w / 2, cy, [(t, 14, 400, NOTE_TEXT) for t in lines], container=nm,
                lead=1.43)

    def down(y1, y2, x=CX):
        d.path([(x, y1), (x, y2)], L, 1.6)

    def yes_label(y_from):
        d.text(CX + 9, y_from + 13, "是", 14, 500, L, "start")

    def no_label(x_from, cy):
        d.text(x_from + 24, cy - 13, "否", 14, 500, L, "middle")

    # ① gate
    T1 = 150
    band(0, T1, 198, "① 開關", "排程觸發時")
    d.pill("start", CX - 75, T1 + 20, 150, 40, START_FILL, None)
    d.text(CX, T1 + 40, "開始", 16, 700, "#FFFFFF", container="start")
    d1 = T1 + 131
    down(T1 + 60, d1 - DH / 2)
    dia("d1", d1, ["今天是", "交易日？"])
    endpill("skip", d1, ["整輪跳過", "（不輸出）"], GP_FILL, GP_STROKE, GP_TEXT, RX + 18, 200, 52)
    d.path([(CX + DW / 2, d1), (RX + 18, d1)], L, 1.6)
    no_label(CX + DW / 2, d1)

    # ② crawl
    T2 = 360
    band(1, T2, 284, "② 抓取", "21:17 起，約 20–40 分")
    a_cy = T2 + 44
    down(d1 + DH / 2, a_cy - BH / 2)
    yes_label(d1 + DH / 2)
    box("a", a_cy, ["抓 82 個分點（金額頁＋張數頁）"])
    d2 = T2 + 137
    down(a_cy + BH / 2, d2 - DH / 2)
    dia("d2", d2, ["頁面是要的", "分點？"])
    box("r1", d2, ["重試，仍錯記為失敗"], x=RX, w=RW)
    d.path([(CX + DW / 2, d2), (RX, d2)], L, 1.6)
    no_label(CX + DW / 2, d2)
    b_cy = T2 + 234
    down(d2 + DH / 2, b_cy - BH / 2)
    yes_label(d2 + DH / 2)
    box("b", b_cy, ["行情・三大法人（TWSE / TPEx）"])
    box("r2", b_cy, ["全部抓完後，", "同輪補抓失敗分點"], x=RX, w=RW, h=60)
    down(d2 + BH / 2, b_cy - 30, x=RC)
    d.path([(RX, b_cy), (CX + BW / 2, b_cy)], L, 1.6)
    note("n1", NX, d2, ["頁面回傳的分點代號", "要跟送出的一致", "防 9A9g / 9A9G 大小寫混淆"])
    d.path([(NX + NW, d2), (CX - DW / 2, d2)], NOTE_LINE, 1.2, end=False, dash="4 3")

    # ③ process
    T3 = 656
    band(2, T3, 296, "③ 加工", None)
    steps3 = ["注入收盤價、估算張數", "彙總・共識・漲停", "融資・處置預測・產業・集保",
              "個股歷史（大盤缺口自我修復）"]
    prev = b_cy + BH / 2
    cys3 = []
    for i, s in enumerate(steps3):
        cy = T3 + 44 + i * 70
        down(prev, cy - BH / 2)
        box(f"c{i}", cy, [s])
        prev = cy + BH / 2
        cys3.append(cy)
    note("n2", RX, cys3[1], ["排除清單", "已知抓錯的 52 個分點日", "讀取時排除"], w=RW)
    d.path([(CX + BW / 2, cys3[1]), (RX, cys3[1])], NOTE_LINE, 1.2, end=False, dash="4 3")

    # ④ output
    T4 = 964
    band(3, T4, 654, "④ 產出", None)
    steps4 = ["Excel 第一次產表＋自動稽核", "加密存檔", "抓 attstock 處置股", "Excel 最終版＋信件文字檔"]
    for i, s in enumerate(steps4):
        cy = T4 + 44 + i * 70
        down(prev, cy - BH / 2)
        box(f"e{i}", cy, [s])
        prev = cy + BH / 2
    e5 = T4 + 332
    down(prev, e5 - 30)
    box("e5", e5, ["來源逐列比對", "Excel 每列 vs 富邦原始頁"], h=60)
    note("n3", RX, e5, ["不符 → 信件第一行警示", "＋開 GitHub Issue"], w=RW)
    d.path([(CX + BW / 2, e5), (RX, e5)], NOTE_LINE, 1.2, end=False, dash="4 3")
    prev = e5 + 30
    d4 = T4 + 433
    down(prev, d4 - DH / 2)
    dia("d4", d4, ["資料有", "變動？"])
    endpill("nomail", d4, ["不寄信", "（兜底排程已跑過）"], GP_FILL, GP_STROKE, GP_TEXT, RX, RW, 56)
    d.path([(CX + DW / 2, d4), (RX, d4)], L, 1.6)
    no_label(CX + DW / 2, d4)
    f1 = T4 + 530
    down(d4 + DH / 2, f1 - BH / 2)
    yes_label(d4 + DH / 2)
    box("f1", f1, ["commit 上雲"])
    f2 = T4 + 606
    down(f1 + BH / 2, f2 - 28)
    endpill("mail", f2, ["寄每日 Email", "（第一行＝比對結果，附 Excel）"], GREEN_FILL, GREEN,
            GREEN_TEXT, CX - BW / 2, BW, 56)
    footer(d, 1656)
    return d


# =====================================================================
# D. program architecture (two panels)
# =====================================================================
def build_architecture():
    W, H = 1280, 836
    d = Dia("architecture", W, H)
    header(d, "程式架構圖", "程式怎麼分工、目前狀態")
    legend(d, 40, 124, [
        ("rect", PROC_FILL, PROC_STROKE, None, "已上線"),
                ("rect", PAUSE_FILL, PAUSE_STROKE, "4 3", "暫停中"),
    ])
    L = FLOW_LINE
    # left panel
    d.rect("lp", 40, 150, 760, 616, "#F4F8FB", None, rx=12, container=True)
    d.text(64, 182, "雲端每天跑的程式", 19, 700, NAVY, "start", container="lp")
    CX = 420
    d.rect("sched", CX - 200, 208, 400, 46, PROC_FILL, PROC_STROKE, 1.5, rx=6)
    d.text(CX, 231, "排程：16 支 workflow＋交易日開關", 16, 700, TEXT, container="sched")
    lc, rc = 234, 606
    d.path([(CX, 254), (CX, 276)], L, 1.6, end=False)
    d.path([(lc, 276), (rc, 276)], L, 1.6, end=False)
    d.dot(CX, 276, L, 3.2)
    d.path([(lc, 276), (lc, 300)], L, 1.6)
    d.path([(rc, 276), (rc, 300)], L, 1.6)
    d.rect("crawler", 64, 300, 340, 64, PROC_FILL, PROC_STROKE, 1.5, rx=6)
    d.block(234, 332, [("crawler.py 主流程", 16, 700, TEXT),
                       ("full / margin_only", 14, 400, TEXT2)], container="crawler")
    d.rect("scripts", 436, 300, 340, 64, PROC_FILL, PROC_STROKE, 1.5, rx=6)
    d.block(606, 332, [("scripts/ 每日腳本", 16, 700, TEXT),
                       ("滾動回測、處置股、信件文字", 14, 400, TEXT2)], container="scripts")
    d.path([(lc, 364), (lc, 392)], L, 1.6)
    d.path([(rc, 364), (rc, 392)], L, 1.6)
    d.rect("src", 64, 392, 712, 236, "#FFFFFF", "#B9C8DA", 1.2, rx=10, container=True)
    d.text(84, 418, "src/ 模組", 16, 700, NAVY, "start", container="src")
    mods = [
        ("fetchers", ["抓取"]),
        ("pipelines", ["抓取層・彙總", "加密・資料庫"]),
        ("analyzers", ["主力統計・訊號"]),
        ("exports", ["Excel 報表"]),
        ("alerts", ["告警"]),
        ("audit", ["自動稽核・來源比對"]),
        ("core", ["分點登錄・交易日曆", "排除清單"]),
        ("backtest", ["回測（多為手動）"]),
    ]
    mw, mh, mg = 159, 80, 12
    for k, (nm, desc) in enumerate(mods):
        r_, c_ = divmod(k, 4)
        x = 84 + c_ * (mw + mg)
        y = 438 + r_ * (mh + mg)
        d.rect(f"m_{nm}", x, y, mw, mh, PROC_FILL, PROC_STROKE, 1.3, rx=6)
        d.block(x + mw / 2, y + mh / 2, [(nm, 15, 700, TEXT)] + [(t, 14, 400, TEXT2) for t in desc],
                container=f"m_{nm}", lead=1.36)
    d.path([(CX, 628), (CX, 654)], L, 1.6)
    d.cylinder("data", CX - 150, 654, 300, 88, 11, fill=PROC_FILL, top="#E1EBF7", stroke=PROC_STROKE)
    d.block(CX, 654 + 11 + 44, [("data/", 16, 700, TEXT), ("加密日檔・歷史・報表", 14, 400, TEXT2)],
            container="data")

    # right panel
    d.rect("rp", 820, 150, 420, 616, "#F4F9F5", None, rx=12, container=True)
    d.text(844, 182, "測試與稽核", 19, 700, NAVY, "start", container="rp")
    RXX, RWW = 844, 372
    items = [
        ("live1", 208, 64, None, "tests/run_all.py 61 支測試", "每次推送雲端自動跑"),
        ("live2", 300, 64, None, "來源逐列比對稽核", "每晚對富邦原始頁"),
        ("pause", 392, 86, "暫停中", "分點勝率研究 Phase 1", "Task 1.1 在分支上"),
    ]
    for nm, y, h, tag, title, detail in items:
        if nm.startswith("live"):
            d.rect(nm, RXX, y, RWW, h, PROC_FILL, PROC_STROKE, 1.5, rx=6)
            blk = [(title, 16, 700, TEXT), (detail, 14, 400, TEXT2)]
        elif nm.startswith("todo"):
            d.rect(nm, RXX, y, RWW, h, ORANGE_FILL, ORANGE, 1.6, rx=6, dash="5 4")
            blk = [(tag, 14, 700, ORANGE), (title, 16, 700, ORANGE_TEXT), (detail, 14, 400, ORANGE_TEXT)]
        else:
            d.rect(nm, RXX, y, RWW, h, PAUSE_FILL, PAUSE_STROKE, 1.5, rx=6, dash="5 4")
            blk = [(tag, 14, 700, PAUSE_STROKE), (title, 16, 700, PAUSE_TEXT), (detail, 14, 400, PAUSE_TEXT)]
        d.block(RXX + RWW / 2, y + h / 2, blk, container=nm)
    footer(d, 806)
    return d


# =====================================================================
# checks
# =====================================================================
def run_checks(d, meas):
    iss = []
    for t in d.texts:
        m = meas.get(t["id"])
        if m:
            t["left"], t["w"] = m[0], m[1]
        else:
            iss.append(f"no chrome measurement for {t['id']} {t['t']}")
    leaves = [s for s in d.shapes.values() if not s.container]
    conts = [s for s in d.shapes.values() if s.container]
    M = 16
    for s in d.shapes.values():
        if s.x < M or s.y < M or s.x + s.w > d.W - M or s.y + s.h > d.H - M:
            iss.append(f"shape near/over canvas edge: {s.name}")
    for t in d.texts:
        if t["left"] < M or t["left"] + t["w"] > d.W - M or t["top"] < M or t["bot"] > d.H - M:
            iss.append(f"text near/over canvas edge: {t['t']}")

    def bb_overlap(a, b, gap):
        return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])

    def sb(s):
        return (s.x, s.y, s.x + s.w, s.y + s.h)

    def grid(b, step=2.0):
        x0, y0, x1, y1 = b
        nx = max(2, int((x1 - x0) / step) + 1)
        ny = max(2, int((y1 - y0) / step) + 1)
        for i in range(nx):
            for j in range(ny):
                yield x0 + (x1 - x0) * i / (nx - 1), y0 + (y1 - y0) * j / (ny - 1)

    def hits(shape, b):
        if shape.kind == "diamond":
            if not bb_overlap(sb(shape), b, 0):
                return False
            return any(shape.contains(px, py) for px, py in grid(b))
        return bb_overlap(sb(shape), b, 0)

    # leaf-leaf
    for i, a in enumerate(leaves):
        for b in leaves[i + 1:]:
            ea = (a.x - 6, a.y - 6, a.x + a.w + 6, a.y + a.h + 6)
            if a.kind == "diamond" or b.kind == "diamond":
                dmd, oth = (a, b) if a.kind == "diamond" else (b, a)
                ob = (oth.x - 6, oth.y - 6, oth.x + oth.w + 6, oth.y + oth.h + 6)
                if hits(dmd, ob):
                    iss.append(f"shapes too close/overlap: {a.name} / {b.name}")
            elif bb_overlap(ea, sb(b), 0):
                iss.append(f"shapes too close/overlap: {a.name} / {b.name}")
    # leaf vs container
    for c in conts:
        for a in leaves + [x for x in conts if x is not c]:
            if bb_overlap(sb(a), sb(c), 0):
                inside = (a.x >= c.x + 8 and a.y >= c.y + 8 and a.x + a.w <= c.x + c.w - 8
                          and a.y + a.h <= c.y + c.h - 8)
                enclosing = (c.x >= a.x and c.y >= a.y and c.x + c.w <= a.x + a.w
                             and c.y + c.h <= a.y + a.h)
                if not inside and not enclosing:
                    iss.append(f"shape straddles container: {a.name} in {c.name}")
    # text containment / collisions
    for t in d.texts:
        tb = (t["left"], t["top"], t["left"] + t["w"], t["bot"])
        cn = t["container"]
        if cn:
            c = d.shapes[cn]
            if c.kind == "diamond":
                cx, cy = c.x + c.w / 2, c.y + c.h / 2
                for px, py in [(tb[0] - 3, tb[1] - 2), (tb[2] + 3, tb[1] - 2),
                               (tb[0] - 3, tb[3] + 2), (tb[2] + 3, tb[3] + 2)]:
                    if abs(px - cx) / (c.w / 2) + abs(py - cy) / (c.h / 2) > 1.0:
                        iss.append(f"text overflows diamond {cn}: {t['t']}")
                        break
            else:
                padx = 12 if c.kind == "pill" else 6
                top_lim = c.y + 2 * c.ry if c.kind == "cyl" else c.y
                lp = tb[0] - c.x
                rp = c.x + c.w - tb[2]
                if lp < padx or rp < padx or tb[1] - top_lim < 3 or c.y + c.h - tb[3] < 3:
                    iss.append(f"text tight/overflow in {cn}: '{t['t']}' l={lp:.1f} r={rp:.1f} "
                               f"t={tb[1] - top_lim:.1f} b={c.y + c.h - tb[3]:.1f}")
        eb = (tb[0] - 2, tb[1] - 2, tb[2] + 2, tb[3] + 2)
        for s in leaves:
            if s.name == cn:
                continue
            if hits(s, eb):
                iss.append(f"text touches shape {s.name}: {t['t']}")
    for i, a in enumerate(d.texts):
        for b in d.texts[i + 1:]:
            if a.get("group") and a.get("group") == b.get("group"):
                continue
            ab = (a["left"], a["top"], a["left"] + a["w"], a["bot"])
            bb = (b["left"], b["top"], b["left"] + b["w"], b["bot"])
            if bb_overlap(ab, bb, 1):
                iss.append(f"texts overlap: {a['t']} / {b['t']}")
    # segments vs shapes / texts
    for (x1, y1, x2, y2) in d.segs:
        n = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        pts = [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) for k in range(n + 1)]
        for s in leaves:
            if any(s.contains(px, py, 1.0) for px, py in pts):
                iss.append(f"line passes through {s.name}: {(x1, y1, x2, y2)}")
        for t in d.texts:
            tb = (t["left"] - 2, t["top"] - 2, t["left"] + t["w"] + 2, t["bot"] + 2)
            if any(tb[0] < px < tb[2] and tb[1] < py < tb[3] for px, py in pts):
                iss.append(f"line touches text '{t['t']}': {(x1, y1, x2, y2)}")
    # crossings
    crosses = 0
    segs = d.segs
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            ah = abs(a[1] - a[3]) < 1e-6
            bh = abs(b[1] - b[3]) < 1e-6
            if ah == bh:
                continue
            hseg, vseg = (a, b) if ah else (b, a)
            hy = hseg[1]
            vx = vseg[0]
            hx0, hx1 = sorted((hseg[0], hseg[2]))
            vy0, vy1 = sorted((vseg[1], vseg[3]))
            if hx0 + 1 < vx < hx1 - 1 and vy0 + 1 < hy < vy1 - 1:
                crosses += 1
                iss.append(f"line crossing at ({vx:.0f},{hy:.0f})")
    return iss, crosses


# =====================================================================
# render
# =====================================================================
MEASURE_JS = """
<script>
(async function(){
  await document.fonts.ready;
  const r = {};
  document.querySelectorAll('svg text[id]').forEach(t => { const b = t.getBBox(); r[t.id] = [b.x, b.width]; });
  const faces = [...document.fonts].filter(f => f.family.replace(/["']/g,'') === 'Noto Sans TC');
  r.__fonts = {faces: faces.length, loaded: faces.filter(f => f.status === 'loaded').length,
               check700: document.fonts.check('700 20px "Noto Sans TC"', '\\u7cfb\\u7d71'),
               check400: document.fonts.check('400 20px "Noto Sans TC"', '\\u7cfb\\u7d71')};
  document.getElementById('out').textContent = JSON.stringify(r);
})();
</script>
"""


def html_page(d, with_measure):
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<link rel='preconnect' href='https://fonts.googleapis.com'>"
            "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
            f"<link rel='stylesheet' href='{GFONT}'>"
            "<style>html,body{margin:0;padding:0;background:#fff;overflow:hidden}"
            "svg{display:block}</style></head><body>"
            + d.svg(standalone=False)
            + ("<pre id='out' hidden></pre>" + MEASURE_JS if with_measure else "")
            + "</body></html>")


def file_uri(p):
    return "file:///" + p.replace("\\", "/")


def render(d):
    svg_p = os.path.join(BASE, f"{d.key}.svg")
    with open(svg_p, "w", encoding="utf-8") as f:
        f.write(d.svg(standalone=True))
    mh = os.path.join(BASE, f"_{d.key}_measure.html")
    rh = os.path.join(BASE, f"_{d.key}.html")
    with open(mh, "w", encoding="utf-8") as f:
        f.write(html_page(d, True))
    with open(rh, "w", encoding="utf-8") as f:
        f.write(html_page(d, False))
    common = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
              f"--user-data-dir={UDD}", "--no-first-run", "--no-default-browser-check",
              "--virtual-time-budget=15000"]
    out = subprocess.run(common + ["--dump-dom", file_uri(mh)], capture_output=True,
                         timeout=120).stdout.decode("utf-8", "replace")
    m = re.search(r"<pre id=\"out\" hidden=\"\">(.*?)</pre>", out, re.S)
    meas = json.loads(html.unescape(m.group(1))) if m and m.group(1).strip() else {}
    png = os.path.join(BASE, f"{d.key}.png")
    if os.path.exists(png):
        os.remove(png)
    subprocess.run(common + ["--force-device-scale-factor=2", f"--window-size={d.W},{d.H}",
                             f"--screenshot={png}", file_uri(rh)], capture_output=True, timeout=120)
    size = Image.open(png).size if os.path.exists(png) else None
    return meas, size


BUILDERS = {
    "system": build_system,
    "flow_day": build_flow_day,
    "flow_crawl": build_flow_crawl,
    "architecture": build_architecture,
}

if __name__ == "__main__":
    keys = sys.argv[1:] or list(BUILDERS)
    for k in keys:
        d = BUILDERS[k]()
        meas, size = render(d)
        iss, crosses = run_checks(d, meas)
        print(f"== {k}: svg {d.W}x{d.H}  png {size}  fonts {meas.get('__fonts')}  "
              f"crossings={crosses}  issues={len(iss)}")
        for s in iss:
            print("   -", s)
