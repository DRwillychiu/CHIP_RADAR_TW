# -*- coding: utf-8 -*-
"""v3.72.9 P2 #6 — Enrich sniper limit_up_details with top-market-buyer flag.

用途:
  前端 sniper card 內顯示的每檔漲停股 chip, 若該分點是該股當日 histock 全市場
  分點榜 top #1 買方 → 加 is_top_market_buyer=True flag.
  前端 JS 讀此 flag → 套 CSS class .top-market-buyer → 黃色 highlight.

呼叫時機:
  crawler.py compute_limit_up_summary 之後, latest.json 寫入之前.
  in-place 修改 limit_up_summary['sniper_ranking'] + 'master_sniper_ranking'.

Reuse 邏輯:
  histock fetch 邏輯 reuse src.exports.excel_report._fetch_histock_top_buyer
  (含時效 guard + net<=0 guard + stats + cache).
  Excel 產出時 build_day_sheet 會再 fetch 一次 (同 process, cache 不 share).
  未來可考慮共用 module-level cache.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any


def enrich_sniper_top_buyer(
    limit_up_summary: Dict[str, Any],
    sniper_masters: set,
    trade_date: Optional[str] = None,
) -> Dict[str, Any]:
    """對 sniper_ranking / master_sniper_ranking 中 sniper_masters 的 limit_up_details
    加 is_top_market_buyer flag (in-place).

    Args:
      limit_up_summary: raw_output.limit_up_summary dict
      sniper_masters: 白名單, e.g. {"蔣承翰"}
      trade_date: YYYYMMDD, 供時效 guard (histock date != trade_date → skip)

    Returns:
      dict:
        top_buyer_index: {stock_code: top_bno}  — 亦存 raw_output 給其他 consumer
        stats:            histock fetch 統計 (attempted/success/stale/http_err/...)
        fetched_at:       ISO time
    """
    from datetime import datetime
    try:
        from src.exports.excel_report import (
            _fetch_histock_top_buyer, _get_histock_stats, _reset_histock_stats,
        )
    except Exception as e:
        return {
            "top_buyer_index": {}, "stats": {"error": str(e)},
            "fetched_at": None,
        }

    _reset_histock_stats()

    sniper_ranking = limit_up_summary.get('sniper_ranking') or []
    master_sniper_ranking = limit_up_summary.get('master_sniper_ranking') or []

    # 收集 sniper master 買的漲停股 codes
    sniper_stock_codes = set()
    for sn in sniper_ranking:
        if sn.get('master') not in sniper_masters:
            continue
        for d in sn.get('limit_up_details') or []:
            code = d.get('code')
            if code:
                sniper_stock_codes.add(code)

    # Fetch histock (per unique stock)
    top_buyer_index: Dict[str, str] = {}
    cache: Dict[str, Optional[str]] = {}
    for code in sorted(sniper_stock_codes):  # deterministic order
        top_bno = _fetch_histock_top_buyer(code, cache, trade_date=trade_date)
        if top_bno:
            top_buyer_index[code] = top_bno

    # Inject flag into sniper_ranking (per-branch view)
    for sn in sniper_ranking:
        if sn.get('master') not in sniper_masters:
            continue
        branch_code = sn.get('branch_code') or ''
        for d in sn.get('limit_up_details') or []:
            code = d.get('code')
            top_bno = top_buyer_index.get(code)
            d['is_top_market_buyer'] = bool(top_bno) and top_bno == branch_code
            if top_bno:
                d['top_market_buyer_bno'] = top_bno

    # Inject flag into master_sniper_ranking (per-master aggregated view)
    # master_sniper_ranking 的 limit_up_codes 是 code list, 沒有 branch_code 資訊,
    # 所以無法直接判 is_top. 只在 raw_output 加 top-level index 供前端 lookup.

    stats = _get_histock_stats()
    return {
        "top_buyer_index": top_buyer_index,
        "stats": stats,
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
