# -*- coding: utf-8 -*-
"""v3.77.0 API 欄位名漂移稽核 — 防「guard 沒報錯但根本沒在跑」這類 bug

起因 (2026-08-29, v3.76.0):
  history.py 的 stale guard 讀 data[0].get('Date'), 但 MI_INDEX 是中文「日期」
  → response_date 永遠 '' → `if expected_roc and response_date and ...` 短路
  → guard 自 v3.27.3 起從未執行過, 55 筆 market 有 43 筆日期慢一天.

  這類 bug 的共通特徵:
    · 不會拋例外       · workflow 不會變紅
    · 資料看起來正常   · 錯的只是「保護沒生效」
  無人值守跑一個月會累積到無法回溯 → 必須有主動偵測.

本稽核對每個上游 API 做**實際 probe**, 比對「程式碼實際會讀的欄位名」
是否存在於回傳結構中. 欄位不存在 = 該處邏輯靜默失效.

用法:
  python scripts/audit_api_fields.py            # 全掃
  python scripts/audit_api_fields.py --critical # 只掃 critical (heartbeat 用, 快)
"""
from __future__ import annotations
import json, sys, time
import requests

sys.stdout.reconfigure(encoding='utf-8')
CRITICAL_ONLY = '--critical' in sys.argv

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
      'Accept-Language': 'zh-TW,zh;q=0.9'}

# (名稱, url, 讀取者, [程式碼實際會讀的欄位], critical?, 日期欄位)
#   critical = 該欄位若消失會造成「靜默錯誤資料」而非「明顯失敗」
REGISTRY = [
    ("TWSE MI_INDEX (大盤指數)",
     "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
     "fetchers/history.py:_fetch_taiex_index",
     ['日期', '指數', '收盤指數', '漲跌', '漲跌點數', '漲跌百分比'], True, '日期'),

    ("TWSE STOCK_DAY_ALL (上市個股)",
     "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
     "fetchers/institutional.py:324",
     ['Date', 'Code', 'ClosingPrice', 'OpeningPrice', 'HighestPrice',
      'LowestPrice', 'Change', 'TradeVolume'], True, 'Date'),

    ("TPEx daily_close_quotes (上櫃個股)",
     "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
     "fetchers/institutional.py:412",
     ['Date', 'SecuritiesCompanyCode', 'Close', 'Open', 'High', 'Low',
      'Change', 'TradingShares'], True, 'Date'),

    # ⚠️ 這兩支的欄位語言是**相反**的 — TWSE 中文 / TPEx 英文.
    #    margin.py 寫對了 (fetch_twse_margin 讀中文 / fetch_tpex_margin 讀英文),
    #    第一版稽核 registry 反而寫反並誤報 CRITICAL. 保留此註記避免下次再搞混.
    ("TWSE MI_MARGN (上市融資融券) — 中文欄位",
     "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
     "fetchers/margin.py:fetch_twse_margin",
     ['股票代號', '融資今日餘額', '融資前日餘額', '融資買進', '融資賣出',
      '融券今日餘額', '融券前日餘額'], True, None),

    ("TPEx margin_balance (上櫃融資融券) — 英文欄位",
     "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
     "fetchers/margin.py:fetch_tpex_margin",
     ['Date', 'SecuritiesCompanyCode', 'MarginPurchaseBalance',
      'MarginPurchaseBalancePreviousDay', 'ShortSaleBalance',
      'ShortSaleBalancePreviousDay'], True, 'Date'),

    ("TPEx 3insti_daily_trading (上櫃三大法人)",
     "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
     "fetchers/institutional.py",
     ['SecuritiesCompanyCode'], False, None),

    ("TPEx exright_prepost (上櫃除權息)",
     "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost",
     "fetchers/corporate_actions.py:fetch_tpex_exright",
     [], False, None),

    ("TWSE t187ap03_L (上市公司基本)",
     "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
     "fetchers/listing_fetcher.py",
     ['公司代號', '公司簡稱', '產業別', '上市日期'], False, None),

    ("TPEx mopsfin_t187ap03_O (上櫃公司基本)",
     "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
     "fetchers/listing_fetcher.py",
     ['SecuritiesCompanyCode', 'CompanyAbbreviation',
      'SecuritiesIndustryCode', 'DateOfListing'], False, None),
]

# rwd 系列 = {stat, fields, data} 結構, 欄位名在 fields 陣列裡
REGISTRY_RWD = [
    ("TWSE FMTQIK (大盤日成交)",
     "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym}01&response=json",
     "scripts/backfill_taiex_realign.py", ['日期', '發行量加權股價指數'], True),
    ("TWSE TWT49U (除權除息計算)",
     "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?date={ym}01&response=json",
     "fetchers/corporate_actions.py:fetch_twse_exright", ['資料日期'], True),
    ("TWSE TWTAUU (減資恢復買賣)",
     "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?date={ym}01&response=json",
     "fetchers/corporate_actions.py:fetch_twse_reduction", [], True),
    # ⚠️ 此端點吃**完整交易日** YYYYMMDD (非月初), 給非交易日會回 stat=沒有符合條件的資料
    ("TWSE MI_MARGN rwd (全市場融資彙總)",
     "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={td}&selectType=MS&response=json",
     "fetchers/margin.py:fetch_margin_market_aggregate", [], True),
]

FAIL = WARN = OK = 0


def _latest_trade_date() -> str:
    """rwd 端點要真實交易日 — 取 stock_history 最後一筆, 沒有就用今天."""
    try:
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[1] / 'data' / 'stock_history.json'
        mk = json.loads(p.read_text(encoding='utf-8')).get('market') or {}
        if mk:
            return max(mk)
    except Exception:
        pass
    return time.strftime('%Y%m%d')


def probe(url, timeout=25):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def report(name, reader, missing, present_sample, note="", critical=True):
    global FAIL, WARN, OK
    if missing:
        if critical:
            FAIL += 1; icon = "❌ CRITICAL"
        else:
            WARN += 1; icon = "⚠️  WARN"
        print(f"{icon}  {name}")
        print(f"           讀取者: {reader}")
        print(f"           欄位不存在: {missing}")
        print(f"           實際欄位: {present_sample}")
    else:
        OK += 1
        print(f"✅ {name}{('  ' + note) if note else ''}")


def main():
    ym = time.strftime('%Y%m')
    td = _latest_trade_date()
    print("═" * 78)
    print("API 欄位名漂移稽核 — 程式碼讀的欄位, 上游真的還在嗎?")
    print("═" * 78)

    print("\n【A】OpenAPI 系列 (list of dict)")
    for name, url, reader, fields, crit, datefield in REGISTRY:
        if CRITICAL_ONLY and not crit:
            continue
        try:
            j = probe(url)
        except Exception as e:
            print(f"❌ {name} — 抓取失敗 {type(e).__name__}: {e}")
            globals()['FAIL'] = FAIL + 1
            continue
        if not isinstance(j, list) or not j:
            print(f"⚠️  {name} — 回傳非陣列或為空 (type={type(j).__name__})")
            globals()['WARN'] = WARN + 1
            continue
        keys = list(j[0].keys())
        missing = [f for f in fields if f not in keys]
        note = ""
        if datefield and datefield in keys:
            note = f"(日期欄「{datefield}」= {j[0][datefield]}, {len(j)} 筆)"
        report(name, reader, missing, keys[:12], note, crit)
        time.sleep(0.5)

    print("\n【B】rwd 系列 ({stat, fields, data} 結構)")
    for name, tmpl, reader, fields, crit in REGISTRY_RWD:
        if CRITICAL_ONLY and not crit:
            continue
        url = tmpl.format(ym=ym, td=td)
        try:
            j = probe(url)
        except Exception as e:
            print(f"❌ {name} — 抓取失敗 {type(e).__name__}")
            globals()['FAIL'] = FAIL + 1
            continue
        stat = j.get('stat')
        if stat != 'OK':
            print(f"⚠️  {name} — stat={stat!r} (本月可能尚無資料)")
            globals()['WARN'] = WARN + 1
            continue
        # ⚠️ rwd 有兩種形狀: 頂層 fields/data, 或資料包在 tables[] 內
        #    (MI_MARGN selectType=MS 屬後者, margin.py 讀的正是 tables)
        f_list = j.get('fields') or []
        n_rows = len(j.get('data') or [])
        if not f_list and (j.get('tables') or []):
            t0 = j['tables'][0]
            f_list = t0.get('fields') or []
            n_rows = len(t0.get('data') or [])
        missing = [f for f in fields if not any(f in x for x in f_list)]
        report(name, reader, missing, f_list[:12], f"({n_rows} 筆)", crit)
        time.sleep(0.5)

    print("\n" + "═" * 78)
    print(f"結果: {OK} OK / {WARN} WARN / {FAIL} CRITICAL")
    print("═" * 78)
    if FAIL:
        print("\n⚠️ CRITICAL 代表程式碼讀的欄位在上游已不存在 —")
        print("   該處不會拋例外, 只會靜默拿到 None. 立即檢查對應讀取者.")
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
