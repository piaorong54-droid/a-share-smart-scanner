from datetime import datetime
import json
import pytest
from scan import CN, eligible,run,save,yang,sepa

@pytest.mark.parametrize("code,name,ok",[("600000.SH","示例",True),("600000.SH","*ST示例",False),("600000.SH","ST示例",False),("301001.SZ","示例",False),("688001.SH","示例",False),("920001.BJ","示例",False)])
def test_board(code,name,ok):
    assert eligible(dict(ts_code=code,name=name,market="主板")) is ok

@pytest.mark.parametrize("rise,cap,turn",[(3,50,5),(5,200,10)])
def test_yang_fixture(rise,cap,turn):
    q=dict(price=10,rise_pct=rise,float_cap_yi=cap,turnover_pct=turn,amplitude_pct=8,volume_ratio=1,expected_minutes=["09:31"])
    bars=[dict(high=10,close=10,adjusted_high=10,limit_up=i==0) for i in range(20)]
    mins=[dict(minute="09:31",amount_yuan=100,shares=10,close=10)]
    assert all(yang(q,bars,mins).values())
    with pytest.raises(ValueError): yang(q,bars[:-1],mins)
    with pytest.raises(ValueError): yang(q,bars,[])

def test_future_disclosure():
    with pytest.raises(ValueError): sepa(1,[{}]*150,dict(disclosed_at="20261110"),"20261109")

def test_failure(tmp_path):
    def fail(): raise OSError("fixture offline")
    report=run("combined",datetime(2026,11,9,14,45,tzinfo=CN),fail)
    save(report,tmp_path)
    assert json.loads((tmp_path/"latest.json").read_text(encoding="utf8"))["status"]=="FAILED"

def test_closed():
    class Closed:
        def rows(self,*args,**kwargs): return [dict(cal_date="20261108",is_open=0)]
    assert run("yang",datetime(2026,11,8,tzinfo=CN),Closed)["status"]=="SKIPPED"
