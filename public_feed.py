"""Public market feeds. Percent fields are percentage points, cap is CNY."""
import calendar
import json
import math
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import urlopen

from strategy import number, sepa, yang


def read(url, **params):
    for attempt in range(3):
        try:
            with urlopen(url + "?" + urlencode(params), timeout=12) as response:
                return json.load(response)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)


class PublicProvider:
    def rows(self, api, fields, **params):
        if api == "trade_cal":
            start = date.fromisoformat(params["start_date"])
            end = date.fromisoformat(params["end_date"])
            month = start.replace(day=1)
            result = []
            while month <= end:
                data = read("https://www.szse.cn/api/report/exchange/onepersistenthour/monthList",
                            month=month.strftime("%Y-%m"))["data"]
                days = {d["jyrq"]: str(d["jybz"]) for d in data}
                for i in range(calendar.monthrange(month.year, month.month)[1]):
                    day = month + timedelta(days=i)
                    if start <= day <= end:
                        flag = days[day.isoformat()]
                        if flag not in ("0","1"):
                            raise ValueError("交易日历标志异常")
                        result.append(dict(cal_date=day.strftime("%Y%m%d"), is_open=int(flag)))
                month = (month + timedelta(days=32)).replace(day=1)
            return result
        if api != "stock_basic":
            raise ValueError(api)
        result = []
        total = None
        page = 1
        while total is None or len(result) < total:
            data = read("https://push2.eastmoney.com/api/qt/clist/get", pn=page, pz=100, fltt=2,
                        fid="f12", po=1, fs="m:1 t:2 f:!2,m:0 t:6 f:!2,m:0 t:13 f:!2",
                        fields="f2,f3,f7,f8,f10,f12,f13,f14,f21,f26,f124")["data"]
            if total is not None and total != data["total"]:
                raise ValueError("分页期间证券总数变化")
            total = data["total"]
            batch = data["diff"]
            if not batch:
                raise ValueError("主板清单分页不完整")
            for q in batch.values() if isinstance(batch,dict) else batch:
                exchange = {0:"SZ",1:"SH"}[q["f13"]]
                result.append(dict(ts_code=q["f12"]+"."+exchange, market="主板", name=q["f14"],
                                   list_date=str(q["f26"]), quote=q))
            page += 1
        if len(result) != total:
            raise ValueError("主板清单数量冲突")
        return result


@lru_cache(maxsize=24)
def pool(day):
    data = read("https://push2ex.eastmoney.com/getTopicZTPool", ut="7eea3edcaed734bea9cbfc24409ed989",
                dpt="wz.ztzt", Pageindex=0, pagesize=1000, sort="fbt:asc", date=day)["data"]
    if not data or str(data["qdate"]) != day or len(data["pool"]) != data["tc"]:
        raise ValueError("历史涨停池日期或覆盖未核实 "+day)
    return {r["c"] for r in data["pool"]}


def financial(code, now, stock):
    data = read("https://datacenter-web.eastmoney.com/api/data/v1/get", reportName="RPT_LICO_FN_CPD",
                columns="ALL", pageSize=40, sortColumns="REPORTDATE", sortTypes="-1",
                filter=f'(SECURITY_CODE="{code}")')["result"]["data"]
    today = now.date().isoformat()
    rows = {date.fromisoformat(r["REPORTDATE"][:10]):r for r in data if r["SECURITY_CODE"]==code
            and r["NOTICE_DATE"] and r["NOTICE_DATE"][:10]<today and r["UPDATE_DATE"] and r["UPDATE_DATE"][:10]<today}
    end=max(rows)
    def previous(d):
        return d.replace(day=1,month=d.month-2)-timedelta(days=1)
    def quarter(d, key):
        value=number(rows[d][key])
        return value if d.month==3 else value-number(rows[previous(d)][key])
    def growth(key, base_date):
        base=quarter(base_date,key)
        if base<=0:
            raise ValueError("增长率基期非正")
        return 100*(quarter(end,key)/base-1)
    annual=max(d for d in rows if d.month==12)
    prior=end.replace(year=end.year-1)
    return dict(disclosed_at=rows[end]["NOTICE_DATE"][:10],listing_days=(now.date()-date.fromisoformat(stock["list_date"])).days,
                quarter_revenue_yoy=growth("TOTAL_OPERATE_INCOME",prior),quarter_profit_yoy=growth("PARENT_NETPROFIT",prior),
                quarter_profit_qoq=growth("PARENT_NETPROFIT",previous(end)),annual_roe=number(rows[annual]["WEIGHTAVG_ROE"]),
                annual_profit=number(rows[annual]["PARENT_NETPROFIT"]),annual_profit_3y_ago=number(rows[annual.replace(year=annual.year-3)]["PARENT_NETPROFIT"]))


def evaluate(stock, days, now, mode, expected):
    code, exchange=stock["ts_code"].split(".")
    symbol=exchange.lower()+code
    raw=stock["quote"]
    stamp=datetime.fromtimestamp(number(raw["f124"]),now.tzinfo)
    if stamp.date()!=now.date() or abs((now-stamp).total_seconds())>120:
        raise ValueError("快照与扫描时刻偏离超过120秒")
    price=number(raw["f2"])
    if price<=0:
        raise ValueError("无有效现价")
    item={k:v for k,v in stock.items() if k!="quote"}
    checks={}
    item.update(price=price,market_time=stamp.isoformat(),checks=checks)
    if mode!="sepa":
        q=dict(price=price,rise_pct=number(raw["f3"]),float_cap_yi=number(raw["f21"])/1e8,
               volume_ratio=number(raw["f10"]),turnover_pct=number(raw["f8"]),amplitude_pct=number(raw["f7"]))
        item.update(q)
        checks.update(rise=3<=q["rise_pct"]<=5,cap=50<=q["float_cap_yi"]<=200,ratio=q["volume_ratio"]>=1,
                      turnover=5<=q["turnover_pct"]<=10,amplitude=0<=q["amplitude_pct"]<=8)
        if not all(checks.values()):
            return item
    k=read("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",param=f"{symbol},day,,,200,qfq")["data"][symbol]
    bars={d[0].replace("-",""):dict(close=d[2],high=d[3],adjusted_close=d[2],adjusted_high=d[3],volume=d[5])
          for d in k.get("qfqday",k.get("day",[]))}
    hist=[bars[d] for d in days]
    if mode!="yang":
        f=financial(code,now,stock)
        item["financial"]=f
        checks.update(sepa(price,hist,f,now.date().isoformat()))
        if not all(checks.values()):
            return item
    if mode!="sepa":
        feed=read("https://web.ifzq.gtimg.cn/appstock/app/minute/query",code=symbol)["data"][symbol]["data"]
        if str(feed["date"])!=now.strftime("%Y%m%d"):
            raise ValueError("分钟日期不符")
        mins=[]
        last_amount=last_vol=0
        for line in feed["data"]:
            clock,close,vol,amount=line.split()[:4]
            label=clock[:2]+":"+clock[2:]
            if label not in expected:
                continue
            vol=number(vol)*100
            amount=number(amount)
            if vol<last_vol or amount<last_amount:
                raise ValueError("分钟累计量额倒退")
            mins.append(dict(minute=label,close=close,shares=vol-last_vol,amount_yuan=amount-last_amount))
            last_vol,last_amount=vol,amount
        if not mins or number(mins[-1]["close"])!=price:
            raise ValueError("分钟与快照现价冲突")
        # One verified historical limit-up proves existence even if other pools are unavailable.
        found=False
        unknown=False
        for d in reversed(days[-20:]):
            try:
                bars[d]["limit_up"]=code in pool(d)
            except (ValueError,TypeError,KeyError,OSError):
                unknown=True
                continue
            if bars[d]["limit_up"]:
                found=True
                item["limit_up_date"]=d
                break
        if not found and unknown:
            raise ValueError("近20日涨停事实未核实")
        # yang() expects complete daily flags; evaluate the confirmed existential condition separately.
        reviewed=[dict(b,limit_up=bool(b.get("limit_up"))) for b in hist[-20:]]
        checks.update(yang(dict(q,expected_minutes=expected),reviewed,mins))
    return item
