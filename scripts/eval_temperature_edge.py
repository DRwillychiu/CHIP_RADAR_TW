# -*- coding: utf-8 -*-
"""P1 溫度計去留評估 — 用乾淨資料判定「重設計」還是「退役」

背景:
  v3.76.0 修好大盤日期錯位後, 溫度計在 59 天樣本上 Δ +0.0pp (55.8% vs 55.8%).
  但 59 天太少, 不足以下判決. P0 稽核已確認另兩個資料集乾淨:
    · signal_history_official.json  119 天 (2025-12-29~2026-06-30), 7 信號齊
    · temp_history.json (v3.76.0 重建)  60 天 (2026-06-04~2026-08-28), 7 信號齊
  兩者時間連續(重疊 6/04~6/30) → 合併後約 165 天, 是目前能取得的最佳證據.

方法論紀律 (小樣本搜尋極易 overfit, 先講清楚再跑):
  1. 合併重疊日以 official 為準 (官方 backfill 優先於每日爬取)
  2. train = official 期間 / test = official 之後 (真 out-of-sample, 時間不重疊)
  3. 任何候選規則都必須 **先在 train 決定, 再看 test**, 不得回頭改
  4. 報告多重比較暴露量 (試了幾個候選), 不只報最好的那個
  5. 判準是 **vs 無腦全多的配對差**, 不是絕對命中率 —
     多頭市場任何偏多規則都會有高命中率, 那不是 alpha
"""
from __future__ import annotations
import json, io, math, sys, itertools
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
sys.path.insert(0, str(ROOT))


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * (c - h), 100 * (c + h))


def mcnemar_p(b, c):
    """精確二項檢定 (雙尾) — b/c 為兩系統判定分歧的兩種方向次數."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def load_merged():
    """合併 official + temp_history, 重疊日以 official 為準."""
    out = {}
    o = json.loads((DATA / 'signal_history_official.json').read_text(encoding='utf-8'))
    for e in o['history']:
        if e.get('next_day_change_pct') is None:
            continue
        out[e['date']] = {'date': e['date'], 'signals': e['signals'],
                          'next': e['next_day_change_pct'], 'src': 'official'}
    official_last = max(out) if out else '00000000'

    t = json.loads((DATA / 'temp_history.json').read_text(encoding='utf-8'))
    for e in t['history']:
        if e.get('next_day_change_pct') is None:
            continue
        d = e['date']
        if d in out:          # 重疊 → 官方優先
            continue
        out[d] = {'date': d, 'signals': e['signals'],
                  'next': e['next_day_change_pct'], 'src': 'temp'}
    rows = [out[d] for d in sorted(out)]
    return rows, official_last


def sig_map(row):
    return {s['name']: s for s in row['signals']}


def evaluate(rows, decide, label, verbose=True):
    """decide(row) -> '偏多'|'偏空'|'中性'; 只在非中性日計分, 與全多配對比較."""
    n = hit = base = b_only = c_only = 0
    for r in rows:
        d = decide(r)
        if d == '中性':
            continue
        n += 1
        s_ok = (r['next'] > 0) if d == '偏多' else (r['next'] < 0)
        b_ok = r['next'] > 0
        hit += s_ok
        base += b_ok
        if s_ok and not b_ok:
            b_only += 1
        if b_ok and not s_ok:
            c_only += 1
    if n == 0:
        if verbose:
            print(f"  {label:<34} 無可評估日")
        return None
    d_pp = 100 * (hit - base) / n
    p = mcnemar_p(b_only, c_only)
    lo, hi = wilson(hit, n)
    if verbose:
        print(f"  {label:<34} n={n:3d}  {100*hit/n:5.1f}% [{lo:4.1f},{hi:4.1f}]  "
              f"全多 {100*base/n:5.1f}%  Δ{d_pp:+5.1f}pp  p={p:.3f}")
    return {'label': label, 'n': n, 'hit': hit, 'base': base,
            'delta_pp': d_pp, 'p': p, 'b_only': b_only, 'c_only': c_only}


def main():
    rows, official_last = load_merged()
    train = [r for r in rows if r['date'] <= official_last]
    test = [r for r in rows if r['date'] > official_last]

    print("=" * 92)
    print("P1 溫度計去留評估 — 乾淨資料")
    print("=" * 92)
    print(f"合併樣本 {len(rows)} 天  {rows[0]['date']} ~ {rows[-1]['date']}")
    print(f"  train (official) {len(train):3d} 天  {train[0]['date']} ~ {train[-1]['date']}")
    print(f"  test  (之後)     {len(test):3d} 天  "
          f"{test[0]['date'] if test else '-'} ~ {test[-1]['date'] if test else '-'}")
    up = sum(1 for r in rows if r['next'] > 0)
    print(f"  期間多頭比例 {up}/{len(rows)} = {100*up/len(rows):.1f}%  ← 無腦全多的成績")
    for nm, ds in (('train', train), ('test', test)):
        u = sum(1 for r in ds if r['next'] > 0)
        print(f"    {nm}: {u}/{len(ds)} = {100*u/len(ds):.1f}%")

    # ── 1. 現行系統 ──
    from src.analyzers.signal_engine import infer_market_direction
    print("\n【1】現行 infer_market_direction (net > 0.10)")
    cur = lambda r: infer_market_direction(r['signals'])['direction']
    for nm, ds in (('全期', rows), ('train', train), ('test', test)):
        evaluate(ds, cur, f'現行系統 · {nm}')

    # ── 2. 逐信號單獨的預測力 ──
    print("\n【2】逐信號單獨預測力 — 各 level 對隔日方向 (全期)")
    names = sorted({s['name'] for r in rows for s in r['signals']})
    single = []
    for nm in names:
        lv_stats = {}
        for r in rows:
            s = sig_map(r).get(nm)
            if not s:
                continue
            lv_stats.setdefault(s.get('level'), []).append(r['next'])
        print(f"  {nm}")
        for lv, ch in sorted(lv_stats.items(), key=lambda x: -len(x[1])):
            k = sum(1 for c in ch if c > 0)
            n = len(ch)
            if n < 10:
                print(f"     {str(lv):<14} n={n:3d}  (樣本 <10, 不評估)")
                continue
            lo, hi = wilson(k, n)
            mark = "  ← CI 不含 50%" if (lo > 50 or hi < 50) else ""
            print(f"     {str(lv):<14} n={n:3d}  上漲 {100*k/n:5.1f}% [{lo:4.1f},{hi:4.1f}]"
                  f"  平均 {sum(ch)/n:+.3f}%{mark}")
            single.append((nm, lv, n, k, lo, hi))
    return rows, train, test, single


if __name__ == '__main__':
    main()


# ════════════════════════════════════════════════════════════════════
#  第二部分: 選擇性 alpha + 候選重設計
# ════════════════════════════════════════════════════════════════════
#
# ⚠️ 度量方式的關鍵陷阱 (第一部分跑完才看清楚):
#   配對命中率比較有個結構性後果 — **一個只會說「偏多」或「中性」的系統,
#   在這個度量下 Δ 恆為 0**, 不管它多會挑日子.
#   因為兩邊都只在它出手的日子上評分, 而它出手時一律看多 = 跟全多同一邊.
#   現行系統正是如此 (全期/train/test 三段 Δ 都剛好 +0.0pp, p=1.000).
#
#   但「不出手」對實際使用者是有價值的 — 那是**規避風險**, 不是預測方向.
#   要衡量它必須換一把尺:
#     M1 方向 alpha  : 出手日的命中率 vs 全多 (配對)  → 會不會看方向
#     M2 選擇 alpha  : 說偏多那些日子的平均漲跌 vs 全期平均 → 會不會挑日子
#   兩把尺都不過, 才是真的沒有價值.

def mean_(xs):
    return sum(xs) / len(xs) if xs else 0.0


def eval_selection(rows, decide, label, verbose=True):
    """M2 選擇 alpha — 說偏多的日子, 平均漲跌是否高於全期平均."""
    picked = [r['next'] for r in rows if decide(r) == '偏多']
    allc = [r['next'] for r in rows]
    if not picked:
        return None
    mp, ma = mean_(picked), mean_(allc)
    # 隨機抽同樣張數的日子, 平均會落在哪 (permutation, 決定性種子替代: 用全組合近似)
    sd = (sum((c - ma) ** 2 for c in allc) / max(1, len(allc) - 1)) ** 0.5
    se = sd / math.sqrt(len(picked))
    z = (mp - ma) / se if se else 0.0
    if verbose:
        print(f"  {label:<34} 出手 {len(picked):3d}/{len(allc):3d} 天  "
              f"平均 {mp:+.3f}%  vs 全期 {ma:+.3f}%  Δ{mp-ma:+.3f}%  z={z:+.2f}")
    return {'label': label, 'n_picked': len(picked), 'mean_picked': mp,
            'mean_all': ma, 'delta': mp - ma, 'z': z}


def run_part2():
    rows, official_last = load_merged()
    train = [r for r in rows if r['date'] <= official_last]
    test = [r for r in rows if r['date'] > official_last]
    from src.analyzers.signal_engine import infer_market_direction

    print("\n" + "=" * 92)
    print("【3】結構檢查 — 現行系統到底有沒有喊過偏空?")
    print("=" * 92)
    from collections import Counter
    for nm, ds in (('全期', rows), ('train', train), ('test', test)):
        c = Counter(infer_market_direction(r['signals'])['direction'] for r in ds)
        print(f"  {nm:<6} {dict(c)}")
    nets = [infer_market_direction(r['signals'])['net_weight'] for r in rows]
    print(f"  net_weight 值域 {min(nets):+.3f} ~ {max(nets):+.3f}  "
          f"(方向門檻 ±0.10)  負值天數 {sum(1 for x in nets if x < 0)}")

    print("\n" + "=" * 92)
    print("【4】M2 選擇 alpha — 現行系統會不會挑日子?")
    print("=" * 92)
    cur = lambda r: infer_market_direction(r['signals'])['direction']
    for nm, ds in (('全期', rows), ('train', train), ('test', test)):
        eval_selection(ds, cur, f'現行系統 · {nm}')

    # ── 候選重設計: 先在 train 選, 再看 test ──
    print("\n" + "=" * 92)
    print("【5】候選重設計 — 規則在 train 決定, test 完全不參與選擇")
    print("=" * 92)

    def S(r):
        return {s['name']: s for s in r['signals']}

    # 候選群 (⚠️ 多重比較暴露量 = 下面這串的長度, 報告時必須揭露)
    cands = []
    # C1 單一最強信號: 外資現貨 extreme-bull
    cands.append(('C1 外資現貨=extreme-bull 才做多',
                  lambda r: '偏多' if (S(r).get('外資現貨') or {}).get('level') == 'extreme-bull' else '中性'))
    # C2 一致性法: 統計 bull-ish vs bear-ish 信號個數, 需明顯多數
    def consensus(k):
        def f(r):
            lv = [(s.get('level') or '') for s in r['signals']]
            b = sum(1 for x in lv if 'bull' in x)
            d = sum(1 for x in lv if 'bear' in x)
            if b - d >= k:
                return '偏多'
            if d - b >= k:
                return '偏空'
            return '中性'
        return f
    for k in (2, 3, 4):
        cands.append((f'C2 一致性 多空差≥{k}', consensus(k)))
    # C3 提高現行門檻
    for th in (0.20, 0.30, 0.40):
        cands.append((f'C3 現行 net 門檻 {th:.2f}',
                      lambda r, th=th: ('偏多' if infer_market_direction(r['signals'])['net_weight'] > th
                                        else ('偏空' if infer_market_direction(r['signals'])['net_weight'] < -th
                                              else '中性'))))
    # C4 迴避法: 融資熱度 neutral 當天不做 (全期 35.7% 最差的一格)
    cands.append(('C4 避開 融資熱度=neutral',
                  lambda r: '中性' if (S(r).get('融資熱度') or {}).get('level') == 'neutral' else '偏多'))
    # C5 外資現貨 extreme-bull 且 融資熱度非 neutral
    cands.append(('C5 C1 且 非融資neutral',
                  lambda r: '偏多' if ((S(r).get('外資現貨') or {}).get('level') == 'extreme-bull'
                                     and (S(r).get('融資熱度') or {}).get('level') != 'neutral') else '中性'))

    print(f"\n多重比較暴露量: 候選 {len(cands)} 個 (α=0.05 下期望假陽性 ≈ {0.05*len(cands):.1f} 個)\n")
    print("─── TRAIN (規則在這裡挑) ───")
    tr = []
    for lab, fn in cands:
        m1 = evaluate(train, fn, lab, verbose=False)
        m2 = eval_selection(train, fn, lab, verbose=False)
        if m1 and m2:
            print(f"  {lab:<28} M1 n={m1['n']:3d} Δ{m1['delta_pp']:+5.1f}pp p={m1['p']:.3f}"
                  f"   M2 出手{m2['n_picked']:3d} Δ{m2['delta']:+.3f}% z={m2['z']:+.2f}")
            tr.append((lab, fn, m1, m2))

    # 預先宣告的挑選準則: M2 z 最高且出手天數 ≥ train 的 25%
    minpick = len(train) * 0.25
    elig = [x for x in tr if x[3]['n_picked'] >= minpick]
    if not elig:
        print("\n  ⚠️ 無候選滿足「出手天數 ≥ train 25%」→ 不進 test")
        return
    best = max(elig, key=lambda x: x[3]['z'])
    print(f"\n  依預先宣告準則 (M2 z 最高 且 出手 ≥{minpick:.0f} 天) 選出: 「{best[0]}」")

    print("\n─── TEST (out-of-sample, 完全沒參與挑選) ───")
    m1 = evaluate(test, best[1], best[0], verbose=False)
    m2 = eval_selection(test, best[1], best[0], verbose=False)
    if m1:
        print(f"  {best[0]:<28} M1 n={m1['n']:3d} Δ{m1['delta_pp']:+5.1f}pp p={m1['p']:.3f}")
    if m2:
        print(f"  {best[0]:<28} M2 出手{m2['n_picked']:3d}/{len(test)} "
              f"平均{m2['mean_picked']:+.3f}% vs 全期{m2['mean_all']:+.3f}% "
              f"Δ{m2['delta']:+.3f}% z={m2['z']:+.2f}")
    print("\n  對照 — 現行系統在同一段 test:")
    evaluate(test, lambda r: infer_market_direction(r['signals'])['direction'], '現行系統')
    eval_selection(test, lambda r: infer_market_direction(r['signals'])['direction'], '現行系統')


if __name__ == '__main__':
    run_part2()


# ════════════════════════════════════════════════════════════════════
#  第三部分: 換 horizon — 也許它本來就不該預測「隔日」
# ════════════════════════════════════════════════════════════════════
#
# 退役一個東西之前, 該先確認不是**問題問錯了**.
# 溫度計是籌碼溫度, 籌碼的影響未必在隔天就反映完 —
# Phase 3.5 的個股 multiday peak 86.8% 就是這個道理.
# 所以在下判決前, 把同一套判定拿去測 t+1 ~ t+10 累積報酬.
# 若某個 horizon 有穩定 edge, 那結論就不是「退役」而是「改 horizon」.

def fetch_official_index(months):
    import requests, time as _t
    UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Accept-Language': 'zh-TW,zh;q=0.9'}
    out = {}
    for ym in months:
        try:
            j = requests.get(f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK'
                             f'?date={ym}01&response=json', headers=UA, timeout=25).json()
            if j.get('stat') == 'OK':
                for r in j['data']:
                    p = r[0].split('/')
                    out[f'{int(p[0]) + 1911}{p[1]}{p[2]}'] = float(r[4].replace(',', ''))
        except Exception as e:
            print(f'  ! {ym} {type(e).__name__}')
        _t.sleep(0.5)
    return out


def run_part3():
    rows, official_last = load_merged()
    from src.analyzers.signal_engine import infer_market_direction
    months = sorted({r['date'][:6] for r in rows})
    # 多抓兩個月讓最後幾天也有 t+10
    last = months[-1]
    y, m = int(last[:4]), int(last[4:])
    for _ in range(2):
        m += 1
        if m > 12:
            m = 1; y += 1
        months.append(f'{y}{m:02d}')
    print("\n" + "=" * 92)
    print("【6】換 horizon — 溫度計也許不該預測隔日")
    print("=" * 92)
    print(f"抓官方指數 {len(months)} 個月...")
    idx = fetch_official_index(months)
    dates = sorted(idx)
    pos = {d: i for i, d in enumerate(dates)}
    print(f"取得 {len(idx)} 個交易日\n")

    HOR = [1, 2, 3, 5, 10]

    def fwd(d, h):
        i = pos.get(d)
        if i is None or i + h >= len(dates):
            return None
        return (idx[dates[i + h]] - idx[dates[i]]) / idx[dates[i]] * 100

    def S(r):
        return {s['name']: s for s in r['signals']}

    rules = [
        ('現行系統 (net>0.10)', lambda r: infer_market_direction(r['signals'])['direction']),
        ('C5 外資現貨EB 且 非融資neutral',
         lambda r: '偏多' if ((S(r).get('外資現貨') or {}).get('level') == 'extreme-bull'
                            and (S(r).get('融資熱度') or {}).get('level') != 'neutral') else '中性'),
    ]

    print(f"{'規則':<32}{'horizon':<9}{'出手':<10}{'選中平均':<12}{'全期平均':<12}{'Δ':<11}{'z'}")
    print("─" * 92)
    for lab, fn in rules:
        for h in HOR:
            pick, allc = [], []
            for r in rows:
                v = fwd(r['date'], h)
                if v is None:
                    continue
                allc.append(v)
                if fn(r) == '偏多':
                    pick.append(v)
            if len(pick) < 10 or len(allc) < 20:
                continue
            ma = mean_(allc); mp = mean_(pick)
            sd = (sum((c - ma) ** 2 for c in allc) / (len(allc) - 1)) ** 0.5
            se = sd / math.sqrt(len(pick))
            z = (mp - ma) / se if se else 0.0
            flag = '  ←' if abs(z) >= 2 else ''
            print(f"{lab:<32}t+{h:<7}{len(pick):3d}/{len(allc):<5}"
                  f"{mp:+8.3f}%   {ma:+8.3f}%   {mp-ma:+8.3f}%  {z:+5.2f}{flag}")
        print()


if __name__ == '__main__':
    run_part3()
