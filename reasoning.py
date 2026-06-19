"""
========================================================================
Module: reasoning.py  (v3.41.0 Sprint 4 — C3)

統一的 reasoning chain 格式 — 從「結論輸出」進化到「推理鏈展示」

機構級可解釋性 (跟 B6 manipulation_flags 的 reasoning field 對齊):
  {
    'conditions': [
      '條件 1 (含實際值 vs 閾值)',
      '條件 2 ...',
    ],
    'conclusion': '推理結論',
    'evidence': ['佐證 1 (raw data)', '佐證 2'],
    'severity': 'high|medium|low|info',
    'category': 'foreign_extreme|volume_spike|consensus|...',
  }

被以下模組使用:
  - alerts.py: 5 種訊號告警
  - auto_audit.py: daily audit verdict
  - daily_signals.py: 異常/共識/連續加碼
  - manipulation_flags.py: 拉抬/對敲/出貨 (已內建相同格式)

呼叫範例:
  from reasoning import build_reasoning

  r = build_reasoning(
      conditions=[
          f"net_lots {net} > threshold {thr}",
          "5 day consecutive same direction",
      ],
      conclusion="外資現貨極端持續, 可能反指標",
      evidence=[f"5d_avg={avg}", f"taiex={taiex}"],
      severity='high', category='foreign_extreme',
  )
========================================================================
"""
from typing import List, Dict, Any, Optional

VALID_SEVERITIES = {'critical', 'high', 'medium', 'low', 'info'}


def build_reasoning(
    conditions: List[str],
    conclusion: str,
    evidence: Optional[List[str]] = None,
    severity: str = 'info',
    category: str = 'unspecified',
) -> Dict[str, Any]:
    """產出統一 reasoning chain dict.

    Args:
      conditions: 觸發條件清單 (含實際值 vs 閾值)
      conclusion: 推理結論 (中文短句)
      evidence: 佐證資料 (raw data refs, 給 audit 用)
      severity: 嚴重度 (critical/high/medium/low/info)
      category: 類別 (foreign_extreme/consensus/wash_trade 等)

    Returns:
      標準化 dict (可直接 JSON serialize)
    """
    if severity not in VALID_SEVERITIES:
        severity = 'info'
    return {
        'conditions': list(conditions or []),
        'conclusion': str(conclusion or ''),
        'evidence': list(evidence or []),
        'severity': severity,
        'category': str(category or 'unspecified'),
    }


def format_reasoning_text(r: Dict[str, Any]) -> str:
    """把 reasoning chain 格式化成單行文字 (給 console / narrative 用).

    範例: '[high foreign_extreme] 外資連 3 天淨空 + 結算 D-2 → 反彈 setup (3 條件 / 2 證據)'
    """
    if not r:
        return ''
    sev = r.get('severity', 'info')
    cat = r.get('category', '')
    conc = r.get('conclusion', '')
    n_cond = len(r.get('conditions') or [])
    n_evid = len(r.get('evidence') or [])
    return f"[{sev} {cat}] {conc} ({n_cond} 條件 / {n_evid} 證據)"


def format_reasoning_html(r: Dict[str, Any]) -> str:
    """產出單句 HTML inline 適合 narrative 嵌入 (no <div> 包裝, caller 控制)."""
    if not r:
        return ''
    conds = r.get('conditions') or []
    evid = r.get('evidence') or []
    conc = r.get('conclusion') or ''
    parts = []
    for c in conds:
        parts.append(f'<span style="color:var(--text-2);">▸ {c}</span>')
    if conc:
        parts.append(f'<strong style="color:var(--gold-bright);">→ {conc}</strong>')
    if evid:
        parts.append(f'<span style="color:var(--text-3);font-size:11px;">證據: {", ".join(evid)}</span>')
    return '<br>'.join(parts)
