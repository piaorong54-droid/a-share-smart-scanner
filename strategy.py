import math
import re
from statistics import mean


def number(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("非有限数值")
    return x


def eligible(stock):
    code, exchange = stock["ts_code"].split(".")
    prefix = {"SH": r"60[0135]\d{3}", "SZ": r"00[0123]\d{3}"}.get(exchange, r"(?!)")
    if not stock["name"] or not stock["market"]:
        raise ValueError("证券元数据缺失")
    return bool(re.fullmatch(prefix, code) and stock["market"] == "主板"
                and "ST" not in stock["name"].upper() and "退" not in stock["name"])


def yang(q, history, minutes):
    checks = dict(rise=3 <= number(q["rise_pct"]) <= 5, turnover=5 <= number(q["turnover_pct"]) <= 10,
                  amplitude=0 <= number(q["amplitude_pct"]) <= 8, ratio=number(q["volume_ratio"]) >= 1,
                  cap=50 <= number(q["float_cap_yi"]) <= 200)
    if len(history) != 20:
        raise ValueError("缺少完整20交易日")
    checks["limit_up"] = any(d["limit_up"] is True for d in history)
    if any(type(d["limit_up"]) is not bool for d in history):
        raise ValueError("涨停状态未知")
    checks["shadow"] = all(number(d["high"]) / number(d["close"]) <= 1.03 for d in history[-5:])
    price = number(q["price"])
    checks["pressure"] = not any(price < number(d["adjusted_high"]) <= price * 1.02 for d in history)
    if not minutes or [m["minute"] for m in minutes] != q["expected_minutes"]:
        raise ValueError("分钟覆盖不全")
    amount = volume = 0
    checks["vwap"] = True
    for m in minutes:
        amount += number(m["amount_yuan"])
        volume += number(m["shares"])
        if volume <= 0:
            raise ValueError("成交量不可用")
        checks["vwap"] &= number(m["close"]) >= .995 * amount / volume
    return checks


def sepa(price, history, f, asof):
    if len(history) < 150 or f["disclosed_at"] > asof:
        raise ValueError("历史不足或财务数据尚未披露")
    close = [number(d["adjusted_close"]) for d in history]
    vol = [number(d["volume"]) for d in history]
    a, b = number(f["annual_profit_3y_ago"]), number(f["annual_profit"])
    return dict(listed=f["listing_days"] >= 365, revenue=number(f["quarter_revenue_yoy"]) > 25,
                profit=number(f["quarter_profit_yoy"]) > 30, sequential=number(f["quarter_profit_qoq"]) > 0,
                roe=number(f["annual_roe"]) > 15, cagr=a > 0 and b > 0 and (b/a)**(1/3) > 1.2,
                ma50=price > mean(close[-50:]), ma150=price > mean(close[-150:]),
                volume=mean(vol[-10:]) > mean(vol[-120:]))
