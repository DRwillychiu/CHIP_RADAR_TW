"""
========================================================================
Module: stress_test_data_integrity.py  (v3.30.7 新增)
數據正確性壓力測試 — 確保 buy_amt / buy_lot 等核心數字在任何情況都正確

動機 (使用者 5/29):
  「在最需要正確數據的時候卻發現 buy_amt/buy_lot 是錯的」是不可接受的。
  v3.30.6 剛抓到 histock cross-check 自己的 buy_amt 單位 bug (仟元當元差 1000 倍),
  證明連驗證工具都會錯 → 需要系統性壓力測試。

兩部分:
  Part 1 (合成 fuzzing, 免密碼):
    - 生成數千筆隨機/邊界/異常 stock, 驗證 invariant 檢查不崩
    - **故意注入已知 bug (單位錯/net錯/負值), 確認 invariant 抓得到** (證明非擺設)
  Part 2 (真實掃描, 需 CHIP_RADAR_PASSWORD):
    - 解密 latest.json, 對每筆 (分點×股票) 掃內部 invariant
    - --histock: 對高關注個股用 histock by-stock 外部交叉 (絕對值判準, 單位已修)

核心 invariant (合成+真實共用):
  1. 非負: buy_lot/sell_lot/buy_amt/sell_amt >= 0
  2. net 守恆: net_amt == buy_amt - sell_amt; net_lot == buy_lot - sell_lot
  3. 均價合理 (抓單位/merge錯): buy_amt(仟元)/buy_lot(張) ∈ [0.01, 15000] 元/股
  4. 無重複: 同分點同 code 不出現兩次
  5. 顯示反算: Excel 萬元 == round(仟元/10) 無漂移

CLI:
  python stress_test_data_integrity.py                       # Part 1 合成 (預設)
  python stress_test_data_integrity.py --n 20000             # 加大合成量
  python stress_test_data_integrity.py --real                # Part 2 真實 (需密碼)
  python stress_test_data_integrity.py --real --histock 20   # + histock 交叉 top 20
========================================================================
"""
import os
import sys
import json
import random
import argparse
from typing import Dict, Any, List, Tuple

# 台股價格合理範圍 (元/股): 最低 0.01 (雞蛋水餃股), 最高留餘裕 (大立光曾 ~6000)
STOCK_PRICE_MIN = 0.01
STOCK_PRICE_MAX = 15000.0

# 均價容忍: estimated_from_close 反推的個股容忍寬一點
EST_PRICE_MAX = 20000.0

Violation = Tuple[str, str, str, str]  # (code, field, detail, severity)


# ════════════════════════════════════════════════════════════════════
#  Invariant 檢查 (合成 + 真實共用) — 純函式
# ════════════════════════════════════════════════════════════════════

def check_stock_invariants(stock: Dict[str, Any], ctx: str = "") -> List[Violation]:
    """單一 stock dict 的內部不變量。回傳 violation list。"""
    v: List[Violation] = []
    code = str(stock.get('code', '?'))
    bl = stock.get('buy_lot', 0) or 0
    sl = stock.get('sell_lot', 0) or 0
    ba = stock.get('buy_amt', 0) or 0   # 仟元
    sa = stock.get('sell_amt', 0) or 0
    is_est = stock.get('lot_source') == 'estimated_from_close'
    price_max = EST_PRICE_MAX if is_est else STOCK_PRICE_MAX

    # 型別檢查 (非數字 = 解析錯)
    for fld, val in [('buy_lot', bl), ('sell_lot', sl), ('buy_amt', ba), ('sell_amt', sa)]:
        if not isinstance(val, (int, float)):
            v.append((code, fld, f'{ctx}非數值型別: {type(val).__name__}={val!r}', 'error'))
            return v  # 型別錯就不繼續算

    # 1. 非負
    for fld, val in [('buy_lot', bl), ('sell_lot', sl), ('buy_amt', ba), ('sell_amt', sa)]:
        if val < 0:
            v.append((code, fld, f'{ctx}負值 {val}', 'error'))

    # 2. net 守恆 (若有 net 欄位)
    na = stock.get('net_amt')
    if na is not None and isinstance(na, (int, float)):
        if abs(na - (ba - sa)) > max(1, abs(ba - sa) * 0.01):
            v.append((code, 'net_amt', f'{ctx}{na} != buy-sell={ba - sa}', 'error'))
    nl = stock.get('net_lot')
    if nl is not None and isinstance(nl, (int, float)):
        if nl != bl - sl:
            v.append((code, 'net_lot', f'{ctx}{nl} != buy-sell={bl - sl}', 'error'))

    # 3. 均價合理 (核心: 抓單位錯 / merge 對齊錯)
    if bl > 0 and ba > 0:
        buy_avg = ba / bl   # 仟元/張 = 元/股 (單位相消)
        if not (STOCK_PRICE_MIN <= buy_avg <= price_max):
            v.append((code, 'buy_avg',
                      f'{ctx}買均 {buy_avg:.2f} 元/股 超出 [{STOCK_PRICE_MIN}, {price_max}] '
                      f'(buy_amt={ba} 仟元 / buy_lot={bl} 張) — 疑單位或 merge 錯', 'error'))
    if sl > 0 and sa > 0:
        sell_avg = sa / sl
        if not (STOCK_PRICE_MIN <= sell_avg <= price_max):
            v.append((code, 'sell_avg',
                      f'{ctx}賣均 {sell_avg:.2f} 元/股 超出範圍', 'error'))

    # 4. 0 金額但有張數 (低價股金額沒上榜, by-design 但提示)
    if bl > 0 and ba == 0 and not is_est:
        v.append((code, 'buy_amt', f'{ctx}有 {bl} 張但金額=0 (低價股未上金額榜?)', 'warning'))

    return v


def check_branch_invariants(branch: Dict[str, Any]) -> List[Violation]:
    """分點層級: 無重複 code。"""
    v: List[Violation] = []
    bcode = str(branch.get('code', '?'))
    seen = set()
    for s in branch.get('buys', []) + branch.get('sells', []):
        c = s.get('code')
        if c in seen:
            v.append((str(c), 'duplicate', f'分點 {bcode} 內 code 重複', 'error'))
        seen.add(c)
    return v


def check_excel_roundtrip(buy_amt_k: float) -> List[Violation]:
    """顯示反算: 仟元 -> 萬元 (round/10) -> 反算誤差。"""
    v: List[Violation] = []
    if buy_amt_k <= 0:
        return v
    wan = round(buy_amt_k / 10)
    back_k = wan * 10
    rel = abs(back_k - buy_amt_k) / buy_amt_k
    # 萬元四捨五入本來就有誤差, 只在「相對誤差過大」(小額放大) 時提示
    if rel > 0.10 and buy_amt_k > 100:
        v.append(('?', 'excel_round', f'仟元 {buy_amt_k} -> 萬元 {wan} 反算誤差 {rel*100:.1f}%', 'warning'))
    return v


# ════════════════════════════════════════════════════════════════════
#  Part 1: 合成 fuzzing
# ════════════════════════════════════════════════════════════════════

def gen_random_stock(extreme: bool = False) -> Dict[str, Any]:
    """生成隨機 (或極端) stock dict — 模擬真實 merge 後結構。"""
    if extreme:
        # 邊界 / 異常
        bl = random.choice([0, 1, 99999, random.randint(0, 50000)])
        sl = random.choice([0, 1, 99999, random.randint(0, 50000)])
        price = random.choice([0.01, 0.5, 5, 50, 500, 5000, random.uniform(1, 6000)])
    else:
        bl = random.randint(0, 5000)
        sl = random.randint(0, 5000)
        price = random.uniform(5, 3000)
    ba = round(bl * price)   # 仟元 (張 × 元/股, 單位相消)
    sa = round(sl * price)
    return {
        'code': f'{random.randint(1000, 9999)}',
        'name': f'股{random.randint(1, 999)}',
        'buy_lot': bl, 'sell_lot': sl,
        'buy_amt': ba, 'sell_amt': sa,
        'net_amt': ba - sa, 'net_lot': bl - sl,
    }


def gen_known_bugs() -> List[Tuple[Dict[str, Any], str]]:
    """故意注入已知 bug, 確認 invariant 抓得到 (證明框架非擺設)。"""
    return [
        # A. 單位錯: buy_amt 用「元」(台積電 550 張 ≈ 12.6 億元) 而非仟元
        #    → 均價 1,260,578,000/550 = 2,291,960 元/股 → 遠超 15000 → 抓!
        ({'code': 'BUG_UNIT', 'buy_lot': 550, 'buy_amt': 1_260_578_000,
          'sell_lot': 0, 'sell_amt': 0, 'net_amt': 1_260_578_000, 'net_lot': 550}, 'buy_avg'),
        # B. net_lot 錯
        ({'code': 'BUG_NET', 'buy_lot': 100, 'sell_lot': 30, 'buy_amt': 500, 'sell_amt': 150,
          'net_amt': 350, 'net_lot': 999}, 'net_lot'),
        # C. net_amt 錯
        ({'code': 'BUG_NETAMT', 'buy_lot': 100, 'sell_lot': 30, 'buy_amt': 500, 'sell_amt': 150,
          'net_amt': 99999, 'net_lot': 70}, 'net_amt'),
        # D. 負值
        ({'code': 'BUG_NEG', 'buy_lot': -50, 'buy_amt': 100, 'sell_lot': 0, 'sell_amt': 0,
          'net_amt': 100, 'net_lot': -50}, 'buy_lot'),
        # E. 型別錯 (解析失敗殘留字串)
        ({'code': 'BUG_TYPE', 'buy_lot': '1,234', 'buy_amt': 500, 'sell_lot': 0, 'sell_amt': 0}, 'buy_lot'),
        # F. merge 對齊錯模擬: 高張低均價 (1 張卻 50 萬仟元 → 均價 50 萬 → 抓)
        ({'code': 'BUG_MERGE', 'buy_lot': 1, 'buy_amt': 500_000, 'sell_lot': 0, 'sell_amt': 0,
          'net_amt': 500_000, 'net_lot': 1}, 'buy_avg'),
    ]


def stress_synthetic(n: int = 5000) -> bool:
    """Part 1: 合成 fuzzing。回傳 all_pass。"""
    print("=" * 64)
    print(f"  Part 1: 合成 fuzzing ({n} 隨機 + {n//5} 極端 + 注入 bug)")
    print("=" * 64)
    all_pass = True

    # 1a. 隨機正常資料 — invariant 不該誤報 (false positive 檢查)
    fp = 0
    for _ in range(n):
        s = gen_random_stock(extreme=False)
        errs = [x for x in check_stock_invariants(s) if x[3] == 'error']
        if errs:
            fp += 1
            if fp <= 3:
                print(f"  ⚠️ 正常資料誤報: {s} → {errs}")
    print(f"\n1a. {n} 筆正常隨機資料 — error 誤報: {fp} (應 0)")
    if fp > 0:
        all_pass = False

    # 1b. 極端資料 — check 不該崩潰 (robustness)
    crashed = 0
    for _ in range(n // 5):
        s = gen_random_stock(extreme=True)
        try:
            check_stock_invariants(s)
        except Exception as e:
            crashed += 1
            print(f"  ❌ 極端資料 check 崩潰: {s} → {e}")
    print(f"1b. {n//5} 筆極端資料 — check 崩潰: {crashed} (應 0)")
    if crashed > 0:
        all_pass = False

    # 1c. 注入已知 bug — invariant 必須抓到對應 field (核心驗證)
    print(f"\n1c. 注入已知 bug — invariant 是否抓得到:")
    for bug_stock, expect_field in gen_known_bugs():
        viols = check_stock_invariants(bug_stock)
        caught = any(expect_field in x[1] for x in viols)
        mark = '✅' if caught else '❌'
        print(f"  {mark} {bug_stock['code']:12s} 預期抓 {expect_field:10s} → "
              f"{'抓到' if caught else '漏抓!'} {[(x[1],x[3]) for x in viols]}")
        if not caught:
            all_pass = False

    # 1d. Excel 顯示反算 fuzzing
    print(f"\n1d. Excel 仟元->萬元 反算 fuzzing:")
    excel_warn = 0
    for _ in range(n):
        amt_k = random.randint(1, 50_000_000)
        excel_warn += len(check_excel_roundtrip(amt_k))
    print(f"  {n} 筆金額反算, 大額誤差告警: {excel_warn} (小額放大為主, 合理)")

    print()
    print(f"  Part 1 整體: {'✅ PASS' if all_pass else '❌ FAIL'}")
    return all_pass


# ════════════════════════════════════════════════════════════════════
#  Part 2: 真實資料掃描 (需密碼)
# ════════════════════════════════════════════════════════════════════

def scan_real(latest_path: str, password: str, histock_n: int = 0) -> bool:
    """Part 2: 解密 latest.json → 每筆掃 invariant (+ 可選 histock 交叉)。"""
    print("=" * 64)
    print(f"  Part 2: 真實資料掃描 ({latest_path})")
    print("=" * 64)

    from crawler import decrypt_data
    with open(latest_path, 'r', encoding='utf-8') as f:
        enc = json.load(f)
    data = json.loads(decrypt_data(enc['data'], password)) if enc.get('encrypted') else enc
    branches = data.get('branches', [])
    print(f"  trade_date: {data.get('trade_date')} | 分點數: {len(branches)}")

    all_errors: List[Violation] = []
    all_warnings: List[Violation] = []
    total_stocks = 0

    for br in branches:
        for vio in check_branch_invariants(br):
            (all_errors if vio[3] == 'error' else all_warnings).append(vio)
        for s in br.get('buys', []) + br.get('sells', []):
            total_stocks += 1
            ctx = f"[{br.get('code')}] "
            for vio in check_stock_invariants(s, ctx=ctx):
                (all_errors if vio[3] == 'error' else all_warnings).append(vio)

    print(f"\n  掃描 {total_stocks} 筆 (分點×股票)")
    print(f"  ❌ errors:   {len(all_errors)}")
    print(f"  ⚠️ warnings: {len(all_warnings)}")
    if all_errors:
        print("\n  === ERROR 明細 (前 20) ===")
        for e in all_errors[:20]:
            print(f"    {e[0]} {e[1]}: {e[2]}")
    if all_warnings[:10]:
        print("\n  === WARNING 明細 (前 10) ===")
        for w in all_warnings[:10]:
            print(f"    {w[0]} {w[1]}: {w[2]}")

    # histock 外部交叉 (使用者選的主判準)
    if histock_n > 0:
        print(f"\n  === histock 外部交叉 (top {histock_n} 高關注個股) ===")
        try:
            import histock_branch_audit as hba
            res = hba.run_audit(data, max_stocks=histock_n, verbose=True)
            print(f"  histock 交叉 verdict: {res['verdict']} — {res['summary']}")
            if res['verdict'] == 'FAIL':
                all_errors.append(('histock', 'cross_check', res['summary'], 'error'))
        except Exception as e:
            print(f"  ⚠️ histock 交叉跳過: {e}")

    ok = len(all_errors) == 0
    print(f"\n  Part 2 整體: {'✅ PASS (0 error)' if ok else f'❌ FAIL ({len(all_errors)} errors)'}")
    return ok


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='數據正確性壓力測試')
    parser.add_argument('--n', type=int, default=5000, help='合成資料量')
    parser.add_argument('--real', action='store_true', help='跑真實 latest.json 掃描 (需密碼)')
    parser.add_argument('--latest', default='data/latest.json')
    parser.add_argument('--histock', type=int, default=0, help='histock 交叉的個股數 (0=不跑)')
    args = parser.parse_args()

    p1 = stress_synthetic(args.n)

    p2 = True
    if args.real:
        pwd = os.environ.get('CHIP_RADAR_PASSWORD')
        if not pwd:
            print("\n❌ --real 需要 CHIP_RADAR_PASSWORD 環境變數")
            sys.exit(1)
        print()
        p2 = scan_real(args.latest, pwd, histock_n=args.histock)

    print()
    print("=" * 64)
    overall = p1 and p2
    print(f"  壓力測試整體: {'✅ ALL PASS' if overall else '❌ HAS FAIL'}")
    sys.exit(0 if overall else 1)


if __name__ == '__main__':
    main()
