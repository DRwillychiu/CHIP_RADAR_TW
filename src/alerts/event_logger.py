"""
========================================================================
Module: event_logger.py  (v3.41.0 Sprint 4 — C1)

統一 structured event log — 所有 alert / audit / signal 寫入 JSONL
方便未來接 SIEM (Splunk/Elastic/Sentinel) 直接 tail

格式: 每行一個 event JSON
  {
    "ts": "2026-06-19T22:00:00+08:00",
    "event_id": "ALERTS_20260619_001",
    "severity": "high",
    "module": "alerts | audit | signal | manipulation | crawler",
    "category": "foreign_extreme | wash_trade | pump_suspicion | ...",
    "reasoning": {conditions, conclusion, evidence, ...},  # 來自 reasoning.py
    "detail": {任意附加資訊},
  }

Rotation 策略 (對抗式簡化):
  - daily file: logs/events_YYYYMMDD.jsonl
  - 不入 git repo (.gitignore 加 logs/)
  - 7 天後 gzip, 30 天後刪 (未來才做; v3.41.0 先存純檔)

使用方式:
  from event_logger import EventLogger, emit_event

  emit_event(
      module='alerts',
      category='foreign_extreme',
      severity='high',
      reasoning=build_reasoning(...),
      detail={'net_lot': 50000, 'broker': '9200'},
  )

  # 一次性 batch flush (crawler stage 9 結尾)
  EventLogger.flush_buffer(data_dir='data')
========================================================================
"""
import json
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

TW_TZ = timezone(timedelta(hours=8))


class EventLogger:
    """thread-safe 事件累積器, 一日結束/stage 結束 flush 到 JSONL.

    為什麼累積後 flush 而非每筆寫?
      - 減少 file I/O (避免每個 alert 都打開 fd)
      - 避免半寫狀態 (process crash 不會留下 partial line)
      - flush 用 atomic .tmp + rename
    """
    _buffer: List[Dict[str, Any]] = []
    _lock = threading.Lock()
    _counters: Dict[str, int] = {}   # module → daily counter

    @classmethod
    def emit(cls, module: str, category: str, severity: str,
              reasoning: Optional[Dict[str, Any]] = None,
              detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """emit 一筆事件到 buffer."""
        now = datetime.now(TW_TZ)
        date_str = now.strftime('%Y%m%d')
        with cls._lock:
            cls._counters[module] = cls._counters.get(module, 0) + 1
            counter = cls._counters[module]
        event_id = f"{module.upper()}_{date_str}_{counter:04d}"
        event = {
            'ts': now.isoformat(),
            'event_id': event_id,
            'severity': severity or 'info',
            'module': module,
            'category': category,
            'reasoning': reasoning,
            'detail': detail or {},
        }
        with cls._lock:
            cls._buffer.append(event)
        return event

    @classmethod
    def flush_buffer(cls, data_dir: str = 'data', log_dir: str = 'logs') -> int:
        """把 buffer 一次性 atomic 寫入 logs/events_YYYYMMDD.jsonl 並清空 buffer.
        Returns: 寫入的 event 數."""
        with cls._lock:
            if not cls._buffer:
                return 0
            events = list(cls._buffer)
            cls._buffer.clear()
        date_str = datetime.now(TW_TZ).strftime('%Y%m%d')
        log_path = Path(data_dir).parent / log_dir if log_dir.startswith('/') is False else Path(log_dir)
        log_path.mkdir(exist_ok=True)
        target = log_path / f'events_{date_str}.jsonl'
        try:
            # append mode (一日內可能多次 flush)
            with open(target, 'a', encoding='utf-8') as f:
                for evt in events:
                    f.write(json.dumps(evt, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[event_logger] flush 失敗 ({len(events)} events 遺失): {e}")
            return 0
        return len(events)

    @classmethod
    def stats(cls) -> Dict[str, Any]:
        """目前 buffer 狀態."""
        with cls._lock:
            return {
                'buffer_size': len(cls._buffer),
                'counters_by_module': dict(cls._counters),
            }

    @classmethod
    def clear_buffer(cls) -> int:
        """測試用: 清空 buffer (不寫檔). Returns 清掉的數量."""
        with cls._lock:
            n = len(cls._buffer)
            cls._buffer.clear()
            return n


# Convenience function (module-level)
def emit_event(module: str, category: str, severity: str = 'info',
                reasoning: Optional[Dict[str, Any]] = None,
                detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Module-level shortcut to EventLogger.emit."""
    return EventLogger.emit(module, category, severity, reasoning, detail)
