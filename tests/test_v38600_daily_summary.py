# v3.86.0 今日總整理 (site first page): builder, script, page wiring, workflow - offline
import sys, pathlib, re, json, os, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

"""Owner 2026-10-09: "登錄後的第一頁，絕對就是當日的總整理…1分鐘讀完" and
"要排除外資大戶，直接獨立列出外資的追蹤大戶就好". Spec: docs/specs/DAILY_SUMMARY_SPEC.md."""
import yaml
from src.analyzers import daily_summary as ds

ROOT = pathlib.Path(__file__).resolve().parent.parent
all_pass = True
BAD = '�'


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


print("=" * 72)
print("  v3.86.0 今日總整理 (離線)")
print("=" * 72)

# A. rule #1 boundaries
print("\n[A] 強籌規則 #1 邊界")
q = ds.qualifies
check("5 天各 6,000 仟 = 3,000 萬 → 符合", q([(1, 6000)] * 5) == 30000)
check("差 1 仟 (29,999) → 不符合", q([(1, 6000)] * 4 + [(1, 5999)]) is None)
check("只出現 4 天 → 不符合", q([(1, 20000)] * 4) is None)
check("買 5 賣 2 (剛好 2.5 倍) → 符合", q([(1, 20000)] * 5 + [(-1, -1000)] * 2) is not None)
check("買 5 賣 3 → 不符合", q([(1, 20000)] * 5 + [(-1, -1000)] * 3) is None)
check("買 6 賣 3 (只有 2 倍) → 不符合", q([(1, 20000)] * 6 + [(-1, -1000)] * 3) is None)
check("回落到高點 80% 剛好 → 符合", q([(1, 10000)] * 5 + [(-1, -10000)]) == 40000)
check("回落到 80% 以下 1 仟 → 不符合", q([(1, 10000)] * 5 + [(-1, -10001)]) is None)
check("ETF / 權證不算 (0050, 03xxxx)", not ds.is_common('0050') and not ds.is_common('030001') and ds.is_common('2330'))


# B. a synthetic 11-day set
def day(i, extra_rows=None):
    def br(code, master, region, rows):
        return {'code': code, 'master': master, 'region': region, 'buys': rows, 'sells': []}
    r2330 = [{'code': '2330', 'name': '台' + BAD + '電', 'net_lot': 10, 'net_amt': 5000}]
    r2317 = [{'code': '2317', 'name': '鴻海', 'net_lot': 10, 'net_amt': 7000}] if i >= 6 else []
    etf = [{'code': '0050', 'name': '元大台灣50', 'net_lot': 99, 'net_amt': 99999}]
    two = [{'code': '3008', 'name': '大立光', 'net_lot': 3, 'net_amt': 9000}]      # only 2 masters: not strong
    return {'date': f'202610{i + 1:02d}', 'data': {
        'crawled_at': f'2026-10-{i + 1:02d}T22:51:28+08:00', 'success': 5, 'failed': 0,
        'futures_data': {'summary': {'foreign_equivalent_net_oi': -800 - 20 * i, 'pc_ratio_oi': 0.9}},
        'margin_market_aggregate': {'margin_amt_change_yi': 10.0 + i, 'margin_amt_balance_yi': 3000},
        'branches': [br('A1', '甲', 'domestic', r2330 + r2317 + etf + two), br('A2', '乙', 'domestic', r2330 + r2317 + two),
                     br('A3', '丙', 'domestic', r2330 + r2317), br('F1', '高盛', 'us', r2330),
                     br('C1', '凱基證券', 'company_total', [{'code': '2454', 'name': '聯發科', 'net_lot': -5, 'net_amt': -4000}])]}}


days = [day(i) for i in range(11)]
sh = {'market': {'20261011': {'index': 20000.0, 'change_pct': 1.0}},
      'stocks': {'2330': {'name': '台' + BAD + '電', 'daily': {'20261011': {'change_pct': 2.5}}}}}
att = {'codes_in_disposal': ['9999'], 'codes_pending_1d': ['2330'], 'fetched_at': '2026-10-11T22:52:00+08:00'}
s = ds.build_summary(days, sh, att, {'2330': '台積電'})
k = s['kpis']
print("\n[B] 合成 11 天: 整頁數字")
check("日期 / 星期 / 爬取時間", (s['date'], s['weekday'], s['crawled_at']) == ('20261011', '日', '22:51'), (s['date'], s['weekday'], s['crawled_at']))
check("強籌 2 檔 (2330 四位, 2317 三位今天才滿 5 天; 3008 只有 2 位不算), 昨 1 檔", (k['strong_count'], k['strong_prev']) == (2, 1), (k['strong_count'], k['strong_prev']))
top = {r['code']: r for r in s['strong_top']}
check("2330 有 4 位大戶 (含外資高盛, 規則 #1 不排外資)", top['2330']['masters'] == 4, top['2330']['masters'])
check("2317 標新進", top['2317']['new'] and not top['2330']['new'])
check("亂碼股名用官方名稱 (台積電)", top['2330']['name'] == '台積電', top['2330']['name'])
check("2330 明日恐處置標記", top['2330']['risk'] == '明日恐處置')
check("本土淨買不含外資: 甲乙丙 (2330 0.15 億 + 2317 0.21 億) + 甲乙 3008 0.18 億 + 凱基證券 −0.04 億 = +0.5 億",
      k['domestic_net_yi'] == 0.5 and k['domestic_masters'] == 4, (k['domestic_net_yi'], k['domestic_masters']))
check("外資另列: 高盛 +0.1 億, 1 家", k['foreign_net_yi'] == 0.1 and [p['master'] for p in s['foreign']] == ['高盛'],
      (k['foreign_net_yi'], s['foreign']))
check("本土前 5 沒有外資", all(p['master'] != '高盛' for p in s['domestic_top']))
check("淨賣的大戶顯示賣最多的股票 (凱基證券 → 聯發科)",
      [p['best_name'] for p in s['domestic_top'] if p['master'] == '凱基證券'] == ['聯發科'])
check("ETF 0050 不進任何數字", '0050' not in json.dumps(s, ensure_ascii=False))
check("外資台指期淨空單 1,000 口, 比昨天增加 20 口", (k['fut_foreign_oi'], k['fut_foreign_oi_chg']) == (-1000, -20))
tags = [c['tag'] for c in s['changes']]
check("今天變了什麼: 新進 1、強籌∩風險、期貨", tags[:1] == ['新進強籌 1'] and '強籌∩風險' in tags and '期貨' in tags, tags)
check("4 句重點, 第 1 句是強籌 **2** 檔", len(s['sentences']) == 4 and s['sentences'][0].startswith('**2**'), s['sentences'][0][:20])
check("第 2 句含外資另列; 外資只有買時寫「買最多」", '外資 1 家合計' in s['sentences'][1] and '買最多 高盛' in s['sentences'][1]
      and '賣最多' not in s['sentences'][1], s['sentences'][1])
sells = [day(i) for i in range(11)]
for d in sells:
    for b in d['data']['branches']:
        for r in b['buys']:
            r['net_lot'], r['net_amt'] = -abs(r['net_lot']), -abs(r['net_amt'])
s2_all = ds.build_summary(sells)
s2 = s2_all['sentences'][1]
check("全部淨賣時不寫「最大買方」, 外資寫「賣最多」", '最大買方' not in s2 and '沒有大戶淨買' in s2 and '賣最多 高盛' in s2, s2)
check("全部淨賣: 大標題寫外資賣超, 說明句寫賣最多", s2_all['headline'].endswith('外資券商合計賣超 0.1 億')
      and '賣最多' in s2_all['notes']['domestic'] and '賣最多 高盛' in s2_all['notes']['foreign'], (s2_all['headline'], s2_all['notes']))
check("大標題: 強籌最集中兩檔 + 外資券商買賣超", s['headline'] == '台積電、鴻海被最多大戶同時布局；外資券商合計買超 0.1 億', s['headline'])
check("說明句: 強籌 / 本土 / 外資 / 風險", s['notes'] == {'strong': '昨 1・新進 1', 'domestic': '4 位合計・買最多 甲 +0.2',
      'foreign': '1 家合計・買最多 高盛 +0.1', 'risk': '台積電（處置中 1）'}, s['notes'])
check("處置雷達: 明日恐處置 2330 台積電 (強籌 4 位)",
      s['risk']['pending'] == [{'code': '2330', 'name': '台積電', 'strong_masters': 4}] and s['risk']['in_disposal'] == 1)
tr = s['trends']
check("20 日走勢: 11 天資料就給 11 點, 日期對齊", len(tr['dates']) == 11 and tr['dates'][-1] == '20261011'
      and all(len(tr[x]) == 11 for x in ('strong', 'domestic', 'foreign', 'taiex', 'fut_oi', 'margin', 'pc')))
check("走勢最後一點 = 今天的大數字", tr['strong'][-1] == k['strong_count'] and tr['strong'][-2] == k['strong_prev']
      and tr['domestic'][-1] == k['domestic_net_yi'] and tr['foreign'][-1] == k['foreign_net_yi'] and tr['fut_oi'][-1] == k['fut_foreign_oi'])
check("強籌走勢每天用自己的 10 日窗 (第 5 天 5 x 500 萬未滿 3,000 萬 → 0, 第 6 天起 1)",
      tr['strong'] == [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2], tr['strong'])
check("本土走勢: 2317 進場前 +0.3、之後 +0.5 億", tr['domestic'][:6] == [0.3] * 6 and tr['domestic'][6:] == [0.5] * 5, tr['domestic'])
gap = [day(i) for i in range(11)]
gap[3]['data']['futures_data']['summary'] = {'foreign_equivalent_net_oi': 0, 'pc_ratio_oi': 0}
tg = ds.build_summary(gap)['trends']
check("期貨沒抓到那天 (存成 0) 在走勢裡是空格, 不是 0 (20260917 實例)", tg['fut_oi'][3] is None and tg['pc'][3] is None
      and tg['fut_oi'][4] == -880, (tg['fut_oi'][2:5], tg['pc'][2:5]))
check("完整清單: 強籌全部 / 本土大戶全部", [r['code'] for r in s['strong_all']] == ['2330', '2317']
      and len(s['domestic_all']) == 4 and s['strong_all'][0]['who'][:1] and len(s['strong_all'][0]['who']) == 3, s['strong_all'][0].get('who'))
check("只有 1 天也能產生 (不當機)", ds.build_summary(days[:1])['kpis']['strong_prev'] == 0)

# C. the script: encrypted envelope, round trip, unchanged night is not rewritten
print("\n[C] 產生腳本: 加密來回 + 沒變不重寫")
sys.path.insert(0, str(ROOT / 'scripts'))
import build_daily_summary as bds
from src.pipelines.crawler_output import encrypt_data, decrypt_data
PW = 'test-only-password'
with tempfile.TemporaryDirectory() as td:
    dd = pathlib.Path(td)
    (dd / 'archive').mkdir()
    for i, d in enumerate(days):
        env = {'encrypted': True, 'iterations': 1000, 'data': encrypt_data(json.dumps(d['data'], ensure_ascii=False), PW, iterations=1000)}
        (dd / ('archive' if i < 6 else '.') / f"{d['date']}.json").write_text(json.dumps(env), encoding='utf-8')
    (dd / 'stock_history.json').write_text(json.dumps(sh, ensure_ascii=False), encoding='utf-8')
    (dd / 'disposal_attstock.json').write_text(json.dumps(att), encoding='utf-8')
    (dd / 'stock_categories.json').write_text(json.dumps({'classifications': {'2330': {'name': '台積電'}}}, ensure_ascii=False), encoding='utf-8')
    os.environ['CHIP_RADAR_PASSWORD'] = PW
    rc = bds.main(['--data-dir', str(dd)])
    out = dd / 'daily_summary.json'
    env = json.loads(out.read_text(encoding='utf-8'))
    back = json.loads(decrypt_data(env['data'], PW, env.get('iterations')))
    check("寫出加密檔 (encrypted / AES-256-GCM / trade_date)", rc == 0 and env['encrypted'] and env['algorithm'] == 'AES-256-GCM'
          and env['trade_date'] == '20261011')
    check("hot + archive 都讀到, 解回來和直接算的一樣", back == json.loads(json.dumps(s, ensure_ascii=False)))
    before = out.read_text(encoding='utf-8')
    bds.main(['--data-dir', str(dd)])
    check("同一晚重跑: 內容沒變 → 不重寫 (git 不長)", out.read_text(encoding='utf-8') == before)
    del os.environ['CHIP_RADAR_PASSWORD']
    check("沒有密碼: 跳過, 不失敗", bds.main(['--data-dir', str(dd)]) == 0)

# D. the page
print("\n[D] index.html 接線")
h = (ROOT / 'index.html').read_text(encoding='utf-8')
if 'id="panel-summary"' not in h and (ROOT / 'preview' / 'index.html').exists():
    h = (ROOT / 'preview' / 'index.html').read_text(encoding='utf-8')   # main during the soak: the page lives at /preview/
    print("  (main: 檢查 preview/index.html)")
nav =re.search(r'<div class="tabs" role="tablist"[^>]*>(.*?)</div>', h, re.S).group(1)
btns = re.findall(r'<button class="([^"]*)" data-tab="(\w+)" role="tab" aria-selected="(\w+)"', nav)
check("分頁列第一顆是今日總整理, 預設選中", btns[0][1] == 'summary' and 'active' in btns[0][0] and btns[0][2] == 'true', btns[0])
check("其他分頁都不是預設 (今日三視角退為第二)", all('active' not in c and sel == 'false' for c, _, sel in btns[1:]) and btns[1][1] == 'today3')
check("總整理面板是開啟的那一個", re.search(r'<div class="panel active" id="panel-summary"', h) is not None
      and len(re.findall(r'<div class="panel active"', h)) == 1)
js = h[h.index('// ========== 00 今日總整理'):h.index('function renderAll() {')]
check("讀 daily_summary.json 並用同一套解密", 'daily_summary.json' in js and 'decryptToken(enc.data, SESSION_PASSWORD, enc.iterations)' in js)
ra = h[h.index('function renderAll() {'):h.index('function renderAll() {') + 600]
check("renderAll 會更新總整理 (每 5 分鐘有新資料也跟著更新)", 'refreshDailySummary();' in ra)
check("數字鍵 1–9 跳過總整理, 原本對應不變", "querySelectorAll('.tab:not([data-tab=\"summary\"])')" in h and "e.key === '`'" in h)
check("總整理頁收起日期列與市場篩選 (其他 5 塊每頁都收, v3.89.0)", '<main id="main-content" class="ds-on"' in h
      and "classList.toggle('ds-on', btn.dataset.tab === 'summary')" in h
      and '#main-content.ds-on > .status-bar,#main-content.ds-on > .market-global-bar{display:none!important}' in h
      and '#chipTemperature,#smartRetailContrast,#tempHistoryWrap,.accuracy-badge-bar,#excelDownloadBtn{display:none!important}' in h)
used_k = set(re.findall(r'\bk\.(\w+)', js))
check("網頁用到的 KPI 欄位, 產生器都有", used_k <= set(k), sorted(used_k - set(k)))
used_s = set(re.findall(r'\bs\.(\w+)', js))
check("網頁用到的頂層欄位, 產生器都有", used_s <= set(s), sorted(used_s - set(s)))
used_t = set(re.findall(r'\bt\.(\w+)', js))
check("網頁用到的走勢欄位, 產生器都有", bool(used_t) and used_t <= set(s['trends']), sorted(used_t - set(s['trends'])))
used_n = set(re.findall(r'\bn\.(\w+)', js))
check("網頁用到的說明句, 產生器都有", bool(used_n) and used_n <= set(s['notes']), sorted(used_n - set(s['notes'])))
check("大標題與說明句一律 escape 後才放進頁面", 'escHtml(headline)' in js and "escHtml(note || '')" in js)

# E. the nightly workflow
print("\n[E] daily-full 每晚流程")
wf = yaml.safe_load((ROOT / '.github/workflows/daily-full.yml').read_text(encoding='utf-8'))
steps = next(j['steps'] for j in wf['jobs'].values() if any(st.get('name') == 'Run full crawler' for st in j['steps']))
names = [st.get('name') for st in steps]
i_b = names.index('Build daily summary') if 'Build daily summary' in names else -1
step = steps[i_b] if i_b >= 0 else {}
check("在處置名單更新之後、commit 之前", 0 <= names.index('Refresh attstock disposal') < i_b < names.index('Commit and push data'))
check("有密碼、失敗不擋流程", 'CHIP_RADAR_PASSWORD' in (step.get('env') or {}) and step.get('continue-on-error') is True
      and 'scripts/build_daily_summary.py' in step.get('run', ''))
up = next(st for st in steps if st.get('name') == 'Test run - upload outputs')
check("測試跑的輸出檔附上 daily_summary.json (週一驗證用)", 'data/daily_summary.json' in up['with']['path'])

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
