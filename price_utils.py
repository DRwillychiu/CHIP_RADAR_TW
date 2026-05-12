"""
price_utils.py - 台股精確漲跌停價計算 (v3.28 新增)

修補 v3.27.x 的 9.5% threshold 近似法:
  舊邏輯: is_limit_up = (change_pct >= 9.5)
  問題: 9.5% 是近似值,不是台股實際漲停規則
         例如 5/12 睿生光電(6861) prev_close=389, 收 426 (+9.51%),
         但精確漲停價 = floor(389*1.10/0.5)*0.5 = 427.5 (差一個 tick),
         舊邏輯標為漲停,實際上沒漲停 (False Positive)

正確算法:
  漲停價 = floor(prev_close × 1.10 / tick_size) × tick_size
  tick_size 取在 raw 1.10 倍價格的區間

Tick-size 規則 (台股 2020 年後現行):
  < 10     : 0.01
  10 ~ 50  : 0.05
  50 ~ 100 : 0.1
  100 ~ 500: 0.5
  500~1000 : 1.0
  >= 1000  : 5.0

注意事項 (v3.28 暫不處理, roll to v3.29+):
  - 新上市股前 5 個交易日無漲跌停限制 (uncapped)
  - 處置股 (T+5 預收款) 漲跌停跟一般股一樣 → 不影響
  - 興櫃股 → chip_radar 不抓,不需考慮
"""
import math


def get_tick_size(price: float) -> float:
    """根據價格區間回傳 tick size (元)"""
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def calc_limit_up_price(prev_close: float) -> float:
    """
    台股漲停價 = floor(prev_close × 1.10 / tick) × tick

    tick 取在 raw (1.10 倍價格) 的區間,不是 prev_close 的區間。
    例如 prev_close=98 (tick 0.1), raw=107.8 (落入 100~500 → tick 0.5),
       limit_up_price = floor(107.8 / 0.5) * 0.5 = 107.5

    Args:
      prev_close: 前一交易日收盤價 (元)

    Returns:
      漲停價 (元), 若 prev_close <= 0 回傳 0
    """
    if not prev_close or prev_close <= 0:
        return 0.0
    raw = prev_close * 1.10
    tick = get_tick_size(raw)
    # floor(raw / tick) * tick — Python float 精度問題用 round + epsilon 處理
    # 不能直接 math.floor 因為 0.1 * 3 = 0.30000000000000004
    units = math.floor(raw / tick + 1e-9)
    result = units * tick
    # 二次保險: round 到 tick 對應的小數位
    decimals = 2 if tick < 1 else 0
    return round(result, decimals)


def calc_limit_down_price(prev_close: float) -> float:
    """
    台股跌停價 = ceil(prev_close × 0.90 / tick) × tick (跌停往上取以保留精度)

    其實台股跌停實務上是 floor,但邊界 case 用 floor 會比真實跌停低一個 tick,
    所以這裡用 ceil 保守(寧可漏 detect 也不誤判)。

    Args:
      prev_close: 前一交易日收盤價 (元)

    Returns:
      跌停價 (元), 若 prev_close <= 0 回傳 0
    """
    if not prev_close or prev_close <= 0:
        return 0.0
    raw = prev_close * 0.90
    tick = get_tick_size(raw)
    units = math.ceil(raw / tick - 1e-9)
    result = units * tick
    decimals = 2 if tick < 1 else 0
    return round(result, decimals)


def is_limit_up_exact(close: float, prev_close: float) -> bool:
    """精確漲停判定: close >= 漲停價"""
    if not close or not prev_close:
        return False
    lu = calc_limit_up_price(prev_close)
    if lu <= 0:
        return False
    # 浮點容差: tick / 2
    tick = get_tick_size(lu)
    return close >= lu - tick / 2


def is_limit_down_exact(close: float, prev_close: float) -> bool:
    """精確跌停判定: close <= 跌停價"""
    if not close or not prev_close:
        return False
    ld = calc_limit_down_price(prev_close)
    if ld <= 0:
        return False
    tick = get_tick_size(ld)
    return close <= ld + tick / 2
