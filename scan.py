import argparse
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from provider import Provider
from strategy import eligible, number, sepa, yang

CN = timezone(timedelta(hours=8))


def minutes_until(now):
    result = []
    for start, length in [(570, 120), (780, 120)]:
        for t in range(start + 1, start + length + 1):
            label = f"{t // 60:02}:{t % 60:02}"
            if label <= now.strftime("%H:%M"):
                result.append(label)
    return result


def evidence(p, stock, days, now, mode):
    symbol = stock["ts_code"]
    today = now.strftime("%Y%m%d")
    def fetch(api, fields, **params):
        return p.rows(api, fields, ts_code=symbol, **params)
    bounds = dict(start_date=days[0], end_date=days[-1])
    bars = fetch("daily", "trade_date,close,high,vol", **bounds)
    bars.sort(key=lambda d: d["trade_date"])
    if [d["trade_date"] for d in bars] != days:
        raise ValueError("日线缺失或停牌")
    factors = {r["trade_date"]: number(r["adj_factor"]) for r in fetch("adj_factor", "trade_date,adj_factor", start_date=days[0], end_date=today)}
    for d in bars:
        factor = factors[d["trade_date"]] / factors[today]
        d.update(adjusted_close=number(d["close"])*factor, adjusted_high=number(d["high"])*factor, volume=d["vol"])
    rows = fetch("stk_mins", "trade_time,close,vol,amount,high,low", freq="1min",
                 start_date=now.strftime("%Y-%m-%d 09:30:00"), end_date=now.strftime("%Y-%m-%d %H:%M:00"))
    rows.sort(key=lambda r: r["trade_time"])
    expected = minutes_until(now)
    if not rows or any(r["trade_time"][:10] != now.date().isoformat() for r in rows):
        raise ValueError("缺少当日分钟数据")
    mins = [dict(minute=r["trade_time"][11:16], close=r["close"], shares=r["vol"], amount_yuan=r["amount"]) for r in rows]
    if [m["minute"] for m in mins] != expected:
        raise ValueError("STALE / 当日分钟覆盖不全")
    price = number(rows[-1]["close"])
    checks = {}
    detail = dict(price=price, market_time=rows[-1]["trade_time"])
    if mode in ("yang","combined"):
        limits = {r["trade_date"]:r["up_limit"] for r in fetch("stk_limit","trade_date,up_limit",start_date=days[-20],end_date=days[-1])}
        for d in bars[-20:]:
            d["limit_up"] = number(d["close"]) == number(limits[d["trade_date"]])
        # Official same-day reference close and float shares must be available.
        refs = fetch("daily","trade_date,pre_close",trade_date=today)
        shares = fetch("daily_basic","trade_date,float_share",trade_date=today)
        prev = number(refs[0]["pre_close"])
        floating = number(shares[0]["float_share"])*10000
        volume = sum(number(m["shares"]) for m in mins)
        q = dict(price=price, rise_pct=(price/prev-1)*100, turnover_pct=100*volume/floating,
                 float_cap_yi=price*floating/1e8, expected_minutes=expected,
                 volume_ratio=volume*240/len(mins)/(sum(number(d["vol"]) for d in bars[-5:])*100/5),
                 amplitude_pct=(max(number(r["high"]) for r in rows)-min(number(r["low"]) for r in rows))/prev*100)
        checks.update(yang(q,bars[-20:],mins))
        detail.update({k:v for k,v in q.items() if k!="expected_minutes"})
    if mode in ("sepa","combined"):
        # Single-quarter figures and audited annual profits only; date-only disclosures available next day.
        fin = fetch("fina_indicator","ann_date,end_date,q_sales_yoy,q_profit_yoy,q_profit_qoq,roe")
        financial = sorted((r for r in fin if r["ann_date"] and r["ann_date"] < today),key=lambda r:(r["end_date"],r["ann_date"]))
        latest = financial[-1]
        annual = next(r for r in reversed(financial) if r["end_date"].endswith("1231"))
        income = fetch("income","ann_date,end_date,n_income_attr_p,report_type",report_type="1")
        profits = {r["end_date"]:r["n_income_attr_p"] for r in sorted(income,key=lambda r:r["ann_date"] or "") if r["ann_date"] and r["ann_date"] < today and str(r["report_type"])=="1"}
        end = annual["end_date"]
        f = dict(disclosed_at=latest["ann_date"],listing_days=(now.date()-datetime.strptime(stock["list_date"],"%Y%m%d").date()).days,
                 quarter_revenue_yoy=latest["q_sales_yoy"], quarter_profit_yoy=latest["q_profit_yoy"],quarter_profit_qoq=latest["q_profit_qoq"],
                 annual_roe=annual["roe"],annual_profit=profits[end],annual_profit_3y_ago=profits[str(int(end[:4])-3)+"1231"])
        checks.update(sepa(price,bars,f,today))
        detail["financial"]=f
    return dict(**stock, **detail, checks=checks)


def run(mode, now, provider=Provider):
    r = dict(id=str(uuid.uuid4()),date=now.date().isoformat(),started=now.isoformat(),mode=mode,source="Tushare Pro",
             sha=os.getenv("GITHUB_SHA"),status="FAILED",total=0,verified=0,matches=[],errors=[],stages=Counter(),details=[])
    try:
        p = provider()
        day = now.strftime("%Y%m%d")
        dates = p.rows("trade_cal","cal_date,is_open",exchange="SSE",start_date=(now-timedelta(days=320)).strftime("%Y%m%d"),end_date=day)
        cal = {d["cal_date"]:int(d["is_open"]) for d in dates}
        if cal[day]==0:
            r["status"]="SKIPPED"
        elif not "14:45" <= now.strftime("%H:%M") < "15:00":
            raise ValueError("实际执行时间超出尾盘窗口")
        else:
            days = sorted(d for d in cal if d<day and cal[d])[-150:]
            stocks = p.rows("stock_basic","ts_code,name,market,list_date",list_status="L")
            if len(days)!=150 or not stocks or len(stocks)>=6000 or len({s["ts_code"] for s in stocks})!=len(stocks):
                raise ValueError("证券清单或交易日历不完整")
            universe=[s for s in stocks if eligible(s)]
            if not universe:
                raise ValueError("主板清单为空")
            r["total"]=len(universe)
            for stock in universe:
                try:
                    item=evidence(p,stock,days,now,mode)
                    r["details"].append(item)
                    r["verified"]+=1
                    for key,passed in item["checks"].items():
                        if not passed:
                            break
                        r["stages"][key]+=1
                    else:
                        r["matches"].append(item)
                except (ValueError,KeyError,IndexError,TypeError,OSError,ZeroDivisionError) as exc:
                    r["errors"].append([stock["ts_code"],str(exc)])
                    if len(r["errors"])>=10 and not r["verified"]:
                        break
            r["status"]="PARTIAL_DATA" if r["verified"]!=r["total"] else ("SUCCESS_WITH_MATCHES" if r["matches"] else "SUCCESS_NO_MATCHES")
    except Exception as exc:
        r["errors"].append(str(exc))
    r["ended"]=datetime.now(CN).isoformat()
    return r


def save(r, folder):
    status=r["status"]
    conclusion={"PARTIAL_DATA":"本次扫描数据不完整，无法确认是否存在符合条件的标的。","SUCCESS_NO_MATCHES":"今日无符合条件标的。","FAILED":"扫描失败，无法判断。","SKIPPED":"非交易日。","SUCCESS_WITH_MATCHES":"已核实标的见下表。"}[status]
    md=[f"# {r['date']} A股尾盘选股报告",f"{status} · {r['mode']} · {r['source']}",f"开始 {r['started']}，已核实 {r['verified']}/{r['total']}，匹配 {len(r['matches'])}。",conclusion,"市场涨跌家数、指数及成交量变化无法确认。","|代码|名称|价格|行情时间|","|---|---|---:|---|"]
    md.extend(f"|{m['ts_code']}|{m['name']}|{m['price']}|{m['market_time']}|" for m in r["matches"])
    md.extend(["详细指标、逐项判定及异常见同名 JSON。","仅供策略研究，不构成投资建议。"])
    for base in [folder/"archive"/r["date"],folder/"latest"]:
        base.parent.mkdir(parents=True,exist_ok=True)
        base.with_suffix(".json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
        base.with_suffix(".md").write_text("\n\n".join(md),encoding="utf8")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["yang","sepa","combined"],default="combined")
    args=parser.parse_args()
    report=run(args.mode,datetime.now(CN))
    save(report,Path("reports"))
    print(report["status"])
    raise SystemExit(int(report["status"] in ("FAILED","PARTIAL_DATA")))
