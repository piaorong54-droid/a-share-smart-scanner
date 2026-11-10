import argparse
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from public_feed import PublicProvider, evaluate
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


def run(mode, now, provider=PublicProvider):
    r = dict(id=str(uuid.uuid4()),date=now.date().isoformat(),started=now.isoformat(),mode=mode,source="深交所交易日历、东方财富主板行情及财报、腾讯日线与分时",
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
                    item=evaluate(stock,days,now,mode,minutes_until(now))
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
