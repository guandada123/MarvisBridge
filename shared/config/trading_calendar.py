"""
通用A股交易日历模块
供所有自动化脚本统一调用，基于 trading_calendar.json 配置文件。

用法:
    from trading_calendar import (
        is_trading_day, is_holiday, is_weekend,
        is_trading_time, get_next_trading_day,
        get_holidays, get_status,
    )

直接运行:
    python trading_calendar.py
"""

import json
import os
from datetime import datetime, timedelta, timezone


# ---------- 模块级加载 ----------

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_CALENDAR_PATH = os.path.join(_MODULE_DIR, "trading_calendar.json")

with open(_CALENDAR_PATH, "r", encoding="utf-8") as f:
    _CALENDAR = json.load(f)

# 时区：中国标准时间 UTC+8
_CST = timezone(timedelta(hours=8))

# 将 JSON 中所有节假日日期展平为一个集合（date 对象）
_holiday_dates: set = set()
for _dates in _CALENDAR.get("holidays_2026", {}).values():
    for d in _dates:
        _holiday_dates.add(datetime.strptime(d, "%Y-%m-%d").date())

# 交易时段
_trading_hours = _CALENDAR.get("trading_hours", {})
_MORNING_START = _trading_hours.get("morning_start", "09:30")
_MORNING_END = _trading_hours.get("morning_end", "11:30")
_AFTERNOON_START = _trading_hours.get("afternoon_start", "13:00")
_AFTERNOON_END = _trading_hours.get("afternoon_end", "15:00")


def _now_cst() -> datetime:
    """返回当前北京时间（UTC+8）"""
    return datetime.now(_CST)


def _today_cst():
    """返回当前北京日期"""
    return _now_cst().date()


# ---------- 公开 API ----------

def is_trading_day() -> bool:
    """判断今天是否为A股交易日"""
    return not is_weekend() and not is_holiday()


def is_holiday() -> bool:
    """判断今天是否为节假日休市"""
    return _today_cst() in _holiday_dates


def is_weekend() -> bool:
    """判断今天是否为周末（周六/周日）"""
    return _today_cst().weekday() in (5, 6)


def is_trading_time() -> bool:
    """判断当前是否在A股交易时段（9:30-11:30, 13:00-15:00）"""
    now = _now_cst()
    t = now.time()
    morning_start = datetime.strptime(_MORNING_START, "%H:%M").time()
    morning_end = datetime.strptime(_MORNING_END, "%H:%M").time()
    afternoon_start = datetime.strptime(_AFTERNOON_START, "%H:%M").time()
    afternoon_end = datetime.strptime(_AFTERNOON_END, "%H:%M").time()
    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)


def get_next_trading_day():
    """获取下一个交易日（返回 date 对象）"""
    d = _today_cst() + timedelta(days=1)
    while d.weekday() in (5, 6) or d in _holiday_dates:
        d += timedelta(days=1)
    return d


def get_holidays() -> set:
    """返回所有节假日日期集合（date 对象）"""
    return _holiday_dates.copy()


def get_status() -> dict:
    """返回当前状态摘要"""
    today = _today_cst()
    now = _now_cst()
    weekend = today.weekday() in (5, 6)
    holiday = today in _holiday_dates

    # 确定休市原因
    if holiday:
        reason = "节假日休市"
    elif weekend:
        reason = "周末休市"
    else:
        reason = ""

    # 查找下一个休市日（周末或节假日）
    next_off = today + timedelta(days=1)
    while next_off.weekday() not in (5, 6) and next_off not in _holiday_dates:
        next_off += timedelta(days=1)

    days_to_next_off = (next_off - today).days

    # 找到当前所在节日名称
    current_holiday_name = None
    for name, dates in _CALENDAR.get("holidays_2026", {}).items():
        if today.strftime("%Y-%m-%d") in dates:
            current_holiday_name = name
            break

    trading = not weekend and not holiday

    return {
        "date": today.strftime("%Y-%m-%d"),
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()],
        "is_weekend": weekend,
        "is_holiday": holiday,
        "holiday_name": current_holiday_name,
        "is_trading_day": trading,
        "is_trading_time": is_trading_time(),
        "reason": reason if not trading else "交易日",
        "next_off_day": next_off.strftime("%Y-%m-%d"),
        "days_to_next_off": days_to_next_off,
        "current_time": now.strftime("%H:%M:%S"),
    }


# ---------- __main__ 入口 ----------

if __name__ == "__main__":
    status = get_status()

    print("=" * 42)
    print("  A股交易日历状态")
    print("=" * 42)
    print(f"  日期:       {status['date']} ({status['weekday']})")
    print(f"  当前时间:   {status['current_time']}")
    print(f"  周末:       {'是' if status['is_weekend'] else '否'}")
    print(f"  节假日:     {'是' if status['is_holiday'] else '否'}")
    if status["holiday_name"]:
        print(f"  节日名称:   {status['holiday_name']}")
    print(f"  交易日:     {'是' if status['is_trading_day'] else '否'}")
    print(f"  交易时段:   {'是' if status['is_trading_time'] else '否'}")
    print(f"  状态:       {status['reason']}")
    print(f"  下一个休市: {status['next_off_day']}（{status['days_to_next_off']}天后）")
    print("=" * 42)
