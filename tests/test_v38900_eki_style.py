# v3.89.0 駅 EKI site style: line colours, contrast, station codes, sparklines - offline
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-10: style B (heavy sans, condensed big numbers, full line-colour bands,
S01 / P02 station codes) plus C's 20-day sparklines; colour tells the blocks apart."""

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def lum(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


h = (ROOT / 'index.html').read_text(encoding='utf-8')
css = h[h.index('/* v3.89.0 駅 EKI style'):h.index('</style>', h.index('/* v3.89.0 駅 EKI style'))]
root = re.search(r':root\{(--b-stocks[^}]*)\}', css).group(1)
light = re.search(r':root\[data-theme="light"\]\{(--c-stocks[^}]*)\}', css).group(1)
var = dict(re.findall(r'--([\w-]+):(#[0-9A-Fa-f]{3,6})', root))
var_l = dict(re.findall(r'--([\w-]+):(#[0-9A-Fa-f]{3,6})', light))
CATS = ['stocks', 'players', 'market', 'risk', 'meta']
print("=" * 72)
print("  v3.89.0 駅 EKI 全站風格 (離線)")
print("=" * 72)

print("\n[A] 路線色: 五類、固定意義、看得清楚")
check("五類路線色都有色帶 / 色帶上的字 / 一般文字三種", all(f'b-{c}' in var and f'on-{c}' in var and f'c-{c}' in var for c in CATS))
for c in CATS:
    check(f"{c}: 色帶上的字對比 >= 4.5", contrast(var[f'b-{c}'], var[f'on-{c}']) >= 4.5, round(contrast(var[f'b-{c}'], var[f'on-{c}']), 1))
    check(f"{c}: 文字色在深色底 >= 4.5、淺色底 >= 4.5",
          contrast(var[f'c-{c}'], '#0a0e1a') >= 4.5 and contrast(var_l[f'c-{c}'], '#f5f7fb') >= 4.5,
          (round(contrast(var[f'c-{c}'], '#0a0e1a'), 1), round(contrast(var_l[f'c-{c}'], '#f5f7fb'), 1)))
codes = dict(re.findall(r'\.k-(\w+)\{[^}]*--L:"(\w)"\}', css))
check("站名字母: S 個股 / P 大戶 / M 市場 / R 風險 / C 一般", codes == {'stocks': 'S', 'players': 'P', 'market': 'M', 'risk': 'R', 'meta': 'C'}, codes)
check("紅漲綠跌不被路線色蓋掉 (沒有改 --red / --green)", '--red:' not in css and '--green:' not in css)

print("\n[B] 每頁的區塊: 色帶 + 編號")
check("區塊標題 = 路線色色帶 + 站名編號 (字母 + 頁內序號)",
      'counter-increment:sec' in css and 'content:var(--L) counter(sec,decimal-leading-zero)' in css and 'background:var(--b)!important' in css)
check("每頁重新編號", re.search(r'\.panel\{[^}]*counter-reset:sec', css) is not None)
for pid, cat in [('today3', 'market'), ('overview', 'stocks'), ('masterview', 'players'), ('futures', 'market')]:
    check(f"#panel-{pid} 主線是 {cat}", re.search(rf'#panel-{pid}[,\s][^{{]*\{{--b:var\(--b-{cat}\)', css) is not None
          or re.search(rf'#panel-{pid},[^{{]*\{{--b:var\(--b-{cat}\)', css) is not None)
check("警報區塊是風險 (紫)", '#today3Alerts{--b:var(--b-risk)' in css)
check("窄體數字字型有載入 (Barlow Condensed)", 'family=Barlow+Condensed' in h and "'Barlow Condensed'" in css)
check("已暫停的研究儀表在每頁收起", '#chipTemperature,#smartRetailContrast,#tempHistoryWrap' in css)

print("\n[C] 今日總整理: 編號 + 走勢小圖")
js = h[h.index('function _dsSpark('):h.index('function renderAll() {')]
for L, no in [('S', '01'), ('P', '02'), ('P', '03'), ('R', '04'), ('S', '05'), ('C', '06'), ('M', '07')]:
    check(f"有 {L}{no}", f"'{L}', '{no}'" in js)
check("01 / 02 / 03 有 20 日走勢, 04 沒有 (處置歷史兩個來源對不起來)",
      't.strong, false)' in js and 't.domestic, true)' in js and 't.foreign, true' in js and "n.risk, null, false)" in js)
check("市場四列都有小走勢", all(f't.{x}' in js for x in ('taiex', 'fut_oi', 'margin', 'pc')))
sp = js[js.index('function _dsSpark('):js.index('function renderDailySummary()')]
check("走勢小圖: 不足 2 點不畫、略過空值、淨買賣畫 0 線",
      "if (pts.length < 2) return '';" in sp and "isFinite(p[1])" in sp and 'stroke-dasharray' in sp)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
