"""
========================================================================
Module: reports.py  (v3.9 新增)
功能：週報 / 月報自動生成

設計原則：
  - 從 positions.json 和 chips_YYYYMMDD.json 讀取歷史資料
  - 計算各類排行榜與洞察
  - 同時輸出 JSON（加密）+ Markdown（公開可讀）
  - 命名：weekly_YYYY_WNN.{json,md}  /  monthly_YYYY_MM.{json,md}

報告內容：
  A. 執行摘要（3-5 條 AI 風格洞察）
  B. 高手績效排行（按浮盈 / 累積損益）
  C. 高手 vs 外資同向率
  D. 熱門個股 Top 20（按共買分點數 / 淨買量）
  E. 風格分析（當沖 vs 波段的關注股票差異）
  F. 外資分點動向（8 個外資的週/月行為）
  G. FIFO 累積損益 Top/Bottom 10
========================================================================
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict, Counter

TW_TZ = timezone(timedelta(hours=8))


# ════════════════════════════════════════════════════════════════════
#  日期計算工具
# ════════════════════════════════════════════════════════════════════

def get_week_number(dt):
    """回傳 ISO 週數 (YYYY, WW)"""
    y, w, _ = dt.isocalendar()
    return y, w


def get_week_range(year, week):
    """回傳週一與週五的日期字串"""
    # ISO 週第一天為週一
    jan4 = date(year, 1, 4)  # 第一週一定包含 1/4
    week1_mon = jan4 - timedelta(days=jan4.isoweekday() - 1)
    mon = week1_mon + timedelta(weeks=week - 1)
    fri = mon + timedelta(days=4)
    return mon.strftime("%Y%m%d"), fri.strftime("%Y%m%d")


def get_last_week():
    """回傳上週的年份和週數"""
    now = datetime.now(TW_TZ)
    last_week_dt = now - timedelta(days=7)
    return get_week_number(last_week_dt)


def get_last_month():
    """回傳上月的年份和月份"""
    now = datetime.now(TW_TZ)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def get_month_range(year, month):
    """回傳當月第一天與最後一天"""
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first.strftime("%Y%m%d"), last.strftime("%Y%m%d")


# ════════════════════════════════════════════════════════════════════
#  資料載入：從 positions + 各日 chips 彙整
# ════════════════════════════════════════════════════════════════════

def load_period_data(data_dir: Path, password: str,
                     start_date: str, end_date: str,
                     decrypt_fn):
    """
    載入指定期間內所有每日資料
    
    Args:
        decrypt_fn: crawler.py 提供的 decrypt_data 函式
    
    Returns:
        {
          "trade_dates": [YYYYMMDD, ...],
          "daily_data": {date: {branches, institutional_rankings, ...}},
          "positions": {...}  # 累積部位
        }
    """
    # 列出區間內存在的日期
    all_dates = sorted([p.stem for p in data_dir.glob('*.json') 
                        if p.stem.isdigit() and len(p.stem) == 8])
    in_range = [d for d in all_dates if start_date <= d <= end_date]
    
    daily_data = {}
    for d in in_range:
        fpath = data_dir / f"{d}.json"
        try:
            with open(fpath) as f:
                enc = json.load(f)
            if enc.get('encrypted'):
                plain = decrypt_fn(enc['data'], password)
                daily_data[d] = json.loads(plain)
            else:
                daily_data[d] = enc
        except Exception as e:
            print(f"  ⚠️ 無法讀取 {d}: {e}")
    
    # 載入累積部位
    positions = None
    pos_path = data_dir / "positions.json"
    if pos_path.exists():
        try:
            with open(pos_path) as f:
                enc = json.load(f)
            if enc.get('encrypted'):
                plain = decrypt_fn(enc['data'], password)
                positions = json.loads(plain)
            else:
                positions = enc
        except Exception as e:
            print(f"  ⚠️ 無法讀取 positions.json: {e}")
    
    return {
        "trade_dates": in_range,
        "daily_data": daily_data,
        "positions": positions,
    }


# ════════════════════════════════════════════════════════════════════
#  核心分析函數
# ════════════════════════════════════════════════════════════════════

def analyze_master_performance(period_data):
    """
    分析每位 master 的期間績效
    
    Returns: [
        {master, branches_count, total_net_lot, avg_daytrade_ratio, 
         unique_stocks, avg_alignment_rate, top_stocks}
    ]
    """
    master_stats = defaultdict(lambda: {
        "branches": set(),
        "total_buy_amt": 0.0,
        "total_sell_amt": 0.0,
        "total_net_amt": 0.0,
        "total_buy_lot": 0,
        "total_sell_lot": 0,
        "total_net_lot": 0,
        "daytrade_count": 0,
        "overnight_count": 0,
        "stock_counter": Counter(),  # 股票代號 → 出現次數
        "aligned_count": 0,
        "opposing_count": 0,
        "days_active": 0,
    })
    
    for trade_date, data in period_data["daily_data"].items():
        for br in data.get("branches", []):
            master = br.get("master", "未知")
            if not br.get("buys"):
                continue
            
            stats = master_stats[master]
            stats["branches"].add(br["code"])
            stats["days_active"] += 1
            
            for s in (br.get("buys", []) + br.get("sells", [])):
                # 只處理 buys 為主（sells 會重複）
                if s not in br.get("buys", []):
                    continue
                stats["total_buy_amt"] += s.get("buy_amt", 0) or 0
                stats["total_sell_amt"] += s.get("sell_amt", 0) or 0
                stats["total_net_amt"] += s.get("net_amt", 0) or 0
                stats["total_buy_lot"] += s.get("buy_lot", 0) or 0
                stats["total_sell_lot"] += s.get("sell_lot", 0) or 0
                stats["total_net_lot"] += s.get("net_lot", 0) or 0
                
                style = s.get("trade_style", "")
                if style == "daytrade":
                    stats["daytrade_count"] += 1
                elif style == "overnight":
                    stats["overnight_count"] += 1
                
                stats["stock_counter"][s.get("code", "")] += 1
                
                align = s.get("align_with_foreign")
                if align == "aligned":
                    stats["aligned_count"] += 1
                elif align == "opposing":
                    stats["opposing_count"] += 1
    
    result = []
    for master, stats in master_stats.items():
        total_styled = stats["daytrade_count"] + stats["overnight_count"]
        daytrade_ratio = stats["daytrade_count"] / total_styled if total_styled else 0
        
        align_total = stats["aligned_count"] + stats["opposing_count"]
        alignment_rate = stats["aligned_count"] / align_total if align_total else None
        
        top_stocks = stats["stock_counter"].most_common(5)
        
        result.append({
            "master": master,
            "branches_count": len(stats["branches"]),
            "days_active": stats["days_active"],
            "total_net_amt": round(stats["total_net_amt"], 2),
            "total_buy_lot": stats["total_buy_lot"],
            "total_sell_lot": stats["total_sell_lot"],
            "total_net_lot": stats["total_net_lot"],
            "daytrade_ratio": round(daytrade_ratio, 3),
            "daytrade_count": stats["daytrade_count"],
            "overnight_count": stats["overnight_count"],
            "unique_stocks": len(stats["stock_counter"]),
            "alignment_rate": round(alignment_rate, 3) if alignment_rate is not None else None,
            "aligned_count": stats["aligned_count"],
            "opposing_count": stats["opposing_count"],
            "top_stocks": [{"code": c, "count": n} for c, n in top_stocks],
        })
    
    return sorted(result, key=lambda x: -x["total_net_amt"])


def analyze_hot_stocks(period_data, top_n=20):
    """
    分析期間內最熱門的個股（按累積共買分點數 + 淨買量）
    
    Returns: [
        {code, name, days_appeared, total_buyers, total_net_lot, 
         masters_bought, foreign_net, alignment}
    ]
    """
    stock_stats = defaultdict(lambda: {
        "days_appeared": set(),
        "all_buyers": set(),  # (date, branch_code) 組合
        "masters": set(),
        "total_net_amt": 0.0,
        "total_net_lot": 0,
        "total_buy_lot": 0,
        "foreign_net_total": 0,
        "trust_net_total": 0,
        "close_prices": [],
        "last_close": None,
        "last_change_pct": None,
        "name": "",
    })
    
    for trade_date, data in period_data["daily_data"].items():
        for br in data.get("branches", []):
            for s in br.get("buys", []):
                code = s.get("code", "")
                if not code:
                    continue
                st = stock_stats[code]
                st["name"] = s.get("name", "") or st["name"]
                st["days_appeared"].add(trade_date)
                st["all_buyers"].add((trade_date, br["code"]))
                st["masters"].add(br.get("master", ""))
                st["total_net_amt"] += s.get("net_amt", 0) or 0
                st["total_net_lot"] += s.get("net_lot", 0) or 0
                st["total_buy_lot"] += s.get("buy_lot", 0) or 0
                
                # 三大法人（取最後一天的值）
                if s.get("inst_foreign_net_lot") is not None:
                    st["foreign_net_total"] += s.get("inst_foreign_net_lot", 0)
                    st["trust_net_total"] += s.get("inst_trust_net_lot", 0) or 0
                
                if s.get("close_price"):
                    st["close_prices"].append((trade_date, s["close_price"]))
                    st["last_close"] = s["close_price"]
                    st["last_change_pct"] = s.get("change_pct")
    
    result = []
    for code, st in stock_stats.items():
        if not st["days_appeared"]:
            continue
        # 計算週/月價格變化
        prices = sorted(st["close_prices"], key=lambda x: x[0])
        price_change_pct = None
        if len(prices) >= 2:
            first_close = prices[0][1]
            last_close = prices[-1][1]
            if first_close:
                price_change_pct = round((last_close - first_close) / first_close * 100, 2)
        
        result.append({
            "code": code,
            "name": st["name"],
            "days_appeared": len(st["days_appeared"]),
            "total_buyers": len(st["all_buyers"]),
            "masters_count": len(st["masters"]),
            "masters_list": sorted(st["masters"]),
            "total_net_amt": round(st["total_net_amt"], 2),
            "total_net_lot": st["total_net_lot"],
            "total_buy_lot": st["total_buy_lot"],
            "foreign_net_total": st["foreign_net_total"],
            "trust_net_total": st["trust_net_total"],
            "last_close": st["last_close"],
            "period_change_pct": price_change_pct,
        })
    
    # 排序：先按 masters_count（多少人買）→ 再按 total_buyers（累積熱度）
    result.sort(key=lambda x: (-x["masters_count"], -x["total_buyers"]))
    return result[:top_n]


def analyze_foreign_branches(period_data):
    """分析 8 個外資分點的期間動向"""
    foreign_stats = defaultdict(lambda: {
        "master": "",
        "name": "",
        "code": "",
        "region": "",
        "days_active": 0,
        "total_net_lot": 0,
        "total_net_amt": 0.0,
        "stock_counter": Counter(),
    })
    
    for trade_date, data in period_data["daily_data"].items():
        for br in data.get("branches", []):
            if br.get("region", "domestic") == "domestic":
                continue  # 只處理外資
            if not br.get("buys"):
                continue
            
            code = br["code"]
            st = foreign_stats[code]
            st["code"] = code
            st["master"] = br.get("master", "")
            st["name"] = br.get("name", "")
            st["region"] = br.get("region", "")
            st["days_active"] += 1
            
            for s in br.get("buys", []):
                st["total_net_lot"] += s.get("net_lot", 0) or 0
                st["total_net_amt"] += s.get("net_amt", 0) or 0
                if s.get("code"):
                    st["stock_counter"][s["code"]] += 1
    
    result = []
    for code, st in foreign_stats.items():
        result.append({
            "code": code,
            "master": st["master"],
            "name": st["name"],
            "region": st["region"],
            "days_active": st["days_active"],
            "total_net_lot": st["total_net_lot"],
            "total_net_amt": round(st["total_net_amt"], 2),
            "top_stocks": [{"code": c, "count": n} for c, n in st["stock_counter"].most_common(5)],
        })
    
    return sorted(result, key=lambda x: -x["total_net_amt"])


def analyze_style_distribution(period_data):
    """分析當沖家 vs 波段家在關注個股上的差異"""
    daytrade_masters = Counter()  # 當沖家買的個股
    overnight_masters = Counter()  # 波段家買的個股
    
    for trade_date, data in period_data["daily_data"].items():
        # 看每位 master 今天整體風格
        master_day_style = defaultdict(lambda: {"day": 0, "over": 0})
        master_stocks = defaultdict(set)
        
        for br in data.get("branches", []):
            master = br.get("master", "")
            for s in br.get("buys", []):
                style = s.get("trade_style", "")
                if style == "daytrade":
                    master_day_style[master]["day"] += 1
                elif style == "overnight":
                    master_day_style[master]["over"] += 1
                if s.get("code"):
                    master_stocks[master].add(s["code"])
        
        # 歸類每位 master
        for master, styles in master_day_style.items():
            total = styles["day"] + styles["over"]
            if total < 3:
                continue  # 樣本不足
            ratio = styles["day"] / total
            stocks = master_stocks[master]
            if ratio >= 0.55:
                for code in stocks:
                    daytrade_masters[code] += 1
            elif ratio < 0.30:
                for code in stocks:
                    overnight_masters[code] += 1
    
    # 找出兩群關注重疊 / 差異的股票
    daytrade_only = [c for c in daytrade_masters if c not in overnight_masters]
    overnight_only = [c for c in overnight_masters if c not in daytrade_masters]
    both = [c for c in daytrade_masters if c in overnight_masters]
    
    return {
        "daytrade_hot": daytrade_masters.most_common(10),
        "overnight_hot": overnight_masters.most_common(10),
        "daytrade_only": daytrade_only[:10],
        "overnight_only": overnight_only[:10],
        "both_camps": both[:10],
    }


def analyze_fifo_pnl(period_data, top_n=10):
    """從 positions 資料取 FIFO 累積損益 Top/Bottom"""
    positions = period_data.get("positions") or {}
    branches = positions.get("branches", {})
    
    # 彙總每個 branch 的累積損益
    branch_pnls = []
    for branch_code, br_pos in branches.items():
        total_pnl = 0.0
        for stock_code, stock_pos in (br_pos.get("stocks") or {}).items():
            total_pnl += stock_pos.get("cumulative_pnl", 0) or 0
        branch_pnls.append({
            "code": branch_code,
            "branch_name": br_pos.get("branch_name", ""),
            "master": br_pos.get("master", ""),
            "cumulative_pnl": round(total_pnl, 2),
        })
    
    branch_pnls.sort(key=lambda x: -x["cumulative_pnl"])
    
    return {
        "top_winners": branch_pnls[:top_n],
        "top_losers": [b for b in branch_pnls if b["cumulative_pnl"] < 0][-top_n:][::-1],
    }


# ════════════════════════════════════════════════════════════════════
#  洞察文字生成
# ════════════════════════════════════════════════════════════════════

def generate_insights(report_data):
    """依資料自動產生 3-5 條洞察文字"""
    insights = []
    masters = report_data.get("master_performance", [])
    hot_stocks = report_data.get("hot_stocks", [])
    foreign = report_data.get("foreign_branches", [])
    
    # 1. 最強高手
    if masters:
        top = masters[0]
        if top.get("total_net_amt", 0) > 0:
            insights.append(
                f"🏆 本期淨買金額冠軍：**{top['master']}** "
                f"（淨買 {top['total_net_amt']/10000:.1f} 億，"
                f"涉及 {top['unique_stocks']} 檔個股）"
            )
    
    # 2. 最熱門個股
    if hot_stocks:
        hottest = hot_stocks[0]
        masters_str = "、".join(hottest.get("masters_list", [])[:3])
        if len(hottest.get("masters_list", [])) > 3:
            masters_str += " 等"
        change_str = ""
        if hottest.get("period_change_pct") is not None:
            change_str = f"，期間漲跌 {hottest['period_change_pct']:+.2f}%"
        insights.append(
            f"🔥 最熱門共買：**{hottest['name']} ({hottest['code']})** "
            f"- 累積 {hottest['masters_count']} 位高手買進（{masters_str}）{change_str}"
        )
    
    # 3. 對齊率最高的高手
    align_sorted = [m for m in masters if m.get("alignment_rate") is not None 
                    and m.get("aligned_count", 0) + m.get("opposing_count", 0) >= 5]
    align_sorted.sort(key=lambda x: -x["alignment_rate"])
    if align_sorted:
        top_aligned = align_sorted[0]
        insights.append(
            f"🎯 與外資最同向：**{top_aligned['master']}** "
            f"（同向率 {top_aligned['alignment_rate']*100:.0f}%，"
            f"同 {top_aligned['aligned_count']} / 反 {top_aligned['opposing_count']}）"
        )
    
    # 4. 外資最活躍
    if foreign:
        top_foreign = max(foreign, key=lambda x: abs(x.get("total_net_amt", 0)))
        direction = "買超" if top_foreign["total_net_amt"] > 0 else "賣超"
        insights.append(
            f"🌏 本期最活躍外資：**{top_foreign['master']}** "
            f"（{direction} {abs(top_foreign['total_net_amt'])/10000:.1f} 億）"
        )
    
    # 5. 逆勢者
    opposing_sorted = [m for m in masters if m.get("alignment_rate") is not None 
                       and m.get("aligned_count", 0) + m.get("opposing_count", 0) >= 5]
    opposing_sorted.sort(key=lambda x: x["alignment_rate"])
    if opposing_sorted and opposing_sorted[0]["alignment_rate"] < 0.4:
        top_opp = opposing_sorted[0]
        insights.append(
            f"⚠️ 逆勢最強：**{top_opp['master']}** "
            f"（反外資率 {(1-top_opp['alignment_rate'])*100:.0f}%，"
            f"值得追蹤是否逆勢成功）"
        )
    
    return insights


# ════════════════════════════════════════════════════════════════════
#  主報告生成（週報 / 月報）
# ════════════════════════════════════════════════════════════════════

def generate_report(period_data, period_type, period_label):
    """
    產生完整報告資料結構
    
    period_type: "weekly" / "monthly"
    period_label: "2026_W17" / "2026_04"
    """
    if not period_data["trade_dates"]:
        return {
            "period_type": period_type,
            "period_label": period_label,
            "empty": True,
            "message": "此期間無交易資料",
        }
    
    master_perf = analyze_master_performance(period_data)
    hot_stocks = analyze_hot_stocks(period_data, top_n=20)
    foreign = analyze_foreign_branches(period_data)
    styles = analyze_style_distribution(period_data)
    fifo = analyze_fifo_pnl(period_data, top_n=10)
    
    report = {
        "period_type": period_type,
        "period_label": period_label,
        "generated_at": datetime.now(TW_TZ).isoformat(),
        "start_date": period_data["trade_dates"][0],
        "end_date": period_data["trade_dates"][-1],
        "trade_days": len(period_data["trade_dates"]),
        "trade_dates": period_data["trade_dates"],
        "master_performance": master_perf,
        "hot_stocks": hot_stocks,
        "foreign_branches": foreign,
        "style_distribution": styles,
        "fifo_pnl": fifo,
    }
    
    report["insights"] = generate_insights(report)
    return report


# ════════════════════════════════════════════════════════════════════
#  Markdown 輸出（公開可讀）
# ════════════════════════════════════════════════════════════════════

def format_amount_wan(amt_wan):
    """格式化為 億/萬"""
    if amt_wan is None:
        return "—"
    if abs(amt_wan) >= 10000:
        return f"{amt_wan/10000:+.2f} 億"
    return f"{amt_wan:+,.0f} 萬"


def report_to_markdown(report):
    """將 report JSON 轉為 Markdown"""
    if report.get("empty"):
        return f"# {report['period_label']} 報告\n\n⚠️ 此期間無交易資料。\n"
    
    period_name = "週報" if report["period_type"] == "weekly" else "月報"
    md = []
    md.append(f"# 📊 分點籌碼 {period_name}：{report['period_label']}")
    md.append(f"")
    md.append(f"**期間**：{report['start_date']} ~ {report['end_date']}　"
              f"**交易日**：{report['trade_days']} 天　"
              f"**生成時間**：{report['generated_at'][:19]}")
    md.append(f"")
    
    # 執行摘要
    md.append(f"## 💡 執行摘要")
    md.append(f"")
    for ins in report.get("insights", []):
        md.append(f"- {ins}")
    md.append(f"")
    
    # 高手績效
    md.append(f"## 👤 高手績效排行")
    md.append(f"")
    md.append(f"| # | 高手 | 分點數 | 期間淨買 | 淨買張 | 當沖比 | 關注個股 | 與外資同向率 |")
    md.append(f"|---|------|-------|---------|-------|--------|---------|------------|")
    for i, m in enumerate(report["master_performance"][:15], 1):
        align_str = f"{m['alignment_rate']*100:.0f}% ({m['aligned_count']}/{m['opposing_count']})" \
                    if m.get("alignment_rate") is not None else "—"
        md.append(f"| {i} | **{m['master']}** | {m['branches_count']} | "
                  f"{format_amount_wan(m['total_net_amt'])} | "
                  f"{m['total_net_lot']:+,} | "
                  f"{m['daytrade_ratio']*100:.0f}% | "
                  f"{m['unique_stocks']} 檔 | {align_str} |")
    md.append(f"")
    
    # 熱門個股
    md.append(f"## 🔥 熱門個股 Top 20")
    md.append(f"")
    md.append(f"| # | 股票 | 共買天數 | 共買分點次 | 涉及高手 | 累積淨買張 | 外資累計 | 期間漲跌 |")
    md.append(f"|---|------|---------|----------|--------|----------|---------|---------|")
    for i, s in enumerate(report["hot_stocks"][:20], 1):
        change = f"{s['period_change_pct']:+.2f}%" if s.get("period_change_pct") is not None else "—"
        md.append(f"| {i} | **{s['name']}** `{s['code']}` | "
                  f"{s['days_appeared']} 天 | "
                  f"{s['total_buyers']} 人次 | "
                  f"{s['masters_count']} 位 | "
                  f"{s['total_net_lot']:+,} | "
                  f"{s['foreign_net_total']:+,} 張 | "
                  f"{change} |")
    md.append(f"")
    
    # 外資分點動向
    md.append(f"## 🌏 外資分點動向")
    md.append(f"")
    if report["foreign_branches"]:
        md.append(f"| 外資 | 地區 | 活躍天 | 期間淨買 | 淨買張 | 重點個股 |")
        md.append(f"|------|------|-------|---------|-------|---------|")
        region_labels = {"us": "🇺🇸 美系", "eu": "🇪🇺 歐系", "asia": "🌏 亞系"}
        for f in report["foreign_branches"]:
            top3 = "、".join(ts["code"] for ts in f.get("top_stocks", [])[:3]) or "—"
            md.append(f"| **{f['master']}** ({f['name']}) | "
                      f"{region_labels.get(f['region'], f['region'])} | "
                      f"{f['days_active']} | "
                      f"{format_amount_wan(f['total_net_amt'])} | "
                      f"{f['total_net_lot']:+,} | {top3} |")
    else:
        md.append(f"⚠️ 此期間無外資分點資料（尚未累積足夠交易日）")
    md.append(f"")
    
    # 風格分析
    md.append(f"## ⚡ 風格分析")
    md.append(f"")
    styles = report.get("style_distribution", {})
    md.append(f"### 🔥 當沖家熱門股 (Top 10)")
    if styles.get("daytrade_hot"):
        for code, count in styles["daytrade_hot"][:10]:
            md.append(f"- `{code}` (被 {count} 次當沖家關注)")
    else:
        md.append(f"- 資料不足")
    md.append(f"")
    md.append(f"### 🌙 波段家熱門股 (Top 10)")
    if styles.get("overnight_hot"):
        for code, count in styles["overnight_hot"][:10]:
            md.append(f"- `{code}` (被 {count} 次波段家關注)")
    else:
        md.append(f"- 資料不足")
    md.append(f"")
    
    # FIFO 累積損益
    md.append(f"## 💰 FIFO 累積損益 Top/Bottom")
    md.append(f"")
    fifo = report.get("fifo_pnl", {})
    md.append(f"### 🟢 累積獲利前 10 分點")
    if fifo.get("top_winners"):
        for i, b in enumerate(fifo["top_winners"][:10], 1):
            md.append(f"{i}. **{b['master']}** ({b['branch_name']}) — "
                      f"{format_amount_wan(b['cumulative_pnl'])}")
    md.append(f"")
    md.append(f"### 🔴 累積虧損前 10 分點")
    if fifo.get("top_losers"):
        for i, b in enumerate(fifo["top_losers"][:10], 1):
            md.append(f"{i}. **{b['master']}** ({b['branch_name']}) — "
                      f"{format_amount_wan(b['cumulative_pnl'])}")
    md.append(f"")
    
    md.append(f"---")
    md.append(f"*此報告由 Chip Radar v3.9 自動生成。基準日：{report.get('start_date')}*")
    
    return "\n".join(md)


# ════════════════════════════════════════════════════════════════════
#  主函式：產生並存檔
# ════════════════════════════════════════════════════════════════════

def save_report(report, data_dir: Path, password: str, encrypt_fn):
    """
    儲存報告：JSON（加密）+ MD（公開）
    
    Returns: (json_path, md_path)
    """
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    prefix = "weekly" if report["period_type"] == "weekly" else "monthly"
    label = report["period_label"]
    
    # JSON（加密存）
    json_path = reports_dir / f"{prefix}_{label}.json"
    plaintext = json.dumps(report, ensure_ascii=False)
    encrypted = encrypt_fn(plaintext, password)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            "encrypted": True,
            "algorithm": "AES-256-GCM",
            "data": encrypted,
        }, f, ensure_ascii=False)
    
    # Markdown（公開存）
    md_path = reports_dir / f"{prefix}_{label}.md"
    md_content = report_to_markdown(report)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    return json_path, md_path


def maybe_generate_reports(data_dir: Path, password: str, decrypt_fn, encrypt_fn):
    """
    判斷今日是否需要產生週報/月報
    - 週一產生上週報告
    - 1 號產生上月報告
    
    Returns: 產生的報告清單
    """
    now = datetime.now(TW_TZ)
    generated = []
    
    # 週一產生上週報告
    if now.isoweekday() == 1:
        year, week = get_last_week()
        label = f"{year}_W{week:02d}"
        start, end = get_week_range(year, week)
        print(f"\n[報告] 📅 週一偵測，產生上週報告 ({label}: {start}~{end})")
        
        data = load_period_data(data_dir, password, start, end, decrypt_fn)
        if not data["trade_dates"]:
            print(f"  ⚠️ 上週無交易資料，略過")
        else:
            report = generate_report(data, "weekly", label)
            json_p, md_p = save_report(report, data_dir, password, encrypt_fn)
            print(f"  ✓ 已生成：{json_p.name} + {md_p.name}")
            print(f"  涵蓋 {report['trade_days']} 個交易日，{len(report['master_performance'])} 位高手")
            generated.append(("weekly", label, md_p))
    
    # 1 號產生上月報告
    if now.day == 1:
        year, month = get_last_month()
        label = f"{year}_{month:02d}"
        start, end = get_month_range(year, month)
        print(f"\n[報告] 📆 月初 1 號偵測，產生上月報告 ({label}: {start}~{end})")
        
        data = load_period_data(data_dir, password, start, end, decrypt_fn)
        if not data["trade_dates"]:
            print(f"  ⚠️ 上月無交易資料，略過")
        else:
            report = generate_report(data, "monthly", label)
            json_p, md_p = save_report(report, data_dir, password, encrypt_fn)
            print(f"  ✓ 已生成：{json_p.name} + {md_p.name}")
            print(f"  涵蓋 {report['trade_days']} 個交易日，{len(report['master_performance'])} 位高手")
            generated.append(("monthly", label, md_p))
    
    return generated


def regenerate_report_for_period(data_dir: Path, password: str, decrypt_fn, encrypt_fn,
                                  period_type: str, year: int, period: int):
    """
    手動重新生成指定期間的報告（for UI 用戶按鈕）
    
    period_type: "weekly" / "monthly"
    period: week number (1-52) or month (1-12)
    """
    if period_type == "weekly":
        label = f"{year}_W{period:02d}"
        start, end = get_week_range(year, period)
    else:
        label = f"{year}_{period:02d}"
        start, end = get_month_range(year, period)
    
    data = load_period_data(data_dir, password, start, end, decrypt_fn)
    report = generate_report(data, period_type, label)
    json_p, md_p = save_report(report, data_dir, password, encrypt_fn)
    return report, json_p, md_p


def list_available_reports(data_dir: Path):
    """列出所有已存在的報告（供 UI 顯示歷史報告）"""
    reports_dir = data_dir / "reports"
    if not reports_dir.exists():
        return {"weekly": [], "monthly": []}
    
    weekly = sorted([p.stem.replace("weekly_", "") 
                     for p in reports_dir.glob("weekly_*.json")], reverse=True)
    monthly = sorted([p.stem.replace("monthly_", "") 
                      for p in reports_dir.glob("monthly_*.json")], reverse=True)
    return {"weekly": weekly, "monthly": monthly}
