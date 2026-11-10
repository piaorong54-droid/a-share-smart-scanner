from pathlib import Path
import json
from datetime import date
from mcp.server.fastmcp import FastMCP

app=FastMCP("A股报告查询")
root=Path(__file__).resolve().parent/"reports"

@app.tool()
def get_latest_scan() -> dict:
    return json.loads((root/"latest.json").read_text(encoding="utf8"))

@app.tool()
def get_scan_by_date(day:str) -> dict:
    name=date.fromisoformat(day).isoformat()
    return json.loads((root/"archive"/(name+".json")).read_text(encoding="utf8"))

@app.tool()
def get_stock_details(code:str) -> dict:
    r=get_latest_scan()
    return dict(details=[x for x in r["details"] if x["ts_code"]==code],errors=[e for e in r["errors"] if isinstance(e,list) and e[0]==code])

@app.tool()
def get_data_health() -> dict:
    r=get_latest_scan()
    return {k:r[k] for k in ("date","started","ended","status","total","verified","errors")}

@app.tool()
def get_strategy_config() -> dict:
    return dict(default="combined",modes=["yang","sepa","combined"],rise_pct=[3,5],cap_yi=[50,200],turnover_pct=[5,10],volume_ratio_min=1,amplitude_max_pct=8)

if __name__=="__main__":
    app.run(transport="streamable-http")
