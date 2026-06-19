"""
========================================================================
Module: intraday_settlement.py  (v3.41.0 Sprint 4)

盤後 13:35 TW 即時 — workflow: intraday-settlement.yml
TWSE 三大法人剛公布的 first look (盤後 5 分鐘)
不等 21:17 主排程, 提早 8 小時看到當日法人態勢

只抓最小必要資料:
  - TWSE OpenAPI BFI82U: 三大法人總表
  - TWSE STOCK_DAY_ALL: 全市場收盤 (粗略)
不打分點 (那個耗時, 等 21:17 全套).

輸出 data/intraday_settlement.json
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _fetch_twse_institutional():
    """從 TWSE OpenAPI 抓今日三大法人總表."""
    try:
        from safe_fetch import safe_get
        url = 'https://openapi.twse.com.tw/v1/exchangeReport/BFI82U'
        r = safe_get(url, source_id='TWSE_BFI82U', max_retries=2, timeout=15)
        return r.json()
    except Exception as e:
        print(f"[intraday] BFI82U fetch failed: {e}")
        return None


def _summary_from_inst(inst_data):
    """從 BFI82U 抽 3 法人淨買賣超."""
    if not inst_data:
        return None
    summary = {'foreign': 0, 'trust': 0, 'dealer': 0, 'raw_rows': len(inst_data)}
    for row in inst_data:
        name = (row.get('單位名稱') or row.get('Name') or '').strip()
        try:
            net = int((row.get('買賣差額') or '0').replace(',', ''))
        except Exception:
            net = 0
        if '外資' in name and '陸資' not in name:
            summary['foreign'] += net
        elif '投信' in name:
            summary['trust'] += net
        elif '自營商' in name:
            summary['dealer'] += net
    summary['total_inst'] = summary['foreign'] + summary['trust'] + summary['dealer']
    return summary


def build_settlement(data_dir: str = 'data'):
    dd = Path(data_dir)
    now = now_tw()

    inst = _fetch_twse_institutional()
    summary = _summary_from_inst(inst)

    out = {
        'generated_at': now.isoformat(),
        'date': now.strftime('%Y%m%d'),
        'institutional_summary_first_look': summary,
        'verdict': (
            None if not summary
            else 'all_inst_long' if summary['total_inst'] > 5000
            else 'all_inst_short' if summary['total_inst'] < -5000
            else 'mixed'
        ),
        'source': 'TWSE OpenAPI BFI82U (intraday first look)',
        'note': '盤後 13:35 first look, 完整資料等 21:17 daily-full',
    }
    target = dd / 'intraday_settlement.json'
    target.parent.mkdir(exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(target)
    return out


def main():
    s = build_settlement()
    if not s.get('institutional_summary_first_look'):
        print("::warning title=Intraday Settlement::TWSE BFI82U 抓取失敗 (盤後資料可能還未更新)")
        return 0   # 不視為錯誤, 排程仍 PASS
    summary = s['institutional_summary_first_look']
    print(f"::notice title=Intraday Settlement {s['date']}::"
          f"外資 {summary['foreign']:+,} 張 / 投信 {summary['trust']:+,} 張 / 自營 {summary['dealer']:+,} 張 "
          f"= 三大法人 {summary['total_inst']:+,} 張 ({s['verdict']})")
    print(f"[Intraday Settlement] → {Path('data')/'intraday_settlement.json'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
