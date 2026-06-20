"""
分點籌碼觀察站 - 完整版爬蟲 (v3.6)
功能：
  1. 爬取每個分點的「金額 (c=B)」和「張數 (c=E)」雙模式資料
  2. FIFO 部位追蹤，累積已實現損益（基準日 2026/4/21 起算）
  3. 資料 AES-256-GCM 加密
  4. 自動更新 positions.json 累積部位狀態
  5. 自動分類股票市場類型 (上市/上櫃/興櫃/ETF/KY/特別股)
  6. 整合個人標記 + 市場公認標記

模組架構 (v3.35.0 B1 拆三層):
  - crawler.py (本檔)      薄編排層: main() 9 階段 + re-export hub
  - crawler_fetch.py       抓取層: TWSE 分點雙模式爬取
  - crawler_pipeline.py    計算層: 溫度計 + FIFO 部位 + 彙總
  - crawler_output.py      輸出層: AES-256-GCM + gzip 加密
  - branches.py            分點清單 + 個人/市場標記
  - market_classifier.py   股票市場分類
"""
import requests
import re
import json
import time
import os
import sys
import random
import base64
from pathlib import Path
from collections import deque
from datetime import datetime, timezone, timedelta
from copy import deepcopy

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ========== 模組化 import ==========
from branches import (
    WATCHED_BRANCHES, get_unique_branches,
    MASTER_STYLES, STYLE_LABELS, LIMIT_UP_THRESHOLD, NEAR_LIMIT_UP_THRESHOLD,
    get_master_styles, get_masters_of_style,
)
from market_classifier import get_classifier, CATEGORY_LABELS, CATEGORY_LABELS_SIMPLE
from institutional import (
    fetch_all_public_data, compute_alignment, compute_floating_pnl_pct
)
import reports  # v3.9 週報/月報生成
import margin   # v3.11 融資融券
import industry_classifier  # v3.15.0 產業分類
import history as hist_mod  # v3.32.1: 改名避免跟 local var 衝突 (Python 3.12+ scope issue)
import futures  # v3.17 期貨選擇權籌碼

# ════════════════════════════════════════════════════════════════════
#  v3.35.0 (B1): crawler.py 拆三層 — 本檔保留 main() 編排 + 完整 re-export
#    crawler_fetch.py    抓取層: TWSE 分點雙模式爬取 + merge_rows
#    crawler_pipeline.py 計算層: 溫度計 + FIFO 部位 + 彙總/漲停/隔日沖驗證
#    crawler_output.py   輸出層: AES-256-GCM + gzip 加密
#  所有舊 `from crawler import X` 透過以下 re-export 完全不變 (7 個 module + tests)
# ════════════════════════════════════════════════════════════════════
from crawler_output import (
    PBKDF2_ITERATIONS, encrypt_data, decrypt_data,
)
from crawler_fetch import (
    TOP_N, DELAY_MIN, DELAY_MAX, COOL_DOWN_EVERY, COOL_DOWN_SECONDS,
    URL_TPL, HOME_URL, UA_POOL, ROW_PATTERN,
    parse_region, fetch_branch_mode, fetch_branch_combined,
)
from crawler_pipeline import (
    TW_TZ, now_tw, BASELINE_DATE, TEMP_THRESHOLDS,
    _temp_signal_score, _days_to_settlement,
    compute_chip_temperature, update_temp_history,
    load_positions, save_positions, _rollback_day, apply_day_to_positions,
    compute_period_summaries, compute_limit_up_summary,
    compute_next_day_flip_verification, compute_master_summaries,
)


# ════════════════════════════════════════════════════════════════════
# v3.47.0 後2: post-processing helpers (從 main() 抽出, 易測 + 易換序)
# 每個 helper 都 try/except 包圍, 不影響主流程
# ════════════════════════════════════════════════════════════════════
def _post_generate_reports(data_dir, password):
    """v3.9: 週報/月報自動生成 (僅在週一/月初觸發)."""
    try:
        generated = reports.maybe_generate_reports(
            data_dir, password, decrypt_data, encrypt_data
        )
        if generated:
            print(f"\n[報告] ✓ 產生 {len(generated)} 份報告")
            reports_list = reports.list_available_reports(data_dir)
            with open(data_dir / "reports_index.json", "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": now_tw().isoformat(),
                    "weekly": reports_list["weekly"],
                    "monthly": reports_list["monthly"],
                }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ 報告生成錯誤(不影響主流程): {e}")
        import traceback; traceback.print_exc()


def _post_build_master_profile(data_dir, password):
    """v3.30.14: master_profile 自動生成 (15 標籤 + per-branch + 族群 + 處置股)."""
    try:
        import master_profile as mp
        history = mp.load_history(str(data_dir), window_days=None, password=password)
        if history:
            mp_result = mp.build_all_profiles(history, data_dir=str(data_dir))
            mp_path = data_dir / "master_profiles.json"
            with open(mp_path, "w", encoding="utf-8") as f:
                json.dump(mp_result, f, ensure_ascii=False, indent=2)
            print(f"\n[Master Profile v3.30.14] ✓ {mp_result['master_count']} 大戶畫像 → {mp_path.name}")
            print(f"                          窗口 {mp_result['window_days']} 天 | "
                  f"族群={'✅' if mp_result.get('industry_classification_available') else '⚠️'} | "
                  f"處置股={'✅' if mp_result.get('disposal_classification_available') else '⚠️'}")
    except Exception as _mpe:
        print(f"  ⚠️ master_profile 生成錯誤(不影響主流程): {_mpe}")
        import traceback; traceback.print_exc()


def _post_upsert_db(raw_output, trade_date, data_dir):
    """v3.31.6 Phase 1.1: 把 raw_output upsert 進 SQLite OLAP DB."""
    try:
        import db_pipeline
        db_conn = db_pipeline.init_db(str(data_dir / "chip_radar_v2.db"))
        db_stats = db_pipeline.upsert_from_raw_dict(
            db_conn, raw_output, trade_date=trade_date,
            source='raw', source_file=f'{trade_date}.json'
        )
        db_conn.close()
        print(f"\n[DB v3.31.6] ✓ upsert {db_stats['daily_chips_rows']} rows → chip_radar_v2.db")
        print(f"             new: traders+{db_stats['traders']} branches+{db_stats['branches']} stocks+{db_stats['stocks']}")
    except Exception as _dbe:
        print(f"  ⚠️ DB pipeline 失敗 (不影響主流程): {type(_dbe).__name__}: {_dbe}")
        import traceback; traceback.print_exc()


def _post_archive_rotate(data_dir):
    """v3.31.6 Phase 1.1: Archive 分層 — hot < 7天 / warm 7-60 / cold ≥60."""
    try:
        import archive_manager
        archive_manager.rotate(str(data_dir), hot_days=7, warm_days=60)
    except Exception as _ae:
        print(f"  ⚠️ archive rotate 失敗 (不影響主流程): {type(_ae).__name__}: {_ae}")


def _post_auto_backfill_history(data_dir, password, industry_map):
    """v3.32.3: 自動回補 stock_history 缺失天數 (防止類似 v3.32.1 bug 再發生)."""
    try:
        _sh_path = data_dir / "stock_history.json"
        if not _sh_path.exists():
            return
        _sh = json.load(open(_sh_path, encoding='utf-8'))
        _existing = set(_sh.get('dates', []))
        _all_jsons = list(data_dir.glob('[0-9]'*8+'.json'))
        _archive = data_dir / 'archive'
        if _archive.exists():
            _all_jsons.extend(_archive.glob('[0-9]'*8+'.json'))
        _available = sorted(set(f.stem for f in _all_jsons))
        _missing = [d for d in _available if d not in _existing]
        if not _missing:
            return
        print(f"\n[Auto-Backfill v3.32.3] stock_history 缺 {len(_missing)} 天, 自動回補...")
        for _md in _missing[-10:]:   # 最多回補最近 10 天
            try:
                _jp = data_dir / f'{_md}.json'
                if not _jp.exists():
                    _jp = _archive / f'{_md}.json'
                if not _jp.exists():
                    continue
                with open(_jp, encoding='utf-8') as _f:
                    _enc = json.load(_f)
                if _enc.get('encrypted'):
                    _raw = json.loads(decrypt_data(_enc['data'], password))
                else:
                    _raw = _enc
                _dq = {}
                for _br in _raw.get('branches', []):
                    for _side in ('buys', 'sells'):
                        for _s in _br.get(_side, []):
                            _c = _s.get('code')
                            _bl = _s.get('buy_lot', 0) or 0
                            _ba = _s.get('buy_amt', 0) or 0
                            if _c and _bl > 0 and _ba > 0 and _c not in _dq:
                                _dq[_c] = {'close': round(_ba/_bl, 2), 'change_pct': 0}
                if _dq:
                    hist_mod.update_history(data_dir=data_dir, trade_date=_md,
                        daily_quotes_map=_dq, industry_map=industry_map or {},
                        branches_results=_raw.get('branches', []))
                    _fd = _raw.get('futures_data')
                    if _fd:
                        hist_mod.update_futures_history(data_dir=data_dir, trade_date=_md, futures_data=_fd)
                    print(f"  ✓ {_md} 回補 {len(_dq)} stocks" + (" + futures" if _fd else ""))
            except Exception as _be:
                print(f"  ⚠️ {_md} 回補失敗: {type(_be).__name__}")
    except Exception as _abf:
        print(f"  ⚠️ auto-backfill 失敗: {type(_abf).__name__}: {_abf}")


def _stage_quote_audit(results):
    """v3.50.0 後2 (Sprint 12): Quote 新鮮度 audit (從 main() L627-651 抽出).

    純 read + print, 不修改 results. 統計各個股 quote source 分布
    + lot 反推估算 + stale 警告.
    """
    _audit_fresh = 0
    _audit_stale = 0
    _audit_missing = 0
    _audit_sources = {}
    _audit_lot_estimated = 0
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            if s.get("quote_stale"):
                _audit_stale += 1
            elif s.get("close_price") is not None:
                _audit_fresh += 1
            else:
                _audit_missing += 1
            src = s.get("quote_source") or "none"
            _audit_sources[src] = _audit_sources.get(src, 0) + 1
            if s.get("lot_source") == "estimated_from_close":
                _audit_lot_estimated += 1
    print(f"[Quote Audit v3.27.3] fresh={_audit_fresh} / stale={_audit_stale} / missing={_audit_missing}")
    print(f"                     source: " + ", ".join(f"{k}={v}" for k, v in sorted(_audit_sources.items())))
    if _audit_lot_estimated:
        print(f"                     lot 反推估算: {_audit_lot_estimated} 筆 (高價股 TWSE Top 15 盲點)")
    if _audit_stale > 0:
        print(f"  🚨 警告:仍有 {_audit_stale} 筆 quote 標記 stale — MIS fallback 沒涵蓋到的全市場股票")
        print(f"           分點+法人欄位資料不受影響,但部分非優先股票顯示可能為舊資料")


def _stage_limit_up_audit(results, _prev_close_map):
    """v3.50.0 後2 (Sprint 12): Limit-Up 漲停判定 audit (從 main() L653-697 抽出).

    純 read + print, 不修改 results. 印出所有 is_limit_up=True 個股及判定依據.
    """
    from crawler_pipeline import LIMIT_UP_THRESHOLD
    _lu_audit = {}
    _lu_suspicious = []
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            code = s.get("code")
            if not code or code in _lu_audit:
                continue
            if s.get("is_limit_up"):
                _lu_audit[code] = {
                    'name': s.get('name', ''),
                    'close': s.get('close_price'),
                    'change_pct': s.get('change_pct'),
                    'source': s.get('quote_source', ''),
                    'prev_close': _prev_close_map.get(code),
                }
                _cp = s.get('change_pct') or 0
                if _cp < LIMIT_UP_THRESHOLD:
                    _lu_suspicious.append((code, s.get('name', ''), _cp, 'below_threshold'))
                elif _cp < 9.8:
                    _lu_suspicious.append((code, s.get('name', ''), _cp, 'near_boundary'))

    print(f"\n[Limit-Up Audit v3.27.4] 今日漲停股: {len(_lu_audit)} 檔 (LIMIT_UP_THRESHOLD={LIMIT_UP_THRESHOLD}%)")
    if _lu_audit:
        _sorted_lu = sorted(_lu_audit.items(), key=lambda x: x[1].get('change_pct') or 0, reverse=True)
        _show = _sorted_lu[:10]
        print(f"  Top 10: ", end="")
        print(" | ".join(f"{v['name']}({k}) {v['change_pct']}%" for k, v in _show))
        if len(_sorted_lu) > 10:
            _bottom3 = _sorted_lu[-3:]
            print(f"  Bottom3:", end="")
            print(" | ".join(f"{v['name']}({k}) {v['change_pct']}%" for k, v in _bottom3))
    if _lu_suspicious:
        print(f"  🚨 可疑漲停判定 ({len(_lu_suspicious)} 筆):")
        for _code, _name, _cp, _reason in _lu_suspicious:
            _pv = _prev_close_map.get(_code)
            print(f"    {_name}({_code}): change_pct={_cp}% reason={_reason}"
                  f"{f' prev_close={_pv}' if _pv else ''}")
    else:
        print(f"  ✅ 所有漲停判定一致 (change_pct ≥ {LIMIT_UP_THRESHOLD}%)")


def _stage_load_yesterday_branches(data_dir, trade_date, password):
    """v3.50.0 後2 (Sprint 12): 載昨日加密檔 + decrypt (從 main() L716-736 抽出).

    給 next_day_flip_verification 用. 找到 < trade_date 最近一檔加密 JSON,
    解密後返 branches list. 首日執行返 [].
    """
    try:
        existing_dates_sorted = sorted(
            [f.stem for f in data_dir.glob("*.json")
              if f.stem.isdigit() and len(f.stem) == 8 and f.stem != trade_date],
            reverse=True
        )
        if not existing_dates_sorted:
            return []
        yest_date = existing_dates_sorted[0]
        yest_file = data_dir / f"{yest_date}.json"
        with open(yest_file, "r", encoding="utf-8") as f:
            yest_raw = json.load(f)
        if yest_raw.get("encrypted"):
            yest_plain = decrypt_data(yest_raw["data"], password)
            yest_data = json.loads(yest_plain)
            branches = yest_data.get("branches", [])
            print(f"  ✓ 載入昨日資料 ({yest_date}): {len(branches)} 個分點")
            return branches
        return []
    except Exception as e:
        print(f"  ⚠️ 昨日資料載入失敗: {e}（首日執行此為正常現象）")
        return []


def _post_refresh_tier2_market_data(data_dir):
    """v3.48.0 Tier 2 整合: 更新 3 個獨立 fetcher cache (注意/借券/除權息).

    Tier 2 main_force_cost 已直接注入 raw_output (見 main() raw_output 之後).
    這 3 個是全市場 daily 資料, 各自有獨立 data/*_map.json cache.
    前端從各 JSON 獨立 fetch (不打 raw_output, 減少 daily JSON 膨脹).
    """
    # 注意股 (TWSE announcement/notice)
    try:
        from attention_fetcher import get_attention_map
        a = get_attention_map(str(data_dir))
        if a:
            print(f"[Tier2 v3.48.0] ✓ 注意股 {a.get('count', 0)} 檔 "
                  f"(stale={a.get('stale', False)})")
    except Exception as _ae:
        print(f"  ⚠️ attention_fetcher 失敗: {type(_ae).__name__}: {_ae}")

    # 借券+融券 (TWSE TWTASU)
    try:
        from short_lending_fetcher import get_short_lending_map
        s = get_short_lending_map(str(data_dir))
        if s:
            print(f"[Tier2 v3.48.0] ✓ 借券+融券 {s.get('count_with_activity', 0)} 檔 "
                  f"(Top borrow {len(s.get('top_borrow_sell', []))} 名)")
    except Exception as _se:
        print(f"  ⚠️ short_lending_fetcher 失敗: {type(_se).__name__}: {_se}")

    # 除權息預告 (TWSE TWT48U)
    try:
        from dividend_fetcher import get_dividend_calendar
        d = get_dividend_calendar(str(data_dir))
        if d:
            print(f"[Tier2 v3.48.0] ✓ 除權息預告 {d.get('count', 0)} 檔 "
                  f"(未來 30 天 {len(d.get('upcoming_30d', []))} 檔)")
    except Exception as _de:
        print(f"  ⚠️ dividend_fetcher 失敗: {type(_de).__name__}: {_de}")


def _post_disposal_snapshot(data_dir):
    """v3.31.16+17: 處置股每日 JSON 快照 + DB 雙份."""
    try:
        from disposal_fetcher import save_daily_snapshot
        snap_path = save_daily_snapshot(str(data_dir))
        if snap_path:
            print(f"[Disposal History v3.31.17] ✓ 快照 → {snap_path.name}")
            try:
                import db_pipeline as _dbp
                _db_conn = _dbp.init_db(str(data_dir / "chip_radar_v2.db"))
                _snap = json.loads(snap_path.read_text(encoding='utf-8'))
                _n = _dbp.upsert_disposal_snapshot(_db_conn, _snap)
                _db_conn.close()
                print(f"                          + DB {_n} rows")
            except Exception as _dbe2:
                print(f"  ⚠️ disposal → DB 失敗: {type(_dbe2).__name__}")
    except Exception as _dse:
        print(f"  ⚠️ disposal snapshot 失敗 (不影響主流程): {type(_dse).__name__}: {_dse}")


def main():
    password = os.environ.get("CHIP_RADAR_PASSWORD", "").strip()
    if not password:
        print("❌ 環境變數 CHIP_RADAR_PASSWORD 未設定！")
        sys.exit(1)
    
    if len(password) < 6:
        print("⚠️  警告：密碼太短（< 6 字元）")
    
    print(f"[{now_tw().strftime('%Y-%m-%d %H:%M:%S')}] 開始爬取 {len(WATCHED_BRANCHES)} 個分點 (🔒 加密+📊 FIFO 模式)")
    
    # 去除重複分點
    seen = set()
    unique_branches = []
    for b in WATCHED_BRANCHES:
        if b["code"] not in seen:
            seen.add(b["code"])
            unique_branches.append(b)
    if len(unique_branches) < len(WATCHED_BRANCHES):
        print(f"  （去重後 {len(unique_branches)} 個分點）")
    
    # ===== 載入股票分類器（規則 + API + 快取）=====
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    today_str = now_tw().strftime("%Y%m%d")
    classify_stock_fn, _ = get_classifier(data_dir, today_str)
    
    # 爬取所有分點
    results = []
    trade_date = None
    success_count = 0
    fail_count = 0
    empty_count = 0
    
    for i, branch in enumerate(unique_branches):
        code = branch["code"]
        print(f"  [{i+1}/{len(unique_branches)}] {branch['master']} | {branch['name']} ({code}) ", end="", flush=True)
        
        data = fetch_branch_combined(code)
        
        if data["error"]:
            print(f"❌ {data['error']}")
            fail_count += 1
        elif not data["buys"] and not data["sells"]:
            print(f"⚪ 無資料")
            empty_count += 1
        else:
            # 檢查是否有張數（沒有的話簡單提示）
            has_lot = any(s.get("buy_lot", 0) > 0 for s in data["buys"])
            lot_hint = "✓" if has_lot else "⚠金額only"
            print(f"{lot_hint} 買{len(data['buys'])}/賣{len(data['sells'])}")
            success_count += 1
            if data["date"] and not trade_date:
                trade_date = data["date"]
        
        # 為每檔股票加上市場分類
        for s in data.get("buys", []):
            cinfo = classify_stock_fn(s["code"], s["name"])
            s["market_type"] = cinfo["category"]              # 細分 (8 類)
            s["market_type_simple"] = cinfo["category_simple"]  # 簡單 (5 類)
            s["market_type_basic"] = cinfo["category_basic"]    # 最簡 (3 類)
            s["industry"] = cinfo.get("industry", "")
            s["is_ky"] = cinfo.get("is_ky", False)
        for s in data.get("sells", []):
            cinfo = classify_stock_fn(s["code"], s["name"])
            s["market_type"] = cinfo["category"]
            s["market_type_simple"] = cinfo["category_simple"]
            s["market_type_basic"] = cinfo["category_basic"]
            s["industry"] = cinfo.get("industry", "")
            s["is_ky"] = cinfo.get("is_ky", False)
        
        results.append({
            **branch,  # 包含 code, name, master, tags_personal, tags_market
            "date": data["date"],
            "buys": data["buys"],
            "sells": data["sells"],
            "error": data["error"],
        })
        
        if i < len(unique_branches) - 1:
            if (i + 1) % COOL_DOWN_EVERY == 0:
                print(f"    ⏸  休息 {COOL_DOWN_SECONDS} 秒...")
                time.sleep(COOL_DOWN_SECONDS)
            else:
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    if not trade_date:
        trade_date = now_tw().strftime("%Y%m%d")
    
    # ════════════════════════════════════════════════════════════════
    # 假日 / 全部失敗 偵測：保留前一日資料，不寫新檔
    # ════════════════════════════════════════════════════════════════
    # 判斷條件:
    #   - 全部分點都失敗或無資料 → 視為假日/系統異常
    #   - 不更新 latest.json / 不寫新日期檔 / 不更新 positions
    #   - 確保前一日有效資料保留可看
    
    if success_count == 0:
        print(f"\n⚠️ ════════════════════════════════════════════════")
        print(f"  全部 {len(unique_branches)} 個分點皆無資料")
        print(f"  失敗: {fail_count} / 無資料: {empty_count}")
        print(f"  推測為假日 / 系統異常 / 富邦頁面變更")
        print(f"  → 保留前一日資料，不寫入新檔，不影響網站運作")
        print(f"════════════════════════════════════════════════════\n")
        # 正常退出（exit code 0），讓 GitHub Actions 不顯示紅字
        return
    
    # ════════════════════════════════════════════════════════════════
    # 正常流程：FIFO 累積 + 寫入新資料
    # ════════════════════════════════════════════════════════════════
    
    # ===== 更新 FIFO 部位 =====
    print(f"\n[FIFO] 更新累積部位...")
    positions = load_positions(data_dir, password)
    apply_day_to_positions(positions, trade_date, results)
    
    # ════════════════════════════════════════════════════════════════
    # v3.7 新增：抓取三大法人 + 收盤行情，注入到每檔股票
    # v3.14.2: 傳入 priority_codes 供 MIS fallback 補抓
    # ════════════════════════════════════════════════════════════════
    print(f"\n[公開資訊] 抓取三大法人與收盤行情...")
    
    # 收集我的分點出現的所有股票代號（供 fallback 使用）
    priority_codes = set()
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            code = s.get("code")
            if code:
                priority_codes.add(code)
    priority_codes = list(priority_codes)
    print(f"  (我的分點今日涉及 {len(priority_codes)} 檔個股)")
    
    # ════════════════════════════════════════════════════════════════
    # v3.28: 預先從 stock_history 構建 prev_close_map
    # 取代 institutional.py 的 `prev_close = close - change` 反推
    # 在 fetch 階段就用正確 prev_close 算 change_pct, 不需事後 L1 修正
    # ════════════════════════════════════════════════════════════════
    _prev_close_map_for_fetch = {}
    try:
        _sh_path = data_dir / "stock_history.json"
        if _sh_path.exists():
            with open(_sh_path, 'r', encoding='utf-8') as _f:
                _sh = json.load(_f)
            _sh_dates = sorted(_sh.get('dates', []))
            _prev_dates = [d for d in _sh_dates if d < trade_date]
            if _prev_dates:
                _prev_date_for_fetch = _prev_dates[-1]
                _sh_stocks = _sh.get('stocks', {})
                for _code, _stk in _sh_stocks.items():
                    _prev_c = _stk.get('daily', {}).get(_prev_date_for_fetch, {}).get('close')
                    if _prev_c and _prev_c > 0:
                        _prev_close_map_for_fetch[_code] = _prev_c
                print(f"  [v3.28] prev_close_map 從 history({_prev_date_for_fetch}) 載入 {len(_prev_close_map_for_fetch)} 檔")
    except Exception as _e:
        print(f"  [v3.28] prev_close_map 載入失敗 ({_e}),institutional.py fallback 回 close-change 反推")

    try:
        institutional_map, daily_quotes_map = fetch_all_public_data(
            trade_date,
            priority_codes=priority_codes,
            prev_close_map=_prev_close_map_for_fetch,
        )
        # P0-2 (v3.38.0): non-empty + shape assertion
        # 防 silent corruption: 空 dict 通過下游 (master_profile / 三大法人排行)
        # 會把「無資料」當「無交易」寫入, 污染 42 天視窗計算
        # 此處只有「STAGE=full 主排程」要 raise; 兜底排程 / margin_only 跳過
        STAGE_CHECK = os.environ.get('CHIP_RADAR_STAGE', 'full').strip().lower()
        if STAGE_CHECK == 'full':
            if not institutional_map and not daily_quotes_map:
                # 兩個都空 → 必定上游錯, raise 讓 workflow 標 fail
                raise RuntimeError(
                    "P0-2 silent corruption guard: institutional_map + "
                    "daily_quotes_map 雙空, 上游 fetch_all_public_data 異常 "
                    "(可能 TWSE OpenAPI stale 或 token rate limit)"
                )
            if institutional_map and not isinstance(next(iter(institutional_map.values())), dict):
                raise RuntimeError(
                    f"P0-2 shape guard: institutional_map value 非 dict "
                    f"({type(next(iter(institutional_map.values())))})"
                )
            if daily_quotes_map and not isinstance(next(iter(daily_quotes_map.values())), dict):
                raise RuntimeError(
                    f"P0-2 shape guard: daily_quotes_map value 非 dict "
                    f"({type(next(iter(daily_quotes_map.values())))})"
                )
            # 部分空也警告 (但不 raise, 因 TWSE 偶爾有單邊端點失敗)
            if not institutional_map:
                print("  🚨 [P0-2 warn] institutional_map 空但 quotes 有資料 → 法人面缺漏, 下游降級")
            if not daily_quotes_map:
                print("  🚨 [P0-2 warn] daily_quotes_map 空但 institutional 有資料 → 行情缺漏, L1/L2 cross-check 失效")
    except Exception as e:
        print(f"  ⚠️ 公開資訊抓取整體失敗: {e}（繼續執行，不影響主流程）")
        institutional_map, daily_quotes_map = {}, {}
    
    # ════════════════════════════════════════════════════════════════
    # v3.27.4 L1: change_pct 交叉驗證 — 用 stock_history 的前日 close
    # 取代 TWSE/TPEx 的反推 prev_close,消除 Change 欄位錯誤風險
    # ════════════════════════════════════════════════════════════════
    _prev_close_map = {}  # {code: prev_day_close}
    _l1_overrides = 0
    try:
        _sh_path = data_dir / "stock_history.json"
        if _sh_path.exists() and daily_quotes_map:
            with open(_sh_path, 'r', encoding='utf-8') as _f:
                _sh = json.load(_f)
            _sh_dates = sorted(_sh.get('dates', []))
            # Find the trading day immediately before trade_date
            _prev_dates = [d for d in _sh_dates if d < trade_date]
            if _prev_dates:
                _prev_date = _prev_dates[-1]
                _sh_stocks = _sh.get('stocks', {})
                for _code, _q in daily_quotes_map.items():
                    _s_hist = _sh_stocks.get(_code, {}).get('daily', {}).get(_prev_date, {})
                    _prev_c = _s_hist.get('close')
                    if _prev_c and _prev_c > 0:
                        _prev_close_map[_code] = _prev_c
                        # Independently verify change_pct
                        _cur_close = _q.get('close', 0)
                        if _cur_close and _cur_close > 0:
                            _verified_pct = round((_cur_close - _prev_c) / _prev_c * 100, 2)
                            _api_pct = _q.get('change_pct', 0)
                            _diff = abs(_verified_pct - _api_pct)
                            if _diff > 1.0:
                                print(f"  ⚠️ [L1 Override] {_code}: API change_pct={_api_pct}% "
                                      f"vs history-verified={_verified_pct}% (diff={_diff:.2f}%) "
                                      f"prev_close={_prev_c} cur_close={_cur_close} → 採用 verified")
                                _q['change_pct'] = _verified_pct
                                _q['change_pct_source'] = 'history_verified'
                                _q['change_pct_api_original'] = _api_pct
                                _l1_overrides += 1
                            else:
                                _q['change_pct_source'] = 'api_confirmed'
                print(f"[L1 交叉驗證] prev_date={_prev_date} | 可比對 {len(_prev_close_map)} 檔 | 修正 {_l1_overrides} 筆")
    except Exception as _e:
        print(f"  [L1] stock_history 載入失敗 ({_e}),跳過交叉驗證")

    # 為每檔股票注入三大法人資料 + 收盤行情 + 浮盈
    inst_inject_count = 0
    quote_inject_count = 0
    align_aligned = 0
    align_opposing = 0
    
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            code = s.get("code")
            if not code:
                continue
            
            # ── 三大法人 ──
            inst = institutional_map.get(code)
            if inst:
                s["inst_foreign_net_lot"] = inst["foreign_net_lot"]
                s["inst_trust_net_lot"] = inst["trust_net_lot"]
                s["inst_dealer_net_lot"] = inst["dealer_net_lot"]
                s["inst_total_net_lot"] = inst["total_net_lot"]
                
                # 計算分點 vs 外資對齊狀況（張數版本）
                branch_net = s.get("net_lot", 0) or 0
                s["align_with_foreign"] = compute_alignment(branch_net, inst["foreign_net_lot"])
                if s["align_with_foreign"] == "aligned":
                    align_aligned += 1
                elif s["align_with_foreign"] == "opposing":
                    align_opposing += 1
                
                inst_inject_count += 1
            else:
                s["inst_foreign_net_lot"] = None
                s["inst_trust_net_lot"] = None
                s["inst_dealer_net_lot"] = None
                s["inst_total_net_lot"] = None
                s["align_with_foreign"] = "neutral"
            
            # ── 收盤行情 + 浮盈 ──
            quote = daily_quotes_map.get(code)
            if quote:
                s["close_price"] = quote["close"]
                s["change_pct"] = quote["change_pct"]
                s["volume_lot"] = quote["volume_lot"]
                # v3.14.2: 標記資料來源 (twse / tpex / mis_tse / mis_otc)
                s["quote_source"] = quote.get("source", "")
                s["quote_date"] = quote.get("quote_date", "")  # v3.27.3: ROC 日期
                # v3.27.3: 真實 stale 檢查 (有資料但日期不對)
                _expected_roc = ""
                if trade_date and len(trade_date) == 8 and trade_date.isdigit():
                    _expected_roc = f"{int(trade_date[:4]) - 1911:03d}{trade_date[4:]}"
                _qd = (quote.get("quote_date") or "").strip()
                s["quote_stale"] = bool(_expected_roc and _qd and _qd != _expected_roc)

                # ════════════════════════════════════════════════════════════
                # v3.27.2 高價股盲點修補
                # TWSE 分點頁面只 publish Top 15 金額榜 + Top 15 張數榜。
                # 創意(5210元)/緯穎(5200元)/台積電(2290元) 等高價股因「張數少」
                # 擠不進張數榜 → buy_lot=0 但 buy_amt 幾億,Excel/網站顯示
                # 「0 張 + 幾億金額」嚴重誤導。
                # 用 close 反推: amt(仟元) = lot(張) × close(元/股), 即 lot = amt/close
                # 加 lot_source 旗標保留誠實性,下游可區分真資料 vs 估算
                # ════════════════════════════════════════════════════════════
                cp_close = quote["close"]
                lot_source = "twse"  # 預設: TWSE 原始排行榜資料
                if cp_close and cp_close > 0:
                    buy_amt_k = s.get("buy_amt", 0) or 0
                    sell_amt_k = s.get("sell_amt", 0) or 0
                    buy_lot_raw = s.get("buy_lot", 0) or 0
                    sell_lot_raw = s.get("sell_lot", 0) or 0
                    estimated = False
                    # 買進: 高價股「金額榜上 + 張數榜沒上」→ 反推張數
                    if buy_lot_raw == 0 and buy_amt_k > 0:
                        s["buy_lot"] = max(1, round(buy_amt_k / cp_close))
                        s["buy_avg"] = round(cp_close, 2)
                        estimated = True
                    # 賣出: 同上
                    if sell_lot_raw == 0 and sell_amt_k > 0:
                        s["sell_lot"] = max(1, round(sell_amt_k / cp_close))
                        s["sell_avg"] = round(cp_close, 2)
                        estimated = True
                    # 反向: 低價股「張數榜上 + 金額榜沒上」→ 反推金額
                    # amt(仟元) = lot(張) × 1000股 × close(元/股) / 1000 = lot × close
                    if buy_amt_k == 0 and buy_lot_raw > 0:
                        s["buy_amt"] = int(round(buy_lot_raw * cp_close))
                        s["buy_avg"] = round(cp_close, 2)
                        estimated = True
                    if sell_amt_k == 0 and sell_lot_raw > 0:
                        s["sell_amt"] = int(round(sell_lot_raw * cp_close))
                        s["sell_avg"] = round(cp_close, 2)
                        estimated = True
                    if estimated:
                        # 重算 net 欄位以保持一致
                        s["net_amt"] = (s.get("buy_amt", 0) or 0) - (s.get("sell_amt", 0) or 0)
                        s["net_lot"] = (s.get("buy_lot", 0) or 0) - (s.get("sell_lot", 0) or 0)
                        lot_source = "estimated_from_close"
                s["lot_source"] = lot_source

                # 計算當日浮盈（買均 vs 收盤）
                buy_avg = s.get("buy_avg", 0) or 0
                if buy_avg and quote["close"]:
                    s["floating_pnl_pct"] = compute_floating_pnl_pct(buy_avg, quote["close"])
                else:
                    s["floating_pnl_pct"] = None
                
                # v3.28 精確漲跌停判定 (取代 v3.12 的 9.5% threshold 近似)
                # 用 tick-size 規則算精確漲停價, fallback 才用 9.5% 近似
                cp = quote["change_pct"] or 0
                _prev_c_for_lu = quote.get("prev_close") or _prev_close_map_for_fetch.get(code)
                if _prev_c_for_lu and _prev_c_for_lu > 0 and quote.get("close"):
                    from price_utils import is_limit_up_exact, calc_limit_up_price
                    s["is_limit_up"] = is_limit_up_exact(quote["close"], _prev_c_for_lu)
                    s["limit_up_price"] = calc_limit_up_price(_prev_c_for_lu)
                    s["limit_up_source"] = "exact"
                else:
                    # fallback: 沒有 prev_close 仍用 9.5% 近似
                    s["is_limit_up"] = cp >= LIMIT_UP_THRESHOLD
                    s["limit_up_price"] = None
                    s["limit_up_source"] = "approximate"
                s["is_near_limit_up"] = cp >= NEAR_LIMIT_UP_THRESHOLD
                
                quote_inject_count += 1
            else:
                s["close_price"] = None
                s["change_pct"] = None
                s["volume_lot"] = None
                s["floating_pnl_pct"] = None
                s["is_limit_up"] = False
                s["is_near_limit_up"] = False
                s["quote_source"] = None
                s["quote_stale"] = True  # 沒抓到，標記為過時
                s["lot_source"] = "twse"  # 沒 close 無法估算,維持原 TWSE 排行榜資料
    
    print(f"[公開資訊] ✓ 注入完成 — 三大法人 {inst_inject_count} 筆 / 收盤行情 {quote_inject_count} 筆")
    print(f"          對齊統計：與外資同向 {align_aligned} / 反向 {align_opposing}")

    # v3.50.0 後2 (Sprint 12): quote audit + limit-up audit 抽 helper
    _stage_quote_audit(results)
    _stage_limit_up_audit(results, _prev_close_map)

    # 計算各期間匯總（含當日風格指標）
    summaries = compute_period_summaries(positions, trade_date, today_branches_data=results)
    
    # 高手聚合摘要
    master_summaries = compute_master_summaries(summaries, unique_branches, today_branches_data=results)
    print(f"[聚合] 高手視角合併完成，共 {len(master_summaries)} 位高手")
    
    # v3.12 漲停狙擊匯總
    limit_up_summary = compute_limit_up_summary(results, unique_branches)
    print(f"[漲停狙擊] 我的分點買到 {limit_up_summary['limit_up_bought_count']} 檔漲停股")
    if limit_up_summary['sniper_ranking']:
        top_sniper = limit_up_summary['sniper_ranking'][0]
        print(f"  🎯 最強狙擊手：{top_sniper['master']} - {top_sniper['branch_name']}"
              f"（買 {top_sniper['limit_up_stocks_bought']} 檔漲停，{top_sniper['total_limit_up_buy_amt']:.0f} 萬）")
    if limit_up_summary['consensus_limit_up']:
        print(f"  👥 多位高手共買漲停股：{len(limit_up_summary['consensus_limit_up'])} 檔")
    
    # v3.13 隔日沖驗證 — 比對昨日漲停買進 × 今日賣超
    # v3.50.0 後2 (Sprint 12): 抽 _stage_load_yesterday_branches helper
    print(f"\n[隔日沖驗證] 比對昨日漲停買進 vs 今日賣超...")
    yesterday_branches_data = _stage_load_yesterday_branches(data_dir, trade_date, password)
    
    next_day_verification = compute_next_day_flip_verification(
        results, yesterday_branches_data, unique_branches)
    
    if next_day_verification["is_first_day"]:
        print(f"  ℹ️ 首日執行，明日才能開始比對")
    else:
        vf = next_day_verification["verified_flips"]
        pp = next_day_verification["pending_positions"]
        full_flips = [r for r in vf if r["status"] == "full_flip"]
        partial_flips = [r for r in vf if r["status"] == "partial_flip"]
        print(f"  ✓ 完全出貨 (flip>=90%): {len(full_flips)} 筆")
        print(f"  ✓ 部分出貨 (flip>=30%): {len(partial_flips)} 筆")
        print(f"  ⏸️ 尚未出貨（留倉中）: {len(pp)} 筆")
        if next_day_verification["flipper_scorecard"]:
            top = next_day_verification["flipper_scorecard"][0]
            print(f"  🎯 最高出貨率：{top['master']} - 整體 {top['overall_flip_ratio']:.1f}% "
                  f"（昨買 {top['total_yesterday_buy_lot']} 張 → 今賣 {top['total_today_sell_lot']} 張）")
    
    save_positions(positions, data_dir, password)
    print(f"[FIFO] 累積部位已更新，涉及 {len(positions.get('branches', {}))} 個分點")
    
    # ════════════════════════════════════════════════════════════════
    # v3.7 新增：建立全市場法人排行（前 100 名各類）
    # ════════════════════════════════════════════════════════════════
    print(f"[公開資訊] 建立全市場排行...")
    
    # 為了讓前端能查股票名稱，建立 code → name 對照（從分點資料）
    code_to_name = {}
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            if s.get("code") and s.get("name"):
                code_to_name[s["code"]] = s["name"]
    # 補上沒在分點裡的（從收盤行情順便取）
    # （這些股票富邦分點沒交易，但有市場活動）
    
    def build_inst_ranking(field_key: str, top_n: int = 100):
        """從 institutional_map 建立某類法人排行"""
        rows = []
        for code, info in institutional_map.items():
            net = info.get(field_key, 0) or 0
            if abs(net) < 1:
                continue
            quote = daily_quotes_map.get(code, {})
            rows.append({
                "code": code,
                "name": code_to_name.get(code, ""),  # 名稱可能空，前端要 fallback
                "net_lot": net,
                "close": quote.get("close"),
                "change_pct": quote.get("change_pct"),
                "market_source": info.get("source", ""),  # twse/tpex
            })
        # 同時排正向（買超）和負向（賣超）
        rows_buy = sorted([r for r in rows if r["net_lot"] > 0], key=lambda x: -x["net_lot"])[:top_n]
        rows_sell = sorted([r for r in rows if r["net_lot"] < 0], key=lambda x: x["net_lot"])[:top_n]
        return {"buy": rows_buy, "sell": rows_sell}
    
    institutional_rankings = {
        "foreign": build_inst_ranking("foreign_net_lot"),
        "trust": build_inst_ranking("trust_net_lot"),
        "dealer": build_inst_ranking("dealer_net_lot"),
        "total": build_inst_ranking("total_net_lot"),
    }
    print(f"  ✓ 外資買超前 {len(institutional_rankings['foreign']['buy'])} / "
          f"投信 {len(institutional_rankings['trust']['buy'])} / "
          f"自營 {len(institutional_rankings['dealer']['buy'])}")
    
    # ════════════════════════════════════════════════════════════════
    # v3.11 新增：融資融券抓取 + 智慧注入 + 排行榜
    # v3.14.4 升級：加入 HiStock 日期驗證 + STAGE 模式
    # ════════════════════════════════════════════════════════════════
    STAGE = os.environ.get('CHIP_RADAR_STAGE', 'full').strip().lower()
    print(f"\n[融資融券] 抓取全市場融資融券資料... (STAGE={STAGE})")
    margin_all = {}
    margin_filtered = {}
    margin_rankings = {}
    margin_inject_count = 0
    margin_verification = None  # v3.14.4
    
    try:
        margin_result = margin.fetch_all_margin(verify_date=True)
        margin_all = margin_result.get('data', {})
        margin_verification = margin_result.get('verification')
        
        if margin_all:
            # 注入到每檔分點個股（無論是否 Top 100）
            margin_inject_count = margin.inject_margin_into_stocks(results, margin_all)
            print(f"[融資融券] ✓ 注入 {margin_inject_count} 筆分點個股")
            
            # 智慧混合策略：我的分點個股 + Top 100 + 使用率高 + 券資比高
            my_branch_codes = set()
            for br in results:
                for s in (br.get("buys", []) + br.get("sells", [])):
                    if s.get("code"):
                        my_branch_codes.add(s["code"])
            
            target_codes = margin.select_target_codes(margin_all, my_branch_codes, top_n=100)
            margin_filtered = margin.filter_margin_data(margin_all, target_codes)
            print(f"[融資融券] ✓ 智慧混合：保留 {len(margin_filtered)} 檔"
                  f"（我的 {len(my_branch_codes)} + 全市場 Top）")
            
            # 全市場排行榜
            margin_rankings = margin.build_margin_rankings(margin_all, top_n=30)
            print(f"[融資融券] ✓ 全市場排行榜 (7 類 × Top 30)")
    except Exception as e:
        print(f"  ⚠️ 融資融券抓取失敗: {e}（不影響主流程）")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.37.0 stage 5.5: 融資維持率估算 + 注入 (B5+B6 後新增)
    # ════════════════════════════════════════════════════════════════
    margin_maint_summary = None
    margin_maint_inject = None
    try:
        import margin_maintenance
        # 讀 stock_history (給 30 日均價估算用)
        sh_path = Path(data_dir) / 'stock_history.json'
        stock_history = None
        if sh_path.exists():
            try:
                with open(sh_path, 'r', encoding='utf-8') as f:
                    stock_history = json.load(f)
            except Exception:
                pass
        print(f"\n[融資維持率] 計算個股市場估算維持率 (30日均價反推)...")
        margin_maint_inject = margin_maintenance.inject_maintenance_into_stocks(
            results, margin_all, daily_quotes_map, stock_history)
        margin_maint_summary = margin_maint_inject.get('summary')
        counts = (margin_maint_summary or {}).get('counts', {})
        print(f"  ✓ 注入 {margin_maint_inject['computed']} 筆分點個股維持率")
        print(f"  ✓ 全市場: 健康 {counts.get('healthy',0)} / 警戒 {counts.get('watch',0)} / "
              f"高風險 {counts.get('high_risk',0)} / 斷頭區 {counts.get('margin_call',0)}")
        if margin_maint_inject.get('margin_call_codes'):
            print(f"  🚨 斷頭區 ({len(margin_maint_inject['margin_call_codes'])} 檔, 分點命中): "
                  f"{margin_maint_inject['margin_call_codes'][:10]}")
    except Exception as e:
        print(f"  ⚠️ 維持率計算失敗: {e} (不影響主流程)")

    # ════════════════════════════════════════════════════════════════
    # v3.15.0 新增：產業分類注入
    # ════════════════════════════════════════════════════════════════
    industry_map = {}
    industry_inject_count = 0
    try:
        print(f"\n[產業分類] 建立/讀取產業對照表...")
        industry_map = industry_classifier.get_industry_map(data_dir)
        industry_inject_count = industry_classifier.inject_industry_into_stocks(results, industry_map)
        print(f"[產業分類] ✓ 注入 {industry_inject_count} 筆分點個股產業資訊")
        
        # 也注入到 margin_filtered (前端排行榜用)
        for code, m in margin_filtered.items():
            ind = industry_map.get('stock_industry', {}).get(code)
            if ind:
                m['industry'] = ind
    except Exception as e:
        print(f"  ⚠️ 產業分類失敗: {e}（不影響主流程）")
        import traceback; traceback.print_exc()

    # ════════════════════════════════════════════════════════════════
    # v3.37.0 stage 6.5: TDCC 集保大戶持股注入 (週頻 cache, 不打網路)
    # ════════════════════════════════════════════════════════════════
    tdcc_inject = None
    try:
        import tdcc_holdings
        tdcc_cache = tdcc_holdings.load_holdings_cache(data_dir)
        if tdcc_cache:
            tdcc_inject = tdcc_holdings.inject_holdings_into_stocks(results, tdcc_cache)
            meta = tdcc_inject.get('metadata') or {}
            print(f"\n[TDCC 集保] 注入 {tdcc_inject['injected']} 筆分點個股持股結構 "
                  f"(資料期 {meta.get('effective_date','?')} / {meta.get('effective_week','?')})")
        else:
            print(f"\n[TDCC 集保] ⏭️ tdcc_holdings.json 不存在 (週六 workflow 還沒跑)")
    except Exception as e:
        print(f"  ⚠️ TDCC 注入失敗: {e} (不影響主流程)")

    # ════════════════════════════════════════════════════════════════
    # v3.40.0 B6 (機構級 P0): 操縱 / 對敲 / 出貨偵測
    # 拉抬 (A_pump) + Wash trade (B_wash) + 出貨 (C_distribution)
    # 輸出 data/red_flags.json + tab 13 detail popup 顯示
    # ════════════════════════════════════════════════════════════════
    red_flags_result = None
    try:
        import manipulation_flags
        # 嘗試載入 60 天 history 給 C_distribution 規則用 (純結構, 不依賴密碼)
        _mf_history = None
        try:
            # 用 master_profile.load_history 同邏輯但無密碼僅讀 stock_history
            # 簡單做法: stage 6.5 已注入分點到 results, 不直接需要密碼
            # C 規則需 30 天分點 sell_lot, 改用 master_profile cache 風格
            from master_profile import load_history as _mp_load_history
            _pw = os.environ.get('CHIP_RADAR_PASSWORD', '')
            if _pw:
                _mf_history = _mp_load_history(data_dir, 30, _pw)
        except Exception:
            pass
        red_flags_result = manipulation_flags.compute_all_flags(
            results, trade_date, history=_mf_history, data_dir=data_dir
        )
        print(manipulation_flags.format_summary(red_flags_result))
    except Exception as e:
        print(f"  ⚠️ 操縱偵測失敗: {e} (不影響主流程)")
    
    # ════════════════════════════════════════════════════════════════
    # v3.15.2 新增：歷史資料累積 (for 三線比較圖)
    # ════════════════════════════════════════════════════════════════
    try:
        hist_mod.update_history(
            data_dir=data_dir,
            trade_date=trade_date,
            daily_quotes_map=daily_quotes_map,
            industry_map=industry_map,
            branches_results=results,
        )
    except Exception as e:
        print(f"  ⚠️ 歷史累積失敗: {e}(不影響主流程)")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.17 新增:期貨選擇權籌碼
    # ════════════════════════════════════════════════════════════════
    futures_data = {}
    try:
        print(f"\n[期貨籌碼] 抓取 TAIFEX 期貨/選擇權/大額交易人...")
        futures_data = futures.fetch_all_futures_data(trade_date)
        # 印出關鍵摘要
        summary = futures_data.get('summary', {})
        if summary:
            print(f"  ✓ 外資等效大台淨 OI: {summary.get('foreign_equivalent_net_oi', 0):,} 口")
            print(f"  ✓ 散戶小台淨 OI (推算): {summary.get('retail_mxf_net_oi', 0):,} 口")
            pc = summary.get('pc_ratio_oi')
            if pc:
                print(f"  ✓ P/C Ratio: {pc}")
            t10_ratio = summary.get('top10_long_ratio')
            if t10_ratio:
                print(f"  ✓ 十大交易人買方集中度: {t10_ratio*100:.1f}%")
            # v3.18: 新指標
            near_close = summary.get('near_month_close')
            if near_close:
                near_chg_pct = summary.get('near_month_change_pct', 0)
                print(f"  ✓ TX 近月收盤: {near_close} ({near_chg_pct:+.2f}%)")
                spread = summary.get('spread_near_next')
                if spread is not None:
                    print(f"  ✓ 跨月價差 (次-近): {spread:+}")
            ah_close = summary.get('after_hours_near_close')
            if ah_close:
                ah_chg_pct = summary.get('after_hours_near_change_pct', 0)
                print(f"  ✓ 夜盤近月收盤: {ah_close} ({ah_chg_pct:+.2f}%)")
            ah_foreign = summary.get('ah_foreign_equivalent_net_trade')
            if ah_foreign is not None:
                print(f"  ✓ 夜盤外資等效大台: {ah_foreign:+,} 口")
        
        # v3.17.1: 累積期貨歷史
        try:
            hist_mod.update_futures_history(
                data_dir=data_dir,
                trade_date=trade_date,
                futures_data=futures_data,
            )
        except Exception as e:
            print(f"  ⚠️ 期貨歷史累積失敗: {e}")
    except Exception as e:
        print(f"  ⚠️ 期貨籌碼抓取失敗: {e}(不影響主流程)")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.20: MOPS 內部人 + 重大訊息
    # ════════════════════════════════════════════════════════════════
    insider_data = {}
    announcements = []
    try:
        import insiders
        from datetime import datetime as _dt
        
        # 1. 重大訊息 (當日)
        td = _dt.strptime(trade_date, '%Y%m%d')
        print(f"\n[MOPS] 抓取重大訊息 ({td.year}/{td.month}/{td.day})...")
        anns_sii = insiders.fetch_daily_announcements(td.year, td.month, td.day, 'sii')
        anns_otc = insiders.fetch_daily_announcements(td.year, td.month, td.day, 'otc')
        announcements = anns_sii + anns_otc
        # 加分類
        for a in announcements:
            a['classification'] = insiders.classify_announcement(a.get('subject', ''))
        high_count = sum(1 for a in announcements if a['classification']['impact'] == 'high')
        print(f"  ✓ 重大訊息 {len(announcements)} 則 (高影響度: {high_count})")
        
        # 2. 董監持股 (只抓 priority_codes - 用戶分點關注的個股)
        # 為了不跑太久, 只抓「分點 buys 中出現過」的 stock_codes (限 50 檔)
        watched_codes = set()
        for br in (results or [])[:10]:  # 前 10 個分點
            for s in (br.get('buys', []) or [])[:5]:
                if s.get('code') and s['code'].isdigit() and len(s['code']) == 4:
                    watched_codes.add(s['code'])
                    if len(watched_codes) >= 50:
                        break
            if len(watched_codes) >= 50:
                break
        
        print(f"  [MOPS] 抓取 {len(watched_codes)} 檔個股董監持股...")
        for i, code in enumerate(list(watched_codes)[:50]):
            try:
                d = insiders.fetch_director_holdings(code, td.year, td.month)
                if d:
                    # 偵測異動 (沒有前期資料,只偵測高設質)
                    alerts_list = insiders.detect_insider_changes(d, prev=None)
                    if alerts_list:
                        # 找 stock name
                        stock_name = ''
                        for br in (results or []):
                            for s in (br.get('buys', []) or []):
                                if s.get('code') == code:
                                    stock_name = s.get('name', '')
                                    break
                            if stock_name: break
                        insider_data[code] = {
                            'name': stock_name,
                            'directors_count': d['directors_count'],
                            'total_pledge_ratio': d['total_pledge_ratio'],
                            'high_pledge_count': d['high_pledge_count'],
                            'alerts': alerts_list,
                        }
                # 限流防禦
                if i < len(watched_codes) - 1:
                    import time as _t
                    _t.sleep(2)
            except Exception as e:
                print(f"    ⚠️ {code} 失敗: {e}")
                continue
        
        print(f"  ✓ 找到 {len(insider_data)} 檔有內部人警報")
    except ImportError:
        print("  [MOPS] insiders 模組未安裝, 略過")
    except Exception as e:
        print(f"  ⚠️ MOPS 抓取失敗: {e}")
        import traceback; traceback.print_exc()
    
    # ═════════════════════════════════════════════════════════════════
    # v3.40.0 B3 (機構級 P0): _meta 欄位 — 「6/12 算的結論用什麼演算法版本?」
    # 載入 config/algo_params.yaml 取 algo_version, 注入 sourcing trail
    # ═════════════════════════════════════════════════════════════════
    _meta_block = None
    try:
        import yaml as _yaml
        from pathlib import Path as _Path
        _algo_yaml = _Path(data_dir).parent / 'config' / 'algo_params.yaml'
        if _algo_yaml.exists():
            with open(_algo_yaml, 'r', encoding='utf-8') as _f:
                _algo_cfg = _yaml.safe_load(_f) or {}
            _meta_block = {
                'algo_version': _algo_cfg.get('algo_version', 'unknown'),
                'algo_frozen_date': _algo_cfg.get('frozen_date'),
                'algo_frozen_by': _algo_cfg.get('frozen_by'),
            }
    except Exception as _e:
        print(f"  ⚠️ algo_params.yaml 載入失敗 (B3 metadata 不完整): {_e}",
              file=sys.stderr)
        _meta_block = {'algo_version': 'unknown', 'algo_load_error': str(_e)}

    if _meta_block is None:
        _meta_block = {'algo_version': 'pre-v3.40.0'}

    # B3 附加: 計算當下時間 + 視窗 + sourcing trail
    _meta_block.update({
        'calculated_at': now_tw().isoformat(),
        'schema_version': 'v1',
        'data_window': {
            'trade_date': trade_date,
            'baseline_date': BASELINE_DATE,
        },
        'sourcing_trail': {
            # 每欄位指向其資料源 (機構審計可追溯)
            'branches': 'fubon-ebrokerdj.fbs.com.tw c=B+c=E (分點雙模式)',
            'institutional_rankings': 'TWSE OpenAPI BFI82U / TPEx tpex_daily_quote_index',
            'daily_quotes': 'TWSE OpenAPI MI_INDEX (+ MIS fallback)',
            'margin_data': 'TWSE OpenAPI MI_MARGN + TPEx tpex_mainboard_margin_balance',
            'margin_maintenance_summary': 'estimated from stock_history 30d avg close × 0.6',
            'tdcc_metadata': 'TDCC opendata getOD.ashx?id=1-5 (weekly)',
            'futures_data': 'TAIFEX futContractsDateDown + callsAndPutsDateDown + pcRatio',
            'limit_up_summary': 'price_utils.calc_limit_up_price (tick-size 精確)',
            'next_day_verification': 'cross_day_tracker T+1 buy vs T+1 sell verification',
            'industry': 'TWSE 33 類產業分類 (v3.15.0)',
            'disposal_codes': 'chengwaye.com/disposal-forecast.html (T+3 lag)',
        },
        'roster_ref': 'data/masters_roster.json (B1 owner trail)',
        'compliance_ref': 'DATA_SOURCES_COMPLIANCE.md (B5 ToS 摘要)',
    })

    # ===== 組裝當日 JSON =====
    raw_output = {
        "_meta": _meta_block,  # v3.40.0 B3: 機構級可追溯性 metadata
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "version": "3.40.0",  # v3.40.0 B3: 從 3.30.1 升 (機構級 P0 ship)
        "stage": STAGE,  # v3.14.4: 記錄此次爬蟲階段 (full/margin_only)
        "success": success_count,
        "failed": fail_count,
        "empty": empty_count,
        "branches": results,
        "branch_summaries": summaries,            # 每分點日/週/月/累積損益 + 風格
        "master_summaries": master_summaries,     # 按高手聚合
        "institutional_rankings": institutional_rankings,  # v3.7 全市場法人排行
        "institutional_count": len(institutional_map),
        "quotes_count": len(daily_quotes_map),
        # v3.11 新增
        "margin_data": margin_filtered,           # 智慧混合後的個股融資融券
        "margin_rankings": margin_rankings,       # 7 類排行榜
        # v3.37.0: 融資維持率市場估算 + TDCC 集保大戶
        "margin_maintenance_summary": margin_maint_summary,   # 全市場分布 + Top 30 危險
        "tdcc_metadata": (tdcc_inject or {}).get('metadata'),
        "tdcc_movers": (tdcc_inject or {}).get('movers'),
        # v3.40.0 B6: 操縱/對敲/出貨偵測 (機構級)
        "red_flags": red_flags_result,
        "margin_total_count": len(margin_all),    # 全市場總檔數（統計用）
        # v3.14.4 新增：融資融券資料日期驗證結果
        "margin_verification": margin_verification,  # HiStock 驗證結果
        # v3.12 新增
        "limit_up_summary": limit_up_summary,     # 漲停狙擊匯總
        # v3.13 新增
        "next_day_verification": next_day_verification,  # 隔日沖驗證
        # v3.15.0 新增：產業分類
        "industry_map": {
            "stock_industry": industry_map.get('stock_industry', {}),
            "industry_groups": industry_map.get('industry_groups', {}),
            "updated_at": industry_map.get('updated_at'),
        },
        # v3.17 新增:期貨選擇權籌碼
        "futures_data": futures_data,
        # v3.20 新增:MOPS 內部人 + 重大訊息
        "insider_data": insider_data,
        "announcements": announcements,
    }

    # ════════════════════════════════════════════════════════════════
    # v3.48.0 Tier 2 整合: 注入主力成本線 5d/20d + premium% 到每筆 stock
    # 用 60 天 stock_history.json (B3 master_profile 同 window) 計算
    # ════════════════════════════════════════════════════════════════
    try:
        import main_force_cost as mfc
        import master_profile as _mp_hist
        _mfc_history = _mp_hist.load_history(str(data_dir), window_days=None, password=password)
        if _mfc_history:
            _mfc_r = mfc.inject_main_force_cost(
                results, _mfc_history, daily_quotes_map=daily_quotes_map)
            print(f"[Tier2 主力成本 v3.48.0] ✓ 注入 {_mfc_r['computed']} 筆 "
                  f"({_mfc_r['unique_codes_5d']} 檔有 5d 成本線)")
    except Exception as _mfce:
        print(f"  ⚠️ main_force_cost inject 失敗: {type(_mfce).__name__}: {_mfce}")

    # ════════════════════════════════════════════════════════════════
    # v3.20: 推播警報系統 (在加密前用 raw_output 跑警報)
    # ════════════════════════════════════════════════════════════════
    try:
        import alerts
        # dry_run = False:有 webhook 會真的推送, 沒 webhook 走 test mode
        alert_result = alerts.run_alerts(
            latest_data=raw_output,
            insider_data=insider_data,
            announcements=announcements,
            dry_run=False,
        )
        print(f"  [警報] 偵測 {len(alert_result['detected'])} 個訊號, "
              f"分類 {alert_result.get('count_by_type', {})}")
    except ImportError:
        print("  [警報] alerts 模組未安裝, 略過")
    except Exception as e:
        print(f"  [警報] 執行失敗: {e}")

    # v3.41.0 C1: 結尾 flush event_logger buffer → logs/events_YYYYMMDD.jsonl
    # (alerts.run_alerts 已在內部 emit 各筆事件, 這裡 batch 寫檔)
    try:
        from event_logger import EventLogger
        n_flushed = EventLogger.flush_buffer(data_dir=str(data_dir))
        if n_flushed > 0:
            print(f"  [event_logger] flush {n_flushed} 筆事件 → logs/events_*.jsonl")
    except Exception as _e:
        print(f"  [event_logger] flush 失敗 (不影響主流程): {_e}")
    
    # ════════════════════════════════════════════════════════════════
    # v3.22+v3.23+v3.24: 老闆版 Excel 日報 (嚴格模仿手動版「分點觀察」)
    # ════════════════════════════════════════════════════════════════
    try:
        import excel_report
        excel_path = excel_report.generate_excel_report(
            branches_data=results,  # results = 56 個分點的 buys/sells
            trade_date=trade_date,
            output_dir=str(data_dir / "reports"),
        )
        if excel_path:
            print(f"  [Excel 日報] 生成成功:{excel_path}")

            # v3.29.3 W2: Excel 生成後立刻 auto_audit (V1 全分點掃描) + ::warning:: 級別
            try:
                import auto_audit
                audit_rpt = auto_audit.run_audit(data_dir)
                auto_audit.save_audit_report(data_dir, audit_rpt)
                verdict = audit_rpt.get('overall_verdict', 'SKIP')
                summary = audit_rpt.get('summary', '')
                print(f"  [Auto Audit v3.29.3] {verdict}: {summary}")
                # GitHub Actions log marker (::error/::warning/::notice::)
                auto_audit._emit_github_actions_marker(audit_rpt)
            except Exception as _ae:
                print(f"  [Auto Audit] 失敗 (不影響主流程): {_ae}")
    except ImportError:
        print("  [Excel 日報] excel_report 模組未安裝, 略過")
    except Exception as e:
        print(f"  [Excel 日報] 生成失敗:{e}")

    # ════════════════════════════════════════════════════════════════
    # v3.25: 籌碼溫度計分數 + 30 天歷史累積 (前端 chart 用)
    # ════════════════════════════════════════════════════════════════
    try:
        temp_result = compute_chip_temperature(raw_output, trade_date=trade_date)
        if temp_result:
            entry = update_temp_history(data_dir, trade_date, temp_result)
            print(f"  [溫度計] 今日 {entry['score']}/100 ({len(entry['signals'])} 信號)")

            # v3.29 Signal Engine: 把 raw signals 變 actionable daily signal
            try:
                import signal_engine
                daily_sig = signal_engine.generate_daily_signal(
                    raw_output, temp_result, trade_date
                )
                sig_path = signal_engine.save_daily_signal(data_dir, daily_sig)
                md = daily_sig.get('market_direction', {})
                stocks = daily_sig.get('top_focus_stocks', [])
                print(f"  [Signal Engine v3.29] {daily_sig.get('headline', '')}")
                print(f"                       寫入 {sig_path.name} ({sig_path.stat().st_size / 1024:.1f} KB)")
                if stocks:
                    print(f"                       Top focus: " +
                          ", ".join(f"{s['code']}({s['name']}) conf={s['confidence_pct']}%" for s in stocks[:3]))
            except Exception as _se:
                print(f"  [Signal Engine] 失敗 (不影響主流程): {_se}")
    except Exception as e:
        print(f"  [溫度計] 失敗: {e}")

    # ════════════════════════════════════════════════════════════════
    # v3.30.0 AI 解讀層: trade_pattern + insight_narrative (per stock)
    # 規則式分類 + 模板式 50-100 字 narrative, 前端 popup 讀
    # 必須在加密前注入 (因為要寫進 raw_output['branches'] 各 stock dict)
    # ════════════════════════════════════════════════════════════════
    try:
        import trade_pattern
        injected_count = trade_pattern.inject_trade_patterns(
            results,                # 56 個分點的 buys/sells
            WATCHED_BRANCHES,       # branches.py 設定
            MASTER_STYLES,          # branches.py MASTER_STYLES dict
        )
        # 統計各 pattern 分布
        from collections import Counter
        _pc = Counter()
        for br in results:
            for side in ('buys', 'sells'):
                for s in br.get(side, []) or []:
                    _pc[s.get('trade_pattern', '未明')] += 1
        _summary = ', '.join(f'{k}={v}' for k, v in _pc.most_common())
        print(f"  [Trade Pattern v3.30] {injected_count} stock 注入 trade_pattern + narrative")
        print(f"                       分布: {_summary}")
    except Exception as _tpe:
        print(f"  [Trade Pattern] 失敗 (不影響主流程): {_tpe}")

    plaintext = json.dumps(raw_output, ensure_ascii=False)
    print(f"[加密] 原始大小: {len(plaintext)/1024:.1f} KB")
    encrypted_token = encrypt_data(plaintext, password)
    print(f"[加密] 加密後大小: {len(encrypted_token)/1024:.1f} KB")
    
    encrypted_output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "data": encrypted_token,
    }
    
    # 寫入日期檔 + latest
    dated_file = data_dir / f"{trade_date}.json"
    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    latest_file = data_dir / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    # index.json
    index_file = data_dir / "index.json"
    existing_dates = []
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                existing_dates = json.load(f).get("dates", [])
        except Exception:
            pass
    
    all_dates = set(existing_dates)
    all_dates.add(trade_date)
    for f in data_dir.glob("*.json"):
        if f.stem.isdigit() and len(f.stem) == 8:
            all_dates.add(f.stem)
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "dates": sorted(all_dates, reverse=True),
            "latest": trade_date,
            "updated_at": now_tw().isoformat(),
            "branches_count": len(unique_branches),
            "baseline_date": BASELINE_DATE,
            "encrypted": True,
            "version": "3.30.1",
        }, f, ensure_ascii=False, indent=2)
    
    # v3.47.0 後2: 6 個 post-processing block 全部抽成 _post_* helper
    # main() 從 1225 → ~1010 行, 各 stage 獨立易測 / 易換序 / 易加新模組
    _post_generate_reports(data_dir, password)
    _post_build_master_profile(data_dir, password)
    _post_upsert_db(raw_output, trade_date, data_dir)
    _post_archive_rotate(data_dir)
    _post_auto_backfill_history(data_dir, password, industry_map)
    _post_disposal_snapshot(data_dir)
    _post_refresh_tier2_market_data(data_dir)   # v3.48.0: 注意/借券/除權息

    print(f"\n[{now_tw().strftime('%H:%M:%S')}] ✅ 完成！")
    print(f"  資料日期: {trade_date}")
    print(f"  成功: {success_count} / 失敗: {fail_count} / 無資料: {empty_count}")
    print(f"  歷史共 {len(all_dates)} 天")
    print(f"  🔒 資料已加密  📊 FIFO 部位已更新")


# ════════════════════════════════════════════════════════════════════
#  v3.14.4 新增: margin_only STAGE - 只更新融資融券 (用於 22:30/00:00/08:00)
# ════════════════════════════════════════════════════════════════════
def main_margin_only():
    """
    v3.14.4 新增：階段 2/3/4 只更新融資融券部分,不重爬分點
    
    流程：
      1. 讀取 data/latest.json (解密)
      2. 抓取最新融資融券 + HiStock 驗證
      3. 比對「驗證日期」vs「現有 margin_verification.data_date」
         - 如果新抓到的日期 > 現有 (更新) → 覆蓋
         - 如果一樣 (已是 T-0) → 跳過本次 (省資源)
         - 如果更舊 → 保留原資料 + 加警告
      4. 寫回加密檔
    """
    password = os.environ.get("CHIP_RADAR_PASSWORD", "").strip()
    if not password:
        print("❌ 環境變數 CHIP_RADAR_PASSWORD 未設定！")
        sys.exit(1)
    
    stage_name = os.environ.get('CHIP_RADAR_STAGE', 'margin_only').strip()
    print(f"[{now_tw().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 STAGE={stage_name} 融資融券補更新")
    
    data_dir = Path(__file__).parent / "data"
    latest_file = data_dir / "latest.json"
    
    if not latest_file.exists():
        print(f"❌ {latest_file} 不存在，無法進行 margin_only 更新")
        print(f"  請先執行主爬蟲 (CHIP_RADAR_STAGE=full python crawler.py)")
        sys.exit(1)
    
    # ===== 讀取現有資料並解密 =====
    print(f"\n[1/4] 讀取現有資料...")
    with open(latest_file, "r", encoding="utf-8") as f:
        encrypted_doc = json.load(f)
    
    try:
        plaintext = decrypt_data(encrypted_doc["data"], password)
        current_data = json.loads(plaintext)
    except Exception as e:
        print(f"❌ 解密失敗: {e}")
        sys.exit(1)
    
    current_date = current_data.get("trade_date")
    current_verification = current_data.get("margin_verification") or {}
    current_data_date = current_verification.get("data_date")
    
    print(f"  現有 trade_date: {current_date}")
    print(f"  現有融資融券驗證日期: {current_data_date or '(未驗證)'}")
    print(f"  現有融資融券信心: {current_verification.get('confidence', 'N/A')}")
    
    # ===== 聰明跳過: 如果已經是 T-0 (最新交易日),跳過本次 =====
    today_str = now_tw().strftime("%Y%m%d")
    # 取最近一個交易日 (週末的情況: 若今天週六,最近交易日是週五)
    import calendar
    now = now_tw()
    check = now
    for _ in range(5):
        if check.weekday() < 5:  # 週一(0) ~ 週五(4)
            break
        check = check - timedelta(days=1)
    latest_trade_day = check.strftime("%Y%m%d")
    # 若已 8 點前，則上個交易日
    if now.hour < 8:
        yesterday = now - timedelta(days=1)
        while yesterday.weekday() >= 5:
            yesterday = yesterday - timedelta(days=1)
        latest_trade_day = yesterday.strftime("%Y%m%d")
    
    if current_data_date and current_data_date >= latest_trade_day and current_verification.get('confidence') == 'high':
        print(f"\n✅ 現有融資融券資料已是 {current_data_date} (最新交易日)，跳過本次更新")
        print(f"   省下 GitHub Actions 分鐘數。")
        return
    
    # ===== 抓取最新融資融券 + 驗證 =====
    print(f"\n[2/4] 抓取最新融資融券 + HiStock 驗證...")
    try:
        margin_result = margin.fetch_all_margin(verify_date=True)
        margin_all = margin_result.get('data', {})
        new_verification = margin_result.get('verification')
    except Exception as e:
        print(f"❌ 融資融券抓取失敗: {e}")
        sys.exit(1)
    
    if not margin_all:
        print(f"❌ 抓到 0 檔融資融券,本次跳過")
        return
    
    new_data_date = (new_verification or {}).get('data_date')
    new_confidence = (new_verification or {}).get('confidence', 'low')
    print(f"  新抓到驗證日期: {new_data_date}")
    print(f"  新抓到信心: {new_confidence}")
    
    # ===== 決定是否覆蓋 =====
    print(f"\n[3/4] 決定是否覆蓋...")
    should_update = False
    
    if not current_data_date:
        # 現有沒驗證過 → 新的一定比較好
        should_update = True
        reason = "現有資料未驗證過"
    elif new_data_date and new_data_date > current_data_date:
        # 新的比現有更新 → 覆蓋
        should_update = True
        reason = f"新日期 {new_data_date} > 現有 {current_data_date}"
    elif new_data_date and new_data_date == current_data_date:
        if new_confidence == 'high' and current_verification.get('confidence') != 'high':
            # 同日期但信心更高 → 也更新
            should_update = True
            reason = f"同日期但驗證信心提升 ({current_verification.get('confidence')}→{new_confidence})"
        else:
            reason = "新日期與現有相同，信心也相同，保持不變"
    else:
        # 新的是 T-1 或未驗證,保留現有
        reason = f"新抓到日期 {new_data_date} 不優於現有 {current_data_date}，保留現有"
    
    print(f"  決定: {'✅ 覆蓋' if should_update else '⏸️ 不覆蓋'} ({reason})")
    
    if not should_update:
        print(f"\n  本次執行結束,未修改資料。")
        return
    
    # ===== 覆蓋並重新加密 =====
    print(f"\n[4/4] 合併、重新加密、寫回...")
    
    # 注入到每檔分點個股 (和主流程相同邏輯)
    margin_inject_count = margin.inject_margin_into_stocks(
        current_data.get("branches", []), margin_all
    )
    print(f"  注入 {margin_inject_count} 筆分點個股")
    
    # 智慧混合
    my_branch_codes = set()
    for br in current_data.get("branches", []):
        for s in (br.get("buys", []) + br.get("sells", [])):
            if s.get("code"):
                my_branch_codes.add(s["code"])
    
    target_codes = margin.select_target_codes(margin_all, my_branch_codes, top_n=100)
    margin_filtered = margin.filter_margin_data(margin_all, target_codes)
    margin_rankings = margin.build_margin_rankings(margin_all, top_n=30)
    
    # 更新相關欄位
    current_data["margin_data"] = margin_filtered
    current_data["margin_rankings"] = margin_rankings
    current_data["margin_total_count"] = len(margin_all)
    current_data["margin_verification"] = new_verification
    current_data["stage"] = stage_name  # 記錄最後一次是哪個階段更新的
    current_data["last_margin_update_at"] = now_tw().isoformat()
    
    # 重新加密
    plaintext = json.dumps(current_data, ensure_ascii=False)
    print(f"  重加密中 (原始 {len(plaintext)/1024:.1f} KB)...")
    encrypted_token = encrypt_data(plaintext, password)
    
    encrypted_output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "trade_date": current_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "data": encrypted_token,
    }
    
    # 寫回日期檔 + latest.json
    dated_file = data_dir / f"{current_date}.json"
    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{now_tw().strftime('%H:%M:%S')}] ✅ margin_only 更新完成！")
    print(f"  融資融券資料日期: {new_data_date}")
    print(f"  驗證信心: {new_confidence}")
    print(f"  篩選保留: {len(margin_filtered)} 檔")


if __name__ == "__main__":
    stage = os.environ.get('CHIP_RADAR_STAGE', 'full').strip().lower()
    if stage == 'margin_only':
        main_margin_only()
    else:
        main()
